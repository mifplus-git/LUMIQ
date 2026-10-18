"""OS별 차이를 한곳에: 단축키 표기, 파일 관리자 이름, 폴더 열기·파일 위치 보기.

단축키는 Qt 표기("Ctrl+Shift+C")로 정의한다. Qt가 macOS에서는 Ctrl을 ⌘로 받으므로 동작은 같고,
화면에 보일 글자만 key_text()로 OS에 맞춘다 (macOS ⇧⌘C, Windows Ctrl+Shift+C).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

MAC = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"

FILE_MANAGER = "Finder" if MAC else "파일 탐색기" if WINDOWS else "파일 관리자"
TRASH = "Finder의 휴지통" if MAC else "휴지통"
MULTI_SELECT = "⌘·⇧" if MAC else "Ctrl·Shift"  # 누르고 클릭하면 여러 장 선택
TRASH_KEY = "Ctrl+Backspace" if MAC else "Del"  # macOS ⌘⌫, 그 밖에는 Delete 키
HELP_KEY = "Ctrl+?" if MAC else "F1"  # QKeySequence.HelpContents와 같은 키 (표시용)

_MAC_MODS = [("Meta+", "⌃"), ("Alt+", "⌥"), ("Shift+", "⇧"), ("Ctrl+", "⌘")]  # macOS 표기 순서
_MAC_KEYS = {"Backspace": "⌫", "Del": "⌦", "Return": "↩", "-": "−"}
_KEYS = {"-": "−"}


def key_text(seq: str) -> str:
    """'Ctrl+Shift+C' → macOS '⇧⌘C', 그 밖에는 'Ctrl+Shift+C'. 두 칸 띄워 여러 키를 한 번에 줄 수 있다."""
    if "  " in seq:
        return "  ".join(key_text(s) for s in seq.split("  "))
    rest, mods = seq, set()
    while True:
        m = next((m for m, _ in _MAC_MODS if rest.startswith(m) and len(rest) > len(m)), None)
        if m is None:
            break
        mods.add(m)
        rest = rest[len(m):]
    if MAC:
        return "".join(sym for m, sym in _MAC_MODS if m in mods) + _MAC_KEYS.get(rest, rest)
    return "".join(m for m in ("Ctrl+", "Alt+", "Shift+", "Meta+") if m in mods) + _KEYS.get(rest, rest)


def open_folder(folder):
    """폴더를 Finder·파일 탐색기·파일 관리자로 연다."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def reveal(path):
    """파일이 있는 폴더를 열고 그 파일을 선택해 보여 준다 (Linux는 폴더만 연다)."""
    path = Path(path)
    try:
        if MAC:
            subprocess.Popen(["open", "-R", str(path)])
            return
        if WINDOWS:
            subprocess.Popen(f'explorer /select,"{path}"')
            return
    except OSError:
        pass
    open_folder(path.parent)
