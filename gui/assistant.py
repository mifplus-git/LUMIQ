"""AI 어시스턴트 패널: 앱 안에서 Claude Code(CLI)를 실행해 대화로 보정한다.

- API 키나 LLM을 앱에 넣지 않는다. 이미 로그인된 Claude Code를 `claude -p`로 부르고, 같은 요금제 사용량을 쓴다.
- Claude Code는 CLAUDE.md 규칙대로 사진 옆 보정값 파일(<사진 파일 이름>.lumiq.json)만 고친다.
  앱은 파일 변경을 감지해 바로 다시 그린다. 사진 폴더는 작업 폴더 밖이라 --add-dir로 허용한다.
- 허용 도구: 읽기/편집/쓰기, 그리고 CLI(`.venv/bin/python main.py ...`) 실행뿐 (그 밖의 명령은 자동 거부).
- 앱 번들로 실행하면 프로젝트 .venv 없이도 되도록 작업 폴더의 `./lumiq`(번들 안 CLI로 가는 링크)를 쓴다.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from pipeline.params import DATA, ROOT

from . import theme as T

BUNDLE = os.environ.get("LUMIQ_BUNDLE")  # 앱 번들 런처가 알려 주는 .app 경로
CLI = "./lumiq" if BUNDLE else ".venv/bin/python main.py"
ALLOWED_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", f"Bash({CLI}:*)"]
SUGGESTIONS = ["자동으로 보기 좋게 맞춰줘", "피부를 화사하게", "필름 느낌으로", "하늘과 하이라이트 살려줘",
               "따뜻한 분위기로", "선택한 사진들 톤을 이 사진과 맞춰줘"]


def find_claude() -> str | None:
    cands = [shutil.which("claude"), str(Path.home() / ".local/bin/claude"), "/opt/homebrew/bin/claude",
             "/usr/local/bin/claude", str(Path.home() / ".claude/local/claude")]
    ext = sorted((Path.home() / ".vscode/extensions").glob("anthropic.claude-code-*/resources/native-binary/claude"))
    cands += [str(p) for p in reversed(ext)]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def ensure_cli_link():
    """앱 번들이면 작업 폴더에 ./lumiq → 번들 안 CLI 링크를 둔다 (앱을 옮겼으면 고침, 같은 이름의 일반 파일은 그대로)."""
    if not BUNDLE:
        return
    link, target = DATA / "lumiq", Path(BUNDLE) / "Contents" / "MacOS" / "lumiq"
    try:
        if link.is_symlink():
            if os.readlink(link) == str(target):
                return
            link.unlink()
        elif link.exists():
            return
        link.symlink_to(target)
    except OSError:
        pass


def guide_text() -> str:
    """작업 폴더에 CLAUDE.md가 없을 때(프로젝트 폴더를 지운 경우) 앱에 든 사본을 시스템 프롬프트로 준다."""
    if (DATA / "CLAUDE.md").exists() or not (ROOT / "CLAUDE.md").exists():
        return ""
    return (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


def describe_tool(name: str, inp: dict) -> str:
    def rel(p):
        try:
            return str(Path(p).relative_to(DATA))
        except (ValueError, TypeError):
            return Path(str(p)).name
    if name in ("Edit", "Write", "MultiEdit"):
        return f"보정값 수정 · {rel(inp.get('file_path', ''))}"
    if name == "Read":
        f = str(inp.get("file_path", ""))
        return f"사진 확인 · {Path(f).name}" if f.lower().endswith((".jpg", ".png")) else f"읽기 · {rel(f)}"
    if name == "Bash":
        cmd = str(inp.get("command", ""))
        if "--info" in cmd:
            return "사진 분석 (--info)"
        if "--preview" in cmd:
            return "미리보기 생성"
        if "--save-preset" in cmd:
            return "프리셋 저장"
        return "실행 · " + cmd.replace(CLI, "main.py")[:60]
    if name in ("Glob", "Grep"):
        return "파일 찾기"
    return name


class ClaudeRunner(QObject):
    delta = Signal(str)          # 답변 글자 (스트리밍)
    text_block_end = Signal()
    tool = Signal(str)           # 도구 사용 설명
    finished = Signal(bool, str, str)  # (성공, 메시지/오류, session_id)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc: QProcess | None = None
        self._buf = b""
        self._session = ""
        self._got_result = False
        self._err = b""

    def running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self, claude: str, prompt: str, system: str, session_id: str | None, dirs=()):
        self._buf, self._err, self._got_result, self._session = b"", b"", False, session_id or ""
        ensure_cli_link()
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(DATA))
        env = QProcessEnvironment.systemEnvironment()
        extra = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin"
        env.insert("PATH", extra + ":" + env.value("PATH", "/usr/bin:/bin"))
        self.proc.setProcessEnvironment(env)
        args = []
        if session_id:
            args += ["--resume", session_id]
        args += ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                 "--permission-mode", "acceptEdits", "--append-system-prompt", system,
                 "--allowedTools", *ALLOWED_TOOLS]
        for d in dirs:  # 사진 폴더: 그 안의 .lumiq.json을 고칠 수 있도록
            args += ["--add-dir", d]
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.readyReadStandardError.connect(lambda: setattr(self, "_err", self._err + self.proc.readAllStandardError().data()))
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(lambda e: None)
        self.proc.start(claude, args)
        self.proc.write(prompt.encode("utf-8"))
        self.proc.closeWriteChannel()

    def stop(self):
        if self.running():
            self.proc.kill()

    def _read(self):
        self._buf += self.proc.readAllStandardOutput().data()
        *lines, self._buf = self._buf.split(b"\n")
        for line in lines:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle(d)

    def _handle(self, d: dict):
        t = d.get("type")
        if d.get("session_id"):
            self._session = d["session_id"]
        if t == "stream_event":
            ev = d.get("event", {})
            et = ev.get("type")
            if et == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                self.delta.emit(ev["delta"].get("text", ""))
            elif et == "content_block_stop":
                self.text_block_end.emit()
        elif t == "assistant":
            for c in d.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    self.tool.emit(describe_tool(c.get("name", ""), c.get("input") or {}))
        elif t == "result":
            self._got_result = True
            ok = not d.get("is_error") and d.get("subtype") == "success"
            msg = d.get("result") or ""
            if not ok and not msg:
                msg = d.get("subtype", "오류")
            self.finished.emit(ok, msg, self._session)

    def _done(self, code, status):
        if self._buf.strip():
            self._buf += b"\n"
            self._read()
        if not self._got_result:
            err = self._err.decode("utf-8", "ignore").strip()
            msg = "중단했습니다" if status == QProcess.CrashExit else (err.splitlines()[-1] if err else f"종료 코드 {code}")
            self.finished.emit(False, msg, self._session)


# ---------------------------------------------------------------- 패널 UI

class _Bubble(QFrame):
    def __init__(self, text: str, mine: bool):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setTextFormat(Qt.PlainText if mine else Qt.MarkdownText)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        if mine:
            self.label.setStyleSheet(f"background: {T.BG3}; color: {T.TEXT}; border-radius: 12px; padding: 8px 12px;")
            lay.addStretch(1)
            lay.addWidget(self.label, 0)
            self.label.setMaximumWidth(260)
        else:
            self.label.setStyleSheet(f"color: {T.TEXT}; padding: 2px 2px;")
            lay.addWidget(self.label, 1)
        self.raw = text

    def append(self, s: str):
        self.raw += s
        self.label.setText(self.raw)


class _ToolLine(QLabel):
    def __init__(self, text: str):
        super().__init__(f"◦ {text}")
        self.setObjectName("Faint")
        self.setWordWrap(True)


class _ChangeCard(QFrame):
    """AI가 바꾼 보정값 요약: '노출 1.00 → 1.40' + [보정 패널에서 보기] [되돌리기]."""
    show = Signal()
    revert = Signal()

    def __init__(self, changes: list, others: list):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        only_others = not changes and bool(others)  # 지금 사진은 그대로, 다른 사진만 바뀜 → 눈에 띄게 알림
        self.title = QLabel("지금 사진은 바뀌지 않았어요" if only_others else "적용된 보정값")
        self.title.setStyleSheet(f"color: {'#ff8a80' if only_others else T.ACCENT_HI}; font-weight: 600;")
        lay.addWidget(self.title)
        for label, old, new in changes[:14]:
            row = QHBoxLayout()
            row.setSpacing(6)
            a = QLabel(label)
            a.setStyleSheet(f"color: {T.TEXT2};")
            b = QLabel(f"{old}  →  <b>{new}</b>")
            b.setTextFormat(Qt.RichText)
            b.setStyleSheet(f"color: {T.TEXT};")
            row.addWidget(a)
            row.addStretch(1)
            row.addWidget(b)
            lay.addLayout(row)
        if len(changes) > 14:
            more = QLabel(f"외 {len(changes) - 14}개")
            more.setObjectName("Faint")
            lay.addWidget(more)
        if others:
            names = ", ".join(others[:5]) + (f" 외 {len(others) - 5}장" if len(others) > 5 else "")
            o = QLabel(f"대신 다른 사진 {len(others)}장이 바뀜: {names}\n의도와 다르면 되돌리기를 누르세요"
                       if only_others else f"다른 사진 {len(others)}장도 바뀜: {names}")
            o.setObjectName("Muted" if only_others else "Faint")
            o.setWordWrap(True)
            lay.addWidget(o)
        btns = QHBoxLayout()
        self.show_btn = QPushButton("보정 패널에서 보기")
        self.show_btn.setObjectName("Ghost")
        self.revert_btn = QPushButton("되돌리기")
        self.revert_btn.setObjectName("Ghost")
        self.show_btn.clicked.connect(self.show.emit)
        self.revert_btn.clicked.connect(self.revert.emit)
        self.show_btn.setVisible(bool(changes))
        btns.addWidget(self.show_btn)
        btns.addStretch(1)
        btns.addWidget(self.revert_btn)
        lay.addLayout(btns)

    def mark_reverted(self):
        self.title.setText("되돌렸습니다")
        self.title.setStyleSheet(f"color: {T.TEXT3}; font-weight: 600;")
        self.revert_btn.setEnabled(False)
        self.show_btn.setEnabled(False)


class _Chip(QPushButton):
    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"QPushButton {{ background: {T.BG2}; color: {T.TEXT2}; border: 1px solid {T.LINE};"
                           f" border-radius: 14px; padding: 5px 12px; text-align: left; }}"
                           f"QPushButton:hover {{ color: {T.TEXT}; border-color: {T.ACCENT}; }}")


class _Input(QPlainTextEdit):
    submit = Signal()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.submit.emit()
            return
        super().keyPressEvent(e)


class AssistantPanel(QWidget):
    send = Signal(str)
    stop = Signal()
    new_chat = Signal()
    show_changes = Signal()
    revert_changes = Signal()

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("AI 어시스턴트")
        title.setObjectName("Title")
        sub = QLabel("Claude Code")
        sub.setObjectName("Faint")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(title)
        col.addWidget(sub)
        head.addLayout(col)
        head.addStretch(1)
        self.new_btn = QToolButton()
        self.new_btn.setIcon(T.icon("plus", T.TEXT2, 16))
        self.new_btn.setToolTip("새 대화")
        self.new_btn.clicked.connect(self.new_chat.emit)
        head.addWidget(self.new_btn)
        lay.addLayout(head)
        self.context = QLabel("")
        self.context.setObjectName("Muted")
        self.context.setWordWrap(True)
        self.context.setStyleSheet(f"background: {T.BG2}; border-radius: 8px; padding: 7px 10px; color: {T.TEXT2};")
        lay.addWidget(self.context)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.msgs = QVBoxLayout(holder)
        self.msgs.setContentsMargins(0, 4, 6, 4)
        self.msgs.setSpacing(10)
        self.msgs.addStretch(1)
        self.scroll.setWidget(holder)
        lay.addWidget(self.scroll, 1)

        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(6)
        hint = QLabel("원하는 느낌을 말로 설명하면 Claude가 보정값을 바꿔요.\n결과는 화면에 바로 반영됩니다.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        el.addWidget(hint)
        for s in SUGGESTIONS:
            chip = _Chip(s)
            chip.clicked.connect(lambda _=False, s=s: self._submit(s))
            el.addWidget(chip)
        self.msgs.insertWidget(0, self.empty)

        self.status = QLabel("")
        self.status.setObjectName("Faint")
        lay.addWidget(self.status)
        box = QFrame()
        box.setObjectName("InputBox")
        box.setStyleSheet(f"QFrame#InputBox {{ background: {T.BG0}; border: 1px solid {T.LINE}; border-radius: 12px; }}")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(10, 6, 6, 6)
        self.input = _Input()
        self.input.setPlaceholderText("예: 좀 어둡고 피부가 칙칙해")
        self.input.setStyleSheet(f"QPlainTextEdit {{ background: transparent; border: none; color: {T.TEXT}; }}")
        self.input.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.input.setFixedHeight(54)
        self.input.submit.connect(lambda: self._submit(self.input.toPlainText()))
        self.send_btn = QToolButton()
        self.send_btn.setFixedSize(30, 30)
        self.send_btn.clicked.connect(self._on_send_btn)
        bl.addWidget(self.input, 1)
        bl.addWidget(self.send_btn, 0, Qt.AlignBottom)
        lay.addWidget(box)
        note = QLabel("VSCode의 Claude Code와 같은 요금제 사용량을 씁니다")
        note.setObjectName("Faint")
        lay.addWidget(note)

        self._running = False
        self._current: _Bubble | None = None
        self._dots = 0
        self._timer = QTimer(self, interval=400, timeout=self._tick)
        self._status_base = ""
        self._set_send_icon()

    # ---- 상태
    def _set_send_icon(self):
        if self._running:
            self.send_btn.setIcon(T.icon("stop", T.TEXT, 16))
            self.send_btn.setToolTip("중지")
            self.send_btn.setStyleSheet(f"QToolButton {{ background: {T.BG3}; border-radius: 15px; }}")
        else:
            self.send_btn.setIcon(T.icon("send", "#1d1206", 16))
            self.send_btn.setToolTip("보내기 (Enter)")
            self.send_btn.setStyleSheet(f"QToolButton {{ background: {T.ACCENT}; border-radius: 15px; }}"
                                        f"QToolButton:hover {{ background: {T.ACCENT_HI}; }}")

    def set_context(self, text: str):
        self.context.setText(text)

    def set_running(self, on: bool, status: str = ""):
        self._running = on
        self._set_send_icon()
        self.input.setReadOnly(on)
        self._status_base = status
        if on:
            self._timer.start()
        else:
            self._timer.stop()
        self.status.setText(status)

    def set_unavailable(self, why: str):
        self.input.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.status.setText(why)

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self.status.setText(self._status_base + " " + "•" * self._dots)

    def _on_send_btn(self):
        if self._running:
            self.stop.emit()
        else:
            self._submit(self.input.toPlainText())

    def _submit(self, text: str):
        text = text.strip()
        if not text or self._running:
            return
        self.input.clear()
        self.send.emit(text)

    # ---- 메시지
    def _add(self, w):
        self.empty.setVisible(False)
        self.msgs.insertWidget(self.msgs.count() - 1, w)
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def add_user(self, text: str):
        self._add(_Bubble(text, True))
        self._current = None

    def append_delta(self, s: str):
        if self._current is None:
            self._current = _Bubble("", False)
            self._add(self._current)
        self._current.append(s)
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def end_block(self):
        self._current = None

    def add_tool(self, text: str):
        self._current = None
        self._add(_ToolLine(text))
        self._status_base = text

    def add_changes(self, changes: list, others: list):
        """바뀐 값 카드. 이전 카드의 되돌리기는 막는다 (되돌리기는 가장 최근 AI 작업에만)."""
        if getattr(self, "_card", None) is not None:
            self._card.revert_btn.setEnabled(False)
        card = _ChangeCard(changes, others)
        card.show.connect(self.show_changes.emit)
        card.revert.connect(self.revert_changes.emit)
        self._card = card
        self._add(card)

    def mark_reverted(self):
        if getattr(self, "_card", None) is not None:
            self._card.mark_reverted()

    def add_error(self, text: str):
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet("color: #ff8a80;")
        self._add(lab)

    def clear(self):
        while self.msgs.count() > 2:
            item = self.msgs.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        self.empty.setVisible(True)
        self._current = None
