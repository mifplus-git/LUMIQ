"""LUMIQ Studio 메인 창.

기본은 보기 모드(그리드 또는 한 장 + 필름스트립)이고, 편집(E)을 누르면 보정 패널이 있는 편집 화면이 된다.
1·2·3 키로 별점을 매기고(0은 지움) 별점 필터로 골라 볼 수 있다.
사진을 오른쪽 클릭하면 휴지통으로 이동·위치(GPS) 추가 같은 메뉴가 나온다 (여러 장 선택 시 선택한 사진 모두).
보정값은 사진 옆 <사진 파일 이름>.lumiq.json에 바로 저장된다. Claude Code(VSCode 또는 오른쪽 AI 패널)가 같은 파일을 고치면
앱에 즉시 반영되고, 앱에서 고친 값도 Claude Code가 그대로 읽는다.
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QEvent, QFile, QFileSystemWatcher, QSettings, QSize, Qt, QThread, QThreadPool, QTimer,
                            QUrl, Signal)
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressDialog, QPushButton, QRadioButton, QScrollArea, QSpinBox,
                               QSplitter, QStackedWidget, QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from pipeline import files, geometry as G, params as P
from pipeline.decode import is_raw
from pipeline.lut import lut_dirs, lut_files
from pipeline.params import DATA, HSL_BANDS, ROOT

from . import native as N
from . import theme as T
from .assistant import CLI, AssistantPanel, ClaudeRunner, find_claude, guide_text
from .engine import Engine, RenderResult
from .help import AboutDialog, HelpDialog
from .icon import draw_icon
from .location import LocationDialog, gps_label, load_recent, parse_coords, remember
from .widgets import (HUE_STOPS, TEMP_STOPS, TINT_STOPS, Filmstrip, Histogram, ImageView, Section, SliderRow,
                      StarRating, ThumbDelegate, del_nested, get_nested, set_nested)
from .workers import ExifJob, ExifSignals, ExportWorker, RenderWorker, ThumbJob, ThumbSignals

APP_NAME = "LUMIQ Studio"
SLOGAN = "빛을 이해하고, 사진을 완성하다."  # 브랜드 슬로건 (Brand Identity 1.0)
SLOGAN_EN = "Understand the Light. Perfect the Image."
FORMATS = "RAW · JPG · HEIC · PNG · WebP · TIFF"
VERSION = "1.0"  # tools/build_app.py의 CFBundleShortVersionString과 맞춘다
GITHUB_URL = "https://github.com/mifplus-git/LUMIQ"
MANY_PHOTOS = 5000  # 하위 폴더까지 이보다 많으면 열기 전에 묻는다
BAND_KO = {"red": "빨강", "orange": "주황", "yellow": "노랑", "green": "초록", "aqua": "아쿠아",
           "blue": "파랑", "purple": "보라", "magenta": "마젠타"}
# 한 글자 단축키: Shift를 누르거나 한글 입력 상태여도 같은 키로 동작 (표시는 E·G만)
#   글자 → (Qt 키, macOS 물리 키 코드)
LETTER_KEYS = {"edit": ({"e", "E", "ㄷ", "ㄸ"}, Qt.Key_E, 0x0E), "grid": ({"g", "G", "ㅎ"}, Qt.Key_G, 0x05)}
CROP_RATIOS = [("원본 비율", "original"), ("자유", None), ("1:1", "1:1"), ("4:5", "4:5"), ("3:2", "3:2"),
               ("16:9", "16:9"), ("5:7", "5:7")]
ROT90 = [None, "cw", "180", "ccw"]
SEASONS = ("spring", "summer", "autumn", "winter")  # 프리셋 목록을 계절 순서로 묶는다
BRIGHT_STOPS = [(0, "#2e2e33"), (0.5, "#85858c"), (1, "#f4f4f6")]
PASTE_SKIP = {"file", "crop_center", "crop_rect", "gps", "rating"}
# 별점 1~3: 숫자 키로 매기고 0으로 지운다 (키패드 숫자도 같음). 보정값이 아니라 보정값 파일의 rating에만 저장
RATING_KEYS = {Qt.Key_0: 0, Qt.Key_1: 1, Qt.Key_2: 2, Qt.Key_3: 3}
RATING_STARS = {1: "★", 2: "★★", 3: "★★★"}
# 별점 필터: (메뉴 이름, 버튼에 보일 짧은 이름, 값). 값 n은 n개 이상, 0은 별점 없는 사진만
RATING_FILTERS = [("모든 사진", "", None), ("★ 1개 이상", "1개 이상", 1), ("★★ 2개 이상", "2개 이상", 2),
                  ("★★★ 3개", "3개", 3), ("별점 없는 사진", "별점 없음", 0)]
# 그리드 보기 옵션: 칸 너비(px). 칸 높이는 모양(맞춤/정사각형)과 이름 표시에 따라 정한다
GRID_SIZES = [("작게", 150), ("보통", 214), ("크게", 290), ("아주 크게", 380)]
GRID_SHAPES = [("맞춤 (사진 전체)", "fit"), ("정사각형 (꽉 채우기)", "square")]
SIDECAR_EXTS = (".yaml", ".yml", ".xmp")  # 사진을 휴지통으로 옮길 때 함께 옮기는 같은 이름의 설정 파일
STATE_FILE = DATA / ".app_state.json"
CURRENT_PREVIEW = DATA / "previews" / "_app_current.jpg"


def to_qimage(arr) -> QImage:
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def hline():
    f = QFrame()
    f.setObjectName("Divider")
    return f


# ====================================================================== 내보내기 대화상자

class ExportDialog(QDialog):
    def __init__(self, parent, n_selected: int, n_all: int, out_dir: Path, settings: QSettings,
                 has_subfolders: bool = False, all_label: str = "폴더 전체"):
        super().__init__(parent)
        self.setWindowTitle("내보내기")
        self.settings = settings
        self.default_out = out_dir
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(14)
        title = QLabel("내보내기")
        title.setObjectName("Title")
        lay.addWidget(title)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.sel = QRadioButton(f"선택한 사진 ({n_selected}장)")
        self.all = QRadioButton(f"{all_label} ({n_all}장)")
        (self.sel if n_selected >= 1 else self.all).setChecked(True)
        if settings.value("export/scope") == "all":
            self.all.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.sel)
        grp.addButton(self.all)
        box = QVBoxLayout()
        box.addWidget(self.sel)
        box.addWidget(self.all)
        form.addRow("대상", box)
        self.size = QComboBox()
        for label, v in (("원본 크기", 0), ("긴 변 4096px", 4096), ("긴 변 3000px", 3000), ("긴 변 2048px", 2048),
                         ("긴 변 1080px (SNS)", 1080), ("직접 입력", -1)):
            self.size.addItem(label, v)
        self.custom = QSpinBox()
        self.custom.setRange(256, 20000)
        self.custom.setValue(int(settings.value("export/custom", 2500)))
        self.custom.setSuffix(" px")
        self.custom.setEnabled(False)
        self.size.currentIndexChanged.connect(lambda _: self.custom.setEnabled(self.size.currentData() == -1))
        self.size.setCurrentIndex(max(self.size.findData(int(settings.value("export/size", 0))), 0))
        row = QHBoxLayout()
        row.addWidget(self.size, 1)
        row.addWidget(self.custom)
        form.addRow("크기", row)
        self.quality = QSpinBox()
        self.quality.setRange(50, 100)
        self.quality.setValue(int(settings.value("export/quality", 92)))
        form.addRow("JPEG 품질", self.quality)
        self.out = QLineEdit(str(out_dir))
        self.out.setObjectName("Field")
        btn = QPushButton("변경…")
        btn.clicked.connect(self._choose)
        row = QHBoxLayout()
        row.addWidget(self.out, 1)
        row.addWidget(btn)
        form.addRow("저장 폴더", row)
        self.reveal = QCheckBox(f"끝나면 {N.FILE_MANAGER}에서 열기")
        self.reveal.setChecked(settings.value("export/reveal", "true") == "true")
        form.addRow("", self.reveal)
        lay.addLayout(form)
        text = ("원본은 바뀌지 않습니다. 같은 이름이 있으면 _1, _2를 붙여 저장합니다. EXIF·GPS는 그대로 복사되고,"
                " 앱에서 추가한 위치가 있으면 그 위치로 기록합니다.")
        if has_subfolders:
            text += ("\n하위 폴더의 사진은 각 폴더의 export에 저장합니다. 저장 폴더를 바꾸면 그 안에 같은 하위 폴더 구조로"
                     " 저장합니다.")
        note = QLabel(text)
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)
        bb = QDialogButtonBox()
        ok = bb.addButton("내보내기", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton("취소", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.setMinimumWidth(520)

    def _choose(self):
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.out.text())
        if d:
            self.out.setText(d)

    def values(self):
        size = self.size.currentData()
        if size == -1:
            size = self.custom.value()
        s = self.settings
        s.setValue("export/size", self.size.currentData())
        s.setValue("export/custom", self.custom.value())
        s.setValue("export/quality", self.quality.value())
        s.setValue("export/reveal", "true" if self.reveal.isChecked() else "false")
        s.setValue("export/scope", "all" if self.all.isChecked() else "sel")
        out = Path(self.out.text()).expanduser()
        return {"all": self.all.isChecked(), "size": size or None, "quality": self.quality.value(),
                "out": None if out == self.default_out else out,  # None: 사진마다 그 폴더의 export/
                "reveal": self.reveal.isChecked()}


# ====================================================================== 설정

class SettingsDialog(QDialog):
    """앱 설정: RAW 카메라 톤 기본값 · 편집 화면 썸네일 위치 · 편집을 마칠 때 저장 여부 묻기."""

    def __init__(self, parent, camera_default: bool, thumbs: str, ask_save: bool):
        super().__init__(parent)
        self.setWindowTitle("설정")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        title = QLabel("설정")
        title.setObjectName("Title")
        lay.addWidget(title)

        def head(text):
            t = QLabel(text)
            t.setObjectName("SectionTitle")
            lay.addSpacing(6)
            lay.addWidget(t)

        def note(text):
            n = QLabel(text)
            n.setObjectName("Faint")
            n.setWordWrap(True)
            lay.addWidget(n)

        head("RAW 사진")
        self.camera = QCheckBox("카메라 톤 맞추기를 기본으로 켜기")
        self.camera.setChecked(camera_default)
        lay.addWidget(self.camera)
        note("RAW 안의 카메라 JPEG(액티브 D-라이팅·픽처 컨트롤이 들어간 밝기·채도)에 맞춰 기본 톤을 잡습니다. "
             "편집 패널의 '카메라 톤'으로 사진마다 따로 켜고 끌 수 있고, 따로 정한 사진은 이 설정을 따르지 않습니다. "
             "따로 정하지 않은 사진은 이미 보정했어도 밝기가 바뀝니다. CLI·Claude Code의 미리보기·내보내기도 같은 값을 씁니다.")
        head("편집 화면")
        row = QHBoxLayout()
        row.addWidget(QLabel("썸네일 위치"))
        self.left = QRadioButton("왼쪽")
        self.bottom = QRadioButton("아래")
        (self.bottom if thumbs == "bottom" else self.left).setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.left)
        grp.addButton(self.bottom)
        row.addSpacing(10)
        row.addWidget(self.left)
        row.addWidget(self.bottom)
        row.addStretch(1)
        lay.addLayout(row)
        self.ask = QCheckBox("편집을 마칠 때 저장할지 묻기")
        self.ask.setChecked(ask_save)
        lay.addWidget(self.ask)
        bb = QDialogButtonBox()
        ok = bb.addButton("확인", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton("취소", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addSpacing(6)
        lay.addWidget(bb)
        self.setMinimumWidth(500)

    def values(self) -> tuple[bool, str, bool]:
        return self.camera.isChecked(), "bottom" if self.bottom.isChecked() else "left", self.ask.isChecked()


# ====================================================================== 프리셋 삭제 대화상자

class PresetDeleteDialog(QDialog):
    """프리셋을 골라 지운다. 내가 만든·가져온 프리셋은 휴지통으로, 기본 프리셋은 목록에서 숨긴다."""

    def __init__(self, parent, items: list[tuple[str, str, bool, int]], n_hidden: int):
        super().__init__(parent)
        self.setWindowTitle("프리셋 삭제")
        self.restore = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        title = QLabel("프리셋 삭제")
        title.setObjectName("Title")
        lay.addWidget(title)
        note = QLabel("지울 프리셋을 체크하세요. 내가 만들거나 가져온 프리셋은 휴지통으로 옮기고(되살릴 수 있음), "
                      "앱 기본 프리셋은 목록에서 숨깁니다. 그 프리셋을 쓰던 사진은 프리셋 없이 보입니다.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.list = QListWidget()
        self.list.setMinimumHeight(320)
        for name, label, builtin, used in items:
            extra = ["기본" if builtin else "내 프리셋"] + ([f"열린 폴더 {used}장이 사용 중"] if used else [])
            it = QListWidgetItem(f"{label}    ·  {' · '.join(extra)}")
            it.setData(Qt.UserRole, name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setToolTip(f"presets/{name}.yaml")
            self.list.addItem(it)
        self.list.itemClicked.connect(lambda it: it.setCheckState(
            Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked))
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox()
        self.ok = bb.addButton("선택한 프리셋 삭제", QDialogButtonBox.AcceptRole)
        self.ok.setObjectName("Primary")
        if n_hidden:
            again = bb.addButton(f"숨긴 기본 프리셋 다시 보이기 ({n_hidden})", QDialogButtonBox.ResetRole)
            again.clicked.connect(self._restore)
        bb.addButton("닫기", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.setMinimumWidth(520)

    def _restore(self):
        self.restore = True
        self.accept()

    def chosen(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


# ====================================================================== 메인 창

class MainWindow(QMainWindow):
    request_render = Signal()

    def __init__(self, start_folder: str | None = None):
        super().__init__()
        self.settings = QSettings("lumiq", APP_NAME)
        if not self.settings.allKeys():  # 이전 이름(RAW Fix)의 최근 폴더·창 크기를 옮겨 온다
            old = QSettings("raw_fix", "RAW Fix")
            for k in old.allKeys():
                self.settings.setValue(k, old.value(k))
        self.mode = "view"  # view: 보기 / edit: 편집
        self._edit_session: dict[str, dict] | None = None  # 편집 모드에 들어온 뒤 손댄 사진 → 그때의 보정값
        self.layout_mode = self.settings.value("view/layout", "grid")  # 보기 모드: grid / single
        if self.layout_mode not in ("grid", "single"):
            self.layout_mode = "grid"
        self._crop_after_render = False
        self._render_pending = False
        self._status_timer = QTimer(self, singleShot=True,
                                    timeout=lambda: self.statusBar().setVisible(self.mode == "edit"))
        self.engine = Engine()
        self.folder: Path | None = None
        self.photos: list[Path] = []
        self.subfolders: list[Path] = []
        self.current: Path | None = None
        self.edit: dict = {}
        self.result: RenderResult | None = None
        self.show_before = False
        self._gen = 0
        self._shown_gen = -1
        self._undo: dict[str, list] = {}
        self._redo: dict[str, list] = {}
        self._last_push = (0.0, None)
        self._clipboard: dict | None = None
        self._prefetch_pending = False
        self._note = ("", 0.0)
        self._crop_wait = False
        self._crop_level = 0.0
        self._thumbs: dict[str, QListWidgetItem] = {}
        self._edited: set[str] = set()
        self._gps: set[str] = set()  # 앱(보정값 파일)에서 위치를 추가한 사진
        self._ratings: dict[str, int] = {}  # 사진 경로 → 별점 1~3
        self.rating_filter: int | None = None  # 별점 필터 (RATING_FILTERS의 값, None이면 모든 사진)
        s = self.settings
        self.grid_shape = s.value("grid/shape", "fit") if s.value("grid/shape") in ("fit", "square") else "fit"
        try:
            self.grid_size = min(max(int(s.value("grid/size", 1)), 0), len(GRID_SIZES) - 1)
        except (TypeError, ValueError):
            self.grid_size = 1
        self.grid_names = s.value("grid/names", "true") == "true"
        self.edit_thumbs = "bottom" if s.value("edit/thumbs") == "bottom" else "left"  # 편집 화면 썸네일: 왼쪽 / 아래
        self.rows: dict[str, SliderRow] = {}
        self.sections: list[tuple[Section, list[str]]] = []
        self.pool = QThreadPool.globalInstance()
        self.thumb_signals = ThumbSignals()
        self.thumb_signals.done.connect(self._on_thumb)
        self.exif_signals = ExifSignals()
        self.exif_signals.done.connect(self._on_exif)
        self.claude_path = find_claude()
        self.runner = ClaudeRunner(self)

        self._build_ui()
        self._build_menus()
        self._start_render_thread()
        self._wire_assistant()

        self._render_timer = QTimer(self, singleShot=True, interval=30, timeout=self._do_render)
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save_now)
        self._reload_timer = QTimer(self, singleShot=True, interval=250, timeout=self._reload_from_disk)
        self._state_timer = QTimer(self, singleShot=True, interval=1200, timeout=self._write_state)
        # 열린 사진 폴더들과 지금 사진의 보정값 파일을 지켜본다 (Claude Code가 고치거나 새로 만들면 다시 불러옴)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self._reload_timer.start())
        self.watcher.fileChanged.connect(lambda _: self._reload_timer.start())
        QTimer.singleShot(0, self._migrate_legacy)

        self._set_has_photo(False)
        self._apply_mode()
        geo = self.settings.value("window/geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1480, 920)
        folder = start_folder or self.settings.value("folder/last")
        if folder and Path(folder).expanduser().is_dir():
            QTimer.singleShot(0, lambda: self.open_folder(Path(folder).expanduser()))
        else:
            self._show_welcome()

    # ================================================================== UI 구성
    def _build_ui(self):
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._build_topbar())
        rl.addWidget(hline())
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        self.left_panel = self._build_left()
        self.right_panel = self._build_right()
        split.addWidget(self.left_panel)
        split.addWidget(self._build_center())
        split.addWidget(self.right_panel)
        split.setStretchFactor(1, 1)
        split.setSizes([210, 920, 350])
        rl.addWidget(split, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("")

    def _tool(self, icon_name, tip, fn, text=None, checkable=False, size=18):
        b = QToolButton()
        b.setIcon(T.icon(icon_name, T.TEXT2, size))
        b.setIconSize(QSize(size, size))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if text:
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.clicked.connect(fn)
        return b

    def _segment(self, specs):
        """둥근 배경 위 탭 버튼 묶음. specs: [(글자, 아이콘, 툴팁)] → (위젯, 버튼 그룹)"""
        seg = QWidget()
        seg.setObjectName("Segment")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        seg.setStyleSheet(f"QWidget#Segment {{ background: {T.BG2}; border-radius: 9px; }}")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for i, (text, ic, tip) in enumerate(specs):
            b = QToolButton()
            b.setText(" " + text)
            b.setIcon(T.icon(ic, T.TEXT2, 15))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setSizePolicy(b.sizePolicy().horizontalPolicy().Expanding, b.sizePolicy().verticalPolicy())
            b.setStyleSheet(f"QToolButton {{ padding: 6px 10px; border-radius: 7px; color: {T.TEXT2}; }}"
                            f"QToolButton:checked {{ background: {T.BG3}; color: {T.TEXT}; }}")
            sl.addWidget(b, 1)
            grp.addButton(b, i)
        return seg, grp

    def _build_topbar(self):
        bar = QWidget()
        bar.setObjectName("Panel")
        bar.setFixedHeight(52)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(4)
        self.open_btn = self._tool("folder", f"폴더 열기 ({N.key_text('Ctrl+O')})", self.choose_folder)
        lay.addWidget(self.open_btn)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.folder_title = QLabel(T.wordmark(APP_NAME))
        self.folder_title.setObjectName("Title")
        self.folder_sub = QLabel("폴더를 열어 시작하세요")
        self.folder_sub.setObjectName("Faint")
        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        title_row.addWidget(self.folder_title)
        self.close_folder_btn = self._tool("close", "폴더 닫기 (처음 화면으로)", self.close_folder, size=12)
        self.close_folder_btn.setFixedSize(20, 20)
        self.close_folder_btn.setVisible(False)
        title_row.addWidget(self.close_folder_btn)
        title_row.addStretch(1)
        col.addLayout(title_row)
        col.addWidget(self.folder_sub)
        lay.addLayout(col)
        lay.addStretch(1)
        # 보기 모드: 그리드 / 한 장
        self.view_seg, grp = self._segment([("그리드", "grid", "그리드 보기 (G)"),
                                            ("한 장", "photo", "한 장씩 보기 (그리드에서 Enter·더블클릭)")])
        self.grid_btn, self.single_btn = grp.button(0), grp.button(1)
        grp.idClicked.connect(lambda i: self.go_view(("grid", "single")[i]))
        lay.addWidget(self.view_seg)
        self.grid_opts_btn = self._tool("tiles", "그리드 보기 옵션 — 모양 · 크기 · 이름 표시", lambda: None)
        self.grid_opts_btn.setPopupMode(QToolButton.InstantPopup)
        self.grid_opts_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        lay.addWidget(self.grid_opts_btn)
        self.filter_btn = self._tool("star", "별점 필터 — 별점으로 골라 보기", lambda: None)
        self.filter_btn.setPopupMode(QToolButton.InstantPopup)
        self.filter_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        lay.addWidget(self.filter_btn)
        # 편집 모드 도구
        self.crop_btn = self._tool("crop", "자르기·회전 (R)", self.toggle_crop, "자르기", checkable=True)
        self.compare_btn = self._tool("compare", "보정 전·후 비교 (\\) — 가운데 선을 좌우로 끌어 보세요",
                                      self._toggle_compare, "비교", checkable=True)
        lay.addWidget(self.crop_btn)
        lay.addWidget(self.compare_btn)
        lay.addStretch(1)
        self.undo_btn = self._tool("undo", f"실행 취소 ({N.key_text('Ctrl+Z')})", self.undo)
        self.redo_btn = self._tool("redo", f"다시 실행 ({N.key_text('Ctrl+Shift+Z')})", self.redo)
        self.copy_btn = self._tool("copy", f"설정 복사 ({N.key_text('Ctrl+Shift+C')})", self.copy_settings)
        self.paste_btn = self._tool("paste", f"선택한 사진에 붙여넣기 ({N.key_text('Ctrl+Shift+V')})", self.paste_settings)
        for b in (self.undo_btn, self.redo_btn):
            lay.addWidget(b)
        lay.addSpacing(8)
        for b in (self.copy_btn, self.paste_btn):
            lay.addWidget(b)
        lay.addSpacing(12)
        self._edit_tools = (self.crop_btn, self.compare_btn, self.undo_btn, self.redo_btn, self.copy_btn,
                            self.paste_btn)
        self.edit_btn = QPushButton()
        self.edit_btn.clicked.connect(self.toggle_edit)
        lay.addWidget(self.edit_btn)
        lay.addSpacing(4)
        self.export_btn = QPushButton("  내보내기")
        self.export_btn.setObjectName("Primary")
        self.export_btn.setIcon(T.icon("export", "#1d1206", 16))
        self.export_btn.setToolTip(f"내보내기 ({N.key_text('Ctrl+E')})")
        self.export_btn.clicked.connect(self.export_dialog)
        lay.addWidget(self.export_btn)
        lay.addSpacing(2)
        lay.addWidget(self._tool("help", f"사용법 · 단축키 ({N.key_text(N.HELP_KEY)})", self.show_help, size=19))
        return bar

    def _build_left(self):
        left = QWidget()
        left.setObjectName("Panel")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 10, 2, 6)
        ll.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 6, 0)
        t = QLabel("사진")
        t.setObjectName("SectionTitle")
        self.count_label = QLabel("")
        self.count_label.setObjectName("Faint")
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(self.count_label)
        ll.addLayout(head)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setFlow(QListView.LeftToRight)
        self.list.setWrapping(True)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        self.list.setItemDelegate(ThumbDelegate(self.list))
        self.list.setGridSize(QSize(ThumbDelegate.W, ThumbDelegate.H))
        self.list.setMouseTracking(True)
        self.list.currentItemChanged.connect(self._on_current_item)
        self.list.itemSelectionChanged.connect(self._on_selection)
        ll.addWidget(self.list, 1)
        left.setMinimumWidth(184)
        return left

    def _build_center(self):
        center = QWidget()
        center.setObjectName("Canvas")
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self._build_welcome())
        viewer = QWidget()
        vl = QVBoxLayout(viewer)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        self.view = ImageView()
        self.view.clicked_empty.connect(self.choose_folder)
        self.view.hold.connect(self._on_hold)
        self.view.zoom_changed.connect(self._on_zoom)
        self.view.crop_changed.connect(self._on_crop_angle)
        self.view.crop_commit.connect(lambda: self.leave_crop(apply=True))
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._view_menu)
        vl.addWidget(self.view, 1)
        self.info_bar = self._build_info_bar()
        self.crop_bar = self._build_crop_bar()
        self.crop_bar.setVisible(False)
        vl.addWidget(self.info_bar)
        vl.addWidget(self.crop_bar)
        # 그리드·필름스트립은 왼쪽 목록(self.list)과 모델·선택을 함께 쓴다 (썸네일·배지·선택이 한 번에 맞춰짐)
        self.filmstrip = Filmstrip()
        self.filmstrip.setObjectName("Filmstrip")
        self.filmstrip.setViewMode(QListView.IconMode)
        self.filmstrip.setFlow(QListView.LeftToRight)
        self.filmstrip.setWrapping(False)
        self.filmstrip.setMovement(QListView.Static)
        self.filmstrip.setUniformItemSizes(True)
        self.filmstrip.setItemDelegate(ThumbDelegate(self.filmstrip, 92, 72, names=False, pins=False))
        self.filmstrip.setGridSize(QSize(92, 72))
        self.filmstrip.setFixedHeight(72 + 10)
        self.filmstrip.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.filmstrip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.filmstrip.setMouseTracking(True)
        self._share_list(self.filmstrip)
        vl.addWidget(self.filmstrip)
        self.center_stack.addWidget(viewer)
        self.grid = QListView()
        self.grid.setObjectName("Grid")
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setFlow(QListView.LeftToRight)
        self.grid.setWrapping(True)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setSelectionMode(QListView.ExtendedSelection)
        self.grid.setUniformItemSizes(True)
        self.grid_delegate = ThumbDelegate(self.grid, 214, 184)
        self.grid.setItemDelegate(self.grid_delegate)
        self.grid.setMouseTracking(True)
        self._share_list(self.grid)
        self.grid.doubleClicked.connect(lambda _: self.set_mode("view", "single"))
        self.center_stack.addWidget(self.grid)
        self._apply_grid_options()
        for v in (self.grid, self.filmstrip, self.list):  # 오른쪽 클릭 메뉴
            v.setContextMenuPolicy(Qt.CustomContextMenu)
            v.customContextMenuRequested.connect(lambda pos, v=v: self._list_menu(v, pos))
        cl.addWidget(self.center_stack)
        return center

    def _share_list(self, view: QListView):
        view.setModel(self.list.model())
        old = view.selectionModel()
        view.setSelectionModel(self.list.selectionModel())
        old.deleteLater()

    def eventFilter(self, obj, e):
        """앱 전체 키 입력: 그리드의 Enter·Space, E·G 단축키 (Shift·한글 ㄷ·ㄸ·ㅎ 포함), 별점 0~3."""
        if e.type() == QEvent.KeyPress:
            if obj is self.grid and e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.set_mode("view", "single")
                return True
            if e.key() in RATING_KEYS and self._plain_key(obj, e):
                self.set_rating(RATING_KEYS[e.key()])
                return True
            action = self._letter_action(obj, e)
            if action == "edit":
                self.toggle_edit()
                return True
            if action == "grid":
                self.go_view("grid")
                return True
        return super().eventFilter(obj, e)

    def _plain_key(self, obj, e) -> bool:
        """한 글자 단축키로 받을 키인지: 이 창에서, ⌘·⌃·⌥ 없이, 글자를 입력하는 중이 아닐 때."""
        if e.isAutoRepeat() or not isinstance(obj, QWidget) or obj.window() is not self:
            return False
        if e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier):
            return False
        fw = QApplication.focusWidget()
        return not ((fw is not None and fw is not obj) or self._typing(fw) or self._typing(obj))

    def _letter_action(self, obj, e) -> str | None:
        if not self._plain_key(obj, e):
            return None
        text = e.text()
        for action, (texts, key, mac_key) in LETTER_KEYS.items():
            if text in texts or e.key() == key:
                return action
            if text and not text.isascii() and e.nativeVirtualKey() == mac_key:  # 다른 한글 자판
                return action
        return None

    @staticmethod
    def _typing(fw) -> bool:
        if isinstance(fw, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
            return True
        return isinstance(fw, QComboBox) and fw.isEditable()

    def _build_welcome(self):
        w = QWidget()
        w.setObjectName("Canvas")
        outer = QVBoxLayout(w)
        outer.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(10)
        logo = QLabel()
        pm = QPixmap.fromImage(draw_icon(256))
        pm.setDevicePixelRatio(2)
        logo.setPixmap(pm)
        logo.setAlignment(Qt.AlignCenter)
        title = QLabel(T.wordmark(APP_NAME))
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet(f"font-size: 26px; font-weight: 700; color: {T.TEXT};")
        title.setAlignment(Qt.AlignCenter)
        bar = QFrame()  # 이름과 슬로건 사이 짧은 강조선
        bar.setFixedSize(28, 2)
        bar.setStyleSheet(f"background: {T.ACCENT}; border: none;")
        slogan = QLabel(SLOGAN)
        slogan.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {T.TEXT};")
        slogan.setAlignment(Qt.AlignCenter)
        slogan_en = QLabel(SLOGAN_EN)
        slogan_en.setStyleSheet(f"font-size: 12px; color: {T.ACCENT_HI}; letter-spacing: 1px;")
        slogan_en.setAlignment(Qt.AlignCenter)
        sub = QLabel(f"사진 폴더를 열어 시작하세요  ·  {FORMATS}")
        sub.setObjectName("Muted")
        sub.setAlignment(Qt.AlignCenter)
        btn = QPushButton("  폴더 열기")
        btn.setObjectName("Primary")
        btn.setIcon(T.icon("folder", "#1d1206", 16))
        btn.setFixedWidth(180)
        btn.clicked.connect(self.choose_folder)
        hint = QLabel("또는 폴더를 이 창에 끌어다 놓으세요")
        hint.setObjectName("Faint")
        hint.setAlignment(Qt.AlignCenter)
        how = QPushButton("사용법 보기")
        how.setObjectName("Ghost")
        how.clicked.connect(self.show_help)
        col.addWidget(logo)
        col.addWidget(title)
        col.addSpacing(2)
        col.addWidget(bar, 0, Qt.AlignCenter)
        col.addSpacing(2)
        pair = QVBoxLayout()  # 한국어·영어 슬로건은 한 덩어리로 붙인다
        pair.setSpacing(3)
        pair.addWidget(slogan)
        pair.addWidget(slogan_en)
        col.addLayout(pair)
        col.addSpacing(10)
        col.addWidget(sub)
        col.addSpacing(8)
        col.addWidget(btn, 0, Qt.AlignCenter)
        col.addWidget(hint)
        col.addWidget(how, 0, Qt.AlignCenter)
        col.addSpacing(18)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        col.addLayout(self.recent_box)
        outer.addLayout(col)
        outer.addStretch(2)
        return w

    def _build_info_bar(self):
        bar = QWidget()
        bar.setFixedHeight(40)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 8)
        self.info_name = QLabel("")
        self.info_name.setStyleSheet(f"color: {T.TEXT}; font-weight: 600;")
        self.info_meta = QLabel("")
        self.info_meta.setObjectName("Muted")
        lay.addWidget(self.info_name)
        lay.addSpacing(10)
        self.stars = StarRating()
        self.stars.rated.connect(lambda n: self.set_rating(n, [self.current] if self.current else []))
        lay.addWidget(self.stars)
        lay.addSpacing(10)
        lay.addWidget(self.info_meta)
        lay.addStretch(1)
        self.info_hint = QLabel("누르고 있으면 보정 전")
        self.info_hint.setObjectName("Faint")
        lay.addWidget(self.info_hint)
        lay.addSpacing(14)
        # 화면 확대 (사진 크기가 아니라 보이는 크기): − 맞춤 +
        zl = QHBoxLayout()
        zl.setSpacing(0)
        zl.addWidget(self._tool("minus", f"축소 ({N.key_text('Ctrl+-')})", lambda: self._zoom(-1), size=14))
        self.zoom_label = QPushButton("맞춤")
        self.zoom_label.setObjectName("Ghost")
        self.zoom_label.setFixedWidth(86)
        self.zoom_label.setToolTip(f"원본 대비 크기 (100% = 원본 한 픽셀이 화면 한 픽셀). 누르면 화면에 맞추기 ({N.key_text('Ctrl+0')})\n"
                                   f"스크롤 · 트랙패드 벌리기 · {N.key_text('Ctrl++  Ctrl+-')}로 확대·축소, 더블클릭은 맞춤 ↔ 100%, 확대 중에는 끌어서 이동\n"
                                   "화면용 미리보기(긴 변 1600px)를 키워 보여 주므로 크게 확대하면 내보낸 결과보다 흐립니다")
        self.zoom_label.clicked.connect(self.view.reset_zoom)
        zl.addWidget(self.zoom_label)
        zl.addWidget(self._tool("plus", f"확대 ({N.key_text('Ctrl++')})", lambda: self._zoom(1), size=14))
        lay.addLayout(zl)
        return bar

    def _build_crop_bar(self):
        bar = QWidget()
        bar.setObjectName("CropBar")  # 선택자로 범위를 좁혀야 안쪽 버튼 스타일이 덮이지 않는다
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(f"QWidget#CropBar {{ background: {T.BG1}; border-top: 1px solid {T.LINE}; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(8)
        lab = QLabel("비율")
        lab.setObjectName("Muted")
        lay.addWidget(lab)
        self.ratio_combo = QComboBox()
        for label, v in CROP_RATIOS:
            self.ratio_combo.addItem(label, v)
        self.ratio_combo.currentIndexChanged.connect(self._on_ratio)
        lay.addWidget(self.ratio_combo)
        self.swap_btn = self._tool("swap", "가로·세로 바꾸기 (X)", self._swap_ratio)
        lay.addWidget(self.swap_btn)
        lay.addSpacing(10)
        self.angle_row = SliderRow("crop.angle", "각도", -45, 45, 0.1, 1, 0, suffix="°")
        self.angle_row.label.setFixedWidth(34)
        self.angle_row.changed.connect(lambda k, v: self.view.set_angle(float(v)))
        self.angle_row.reset.connect(lambda k: (self.view.set_angle(0.0, emit=True)))
        self.angle_row.setMinimumWidth(260)
        lay.addWidget(self.angle_row, 1)
        lay.addWidget(self._tool("level", "자동 수평", self._auto_level_crop, "자동 수평"))
        lay.addWidget(self._tool("reset", "자르기·회전 초기화", self._reset_crop, "초기화"))
        lay.addSpacing(10)
        cancel = QPushButton("취소")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(lambda: self.leave_crop(apply=False))
        done = QPushButton("완료")
        done.setObjectName("Primary")
        done.setToolTip("Enter 또는 R")
        done.clicked.connect(lambda: self.leave_crop(apply=True))
        lay.addWidget(cancel)
        lay.addWidget(done)
        return bar

    def _build_right(self):
        right = QWidget()
        right.setObjectName("Panel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 10, 10, 8)
        rl.setSpacing(10)
        seg, grp = self._segment([("보정", "sliders", ""), ("AI 어시스턴트", "sparkle", f"AI 어시스턴트 ({N.key_text('Ctrl+K')})")])
        self.tab_adjust, self.tab_ai = grp.button(0), grp.button(1)
        self.tab_adjust.setChecked(True)
        rl.addWidget(seg)
        self.right_stack = QStackedWidget()
        grp.idClicked.connect(self.right_stack.setCurrentIndex)
        self.right_stack.addWidget(self._build_adjust_page())
        self.assistant = AssistantPanel()
        self.right_stack.addWidget(self.assistant)
        rl.addWidget(self.right_stack, 1)
        right.setMinimumWidth(330)
        right.setMaximumWidth(440)
        return right

    def _build_adjust_page(self):
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.hist = Histogram()
        pl.addWidget(self.hist)
        pl.addWidget(self._build_preset_card())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QWidget()
        self.panel_layout = QVBoxLayout(panel)
        self.panel_layout.setContentsMargins(0, 0, 8, 0)
        self.panel_layout.setSpacing(0)
        self._build_sections()
        self.panel_layout.addStretch(1)
        scroll.setWidget(panel)
        pl.addWidget(scroll, 1)
        self.adjust_scroll = scroll
        self.adjust_page = page
        return page

    def _build_preset_card(self):
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 10, 10)
        lay.setSpacing(8)
        row = QHBoxLayout()
        lab = QLabel("프리셋")
        lab.setObjectName("Muted")
        lab.setFixedWidth(44)
        row.addWidget(lab)
        self.preset_combo = QComboBox()
        self.preset_combo.currentIndexChanged.connect(lambda _: self._set("preset", self.preset_combo.currentData()))
        row.addWidget(self.preset_combo, 1)
        row.addWidget(self._tool("import", "프리셋 가져오기 — LUMIQ .yaml · 라이트룸 .xmp", self.import_presets, size=16))
        row.addWidget(self._tool("save", "현재 색감·톤을 프리셋으로 저장", self.save_preset, size=16))
        row.addWidget(self._tool("trash", "프리셋 삭제…", self.delete_presets, size=16))
        lay.addLayout(row)
        row = QHBoxLayout()
        self.xmp_btn = QPushButton("라이트룸 xmp 불러오기")
        self.xmp_btn.setObjectName("Ghost")
        self.xmp_btn.clicked.connect(self.choose_xmp)
        self.xmp_label = QLabel("")
        self.xmp_label.setObjectName("Muted")
        self.xmp_clear = self._tool("close", "xmp 해제", lambda: self._set("xmp", None), size=14)
        self.xmp_clear.setVisible(False)
        reset = QPushButton("전체 초기화")
        reset.setObjectName("Ghost")
        reset.clicked.connect(self.reset_all)
        row.addWidget(self.xmp_btn)
        row.addWidget(self.xmp_label, 1)
        row.addWidget(self.xmp_clear)
        row.addWidget(reset)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.auto_check = QCheckBox("자동 보정")
        self.auto_check.setToolTip("노출·화이트밸런스·톤 자동 계산 (인물은 얼굴 노출 우선)")
        self.auto_check.toggled.connect(self._on_auto_toggled)
        self.denoise_check = QCheckBox("AI 노이즈 제거")
        self.denoise_check.setToolTip("SCUNet (Mac GPU). 고감도 사진용, 처리 시간이 늘어납니다")
        self.denoise_check.toggled.connect(lambda on: self._set_bool("ai_denoise", on, False))
        self.camera_check = QCheckBox("카메라 톤")
        self.camera_check.setToolTip("RAW를 카메라 JPEG처럼: 액티브 D-라이팅·픽처 컨트롤이 들어간 카메라 JPEG의 밝기·채도에\n"
                                     f"맞춰 기본 톤을 잡습니다. 사진마다 켜고 끌 수 있고, 기본값은 설정({N.key_text('Ctrl+,')})에서 정합니다.")
        self.camera_check.toggled.connect(lambda on: self._set_bool("camera_match", on, self._camera_default()))
        row.addWidget(self.auto_check)
        row.addSpacing(4)
        row.addWidget(self.camera_check)
        row.addSpacing(4)
        row.addWidget(self.denoise_check)
        row.addStretch(1)
        lay.addLayout(row)
        # 자동 보정의 밝기 선호: 노출만이 아니라 목표 밝기·섀도·하이라이트·흰색·검정·대비를 함께 다시 계산
        self.auto_bright = SliderRow("auto_brightness", "자동 밝기", -100, 100, 1, 0, 0, stops=BRIGHT_STOPS)
        self.auto_bright.setToolTip("← 어둡게 · 밝게 →\n노출만이 아니라 섀도·하이라이트·흰색·검정·대비를 함께 자동으로 다시 맞춥니다")
        self.auto_bright.changed.connect(self._set)
        self.auto_bright.reset.connect(lambda k: self._set(k, None))
        self.rows["auto_brightness"] = self.auto_bright
        self.auto_bright.setVisible(False)
        self.auto_check.toggled.connect(self.auto_bright.setVisible)
        lay.addWidget(self.auto_bright)
        self._reload_presets()
        return card

    def _row(self, section, key, label, lo, hi, step=1, decimals=0, default=0, **kw):
        r = SliderRow(key, label, lo, hi, step, decimals, default, **kw)
        r.changed.connect(self._set)
        r.reset.connect(lambda k: self._set(k, None))
        self.rows[key] = r
        section.add(r)
        return r

    def _section(self, title, expanded=True, extra_keys=()):
        s = Section(title, expanded)
        self.panel_layout.addWidget(s)
        self.sections.append((s, list(extra_keys)))
        s.reset_clicked.connect(lambda s=s: self._reset_section(s))
        return s

    def _tab_pages(self, section, tabs_spec):
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        for name, build in tabs_spec:
            page = QWidget()
            pl = QVBoxLayout(page)
            pl.setContentsMargins(0, 6, 0, 0)
            pl.setSpacing(2)
            build(page, pl)
            tabs.addTab(page, name)
        section.body_layout.addWidget(tabs)
        return tabs

    def _build_sections(self):
        s = self._section("기본")
        r = self._row(s, "temperature", "색온도", 2000, 50000, 50, 0, 5500, kelvin=True, stops=TEMP_STOPS)
        r.edit.setToolTip("K")
        self._row(s, "tint", "틴트", -150, 150, 1, 0, 0, stops=TINT_STOPS)
        self._row(s, "exposure", "노출", -5, 5, 0.05, 2)
        self._row(s, "contrast", "대비", -100, 100)

        s = self._section("톤")
        for k, l in (("highlights", "하이라이트"), ("shadows", "섀도"), ("whites", "흰색 계열"), ("blacks", "검정 계열")):
            self._row(s, k, l, -100, 100)

        s = self._section("외관")
        for k, l in (("texture", "텍스처"), ("clarity", "명료도"), ("dehaze", "디헤이즈"),
                     ("vibrance", "생동감"), ("saturation", "채도")):
            self._row(s, k, l, -100, 100)

        s = self._section("피부 · 얼굴 인식", extra_keys=["skin"])
        self._row(s, "skin.brightness", "밝기", -100, 100)
        self._row(s, "skin.smooth", "매끈함", 0, 100)
        self._row(s, "skin.saturation", "채도", -100, 100)
        self._row(s, "skin.warmth", "따뜻함", -100, 100)

        s = self._section("HSL", expanded=False, extra_keys=["hsl"])

        def hsl_page(mode):
            def build(page, pl):
                class Sink:
                    def add(_, w):
                        pl.addWidget(w)
                        s.keys.append(w.key)
                for b in HSL_BANDS:
                    self._row(Sink(), f"hsl.{b}.{mode}", BAND_KO[b], -100, 100)
            return build
        self._tab_pages(s, [("색조", hsl_page("hue")), ("채도", hsl_page("saturation")), ("휘도", hsl_page("luminance"))])

        s = self._section("컬러 그레이딩", expanded=False, extra_keys=["color_grading"])

        def cg_page(zone):
            def build(page, pl):
                class Sink:
                    def add(_, w):
                        pl.addWidget(w)
                        s.keys.append(w.key)
                self._row(Sink(), f"color_grading.{zone}.hue", "색조", 0, 360, stops=HUE_STOPS)
                self._row(Sink(), f"color_grading.{zone}.saturation", "채도", 0, 100)
                self._row(Sink(), f"color_grading.{zone}.luminance", "휘도", -100, 100)
            return build
        self._tab_pages(s, [("섀도", cg_page("shadows")), ("미드톤", cg_page("midtones")),
                            ("하이라이트", cg_page("highlights")), ("전체", cg_page("global"))])
        self._row(s, "color_grading.blending", "혼합", 0, 100, default=50)
        self._row(s, "color_grading.balance", "균형", -100, 100)

        s = self._section("LUT", extra_keys=["lut"])
        self.lut_combo = QComboBox()
        self.lut_combo.currentIndexChanged.connect(self._on_lut)
        s.add(self.lut_combo)
        self._row(s, "lut.strength", "강도", 0, 100, default=100)
        self._reload_luts()

        s = self._section("디테일", expanded=False, extra_keys=["sharpening", "noise_reduction"])
        self._row(s, "sharpening.amount", "샤프닝", 0, 150)
        self._row(s, "sharpening.radius", "반경", 0.5, 3.0, 0.1, 1, default=1.0)
        self._row(s, "sharpening.detail", "디테일", 0, 100, default=25)
        self._row(s, "sharpening.masking", "마스킹", 0, 100)
        self._row(s, "noise_reduction.luminance", "노이즈 감소", 0, 100)
        self._row(s, "noise_reduction.color", "색 노이즈", 0, 100)
        self._row(s, "ai_denoise.strength", "AI 강도", 0, 100, default=100)

        s = self._section("효과", expanded=False, extra_keys=["vignette", "grain"])
        self._row(s, "vignette.amount", "비네팅", -100, 100)
        self._row(s, "vignette.midpoint", "중간점", 0, 100, default=50)
        self._row(s, "vignette.feather", "페더", 0, 100, default=50)
        self._row(s, "grain.amount", "그레인", 0, 100)
        self._row(s, "grain.size", "크기", 0, 100, default=25)
        self._row(s, "grain.roughness", "거칠기", 0, 100, default=50)

        s = self._section("자르기 · 회전", extra_keys=["crop", "crop_center", "crop_orientation", "crop_rect",
                                                     "rotate90", "flip", "auto_level", "rotate"])
        btn = QPushButton("  화면에서 자르기·회전   R")
        btn.setIcon(T.icon("crop", T.TEXT, 16))
        btn.clicked.connect(self.toggle_crop)
        s.add(btn)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 0)
        rl.addWidget(self._tool("rotl", "왼쪽으로 90°", lambda: self._rotate90(-1)))
        rl.addWidget(self._tool("rotr", "오른쪽으로 90°", lambda: self._rotate90(1)))
        rl.addWidget(self._tool("flip", "좌우 반전", self._flip))
        rl.addStretch(1)
        self.level_check = QCheckBox("자동 수평")
        self.level_check.toggled.connect(lambda on: self._set_bool("auto_level", on, True))
        self.lens_check = QCheckBox("렌즈 보정")
        self.lens_check.toggled.connect(lambda on: self._set_bool("lens", on, self.result.is_raw if self.result else True))
        rl.addWidget(self.level_check)
        rl.addWidget(self.lens_check)
        s.add(row)
        self.geo_label = QLabel("")
        self.geo_label.setObjectName("Faint")
        s.add(self.geo_label)

    def _build_menus(self):
        mb = self.menuBar()
        m_file = mb.addMenu("파일")
        m_edit = mb.addMenu("편집")
        m_view = mb.addMenu("보기")
        m_help = mb.addMenu("도움말")

        def act(menu, text, shortcut, fn, checkable=False):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setCheckable(checkable)
            (a.toggled if checkable else a.triggered).connect(fn)
            menu.addAction(a)
            return a

        act(m_file, "폴더 열기…", "Ctrl+O", self.choose_folder)
        self.close_folder_act = act(m_file, "폴더 닫기", None, self.close_folder)
        self.recent_menu = m_file.addMenu("최근 폴더")
        self._refresh_recent()
        m_file.addSeparator()
        act(m_file, "내보내기…", "Ctrl+E", self.export_dialog)
        act(m_file, f"{N.FILE_MANAGER}에서 보기", "Ctrl+Shift+R", self.reveal_current)
        act(m_file, "프리셋 가져오기…", None, self.import_presets)
        prefs = act(m_file, "설정…", "Ctrl+,", self.show_settings)  # Windows에는 표준 설정 키가 없어 직접 정한다
        prefs.setMenuRole(QAction.PreferencesRole)  # macOS: 앱 메뉴의 '설정…' (⌘,)
        m_file.addSeparator()
        self.trash_act = act(m_file, "휴지통으로 이동", N.TRASH_KEY, self.trash_selected)
        act(m_help, f"{APP_NAME} 사용법", QKeySequence.HelpContents, self.show_help)
        act(m_help, "GitHub 저장소", None, lambda *_: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        about = act(m_help, f"{APP_NAME} 정보", None, self.show_about)
        about.setMenuRole(QAction.AboutRole)  # macOS: 앱 메뉴의 'LUMIQ Studio 정보'
        act(m_edit, "실행 취소", "Ctrl+Z", self.undo)
        act(m_edit, "다시 실행", "Ctrl+Shift+Z", self.redo)
        m_edit.addSeparator()
        act(m_edit, "설정 복사", "Ctrl+Shift+C", self.copy_settings)
        act(m_edit, "선택한 사진에 붙여넣기", "Ctrl+Shift+V", self.paste_settings)
        act(m_edit, "모든 사진에 붙여넣기", None, lambda: self.paste_settings(all_photos=True))
        m_edit.addSeparator()
        act(m_edit, "위치(GPS) 추가…", None, lambda: self.add_location())
        m_rate = m_edit.addMenu("별점 (키보드 0 · 1 · 2 · 3)")
        for n in (1, 2, 3):
            act(m_rate, f"{RATING_STARS[n]}  {n}", None, lambda _=False, n=n: self.set_rating(n))
        m_rate.addSeparator()
        act(m_rate, "별점 지우기  0", None, lambda: self.set_rating(0))
        m_edit.addSeparator()
        act(m_edit, "이 사진 초기화", None, self.reset_all)
        self.ask_save_act = act(m_edit, "편집을 마칠 때 저장할지 묻기", None,
                                lambda on: self.settings.setValue("edit/always_save", "false" if on else "true"),
                                checkable=True)
        self.ask_save_act.blockSignals(True)
        self.ask_save_act.setChecked(self.settings.value("edit/always_save", "false") != "true")
        self.ask_save_act.blockSignals(False)
        act(m_edit, "프리셋 저장…", None, self.save_preset)
        act(m_edit, "프리셋 삭제…", None, self.delete_presets)
        act(m_view, "그리드 보기", None, lambda: self.go_view("grid"))
        act(m_view, "한 장씩 보기", None, lambda: self.go_view("single"))
        self._build_grid_actions()
        self._fill_grid_menu(m_view.addMenu("그리드 보기 옵션"))
        self.grid_opts_btn.setMenu(self._fill_grid_menu(QMenu(self.grid_opts_btn)))
        self._build_filter_actions()
        m_view.addMenu("별점 필터").addActions(self.filter_actions)
        menu = QMenu(self.filter_btn)
        menu.addActions(self.filter_actions)
        self.filter_btn.setMenu(menu)
        act(m_view, "편집 / 보기 전환", None, self.toggle_edit)
        m_view.addSeparator()
        m_view.addActions([self.zoom_in_act, self.zoom_out_act, self.fit_act])
        m_view.addSeparator()
        act(m_view, "자르기·회전", None, self.toggle_crop)
        act(m_view, "보정 전·후 비교", None, self._compare_key)
        act(m_view, "AI 어시스턴트", "Ctrl+K", lambda: self._show_ai(True))
        m_view.addSeparator()
        m_thumbs = m_view.addMenu("편집 화면 썸네일")
        self.thumbs_group = QActionGroup(self)
        for label, key in (("왼쪽", "left"), ("아래", "bottom")):
            a = QAction(label, self, checkable=True)
            a.setData(key)
            a.setChecked(key == self.edit_thumbs)
            self.thumbs_group.addAction(a)
            m_thumbs.addAction(a)
        self.thumbs_group.triggered.connect(lambda a: self._set_edit_thumbs(a.data()))
        m_view.addSeparator()
        self.sub_act = act(m_view, "하위 폴더 포함", None, self._toggle_subfolders, checkable=True)
        self.sub_act.blockSignals(True)
        self.sub_act.setChecked(self.settings.value("view/subfolders", "true") == "true")
        self.sub_act.blockSignals(False)
        self.pairs_act = act(m_view, "RAW+JPEG 쌍의 JPG도 표시", None, self._toggle_pairs, checkable=True)
        self.pairs_act.blockSignals(True)
        self.pairs_act.setChecked(self.settings.value("view/pairs", "false") == "true")
        self.pairs_act.blockSignals(False)
        # 한 글자 단축키 (입력칸에 글자를 칠 때는 동작하지 않도록 직접 처리)
        for key, fn in ((Qt.Key_R, self.toggle_crop), (Qt.Key_Backslash, self._compare_key),
                        (Qt.Key_X, self._swap_ratio), (Qt.Key_Escape, self._on_escape),
                        (Qt.Key_Right, lambda: self._step(1)), (Qt.Key_Left, lambda: self._step(-1))):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda fn=fn: self._single_key(fn))
        QApplication.instance().installEventFilter(self)  # E·G (eventFilter 참고)

    def _build_grid_actions(self):
        """그리드 보기 옵션: 모양(맞춤/정사각형) · 크기 · 파일 이름. 메뉴 막대·옵션 버튼·빈 곳 오른쪽 클릭이 같은 동작을 쓴다."""
        self.shape_group = QActionGroup(self)
        for label, key in GRID_SHAPES:
            a = QAction(label, self, checkable=True)
            a.setData(key)
            a.setChecked(key == self.grid_shape)
            self.shape_group.addAction(a)
        self.shape_group.triggered.connect(lambda a: self._set_grid_option(shape=a.data()))
        self.size_group = QActionGroup(self)
        for i, (label, _w) in enumerate(GRID_SIZES):
            a = QAction(label, self, checkable=True)
            a.setData(i)
            a.setChecked(i == self.grid_size)
            self.size_group.addAction(a)
        self.size_group.triggered.connect(lambda a: self._set_grid_option(size=a.data()))
        self.names_act = QAction("파일 이름 표시", self, checkable=True)
        self.names_act.setChecked(self.grid_names)
        self.names_act.toggled.connect(lambda on: self._set_grid_option(names=on))
        # ⌘+ ⌘−: 그리드에서는 썸네일 크기, 한 장 보기·편집에서는 화면 확대 (_apply_mode가 이름을 바꾼다)
        self.zoom_in_act = QAction("썸네일 크게", self)
        self.zoom_in_act.setShortcuts([QKeySequence("Ctrl+="), QKeySequence(QKeySequence.ZoomIn)])
        self.zoom_in_act.triggered.connect(lambda: self._zoom(1))
        self.zoom_out_act = QAction("썸네일 작게", self)
        self.zoom_out_act.setShortcut(QKeySequence(QKeySequence.ZoomOut))
        self.zoom_out_act.triggered.connect(lambda: self._zoom(-1))
        self.fit_act = QAction("화면에 맞추기", self)
        self.fit_act.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_act.triggered.connect(lambda: self._zoom(0))

    def _build_filter_actions(self):
        """별점 필터: 메뉴 막대·필터 버튼·그리드 빈 곳 오른쪽 클릭이 같은 동작을 쓴다."""
        self.filter_group = QActionGroup(self)
        self.filter_actions = []  # 메뉴에 넣을 순서 (모든 사진 | 별점 | 별점 없음 사이에 구분선)
        for label, _short, value in RATING_FILTERS:
            if value in (1, 0):
                sep = QAction(self)
                sep.setSeparator(True)
                self.filter_actions.append(sep)
            a = QAction(label, self, checkable=True)
            a.setData(value)
            a.setChecked(value is None)
            self.filter_group.addAction(a)
            self.filter_actions.append(a)
        self.filter_group.triggered.connect(lambda a: self.set_rating_filter(a.data()))

    def _fill_grid_menu(self, menu: QMenu) -> QMenu:
        for title, actions in (("모양", self.shape_group.actions()), ("크기", self.size_group.actions())):
            head = menu.addAction(title)
            head.setEnabled(False)
            menu.addActions(actions)
            menu.addSeparator()
        menu.addAction(self.zoom_in_act)
        menu.addAction(self.zoom_out_act)
        menu.addSeparator()
        menu.addAction(self.names_act)
        return menu

    def _single_key(self, fn):
        if self._typing(self.focusWidget()):
            return
        fn()

    def _start_render_thread(self):
        self.render_thread = QThread(self)
        self.worker = RenderWorker(self.engine)
        self.worker.moveToThread(self.render_thread)
        self.request_render.connect(self.worker.wake)
        self.worker.finished.connect(self._on_render)
        self.worker.failed.connect(self._on_render_failed)
        self.worker.busy.connect(self.view.set_busy)
        self.render_thread.start()

    # ================================================================== 보기 · 편집 모드
    def _grid_shown(self) -> bool:
        return self.mode == "view" and self.layout_mode == "grid" and bool(self.photos)

    def set_mode(self, mode: str, layout: str | None = None):
        """mode: view(보기) / edit(편집). layout: 보기 모드의 grid / single."""
        if mode == "edit" and not self.current:
            return
        if mode == "edit" and self.mode != "edit":  # 이번 편집에서 바뀐 것을 알 수 있도록 지금 값을 기억
            self._edit_session = {}
            self._session_note(self.current, self.edit)
        if mode == "view" and self.mode == "edit":
            self._edit_session = None
            if self.view.mode == "crop" or self._crop_wait:
                self.leave_crop(apply=True)
            if self.compare_btn.isChecked():
                self.compare_btn.setChecked(False)
                self._toggle_compare(False)
            self._crop_after_render = False
            layout = layout or "single"
        self.mode = mode
        if layout:
            self.layout_mode = layout
        self._apply_mode()

    def toggle_edit(self):
        if self.mode == "edit":
            self.go_view("single")
        else:
            self.set_mode("edit")

    def go_view(self, layout: str | None = None):
        """보기로 (사용자가 누른 경우). 편집 중 바뀐 보정이 있으면 저장할지 먼저 묻는다."""
        if self.mode == "edit" and not self._confirm_leave_edit():
            return
        self.set_mode("view", layout)

    # ---- 편집을 마칠 때 저장 여부
    @staticmethod
    def _adjust_part(edit: dict) -> dict:
        """보정값만 (별점·위치는 저장 여부와 상관없이 그대로 둔다)."""
        return {k: v for k, v in edit.items() if k not in ("file", "rating", "gps")}

    def _session_note(self, photo: Path | None, edit: dict):
        if self._edit_session is not None and photo is not None and str(photo) not in self._edit_session:
            self._edit_session[str(photo)] = copy.deepcopy(self._adjust_part(edit))

    def _confirm_leave_edit(self) -> bool:
        """이번 편집에서 보정이 바뀐 사진이 있으면 저장 / 저장 안 함(편집 전으로) / 취소를 묻는다. 취소면 False."""
        if self.view.mode == "crop" or self._crop_wait:
            self.leave_crop(apply=True)
        self._flush_save()
        changed = [(Path(k), before) for k, before in (self._edit_session or {}).items()
                   if before != self._adjust_part(self._edit_of(Path(k)))]
        if not changed or self.settings.value("edit/always_save", "false") == "true":
            return True
        n = len(changed)
        box = QMessageBox(QMessageBox.Question, "보정 저장",
                          "보정한 내용을 저장할까요?" if n == 1 else f"사진 {n}장의 보정을 저장할까요?", parent=self)
        box.setInformativeText("저장하지 않으면 이번 편집을 시작하기 전으로 되돌립니다. 별점·위치는 그대로 둡니다.")
        save = box.addButton("저장", QMessageBox.AcceptRole)
        discard = box.addButton("저장 안 함", QMessageBox.DestructiveRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.setDefaultButton(save)
        always = QCheckBox("다음부터 묻지 않고 저장 (편집 메뉴에서 다시 켤 수 있음)")
        box.setCheckBox(always)
        box.exec()
        if box.clickedButton() is save:
            if always.isChecked():
                self.ask_save_act.setChecked(False)
            return True
        if box.clickedButton() is not discard:
            return False
        for photo, before in changed:
            self._restore_adjustments(photo, before)
        self._scan_edited()
        self._refresh_badges()
        self._flash(f"편집 전으로 되돌렸습니다 ({N.key_text('Ctrl+Z')}로 다시 적용)" if n == 1 else f"{n}장을 편집 전으로 되돌렸습니다")
        return True

    def _restore_adjustments(self, photo: Path, before: dict):
        now = self._edit_of(photo)
        restored = copy.deepcopy(before)
        for k in ("rating", "gps"):
            if now.get(k) is not None:
                restored[k] = now[k]
        if photo == self.current:
            self._push_undo()
            self.edit = restored
            self._after_edit_change(sync=True)
            self._flush_save()
        else:
            files.save_edit(photo, restored)
            it = self._thumbs.get(str(photo))
            if it is not None:
                it.setData(Qt.UserRole + 2, None)

    def _apply_mode(self):
        edit = self.mode == "edit"
        self.settings.setValue("view/layout", self.layout_mode)
        self.left_panel.setVisible(edit and self.edit_thumbs == "left")
        self.right_panel.setVisible(edit)
        self.statusBar().setVisible(edit or self._status_timer.isActive())
        self.view_seg.setVisible(not edit and self.folder is not None)
        self.grid_opts_btn.setVisible(self._grid_shown())
        self.filter_btn.setVisible(not edit and self.folder is not None)
        for b in self._edit_tools:
            b.setVisible(edit)
        (self.grid_btn if self.layout_mode == "grid" else self.single_btn).setChecked(True)
        grid = self._grid_shown()
        self.zoom_in_act.setText("썸네일 크게" if grid else "확대")
        self.zoom_out_act.setText("썸네일 작게" if grid else "축소")
        self.edit_btn.setText("  보기" if edit else "  편집")
        self.edit_btn.setIcon(T.icon("photo" if edit else "sliders", T.TEXT, 16))
        self.edit_btn.setToolTip("보기로 돌아가기 (E · Esc) — 바뀐 보정이 있으면 저장할지 묻습니다" if edit else "편집 (E)")
        self.filmstrip.setVisible(self.layout_mode == "single" if not edit else self.edit_thumbs == "bottom")
        self._show_center()
        self._refresh_hint()
        idx = self.list.currentIndex()
        if self._grid_shown():
            self.grid.setFocus()
            if idx.isValid():
                self.grid.scrollTo(idx)
            return
        if idx.isValid() and self.filmstrip.isVisible():
            QTimer.singleShot(0, lambda: self.filmstrip.scrollTo(idx, QListView.PositionAtCenter))
        self.view.setFocus()
        if self._render_pending:
            self._schedule_render()

    def _show_center(self):
        if not self.folder:
            self.center_stack.setCurrentIndex(0)
        else:
            self.center_stack.setCurrentIndex(2 if self._grid_shown() else 1)

    def _refresh_hint(self):
        if self.view.zoom > 1.0 and not self.compare_btn.isChecked():
            self.info_hint.setText(f"끌어서 이동  ·  더블클릭 · {N.key_text('Ctrl+0')} 맞춤")
        elif self.mode != "edit":
            self.info_hint.setText("← → 이동  ·  1 2 3 별점  ·  E 편집  ·  G 그리드")
        elif self.compare_btn.isChecked():
            self.info_hint.setText("선을 좌우로 끌어 비교")
        else:
            self.info_hint.setText("누르고 있으면 보정 전  ·  스크롤 확대")

    def _on_escape(self):
        if self.view.mode == "crop" or self._crop_wait:
            self.leave_crop(apply=False)
        elif self.mode == "edit":
            self.go_view("single")
        elif self.layout_mode == "single" and self.photos:
            self.set_mode("view", "grid")

    def _compare_key(self):
        if self.mode != "edit":
            self.set_mode("edit")
        if self.mode == "edit":
            self.compare_btn.click()

    # ================================================================== 폴더 · 사진
    def _set_has_photo(self, on: bool):
        """사진이 없을 때는 보정 패널과 도구를 잠근다."""
        self.adjust_page.setEnabled(on)
        for b in (self.crop_btn, self.compare_btn, self.undo_btn, self.redo_btn, self.copy_btn, self.paste_btn,
                  self.export_btn, self.edit_btn):
            b.setEnabled(on)

    def _show_welcome(self):
        self.center_stack.setCurrentIndex(0)
        while self.recent_box.count():
            it = self.recent_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        recent = [r for r in self._recent() if Path(r).is_dir()][:5]
        if recent:
            t = QLabel("최근 폴더")
            t.setObjectName("Faint")
            t.setAlignment(Qt.AlignCenter)
            self.recent_box.addWidget(t)
        for r in recent:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(2)
            b = QPushButton(f"{Path(r).name}   —   {r.replace(str(Path.home()), '~', 1)}")
            b.setObjectName("Ghost")
            b.clicked.connect(lambda _=False, r=r: self.open_folder(Path(r)))
            x = QToolButton()
            x.setIcon(T.icon("close", T.TEXT3, 12))
            x.setIconSize(QSize(12, 12))
            x.setFixedSize(22, 22)
            x.setToolTip("최근 목록에서 지우기 (폴더와 사진은 그대로)")
            x.clicked.connect(lambda _=False, r=r: self.forget_recent(r))
            hl.addSpacing(24)  # 오른쪽 × 만큼 비워 이름을 가운데에 둔다
            hl.addWidget(b)
            hl.addWidget(x)
            self.recent_box.addWidget(row, 0, Qt.AlignCenter)

    def _recent(self) -> list[str]:
        v = self.settings.value("folder/recent") or []
        return [v] if isinstance(v, str) else list(v)

    def forget_recent(self, folder: str):
        """최근 폴더 목록에서만 뺀다 (폴더·사진·보정값은 그대로)."""
        self.settings.setValue("folder/recent", [r for r in self._recent() if r != folder])
        if self.settings.value("folder/last") == folder:
            self.settings.remove("folder/last")
        self._refresh_recent()
        if not self.folder:
            self._show_welcome()

    def choose_folder(self):
        start = str(self.folder or self.settings.value("folder/last") or Path.home() / "Pictures")
        d = QFileDialog.getExistingDirectory(self, "사진 폴더 선택", start)
        if d:
            self.open_folder(Path(d))

    def show_help(self, *_):
        HelpDialog(self, APP_NAME, SLOGAN_EN, FORMATS, GITHUB_URL).exec()

    def show_about(self, *_):
        AboutDialog(self, APP_NAME, SLOGAN, SLOGAN_EN, FORMATS, VERSION, GITHUB_URL).exec()

    def close_folder(self, *_):
        """열린 폴더를 닫고 처음 화면으로 (다음 실행도 처음 화면에서 시작). 보정값·사진은 그대로."""
        if not self.folder:
            return
        if self.view.mode == "crop" or self._crop_wait:
            self.leave_crop(apply=True)
        self._flush_save()
        self.set_mode("view", self.layout_mode)
        for t in (self._render_timer, self._state_timer):
            t.stop()
        self.folder, self.photos, self.subfolders = None, [], []
        self.current, self.edit, self.result = None, {}, None
        self._render_pending = self._crop_after_render = False
        self.list.blockSignals(True)
        self.list.clear()
        self.list.blockSignals(False)
        self._thumbs.clear()
        self._edited = set()
        self._set_filter_ui(None)
        if self.watcher.files() or self.watcher.directories():
            self.watcher.removePaths(self.watcher.files() + self.watcher.directories())
        self.view.set_before(None)
        self.view.set_image(None)
        self.view.set_badge("")
        self.hist.set_data(None)
        self._update_info()
        self.folder_title.setText(T.wordmark(APP_NAME))
        self.folder_sub.setText("폴더를 열어 시작하세요")
        self.count_label.setText("")
        self.setWindowTitle(APP_NAME)
        self.close_folder_btn.setVisible(False)
        self.settings.remove("folder/last")
        self.assistant.clear()
        self._update_ai_context()
        self._set_has_photo(False)
        self._apply_mode()
        self._show_welcome()
        self.statusBar().clearMessage()
        try:  # Claude Code가 '지금 보는 사진'을 잘못 찾지 않도록
            STATE_FILE.write_text(json.dumps({"folder": None, "current": None, "current_edit_file": None,
                                              "current_preview": None, "selected": [],
                                              "updated": datetime.now().isoformat(timespec="seconds")},
                                             ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    def open_folder(self, folder: Path, select: Path | None = None, single: bool = False):
        """폴더를 보기 모드로 연다. single이면 select 사진을 한 장 보기로 (Finder에서 사진을 열었을 때)."""
        if self.view.mode == "crop":
            self.leave_crop(apply=True)
        self._flush_save()
        folder = folder.expanduser().absolute()
        recursive = self.sub_act.isChecked()
        try:
            photos = files.collect_images(folder, include_paired_jpeg=self.pairs_act.isChecked(),
                                          recursive=recursive, limit=MANY_PHOTOS)
            if len(photos) > MANY_PHOTOS:  # 홈 폴더 같은 큰 폴더를 실수로 열었을 때
                box = QMessageBox(QMessageBox.Question, "폴더 열기",
                                  f"하위 폴더까지 사진이 {MANY_PHOTOS:,}장이 넘습니다.\n모두 열면 썸네일을 만드는 데 "
                                  "시간과 메모리가 많이 듭니다.", parent=self)
                only = box.addButton("이 폴더만 열기", QMessageBox.AcceptRole)
                box.addButton("모두 열기", QMessageBox.DestructiveRole)
                cancel = box.addButton("취소", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is cancel:
                    return
                recursive = box.clickedButton() is not only
                photos = files.collect_images(folder, include_paired_jpeg=self.pairs_act.isChecked(),
                                              recursive=recursive)
        except OSError as e:
            QMessageBox.warning(self, "폴더 열기", f"폴더를 열 수 없습니다:\n{e}")
            return
        if folder != self.folder or single:
            self.set_mode("view", "single" if single else None)
        if folder != self.folder:  # 다른 폴더를 열면 별점 필터를 푼다
            self._set_filter_ui(None)
        self.folder = folder
        self.photos = photos
        self.subfolders = sorted({p.parent for p in photos if p.parent != folder})
        self.settings.setValue("folder/last", str(folder))
        recent = [str(folder)] + [r for r in self._recent() if r != str(folder)]
        self.settings.setValue("folder/recent", recent[:8])
        self._refresh_recent()
        self.setWindowTitle(f"{folder.name} — {APP_NAME}")
        self.folder_title.setText(folder.name)
        self.close_folder_btn.setVisible(True)
        self._update_counts()
        self._scan_edited()
        self._watch_folders()
        self.list.blockSignals(True)
        self.list.clear()
        self._thumbs.clear()
        for p in photos:
            it = QListWidgetItem(self._display_name(p))
            it.setData(Qt.UserRole, str(p))
            it.setToolTip(str(p))
            self.list.addItem(it)
            self._thumbs[str(p)] = it
            self.pool.start(ThumbJob(p, self.thumb_signals))
        self.list.blockSignals(False)
        self._refresh_badges()
        self._apply_filter(move=False)
        self.pool.start(ExifJob(photos, self.exif_signals))
        self.assistant.clear()
        self._update_ai_context()
        if not photos:
            self.current = None
            self._set_has_photo(False)
            self.set_mode("view")
            self.view.set_image(None)
            self.info_name.setText(f"이 폴더에 사진이 없습니다 ({FORMATS})")
            self.info_meta.setText("")
            return
        shown = self._visible_photos() or photos
        target = select if select in shown else shown[0]
        self.list.setCurrentItem(self._thumbs[str(target)])
        self._apply_mode()

    def _update_counts(self):
        photos = self.photos
        n_raw = sum(1 for p in photos if p.suffix.lower() in files.RAW_EXTS)
        sub = f"  ·  하위 폴더 {len(self.subfolders)}개" if self.subfolders else ""
        self.folder_sub.setText(f"{str(self.folder).replace(str(Path.home()), '~', 1)}  ·  {len(photos)}장{sub}")
        if self.rating_filter is None:
            self.count_label.setText(f"{len(photos)}장 · RAW {n_raw}")
        else:
            self.count_label.setText(f"{len(self._visible_photos())} / {len(photos)}장")

    def _display_name(self, p: Path) -> str:
        """하위 폴더의 사진은 '폴더/파일명'으로 보여 준다."""
        try:
            return str(p.relative_to(self.folder)) if self.folder else p.name
        except ValueError:
            return p.name

    def _refresh_recent(self):
        self.recent_menu.clear()
        for r in self._recent():
            a = self.recent_menu.addAction(r.replace(str(Path.home()), "~", 1))
            a.triggered.connect(lambda _=False, r=r: self.open_folder(Path(r)))

    def _set_edit_thumbs(self, pos: str):
        """편집 화면의 썸네일 위치: left(왼쪽 목록) / bottom(아래 필름스트립)."""
        self.edit_thumbs = "bottom" if pos == "bottom" else "left"
        self.settings.setValue("edit/thumbs", self.edit_thumbs)
        for a in self.thumbs_group.actions():
            a.setChecked(a.data() == self.edit_thumbs)
        self._apply_mode()

    def _camera_default(self) -> bool:
        return bool(P.app_config().get("camera_match_default", False))

    def show_settings(self):
        dlg = SettingsDialog(self, self._camera_default(), self.edit_thumbs, self.ask_save_act.isChecked())
        if dlg.exec() != QDialog.Accepted:
            return
        cam, thumbs, ask = dlg.values()
        if cam != self._camera_default():
            P.save_app_config(camera_match_default=cam)
            self._sync_controls_from_edit()
            self._schedule_render()  # 이 사진에 따로 정하지 않았으면 새 기본값으로 다시 그린다
        if thumbs != self.edit_thumbs:
            self._set_edit_thumbs(thumbs)
        self.ask_save_act.setChecked(ask)

    def _toggle_subfolders(self, on):
        self.settings.setValue("view/subfolders", "true" if on else "false")
        if self.folder:
            self.open_folder(self.folder, self.current)

    def _toggle_pairs(self, on):
        self.settings.setValue("view/pairs", "true" if on else "false")
        if self.folder:
            self.open_folder(self.folder, self.current)

    def _on_thumb(self, path: str, img: QImage):
        it = self._thumbs.get(path)
        if it is not None and it.data(Qt.UserRole + 2) is None:  # 보정 결과 썸네일이 있으면 유지
            it.setIcon(QIcon(QPixmap.fromImage(img)))

    def _on_exif(self, data: dict):
        self.engine.set_exif(data)
        self._refresh_badges()  # 위치 핀
        self._update_info()

    def _step(self, d: int):
        if self.view.mode == "crop" or not self.photos:
            return
        row = self.list.currentRow() + d
        while 0 <= row < self.list.count() and self.list.isRowHidden(row):  # 별점 필터로 숨긴 사진은 건너뜀
            row += d
        if 0 <= row < self.list.count():
            self.list.setCurrentRow(row)

    def _on_current_item(self, item, _prev):
        if item is None:
            return
        if self.view.mode == "crop":
            self.leave_crop(apply=True)
        self._flush_save()
        self.current = Path(item.data(Qt.UserRole))
        self._crop_after_render = False
        self.view.reset_zoom()  # 다른 사진은 맞춤 크기로
        self.view.set_source_scale(0.0)  # 이 사진의 해상도는 렌더가 끝나야 안다
        if not item.icon().isNull():  # 렌더가 끝날 때까지 썸네일을 먼저 보여 준다 (이전 사진이 남아 있지 않도록)
            self.view.set_before(None)
            self.view.set_image(item.icon().pixmap(QSize(320, 320)).toImage())
        if self.filmstrip.isVisible():
            self.filmstrip.scrollTo(self.list.currentIndex(), QListView.PositionAtCenter)
        self._set_has_photo(True)
        self._mark_ai([])
        self.edit = files.load_edit(self.current)
        self.edit.pop("file", None)
        self._session_note(self.current, self.edit)
        self._last_push = (0.0, None)
        self._prefetch_pending = True
        self.result = None
        self.view.set_badge("")
        self._watch_current()
        self._sync_controls_from_edit()
        self._update_info()
        self._update_ai_context()
        self._state_timer.start()
        self._schedule_render()

    def _on_selection(self):
        self._update_ai_context()
        self._state_timer.start()

    def _watch_current(self):
        old = self.watcher.files()
        if old:
            self.watcher.removePaths(old)
        if self.current:
            p = files.find_edit(self.current)
            if p:
                self.watcher.addPath(str(p))

    def _exif_caption(self, ex: dict) -> str:
        parts = []
        for k, fmt in (("ISO", "ISO {}"), ("ExposureTime", "{}s"), ("FNumber", "f/{}"), ("FocalLength", "{}")):
            if ex.get(k) not in (None, ""):
                parts.append(fmt.format(ex[k]).replace(".0 mm", "mm").replace(" mm", "mm"))
        return "   ".join(parts)

    def _update_info(self):
        self.stars.setVisible(self.current is not None)
        if not self.current:
            self.info_name.setText("")
            self.info_meta.setText("")
            self.hist.set_caption("")
            return
        ex = self.engine._exif.get(str(self.current), {})
        self.info_name.setText(self._display_name(self.current))
        meta = [str(x) for x in (ex.get("Model"), ex.get("LensModel") or ex.get("LensID")) if x]
        if ex.get("ImageSize"):
            meta.append(str(ex["ImageSize"]).replace("x", " × "))
        gps = self.edit.get("gps") if isinstance(self.edit.get("gps"), dict) else self._exif_gps(self.current)
        if gps:
            meta.append(f"위치 {gps_label(gps)}")
        shown = self.photos if self.rating_filter is None else self._visible_photos()
        i = shown.index(self.current) + 1 if self.current in shown else 0
        meta.append(f"{i} / {len(shown)}")
        self.info_meta.setText("   ·   ".join(meta))
        self.stars.set_value(self._rating(self.current))
        self.hist.set_caption(self._exif_caption(ex))

    # ================================================================== 보정값 편집
    def _push_undo(self, key=None):
        if not self.current:
            return
        now = time.time()
        last_t, last_k = self._last_push
        if key is not None and key == last_k and now - last_t < 1.0:
            self._last_push = (now, key)  # 같은 슬라이더를 연속으로 움직이면 한 번으로 묶음
            return
        self._last_push = (now, key)
        stack = self._undo.setdefault(str(self.current), [])
        stack.append(copy.deepcopy(self.edit))
        del stack[:-100]
        self._redo[str(self.current)] = []

    def _set(self, key: str, value):
        """보정값 하나를 바꾼다. value가 None이면 지워서 기본값(프리셋/자동)으로."""
        if not self.current:
            return
        if key == "ai_denoise.strength":
            key = "ai_denoise"
            value = None if value is None else {"strength": value}
        if get_nested(self.edit, key) == value:
            return
        row = self.rows.get(key) or (self.rows.get("ai_denoise.strength") if key == "ai_denoise" else None)
        if row is not None:
            row.set_ai(False)
        self._push_undo(key)
        if value is None:
            del_nested(self.edit, key)
        else:
            set_nested(self.edit, key, value)
        self._after_edit_change()

    def _set_bool(self, key: str, on: bool, default: bool):
        """켜기/끄기: 프리셋·사진별 yaml에서 물려받는 값과 같으면 키를 지우고, 다르면 명시한다."""
        if not self.current:
            return
        rest = copy.deepcopy(self.edit)
        rest.pop(key, None)
        inherited, _ = self.engine.settings(self.current, rest)
        inh = inherited.get(key, default)
        self._set(key, None if bool(inh) == bool(on) else bool(on))

    def _on_auto_toggled(self, on: bool):
        """자동 보정을 끄면 자동 밝기도 함께 지운다 (실행 취소 한 번으로 묶음)."""
        dropped = not on and self.current is not None and self.edit.get("auto_brightness") is not None
        if dropped:
            self._push_undo("auto")
            self.edit.pop("auto_brightness")
        self._set_bool("auto", on, False)
        if dropped:
            self._after_edit_change(sync=True)

    def _after_edit_change(self, sync=False):
        if sync:
            self._sync_controls_from_edit()
        else:
            self._mark_overrides()
        self._save_timer.start()
        self._schedule_render()

    def _reset_section(self, section: Section):
        if not self.current:
            return
        keys = next((list(section.keys) + extra for s, extra in self.sections if s is section), [])
        if not any(get_nested(self.edit, k) is not None for k in keys):
            return
        self._push_undo()
        for k in keys:
            if k == "ai_denoise.strength":
                continue
            del_nested(self.edit, k)
        self._after_edit_change(sync=True)

    def reset_all(self):
        if not self.current or not set(self.edit) - {"rating"}:
            return
        self._push_undo()
        self.edit = self._keep_rating({})
        self._after_edit_change(sync=True)

    def _keep_rating(self, edit: dict) -> dict:
        """별점은 보정 기록과 따로 간다: 실행 취소·다시 실행·초기화를 해도 지금 별점을 유지."""
        edit.pop("rating", None)
        if self.edit.get("rating"):
            edit["rating"] = self.edit["rating"]
        return edit

    def undo(self):
        st = self._undo.get(str(self.current), [])
        if not st or self.view.mode == "crop":
            return
        self._redo.setdefault(str(self.current), []).append(copy.deepcopy(self.edit))
        self.edit = self._keep_rating(st.pop())
        self._last_push = (0.0, None)
        self._after_edit_change(sync=True)

    def redo(self):
        st = self._redo.get(str(self.current), [])
        if not st or self.view.mode == "crop":
            return
        self._undo.setdefault(str(self.current), []).append(copy.deepcopy(self.edit))
        self.edit = self._keep_rating(st.pop())
        self._last_push = (0.0, None)
        self._after_edit_change(sync=True)

    def _rotate90(self, d: int):
        cur = self.edit.get("rotate90")
        i = ROT90.index(cur) if cur in ROT90 else 0
        self._push_undo()
        nxt = ROT90[(i + d) % 4]
        if nxt is None:
            self.edit.pop("rotate90", None)
        else:
            self.edit["rotate90"] = nxt
        self.edit.pop("crop_rect", None)  # 방향이 바뀌면 자유 크롭 영역은 의미가 없어짐
        self._after_edit_change()

    def _flip(self):
        self._push_undo()
        if self.edit.get("flip") == "h":
            self.edit.pop("flip")
        else:
            self.edit["flip"] = "h"
        if self.edit.get("crop_rect"):
            x, y, w, h = self.edit["crop_rect"]
            self.edit["crop_rect"] = [round(1 - x - w, 5), y, w, h]
        if self.edit.get("rotate"):
            self.edit["rotate"] = -self.edit["rotate"]
        self._after_edit_change()

    def choose_xmp(self):
        f, _ = QFileDialog.getOpenFileName(self, "라이트룸 프리셋(.xmp) 선택", str(Path.home()), "Lightroom XMP (*.xmp)")
        if f:
            self._set("xmp", f)
            self._sync_controls_from_edit()

    def _on_lut(self, _):
        data = self.lut_combo.currentData()
        if data == "__pick__":
            start = next((d for d in lut_dirs() if d.is_dir()), ROOT / "luts")
            f, _ = QFileDialog.getOpenFileName(self, "LUT(.cube) 선택", str(start), "Cube LUT (*.cube)")
            if f:
                for base in dict.fromkeys((DATA, ROOT)):
                    try:
                        f = str(Path(f).relative_to(base))
                        break
                    except ValueError:
                        pass
                self._set("lut.file", f)
            self._sync_controls_from_edit()
            return
        if data is None:
            self._set("lut", None)
        else:
            self._set("lut.file", data)

    def _reload_presets(self):
        """기본 프리셋 → 봄 → 여름 → 가을 → 겨울 순서로, 묶음 사이에 구분선. 이름은 label(한글)."""
        combo = self.preset_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("없음", None)
        items = []
        hidden = self._hidden_presets()
        for f in P.preset_files().values():
            if f.stem in hidden:
                continue
            season = f.stem.split("_")[0]
            items.append((SEASONS.index(season) + 1 if season in SEASONS else 0, f.stem, *P.preset_info(f)))
        group = None
        for rank, stem, label, desc in sorted(items):
            if rank != group:
                combo.insertSeparator(combo.count())
                group = rank
            combo.addItem(label, stem)
            if desc:
                combo.setItemData(combo.count() - 1, desc, Qt.ToolTipRole)
        combo.blockSignals(False)

    @staticmethod
    def _lut_label(f: Path) -> str:
        """.cube 머리의 '# LABEL 이름' (없으면 파일 이름)."""
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for _, line in zip(range(12), fh):
                    if line.startswith("# LABEL"):
                        return line[7:].strip() or f.stem
        except OSError:
            pass
        return f.stem

    def _reload_luts(self):
        self.lut_combo.blockSignals(True)
        self.lut_combo.clear()
        self.lut_combo.addItem("없음", None)
        for label, f in sorted((self._lut_label(f), f) for f in lut_files().values()):
            self.lut_combo.addItem(label, f"luts/{f.name}")
        self.lut_combo.addItem("파일 선택…", "__pick__")
        self.lut_combo.blockSignals(False)

    def save_preset(self):
        if not self.current:
            return
        name, ok = QInputDialog.getText(self, "프리셋 저장",
                                        "이름 (영문 소문자·숫자·밑줄, 예: my_film)\n색감·톤만 저장되고 노출·WB·크롭은 빠집니다")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not re.fullmatch(r"[a-z0-9_]+", name):
            QMessageBox.warning(self, "프리셋 저장", "이름은 영문 소문자, 숫자, 밑줄(_)만 쓸 수 있습니다.")
            return
        if name in P.preset_files():
            if QMessageBox.question(self, "프리셋 저장", f"{name} 프리셋이 이미 있습니다. 덮어쓸까요?") != QMessageBox.Yes:
                return
        merged, _ = self.engine.settings(self.current, self.edit)
        path = P.save_preset(name, P.validate(merged, warn=lambda m: None))
        self._unhide_preset(name)
        self._reload_presets()
        self._sync_controls_from_edit()
        self._flash(f"프리셋 저장: presets/{path.name}")

    def _hidden_presets(self) -> set[str]:
        v = self.settings.value("presets/hidden") or []
        return {v} if isinstance(v, str) else set(v)

    def _set_hidden_presets(self, names: set[str]):
        self.settings.setValue("presets/hidden", sorted(names))

    def _unhide_preset(self, name: str):
        hidden = self._hidden_presets()
        if name in hidden:
            self._set_hidden_presets(hidden - {name})

    def _preset_usage(self) -> dict[str, int]:
        """열린 폴더들의 보정값 파일에서 프리셋별 사용 장수."""
        used: dict[str, int] = {}
        for f in files.edit_files_in(self._photo_dirs()):
            try:
                name = json.loads(f.read_text(encoding="utf-8")).get("preset")
            except (OSError, ValueError, AttributeError):
                continue
            if name:
                used[name] = used.get(name, 0) + 1
        return used

    def delete_presets(self):
        """프리셋 삭제: 내가 만든·가져온 프리셋은 휴지통으로, 기본 프리셋은 목록에서 숨긴다 (다시 보이기 가능)."""
        self._flush_save()
        found = P.preset_files()
        hidden = self._hidden_presets()
        used = self._preset_usage()
        items = sorted(((name, P.preset_info(f)[0], name in P.BUILTIN_PRESETS, used.get(name, 0))
                        for name, f in found.items() if name not in hidden), key=lambda t: (t[2], t[1]))
        dlg = PresetDeleteDialog(self, items, len(hidden & set(found)))
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.restore:
            self._set_hidden_presets(set())
            self._reload_presets()
            self._sync_controls_from_edit()
            self._flash("숨긴 기본 프리셋을 다시 보이게 했습니다")
            return
        names = dlg.chosen()
        if not names:
            return
        labels = [next(l for n, l, _b, _u in items if n == name) for name in names]
        n_used = sum(used.get(n, 0) for n in names)
        box = QMessageBox(QMessageBox.Question, "프리셋 삭제",
                          f"프리셋 {len(names)}개를 삭제할까요?\n" + ", ".join(labels[:8]) + (" …" if len(labels) > 8 else ""),
                          parent=self)
        box.setInformativeText("내가 만든·가져온 프리셋은 휴지통으로 옮기고, 기본 프리셋은 목록에서 숨깁니다."
                               + (f"\n열린 폴더에서 {n_used}장이 이 프리셋을 쓰고 있어 프리셋 없이 보이게 됩니다." if n_used else ""))
        ok = box.addButton("삭제", QMessageBox.DestructiveRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not ok:
            return
        failed = []
        for name in names:
            own = P.PRESET_DIR / f"{name}.yaml"
            if name not in P.BUILTIN_PRESETS and own.exists() and not self._move_to_trash(own):
                failed.append(name)
                continue
            if name in P.preset_files():  # 기본 프리셋, 또는 앱 안에 든 사본이 남은 경우: 목록에서만 숨긴다
                hidden.add(name)
        self._set_hidden_presets(hidden)
        self._reload_presets()
        self._sync_controls_from_edit()
        if self.current and self.edit.get("preset") in names:
            self._schedule_render()
        if failed:
            QMessageBox.warning(self, "프리셋 삭제", "휴지통으로 옮기지 못한 프리셋:\n" + "\n".join(failed))
        else:
            self._flash(f"프리셋 {len(names)}개를 삭제했습니다")

    def import_presets(self):
        """프리셋 파일(.yaml · 라이트룸 .xmp)을 presets/에 넣어 목록에 보이게 한다. 지금 사진에는 적용하지 않는다."""
        fs, _ = QFileDialog.getOpenFileNames(self, "프리셋 가져오기", str(Path.home()),
                                             "프리셋 (*.yaml *.yml *.xmp);;LUMIQ 프리셋 (*.yaml *.yml);;"
                                             "라이트룸 프리셋 (*.xmp)")
        if not fs:
            return
        done, failed, notes = [], [], []
        for f in fs:
            try:
                data, label, desc, warn = P.read_preset_file(f)
            except Exception as e:  # 형식이 다른 파일 (yaml·xml 오류 포함)
                failed.append(f"{Path(f).name}: {e if isinstance(e, ValueError) else '프리셋 파일로 읽을 수 없습니다'}")
                continue
            existing = P.preset_files()
            name = P.preset_slug(Path(f).stem)
            if name in existing:
                box = QMessageBox(QMessageBox.Question, "프리셋 가져오기",
                                  f"'{label}'와(과) 같은 이름의 프리셋({name})이 이미 있습니다.", parent=self)
                keep = box.addButton("이름 바꿔 가져오기", QMessageBox.AcceptRole)
                over = box.addButton("덮어쓰기", QMessageBox.DestructiveRole)
                box.addButton("건너뛰기", QMessageBox.RejectRole)
                box.setDefaultButton(keep)
                box.exec()
                if box.clickedButton() is keep:
                    i = 2
                    while f"{name}_{i}" in existing:
                        i += 1
                    name = f"{name}_{i}"
                elif box.clickedButton() is not over:
                    continue
            P.write_preset(name, data, label, desc)
            self._unhide_preset(name)
            done.append(label)
            notes += warn
        if done:
            self._reload_presets()
            self._sync_controls_from_edit()
            self._flash(f"프리셋 {len(done)}개 가져옴: {', '.join(done)}  ·  프리셋 목록에서 고르세요", 8)
        if failed or notes:
            text = ""
            if failed:
                text += "가져오지 못한 파일:\n" + "\n".join(failed[:10])
            if notes:
                text += ("\n\n" if text else "") + "참고:\n" + "\n".join(notes[:15])
            QMessageBox.information(self, "프리셋 가져오기", text)

    # ================================================================== 컨트롤 ↔ 값
    def _set_combo(self, combo: QComboBox, data):
        combo.blockSignals(True)
        i = combo.findData(data)
        if i < 0 and data is not None:
            pos = combo.count() - 1 if combo is self.lut_combo else combo.count()
            combo.insertItem(pos, Path(str(data)).stem, data)
            i = combo.findData(data)
        combo.setCurrentIndex(max(i, 0))
        combo.blockSignals(False)

    def _set_check(self, box: QCheckBox, on: bool):
        box.blockSignals(True)
        box.setChecked(bool(on))
        box.blockSignals(False)
        if box is self.auto_check:  # 자동 밝기는 자동 보정이 켜져 있을 때만 보인다
            self.auto_bright.setVisible(bool(on))

    def _sync_controls_from_edit(self):
        """사진을 바꾸거나 실행 취소했을 때: 렌더 전이라도 edit 값으로 컨트롤을 맞춘다."""
        e = self.edit
        self._set_combo(self.preset_combo, e.get("preset"))
        xmp = e.get("xmp")
        self.xmp_label.setText(Path(xmp).name if xmp else "")
        self.xmp_clear.setVisible(bool(xmp))
        self.xmp_btn.setText("xmp" if xmp else "라이트룸 xmp 불러오기")
        self._set_check(self.auto_check, e.get("auto"))
        self._set_check(self.denoise_check, e.get("ai_denoise"))
        raw = self.current is not None and is_raw(self.current)
        self.camera_check.setEnabled(raw)
        self._set_check(self.camera_check, e.get("camera_match", self._camera_default()) if raw else False)
        lut = e.get("lut") or {}
        self._set_combo(self.lut_combo, lut.get("file") if isinstance(lut, dict) else lut)
        self._set_check(self.level_check, e.get("auto_level", True))
        for key, row in self.rows.items():
            v = self._value_for(e, key)
            if v is not None:
                row.set_value(v)
        self._mark_overrides()

    def _value_for(self, p: dict, key: str):
        if key == "ai_denoise.strength":
            ad = p.get("ai_denoise")
            return ad.get("strength", 100) if isinstance(ad, dict) else 100
        return get_nested(p, key)

    def _mark_overrides(self):
        for key, row in self.rows.items():
            if key == "ai_denoise.strength":
                on = isinstance(self.edit.get("ai_denoise"), dict)
            else:
                on = get_nested(self.edit, key) is not None
            row.set_overridden(on)

    def _sync_controls_from_result(self, r: RenderResult):
        """렌더 결과의 실제 적용값(프리셋·자동 포함)을 슬라이더에 표시."""
        p = r.applied
        self.rows["temperature"].set_origin(r.as_shot[0])
        self.rows["tint"].set_origin(r.as_shot[1])
        for key, row in self.rows.items():
            v = self._value_for(p, key)
            if v is None:
                v = r.as_shot[0] if key == "temperature" else r.as_shot[1] if key == "tint" else row.default
            row.set_value(v)
        self._set_check(self.lens_check, p.get("lens", r.is_raw))
        self._set_check(self.auto_check, p.get("auto"))
        self._set_check(self.denoise_check, p.get("ai_denoise"))
        self._set_check(self.level_check, p.get("auto_level", True))
        self.camera_check.setEnabled(r.is_raw)
        self._set_check(self.camera_check, r.is_raw and p.get("camera_match", False))
        geo = []
        if abs(r.angle) > 0.01:
            geo.append(f"회전 {r.angle:+.1f}°")
        if p.get("crop_rect"):
            geo.append("자유 크롭")
        elif p.get("crop"):
            geo.append(f"크롭 {p['crop']}")
        if p.get("rotate90"):
            geo.append({"cw": "오른쪽 90°", "ccw": "왼쪽 90°", "180": "180°"}[str(p["rotate90"])])
        if p.get("flip"):
            geo.append("반전")
        self.geo_label.setText("   ·   ".join(geo) if geo else "자르기·회전 없음")
        self._mark_overrides()

    # ================================================================== 렌더
    def _schedule_render(self):
        if not self.current:
            return
        if self._grid_shown():
            self._render_pending = True  # 그리드에서는 큰 사진을 보지 않으니 나갈 때 렌더
            return
        self._render_pending = False
        self._render_timer.start()

    def _do_render(self):
        if not self.current:
            return
        self._gen += 1
        self.worker.submit(self.current, self.edit, self._gen)
        if self._prefetch_pending:
            self._prefetch_pending = False
            i = self.photos.index(self.current) if self.current in self.photos else -1
            nxt = next((p for p in self.photos[i + 1:] if self._matches(p)), None) if i >= 0 else None
            if nxt is not None:  # 다음 사진을 미리 디코딩해 넘길 때 빠르게
                self.worker.submit_prefetch(nxt, files.load_edit(nxt))
        self.request_render.emit()

    def _on_render(self, r: RenderResult):
        if r.full_frame:
            if self._crop_wait and r.path == self.current:
                self._enter_crop_with(r)
            return
        if r.path != self.current or r.gen < self._shown_gen:
            return
        self._shown_gen = r.gen
        self.result = r
        if self.view.mode != "crop":
            self._show_image()
        self.hist.set_data(r.hist)
        if r.gen == self._gen:
            self._sync_controls_from_result(r)
            it = self._thumbs.get(str(r.path))
            if it is not None:  # 썸네일도 보정 결과로
                thumb = to_qimage(r.rgb).scaled(320, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                it.setIcon(QIcon(QPixmap.fromImage(thumb)))
                it.setData(Qt.UserRole + 2, True)
            self._state_timer.start()
            if self._crop_after_render and self.mode == "edit":  # 보기 모드에서 R을 눌렀을 때
                self._crop_after_render = False
                self.enter_crop()
        msg = []
        if self.mode == "edit":  # 보기 모드에서는 처리 정보를 감춘다
            msg.append(f"{r.seconds:.2f}초")
            if r.auto_reasons:
                msg.append("자동: " + ", ".join(r.auto_reasons))
            if r.faces:
                msg.append(f"얼굴 {r.faces}")
            msg += [m.strip() for m in r.logs]
        if time.time() < self._note[1]:
            msg.insert(0, self._note[0])
        self.statusBar().showMessage("    ·    ".join(msg))

    def _on_render_failed(self, path, gen, msg):
        if Path(path) == self.current:
            self.statusBar().showMessage(f"처리 실패: {msg}")
            if self.result is None:
                self.info_name.setText(f"이 사진을 열 수 없습니다 — {msg}")

    def _show_image(self, *_):
        if not self.result:
            return
        self.view.set_source_scale(self.result.scale)
        if self.compare_btn.isChecked():  # 비교선: 왼쪽 보정 전 / 오른쪽 보정 후
            self.view.set_before(to_qimage(self.result.before))
            self.view.set_image(to_qimage(self.result.rgb))
            self.view.set_badge("")
            return
        before = self.show_before
        self.view.set_before(None)
        self.view.set_image(to_qimage(self.result.before if before else self.result.rgb))
        self.view.set_badge("보정 전" if before else "")

    def _toggle_compare(self, on: bool):
        self.view.set_compare(on)
        self._refresh_hint()
        self._show_image()

    def _on_hold(self, on: bool):
        if on and self.mode != "edit":  # 보기 모드에서는 클릭해도 보정 전으로 바꾸지 않는다
            return
        self.show_before = on
        self._show_image()

    def _flash(self, text: str, sec: float = 6):
        self._note = (text, time.time() + sec)
        self.statusBar().showMessage(text, int(sec * 1000))
        if self.mode != "edit":  # 보기 모드에서는 알림이 있을 때만 상태 줄을 잠깐 보인다
            self.statusBar().show()
            self._status_timer.start(int(sec * 1000))

    # ================================================================== 자르기·회전 (R)
    def toggle_crop(self):
        if self.view.mode == "crop":
            self.leave_crop(apply=True)
            return
        if self.mode != "edit":
            self.set_mode("edit")
        self.enter_crop()

    def enter_crop(self):
        if not self.current or self.mode != "edit":
            self.crop_btn.setChecked(False)
            return
        if self.result is None or self.result.path != self.current:
            self._crop_after_render = True  # 첫 렌더가 끝나면 들어간다
            self.crop_btn.setChecked(False)
            return
        self._flush_save()
        self._crop_wait = True
        self.crop_btn.setChecked(True)
        self._gen += 1
        self.worker.submit(self.current, self.edit, self._gen, full_frame=True)
        self.request_render.emit()

    def _enter_crop_with(self, r: RenderResult):
        self._crop_wait = False
        img = to_qimage(r.rgb)
        W, H = img.width(), img.height()
        p = r.applied
        self._crop_level = r.level_angle
        angle = float(p.get("rotate", 0) or 0) + (r.level_angle if p.get("auto_level", True) else 0.0)
        lock_label = self.edit.get("crop") or p.get("crop")
        if p.get("crop_rect"):
            cx, cy, cw, ch = G.fit_rect(*G.rect_to_pixels(p["crop_rect"], W, H), W, H, angle)
        elif p.get("crop") or p.get("crop_center") or abs(angle) > 1e-3:
            ratio = G.parse_ratio(p.get("crop"), W, H, p.get("crop_orientation", "auto"))
            cw, ch = G.largest_rect(W, H, angle, ratio)
            cx = cy = 0.0
            if p.get("crop_center"):
                cx = (float(p["crop_center"][0]) - 0.5) * W
                cy = (float(p["crop_center"][1]) - 0.5) * H
                cx, cy, cw, ch = G.fit_rect(cx, cy, cw, ch, W, H, angle)
        else:
            cx, cy, cw, ch = 0.0, 0.0, float(W), float(H)
        if lock_label:
            lock = G.parse_ratio(lock_label, W, H, "landscape" if cw >= ch else "portrait")
            label = lock_label
        elif abs(cw / ch - W / H) < 0.01:
            lock, label = W / H, "original"
        else:
            lock, label = None, None
        self.ratio_combo.blockSignals(True)
        self.ratio_combo.setCurrentIndex(max(self.ratio_combo.findData(label), 0))
        self.ratio_combo.blockSignals(False)
        self.view.enter_crop(img, angle, (cx, cy, cw, ch), lock)
        self.angle_row.set_value(angle)
        self.info_bar.setVisible(False)
        self.crop_bar.setVisible(True)
        self.adjust_page.setEnabled(False)
        for b in (self.compare_btn, self.copy_btn, self.paste_btn, self.undo_btn, self.redo_btn):
            b.setEnabled(False)
        self._flash("드래그: 틀 안 = 이동 · 모서리 = 크기 · 틀 밖 = 회전    Enter 완료 · Esc 취소 · X 가로/세로", 10)

    def leave_crop(self, apply: bool):
        if self._crop_wait:
            self._crop_wait = False
            self.crop_btn.setChecked(False)
            return
        if self.view.mode != "crop":
            return
        if apply:
            angle, rect = self.view.crop_result()
            W, H = self.view.W, self.view.H
            full = abs(rect[0]) < 0.002 and abs(rect[1]) < 0.002 and rect[2] > 0.996 and rect[3] > 0.996
            self._push_undo()
            e = self.edit
            for k in ("crop_center", "crop_orientation", "crop_rect", "crop"):
                e.pop(k, None)
            if abs(angle) < 0.01 and full:
                e.pop("rotate", None)
            else:
                e["rotate"] = round(angle, 2)
                if not full:
                    e["crop_rect"] = rect
            if abs(self._crop_level) > 1e-3 or e.get("rotate") is not None:
                e["auto_level"] = False  # 화면에서 맞춘 각도를 그대로 쓰도록
            label = self.ratio_combo.currentData()
            if label and label != "original" and not full:
                e["crop"] = label
            if e.get("rotate") is None and e.get("auto_level") is False and abs(self._crop_level) < 1e-3:
                e.pop("auto_level")
            self._after_edit_change()
        self.view.leave_crop()
        self.crop_bar.setVisible(False)
        self.info_bar.setVisible(True)
        self.adjust_page.setEnabled(True)
        for b in (self.compare_btn, self.copy_btn, self.paste_btn, self.undo_btn, self.redo_btn):
            b.setEnabled(True)
        self.crop_btn.setChecked(False)
        self._show_image()

    def _on_crop_angle(self, angle: float):
        self.angle_row.set_value(angle)

    def _on_ratio(self, _):
        data = self.ratio_combo.currentData()
        W, H = self.view.W, self.view.H
        cw, ch = self.view.rect_[2], self.view.rect_[3]
        if data is None:
            self.view.set_lock(None)
        elif data == "original":
            self.view.set_lock(W / H if (cw >= ch) == (W >= H) else H / W)
        else:
            self.view.set_lock(G.parse_ratio(data, W, H, "landscape" if cw >= ch else "portrait"))

    def _swap_ratio(self):
        if self.view.mode != "crop":
            return
        if self.view.lock:
            self.view.set_lock(1 / self.view.lock)
        else:
            cx, cy, cw, ch = self.view.rect_
            self.view.lock = None
            self.view.rect_ = self.view.base_rect = G.fit_rect(cx, cy, ch, cw, self.view.W, self.view.H, self.view.angle)
            self.view.update()

    def _auto_level_crop(self):
        self.view.base_rect = self.view.rect_
        self.view.set_angle(self._crop_level, emit=True)
        if abs(self._crop_level) < 1e-3:
            self._flash("뚜렷한 수평선·수직선을 찾지 못했습니다")

    def _reset_crop(self):
        label = self.ratio_combo.currentData()
        W, H = self.view.W, self.view.H
        self.ratio_combo.blockSignals(True)
        self.ratio_combo.setCurrentIndex(self.ratio_combo.findData("original"))
        self.ratio_combo.blockSignals(False)
        self.view.reset_crop(W / H)
        del label

    # ================================================================== 저장 · 외부 변경
    def _save_now(self):
        if not self.current:
            return
        path = files.save_edit(self.current, self.edit)
        key = str(self.current)
        if files.has_adjustments(self.edit):
            self._edited.add(key)
        else:
            self._edited.discard(key)
        (self._gps.add if isinstance(self.edit.get("gps"), dict) else self._gps.discard)(key)
        self._store_rating(key, self.edit)
        self._refresh_badge(key)
        if path.exists() and str(path) not in self.watcher.files():
            self.watcher.addPath(str(path))

    def _flush_save(self):
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()

    def _reload_from_disk(self):
        """Claude Code 등 밖에서 보정값 파일(.lumiq.json)을 고쳤을 때 반영."""
        self._scan_edited()
        self._refresh_badges()
        if self.rating_filter is not None:  # 별점이 밖에서 바뀌었을 수 있다
            self._apply_filter()
        if self.current is not None:
            self.stars.set_value(self._rating(self.current))
        if not self.current or self._save_timer.isActive() or self.view.mode == "crop":
            return
        disk = files.load_edit(self.current)
        disk.pop("file", None)
        self._watch_current()
        if disk != self.edit:
            self._push_undo()
            self.edit = disk
            self._after_edit_change(sync=True)
            self._save_timer.stop()
            self._flash("보정값이 밖에서 바뀌어 다시 불러왔습니다 (Claude Code)", 8)

    def _scan_edited(self):
        self._edited, self._gps, self._ratings = set(), set(), {}
        for f in files.edit_files_in(self._photo_dirs()):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(d, dict):
                continue
            key = str(files.photo_for_edit(f))
            if files.has_adjustments(d):
                self._edited.add(key)
            if isinstance(d.get("gps"), dict):
                self._gps.add(key)
            self._store_rating(key, d)

    def _exported_stems(self, dirs=None) -> set:
        """내보낸 사진 {(사진 폴더, 파일명)}: 각 사진 폴더의 export/를 본다 (하위 폴더 포함)."""
        out = set()
        for d in dirs if dirs is not None else {p.parent for p in self.photos}:
            ex = d / "export"
            if ex.is_dir():
                out |= {(d, f.name.split("_edit")[0]) for f in ex.iterdir() if "_edit" in f.name}
        return out

    def _refresh_badges(self):
        stems = self._exported_stems()
        for key in self._thumbs:
            self._refresh_badge(key, stems)

    def _refresh_badge(self, key: str, exported: set | None = None):
        it = self._thumbs.get(key)
        if it is None or not self.folder:
            return
        p = Path(key)
        if exported is None:
            exported = self._exported_stems([p.parent])
        gps = key in self._gps or bool(self.engine._exif.get(key, {}).get("GPSPosition"))
        it.setData(Qt.UserRole + 1, {"edited": key in self._edited, "exported": (p.parent, p.stem) in exported,
                                     "gps": gps, "rating": self._ratings.get(key, 0)})

    def _write_state(self):
        """VSCode의 Claude Code가 '지금 보고 있는 사진'을 알 수 있도록 상태와 현재 화면을 남긴다."""
        if not self.current:
            return
        try:
            if self.result is not None and self.result.path == self.current:
                img = to_qimage(self.result.rgb).scaled(1024, 1024, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                CURRENT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
                img.save(str(CURRENT_PREVIEW), "JPG", 85)
            edit_file = files.find_edit(self.current) or files.edit_path_for(self.current)
            state = {
                "folder": str(self.folder) if self.folder else None,
                "current": str(self.current),
                "current_edit_file": str(edit_file),
                "current_preview": str(CURRENT_PREVIEW.relative_to(DATA)),
                "selected": [str(p) for p in self._selected_paths()][:200],
                "updated": datetime.now().isoformat(timespec="seconds"),
            }
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    # ================================================================== 복사 · 붙여넣기
    def _selected_paths(self) -> list[Path]:
        return [Path(it.data(Qt.UserRole)) for it in self.list.selectedItems()]

    def copy_settings(self):
        if not self.current:
            return
        self._clipboard = {k: copy.deepcopy(v) for k, v in self.edit.items() if k not in PASTE_SKIP}
        self._flash(f"설정 복사: {len(self._clipboard)}개 항목 (자르기 영역 제외)  ·  {N.key_text('Ctrl+Shift+V')}로 붙여넣기")

    def paste_settings(self, all_photos=False):
        if self._clipboard is None:
            self._flash(f"먼저 설정 복사({N.key_text('Ctrl+Shift+C')})를 하세요")
            return
        targets = self.photos if all_photos else self._selected_paths()
        if not targets:
            return
        self._flush_save()
        for t in targets:
            if t == self.current:
                self._push_undo()
                self.edit.update(copy.deepcopy(self._clipboard))
                self._after_edit_change(sync=True)
            else:
                e = files.load_edit(t)
                e.pop("file", None)
                self._session_note(t, e)
                e.update(copy.deepcopy(self._clipboard))
                files.save_edit(t, e)
                self._edited.add(str(t))
                self._refresh_badge(str(t))
                it = self._thumbs.get(str(t))
                if it is not None:
                    it.setData(Qt.UserRole + 2, None)
        self._flush_save()
        self._flash(f"{len(targets)}장에 붙여넣음")

    # ================================================================== 그리드 보기 옵션
    def _apply_grid_options(self):
        w = GRID_SIZES[self.grid_size][1]
        square = self.grid_shape == "square"
        if self.grid_names:  # 썸네일 칸 = 칸 - 여백(가로 28, 세로 44: 이름 줄 포함)
            h = w + 16 if square else round(w * 0.86)
        else:  # 썸네일 칸 = 칸 - 16
            h = w if square else round((w - 16) * 0.75) + 16
        self.grid_delegate.configure(w, h, self.grid_names, square)
        self.grid.setGridSize(QSize(w, h))
        self.grid.doItemsLayout()  # 같은 크기 캐시(uniformItemSizes)까지 다시 계산
        self.grid.viewport().update()
        idx = self.list.currentIndex()
        if idx.isValid() and self._grid_shown():
            self.grid.scrollTo(idx)

    def _set_grid_option(self, shape=None, size=None, names=None):
        if shape is not None:
            self.grid_shape = shape
            self.settings.setValue("grid/shape", shape)
        if size is not None:
            self.grid_size = min(max(int(size), 0), len(GRID_SIZES) - 1)
            self.settings.setValue("grid/size", self.grid_size)
            for a in self.size_group.actions():
                a.setChecked(a.data() == self.grid_size)
        if names is not None:
            self.grid_names = bool(names)
            self.settings.setValue("grid/names", "true" if names else "false")
        self._apply_grid_options()

    def _zoom(self, d: int):
        """⌘+ ⌘− ⌘0: 그리드에서는 썸네일 크기, 큰 사진에서는 보이는 크기만 (0이면 맞춤)."""
        if self._grid_shown():
            if d:
                self._set_grid_option(size=self.grid_size + d)
        elif self.current and self.center_stack.currentIndex() == 1 and self.view.mode != "crop":
            if d:
                self.view.zoom_step(d)
            else:
                self.view.reset_zoom()

    def _on_zoom(self, z: float):
        """확대율 표시: 원본 대비 % (맞춤이면 '맞춤 33%')."""
        pct = self.view.percent()
        text = "" if pct is None else (f"{pct:.0f}%" if pct >= 10 else f"{pct:.1f}%")
        self.zoom_label.setText(f"맞춤 {text}".strip() if z == 1.0 else text)
        self._refresh_hint()

    # ================================================================== 별점 · 별점 필터
    def _rating(self, photo: Path | None) -> int:
        return self._ratings.get(str(photo), 0) if photo else 0

    def _store_rating(self, key: str, edit: dict):
        try:
            r = min(max(int(edit.get("rating") or 0), 0), 3)
        except (TypeError, ValueError):
            r = 0
        if r:
            self._ratings[key] = r
        else:
            self._ratings.pop(key, None)

    def set_rating(self, n: int, targets: list[Path] | None = None):
        """별점 0~3 (0은 지움). 선택한 사진(그리드) 또는 지금 사진에. 보정값 파일의 rating에만 저장하고 다시 그리지 않는다."""
        if self.view.mode == "crop" or self._crop_wait:
            return
        targets = [t for t in (targets if targets is not None else self._action_targets()) if t]
        if not targets:
            return
        self._flush_save()
        changed = 0
        for t in targets:
            if self._rating(t) == n:
                continue
            if t == self.current:
                if n:
                    self.edit["rating"] = n
                else:
                    self.edit.pop("rating", None)
                self._save_now()
            else:
                e = files.load_edit(t)
                e.pop("file", None)
                if n:
                    e["rating"] = n
                else:
                    e.pop("rating", None)
                files.save_edit(t, e)
                self._store_rating(str(t), e)
                self._refresh_badge(str(t))
            changed += 1
        if not changed:
            return
        self.stars.set_value(self._rating(self.current))
        hidden = self.rating_filter is not None and not all(self._matches(t) for t in targets)
        if len(targets) > 1 or hidden:
            k = len(targets)
            if n:
                note = f"{k}장에 {RATING_STARS[n]} 별점" if k > 1 else f"{RATING_STARS[n]} 별점"
            else:
                note = f"{k}장의 별점을 지웠습니다" if k > 1 else "별점을 지웠습니다"
            self._flash(note + ("  ·  필터에 맞지 않아 숨겼습니다" if hidden else ""), 3)
        if self.rating_filter is not None:
            self._apply_filter()
        else:
            self._update_info()

    def _matches(self, photo: Path) -> bool:
        f = self.rating_filter
        if f is None:
            return True
        r = self._rating(photo)
        return r == 0 if f == 0 else r >= f

    def _visible_photos(self) -> list[Path]:
        return [p for p in self.photos if self._matches(p)]

    def _set_filter_ui(self, value: int | None):
        """필터 값과 메뉴 체크·버튼 표시를 맞춘다 (사진 목록은 _apply_filter가)."""
        self.rating_filter = value
        for a in self.filter_group.actions():
            a.setChecked(a.data() == value)
        short = next(s for _l, s, v in RATING_FILTERS if v == value)
        on = value is not None
        self.filter_btn.setIcon(T.icon("star_fill" if on else "star", T.STAR if on else T.TEXT2, 18))
        self.filter_btn.setText(f" {short}" if on else "")
        self.filter_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if on else Qt.ToolButtonIconOnly)
        self.filter_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }"
                                      + (f"QToolButton {{ color: {T.STAR}; }}" if on else ""))

    def set_rating_filter(self, value: int | None):
        self._set_filter_ui(value)
        self._apply_filter()
        if self.photos and not self._visible_photos():
            label = next(l for l, _s, v in RATING_FILTERS if v == value)
            self._flash(f"'{label}'에 맞는 사진이 없습니다", 4)

    def _apply_filter(self, move: bool = True):
        """별점 필터에 맞지 않는 사진을 왼쪽 목록·그리드·필름스트립에서 숨긴다.
        move면 지금 사진이 숨었을 때 다음(없으면 이전) 사진으로 넘어간다."""
        views = (self.list, self.grid, self.filmstrip)
        for row in range(self.list.count()):
            it = self.list.item(row)
            hide = not self._matches(Path(it.data(Qt.UserRole)))
            for v in views:
                if v.isRowHidden(row) != hide:
                    v.setRowHidden(row, hide)
            if hide and it.isSelected():  # 숨긴 사진이 내보내기·붙여넣기 대상에 남지 않도록
                it.setSelected(False)
        if self.folder:
            self._update_counts()
        cur = self.current
        if move and cur in self.photos and not self._matches(cur):
            i = self.photos.index(cur)
            nxt = next((p for p in self.photos[i + 1:] if self._matches(p)), None) \
                or next((p for p in reversed(self.photos[:i]) if self._matches(p)), None)
            if nxt is not None:
                self.list.setCurrentItem(self._thumbs[str(nxt)])
            elif self.mode == "view":  # 맞는 사진이 하나도 없으면 빈 그리드로
                self.set_mode("view", "grid")
        self._update_info()
        idx = self.list.currentIndex()
        if idx.isValid() and not self.list.isRowHidden(idx.row()):
            (self.grid if self._grid_shown() else self.filmstrip).scrollTo(idx)

    # ================================================================== 오른쪽 클릭 메뉴
    def _selected_in_order(self) -> list[Path]:
        rows = sorted(self.list.row(it) for it in self.list.selectedItems())
        return [Path(self.list.item(r).data(Qt.UserRole)) for r in rows]

    def _action_targets(self) -> list[Path]:
        """메뉴 막대·단축키의 대상: 그리드·목록·필름스트립에서는 선택한 사진, 큰 사진을 보고 있으면 그 사진."""
        if self._grid_shown() or QApplication.focusWidget() in (self.filmstrip, self.list):
            sel = self._selected_in_order()
            if sel:
                return sel
        return [self.current] if self.current else []

    def _list_menu(self, view: QListView, pos):
        if self.view.mode == "crop" or self._crop_wait or not self.photos:
            return
        gpos = view.viewport().mapToGlobal(pos)
        idx = view.indexAt(pos)
        if not idx.isValid():
            if view is self.grid:  # 빈 곳: 보기 옵션 · 별점 필터
                menu = self._fill_grid_menu(QMenu(self))
                menu.addSeparator()
                menu.addMenu("별점 필터").addActions(self.filter_actions)
                menu.exec(gpos)
                menu.deleteLater()
            return
        if not self.list.selectionModel().isSelected(idx):  # Finder처럼 누른 사진만 선택
            view.setCurrentIndex(idx)
        self._photo_menu(gpos, self._selected_in_order() or [self.current], in_grid=view is self.grid)

    def _view_menu(self, pos):
        """한 장 보기·편집 화면의 큰 사진: 지금 사진만 대상."""
        if self.view.mode == "crop" or self._crop_wait or not self.current:
            return
        self._photo_menu(self.view.mapToGlobal(pos), [self.current])

    def _photo_menu(self, gpos, targets: list[Path], in_grid: bool = False):
        targets = [t for t in targets if t]
        if not targets:
            return
        n = len(targets)
        menu = QMenu(self)
        fns = {}

        def add(text, fn, icon=None, shortcut=None):
            a = menu.addAction(text)
            if icon:
                a.setIcon(T.icon(icon, T.TEXT2, 16))
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setShortcutVisibleInContextMenu(True)
            fns[a] = fn
            return a

        def add_rating(title):
            sub = menu.addMenu(T.icon("star", T.TEXT2, 16), title)
            now = {self._rating(t) for t in targets}
            for r, text in ((1, RATING_STARS[1]), (2, RATING_STARS[2]), (3, RATING_STARS[3]), (0, "별점 지우기")):
                if r == 0:
                    sub.addSeparator()
                a = sub.addAction(text)
                a.setCheckable(r > 0)
                a.setChecked(now == {r})
                a.setShortcut(QKeySequence(str(r)))
                a.setShortcutVisibleInContextMenu(True)
                fns[a] = lambda r=r: self.set_rating(r, targets)

        has_gps = [t for t in targets if self._added_gps(t)]
        if n == 1:
            p = targets[0]
            if in_grid:
                add("크게 보기", lambda: self.set_mode("view", "single"), "photo")
            if self.mode != "edit":
                add("편집", lambda: self.set_mode("edit"), "sliders", "E")
            add_rating("별점")
            menu.addSeparator()
            add("위치 수정…" if has_gps else "위치(GPS) 추가…", lambda: self.add_location(targets), "pin")
            if has_gps:
                add("위치 지우기", lambda: self._apply_gps(targets, None))
            menu.addSeparator()
            add("설정 복사", self.copy_settings, "copy", "Ctrl+Shift+C")
            if self._clipboard is not None:
                add("설정 붙여넣기", self.paste_settings, "paste", "Ctrl+Shift+V")
            add(f"{N.FILE_MANAGER}에서 보기", lambda: N.reveal(p), "finder", "Ctrl+Shift+R")
            add("내보내기…", self.export_dialog, "export", "Ctrl+E")
            menu.addSeparator()
            add("휴지통으로 이동", lambda: self.trash_photos(targets), "trash", N.TRASH_KEY)
        else:
            head = menu.addAction(f"선택한 사진 {n}장")
            head.setEnabled(False)
            menu.addSeparator()
            add_rating(f"선택한 {n}장 별점")
            menu.addSeparator()
            add(f"선택한 {n}장에 위치(GPS) 추가…", lambda: self.add_location(targets), "pin")
            if has_gps:
                add(f"위치 지우기 ({len(has_gps)}장)", lambda: self._apply_gps(targets, None))
            menu.addSeparator()
            if self._clipboard is not None:
                add(f"선택한 {n}장에 설정 붙여넣기", self.paste_settings, "paste", "Ctrl+Shift+V")
            add(f"선택한 {n}장 내보내기…", self.export_dialog, "export", "Ctrl+E")
            menu.addSeparator()
            add(f"선택한 {n}장 휴지통으로 이동", lambda: self.trash_photos(targets), "trash", N.TRASH_KEY)
        chosen = menu.exec(gpos)
        menu.deleteLater()
        fn = fns.get(chosen)
        if fn is not None:  # 메뉴가 닫힌 뒤 실행 (대화상자를 띄우는 동작이 많아서)
            fn()

    # ================================================================== 휴지통으로 이동
    def trash_selected(self):
        if self._typing(QApplication.focusWidget()) or self.view.mode == "crop" or self._crop_wait:
            return
        targets = self._action_targets()
        if targets:
            self.trash_photos(targets)

    def _companions(self, targets: list[Path]) -> tuple[list[Path], dict[Path, list[Path]]]:
        """함께 옮길 파일: (목록에 안 보이는 RAW+JPEG 쌍의 JPG, 사진별 같은 이름의 설정 파일 .yaml·.xmp)."""
        shown = set(self.photos)
        by_dir: dict[Path, dict[str, list[Path]]] = {}
        pairs, sidecars = [], {}
        for t in targets:
            stems = by_dir.get(t.parent)
            if stems is None:
                stems = by_dir[t.parent] = {}
                try:
                    for f in t.parent.iterdir():
                        stems.setdefault(f.stem, []).append(f)
                except OSError:
                    pass
            same = [f for f in stems.get(t.stem, []) if f != t]
            if t.suffix.lower() in files.RAW_EXTS:
                pairs += [f for f in same if f.suffix.lower() in files.IMAGE_EXTS
                          and f.suffix.lower() not in files.RAW_EXTS and f not in shown]
            sidecars[t] = [f for f in same if f.suffix.lower() in SIDECAR_EXTS]
        return pairs, sidecars

    def _photo_dirs(self) -> list[Path]:
        """사진이 있는 폴더들 (하위 폴더 포함). 보정값 파일이 여기에 있다."""
        return sorted({p.parent for p in self.photos})

    def _watch_folders(self):
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        dirs = [str(d) for d in self._photo_dirs()]
        if dirs:
            self.watcher.addPaths(dirs)

    def _edit_snapshot(self) -> dict[str, str]:
        """열린 폴더들의 보정값 파일 내용 (AI가 무엇을 바꿨는지 비교·되돌리기용)."""
        out = {}
        for f in files.edit_files_in(self._photo_dirs()):
            try:
                out[str(f)] = f.read_text(encoding="utf-8")
            except OSError:
                pass
        return out

    def _migrate_legacy(self):
        """예전 작업 폴더의 edits/*.json을 사진 옆 .lumiq.json으로 옮긴다 (사진을 못 찾은 것은 남김)."""
        moved, left = files.migrate_legacy_edits()
        if moved:
            self._scan_edited()
            self._refresh_badges()
            self._flash(f"보정값 {len(moved)}개를 사진 옆(.lumiq.json)으로 옮겼습니다"
                        + (f"  ·  사진을 찾지 못한 {len(left)}개는 edits/에 남김" if left else ""), 8)

    def _own_edit_file(self, photo: Path) -> Path | None:
        """이 사진만의 보정값 파일 (file 경로가 정확히 이 사진인 것)."""
        return files.find_edit(photo)

    @staticmethod
    def _move_to_trash(path: Path) -> bool:
        try:
            r = QFile.moveToTrash(str(path))
        except Exception:
            return False
        return bool(r[0] if isinstance(r, tuple) else r)

    def trash_photos(self, targets: list[Path]):
        """사진을 macOS 휴지통으로 (되살릴 수 있음). 보정값 파일·같은 이름의 설정 파일도 함께, export 결과는 그대로."""
        targets = [t for t in self.photos if t in set(targets)]
        if not targets:
            return
        ex = getattr(self, "_export", None)
        if ex and ex["thread"].isRunning():
            self._flash("내보내기가 끝난 뒤에 휴지통으로 옮길 수 있습니다")
            return
        n = len(targets)
        pairs, sidecars = self._companions(targets)
        box = QMessageBox(QMessageBox.Question, "휴지통으로 이동",
                          f"'{self._display_name(targets[0])}'을(를) 휴지통으로 옮길까요?" if n == 1
                          else f"선택한 사진 {n}장을 휴지통으로 옮길까요?", parent=self)
        box.setInformativeText(f"{N.TRASH}에서 되살릴 수 있습니다. 보정값도 함께 옮기고, "
                               "내보낸 JPEG(export 폴더)는 그대로 둡니다.")
        with_pairs = None
        if pairs:
            with_pairs = QCheckBox(f"같은 이름의 JPG도 함께 옮기기 (RAW+JPEG로 찍은 {len(pairs)}장)")
            with_pairs.setChecked(True)
            box.setCheckBox(with_pairs)
        ok = box.addButton("휴지통으로 이동", QMessageBox.DestructiveRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.setDefaultButton(ok)
        box.exec()
        if box.clickedButton() is not ok:
            return
        all_pairs = pairs
        if with_pairs is not None and not with_pairs.isChecked():
            pairs = []
        if self.current in targets:  # 지울 사진의 보정값을 다시 쓰지 않도록
            self._save_timer.stop()
        self._flush_save()
        # 같은 이름의 사진이 남아 있으면 그 설정 파일(.yaml·.xmp)은 남긴다
        kept_stems = {(p.parent, p.stem) for p in self.photos if p not in targets}
        kept_stems |= {(f.parent, f.stem) for f in all_pairs if f not in pairs}
        gone, failed = [], []
        for t in targets:
            edit_file = self._own_edit_file(t)
            if not self._move_to_trash(t):
                failed.append(t.name)
                continue
            gone.append(t)
            if edit_file is not None:
                self._move_to_trash(edit_file)
            if (t.parent, t.stem) not in kept_stems:
                for f in sidecars.get(t, []):
                    self._move_to_trash(f)
        gone_stems = {(g.parent, g.stem) for g in gone}
        for f in pairs:
            if (f.parent, f.stem) in gone_stems:
                edit_file = self._own_edit_file(f)
                if self._move_to_trash(f) and edit_file is not None:
                    self._move_to_trash(edit_file)
        if gone:
            self._remove_photos(gone)
        if failed:
            QMessageBox.warning(self, "휴지통으로 이동", "옮기지 못한 사진:\n" + "\n".join(failed[:20]))
        elif gone:
            self._flash(f"{len(gone)}장을 휴지통으로 옮겼습니다" if len(gone) > 1
                        else f"{gone[0].name}을(를) 휴지통으로 옮겼습니다")

    def _remove_photos(self, gone: list[Path]):
        """목록에서 빼고, 지운 사진을 보고 있었으면 다음 사진으로."""
        gone_set = set(gone)
        nxt = self.current
        if self.current in gone_set:
            i = self.photos.index(self.current)
            after = [p for p in self.photos[i:] if p not in gone_set and self._matches(p)]
            before = [p for p in self.photos[:i] if p not in gone_set and self._matches(p)]
            nxt = after[0] if after else (before[-1] if before else None)
        self.list.blockSignals(True)
        for row in sorted((self.list.row(self._thumbs[str(p)]) for p in gone if str(p) in self._thumbs),
                          reverse=True):
            self.list.takeItem(row)
        self.list.blockSignals(False)
        for p in gone:
            key = str(p)
            self._thumbs.pop(key, None)
            self._undo.pop(key, None)
            self._redo.pop(key, None)
            self._edited.discard(key)
            self._gps.discard(key)
            self._ratings.pop(key, None)
            self.engine.forget(p)
        self.photos = [p for p in self.photos if p not in gone_set]
        self.subfolders = sorted({p.parent for p in self.photos if p.parent != self.folder})
        self._update_counts()
        if not self.photos:
            self.current, self.edit, self.result = None, {}, None
            self._set_has_photo(False)
            self.set_mode("view", "grid")
            self.view.set_image(None)
            self.hist.set_data(None)
            self.info_name.setText("이 폴더에 사진이 없습니다")
            self.info_meta.setText("")
            self._update_ai_context()
            return
        if nxt is None or str(nxt) not in self._thumbs:
            nxt = (self._visible_photos() or self.photos)[0]
        if nxt != self.current:
            self.current = None
        it = self._thumbs[str(nxt)]
        self.list.setCurrentItem(it)
        self.list.clearSelection()
        it.setSelected(True)
        if self.current is None:  # 지운 줄 대신 Qt가 이미 그 사진을 현재로 잡았으면 신호가 안 오므로 직접
            self._on_current_item(it, None)
        self._update_info()
        self._state_timer.start()

    # ================================================================== 위치(GPS)
    def _edit_of(self, photo: Path) -> dict:
        return self.edit if photo == self.current else files.load_edit(photo)

    def _added_gps(self, photo: Path) -> dict | None:
        g = self._edit_of(photo).get("gps")
        return g if isinstance(g, dict) and g.get("lat") is not None and g.get("lon") is not None else None

    def _exif_gps(self, photo: Path) -> dict | None:
        c = parse_coords(str(self.engine._exif.get(str(photo), {}).get("GPSPosition") or ""))
        return {"lat": c[0], "lon": c[1]} if c else None

    def add_location(self, targets: list[Path] | None = None):
        """선택한 사진(또는 지금 사진)에 위치를 추가·수정. 원본은 그대로, 보정값 파일에 저장하고 내보낼 때 기록."""
        if self.view.mode == "crop" or self._crop_wait:
            return
        targets = targets or self._action_targets()
        if not targets:
            return
        self._flush_save()
        added = [self._added_gps(t) for t in targets]
        given = [g for g in added if g]
        current = given[0] if given and len(given) == len(targets) and all(g == given[0] for g in given) else None
        sources, seen = [], set()
        for t in list(dict.fromkeys(targets + ([self.current] if self.current else []))):
            g = self._added_gps(t) or self._exif_gps(t)
            if g and (round(g["lat"], 5), round(g["lon"], 5)) not in seen:
                seen.add((round(g["lat"], 5), round(g["lon"], 5)))
                sources.append((t.name, g))
            if len(sources) >= 8:
                break
        n = len(targets)
        dlg = LocationDialog(self, "위치 수정" if current else "위치(GPS) 추가",
                             self._display_name(targets[0]) if n == 1 else f"선택한 사진 {n}장", current, sources,
                             load_recent(self.settings), n, sum(1 for t in targets if self._exif_gps(t)),
                             can_remove=bool(given))
        r = dlg.exec()
        if r == LocationDialog.REMOVE:
            self._apply_gps(targets, None)
        elif r == QDialog.Accepted and dlg.result_gps:
            remember(self.settings, dlg.result_gps)
            self._apply_gps(targets, dlg.result_gps)

    def _apply_gps(self, targets: list[Path], value: dict | None):
        """위치만 바꾼다 (보정이 아니라 다시 그리지 않음). value가 None이면 앱에서 추가한 위치를 지운다."""
        self._flush_save()
        changed = 0
        for t in targets:
            if t == self.current:
                if self.edit.get("gps") == value:
                    continue
                self._push_undo()
                if value is None:
                    self.edit.pop("gps", None)
                else:
                    self.edit["gps"] = dict(value)
                self._save_now()
            else:
                e = files.load_edit(t)
                e.pop("file", None)
                if e.get("gps") == value:
                    continue
                if value is None:
                    e.pop("gps", None)
                else:
                    e["gps"] = dict(value)
                files.save_edit(t, e)
                (self._gps.add if value else self._gps.discard)(str(t))
                self._refresh_badge(str(t))
            changed += 1
        self._update_info()
        if not changed:
            return
        if value is None:
            self._flash(f"{changed}장의 위치를 지웠습니다")
        else:
            self._flash(f"{changed}장에 위치 추가: {gps_label(value)}  ·  내보낼 때 JPEG에 기록됩니다")

    # ================================================================== AI 어시스턴트
    def _wire_assistant(self):
        a = self.assistant
        a.send.connect(self._ai_send)
        a.stop.connect(self.runner.stop)
        a.new_chat.connect(self._ai_new_chat)
        a.show_changes.connect(self._ai_show_changes)
        a.revert_changes.connect(self._ai_revert)
        self.runner.delta.connect(a.append_delta)
        self.runner.text_block_end.connect(a.end_block)
        self.runner.tool.connect(a.add_tool)
        self.runner.finished.connect(self._ai_done)
        if not self.claude_path:
            a.set_unavailable("Claude Code CLI를 찾지 못했습니다. 터미널에서 claude를 설치·로그인하세요.")

    def _show_ai(self, on: bool):
        if on and self.mode != "edit":
            self.set_mode("edit")
        (self.tab_ai if on else self.tab_adjust).click()

    def _ai_session_key(self):
        return f"ai/session/{self.folder}" if self.folder else "ai/session/none"

    def _ai_target_key(self):
        return f"ai/target/{self.folder}" if self.folder else "ai/target/none"

    def _ai_new_chat(self):
        if self.runner.running():
            return
        self.settings.remove(self._ai_session_key())
        self.settings.remove(self._ai_target_key())
        self.assistant.clear()
        self._flash("새 대화를 시작합니다")

    def _update_ai_context(self):
        if not self.current:
            self.assistant.set_context("폴더를 열면 지금 보는 사진을 대상으로 대화합니다")
            return
        sel = self._selected_paths()
        extra = f"  ·  선택 {len(sel)}장" if len(sel) > 1 else ""
        self.assistant.set_context(f"대상: {self.current.name}{extra}  ·  폴더 {len(self.photos)}장")

    def _ai_system(self) -> str:
        cur = self.current
        edit_file = files.find_edit(cur) or files.edit_path_for(cur)
        sel = self._selected_paths()
        applied = {}
        if self.result is not None:
            applied = {k: v for k, v in self.result.applied.items() if k not in ("file",)}
        lines = [
            f"너는 {APP_NAME} 데스크톱 앱 오른쪽 'AI 어시스턴트' 패널에서 동작하는 사진 보정 어시스턴트다. CLAUDE.md 규칙을 따른다.",
            "사용자는 앱 화면에서 결과를 실시간으로 본다. 보정값 파일(사진 옆 .lumiq.json)을 고치면 앱이 즉시 다시 그리므로"
            " --preview는 보통 필요 없다.",
            f"현재 사진: {cur} ({'RAW' if self.result is None or self.result.is_raw else 'JPG 등, 색온도는 상대값'})",
            f"현재 사진 보정값 파일: {edit_file} (없으면 이 경로로 만든다)",
            f"지금 화면(현재 보정 적용, 1024px): {CURRENT_PREVIEW.relative_to(DATA)} — 사진 내용을 봐야 판단할 때만 Read로 연다.",
            f"지금 실제 적용값(프리셋·자동 포함): {json.dumps(applied, ensure_ascii=False)}",
            f"폴더: {self.folder} (사진 {len(self.photos)}장)",
        ]
        if self.subfolders:
            lines.append(f"앱은 하위 폴더 {len(self.subfolders)}개의 사진까지 함께 열었다. 폴더 전체를 main.py로 처리할 때는"
                         " --recursive를 붙인다. 내보내기 기본 위치는 사진마다 그 폴더의 export/다.")
        if len(sel) > 1:
            names = ", ".join(p.name for p in sel[:40]) + (" …" if len(sel) > 40 else "")
            lines.append(f"선택한 사진 {len(sel)}장: {names}. 사용자가 '선택한 사진/이것들'이라 하면 이 사진들이 대상이다.")
        lines += [
            "대상은 항상 사용자 메시지 맨 앞 [대상 사진: …]에 적힌 사진과 보정값 파일이다. 이전 대화에서 다룬 다른 사진의"
            " 파일은 사용자가 그 사진을 직접 말하지 않는 한 읽거나 고치지 않는다.",
            "사용자가 '전부/모든 사진'이라 하면 폴더 전체가 대상이다. 다른 사진의 보정값 파일은 그 사진 옆"
            " <사진 파일 이름>.lumiq.json이다 (예: DSC_1236.NEF → DSC_1236.NEF.lumiq.json, 없으면 만든다).",
            f"명령은 반드시 `{CLI} ...` 한 줄로 실행한다 (cd, 파이프, &&, 다른 명령 금지)."
            + ("" if CLI.startswith(".venv") else " 이 앱 안에 든 CLI이며 CLAUDE.md의 `.venv/bin/python main.py`와 같다."),
            "원본 사진과 export 결과는 절대 지우거나 덮어쓰지 않는다. 내보내기는 사용자가 분명히 요청할 때만 한다.",
            "답은 한국어 1~3문장으로, 바꾼 값을 짧게 알려 준다.",
        ]
        guide = guide_text()
        if guide:
            lines += ["", "작업 폴더에 CLAUDE.md가 없어 앱에 든 사본을 붙인다:", guide]
        return "\n".join(lines)

    def _ai_send(self, text: str):
        if not self.current or not self.claude_path:
            return
        if self.view.mode == "crop":
            self.leave_crop(apply=True)
        self._flush_save()
        self._write_state()
        self.assistant.add_user(text)
        self.assistant.set_running(True, "Claude가 사진을 보고 있어요")
        # 끝난 뒤 '무엇이 바뀌었는지' 보여주고 되돌릴 수 있도록 지금 상태를 기억
        self._ai_before = {
            "path": self.current,
            "edit": copy.deepcopy(self.edit),
            "applied": copy.deepcopy(self.result.applied) if self.result is not None else {},
            "as_shot": self.result.as_shot if self.result is not None else (None, None),
            "files": self._edit_snapshot(),
        }
        sid = self.settings.value(self._ai_session_key())
        self.runner.start(self.claude_path, self._ai_prompt(text, sid), self._ai_system(), sid,
                          dirs=[str(self.folder)] if self.folder else [])

    def _ai_prompt(self, text: str, sid) -> str:
        """이어지는 대화에서도 지금 사진을 대상으로 삼도록 메시지 앞에 대상을 붙인다 (화면에는 원래 글만 보임)."""
        cur = self.current
        edit_file = files.edit_path_for(cur)
        head = f"[대상 사진: {cur} · 보정값 파일: {edit_file}"
        sel = self._selected_paths()
        if len(sel) > 1:
            head += f" · 앱에서 선택한 사진 {len(sel)}장"
        key = self._ai_target_key()
        last = self.settings.value(key) if sid else None
        if last and last != str(cur):
            head += (f" · 이전 대화의 사진({Path(last).name})이 아니라 이 사진이 대상이다."
                     f" {Path(last).name}의 보정값은 바꾸지 않는다")
        self.settings.setValue(key, str(cur))
        return f"{head}]\n{text}"

    def _ai_done(self, ok: bool, msg: str, session_id: str):
        self.assistant.set_running(False, "")
        self.assistant.end_block()
        if session_id:
            self.settings.setValue(self._ai_session_key(), session_id)
        if not ok:
            self.assistant.add_error(f"실패: {msg}")
        self._reload_from_disk()
        self._ai_report_changes()

    # ---- AI가 바꾼 값 보여주기 · 되돌리기
    def _label_for(self, key: str) -> str:
        parts = key.split(".")
        names = {"preset": "프리셋", "xmp": "xmp 프리셋", "auto": "자동 보정", "ai_denoise": "AI 노이즈 제거",
                 "lut.file": "LUT", "crop": "크롭 비율", "crop_rect": "크롭 영역", "crop_center": "크롭 위치",
                 "rotate90": "90° 회전", "flip": "반전", "auto_level": "자동 수평", "lens": "렌즈 보정",
                 "tone_curve": "톤 커브", "rotate": "각도", "gps": "위치", "rating": "별점",
                 "camera_match": "카메라 톤"}
        if key in names:
            return names[key]
        row = self.rows.get(key)
        base = row.label.text() if row else parts[-1]
        if parts[0] == "skin":
            return f"피부 {base}"
        if parts[0] == "hsl" and len(parts) == 3:
            return f"{BAND_KO.get(parts[1], parts[1])} {dict(hue='색조', saturation='채도', luminance='휘도')[parts[2]]}"
        if parts[0] == "color_grading" and len(parts) == 3:
            zone = dict(shadows="섀도", midtones="미드톤", highlights="하이라이트", **{"global": "전체"})[parts[1]]
            return f"그레이딩 {zone} {base}"
        if parts[0] == "color_grading":
            return f"그레이딩 {base}"
        if parts[0] in ("sharpening", "noise_reduction", "vignette", "grain", "lut") and len(parts) == 2:
            return {"sharpening": "샤프닝 ", "noise_reduction": "", "vignette": "비네팅 ", "grain": "그레인 ",
                    "lut": "LUT "}[parts[0]] + base if base not in ("샤프닝", "비네팅", "그레인") else base
        return base

    @staticmethod
    def _flatten(d: dict, prefix="") -> dict:
        out = {}
        for k, v in (d or {}).items():
            key = f"{prefix}{k}"
            if isinstance(v, dict) and k not in ("ai_denoise", "gps"):
                out.update(MainWindow._flatten(v, key + "."))
            else:
                out[key] = v
        return out

    @staticmethod
    def _fmt(v) -> str:
        if v is None:
            return "기본"
        if isinstance(v, bool):
            return "켬" if v else "끔"
        if isinstance(v, float):
            return f"{v:.2f}".rstrip("0").rstrip(".") if not v.is_integer() else f"{int(v)}"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, (list, tuple)):
            return "지정됨"
        if isinstance(v, dict):
            return gps_label(v) or "켬"
        return Path(str(v)).stem if "/" in str(v) else str(v)

    def _ai_report_changes(self):
        before = getattr(self, "_ai_before", None)
        if not before:
            return
        old_e, new_e = self._flatten(before["edit"]), self._flatten(self.edit if self.current == before["path"]
                                                                    else files.load_edit(before["path"]))
        new_e.pop("file", None)
        old_applied = self._flatten(before["applied"])
        changes, keys = [], []
        for k in sorted(set(old_e) | set(new_e), key=lambda k: (k.split(".")[0], k)):
            if old_e.get(k) == new_e.get(k):
                continue
            old_v = old_e.get(k, old_applied.get(k))
            if old_v is None and k in ("temperature", "tint"):
                old_v = before["as_shot"][0 if k == "temperature" else 1]
            if old_v is None and k in self.rows:
                old_v = self.rows[k].default
            changes.append((self._label_for(k), self._fmt(old_v), self._fmt(new_e.get(k))))
            keys.append(k)
        others = []
        now = self._edit_snapshot()
        cur_file = str(files.edit_path_for(before["path"]))
        for f in set(now) | set(before["files"]):
            if f != cur_file and now.get(f) != before["files"].get(f):
                others.append(files.photo_for_edit(Path(f)).name)
        before["changed_files"] = [f for f in set(now) | set(before["files"]) if now.get(f) != before["files"].get(f)]
        if not changes and not others:
            return
        self.assistant.add_changes(changes, sorted(others))
        self._ai_last = before
        self._ai_keys = keys
        self._mark_ai(keys)

    def _mark_ai(self, keys):
        for key, row in self.rows.items():
            row.set_ai(key in keys or (key == "ai_denoise.strength" and "ai_denoise" in keys))
        for s, _extra in self.sections:
            if any(k in s.keys for k in keys):
                s.expand()

    def _ai_show_changes(self):
        self._show_ai(False)
        first = next((self.rows[k] for k in getattr(self, "_ai_keys", []) if k in self.rows), None)
        if first is not None:
            QTimer.singleShot(50, lambda: self.adjust_scroll.ensureWidgetVisible(first, 0, 60))

    def _ai_revert(self):
        last = getattr(self, "_ai_last", None)
        if not last:
            return
        for f in last.get("changed_files", []):
            old = last["files"].get(f)
            try:
                if old is None:
                    Path(f).unlink(missing_ok=True)  # AI가 새로 만든 보정값 파일 (원본 사진이 아님)
                else:
                    Path(f).write_text(old, encoding="utf-8")
            except OSError:
                pass
        if self.current == last["path"]:
            self._push_undo()
            self.edit = copy.deepcopy(last["edit"])
            self._save_timer.stop()
            self._after_edit_change(sync=True)
            self._save_timer.stop()
        self._mark_ai([])
        self._ai_last = None
        self.assistant.mark_reverted()
        self._scan_edited()
        self._refresh_badges()
        self._flash("AI가 바꾼 보정값을 되돌렸습니다")

    # ================================================================== 내보내기
    def export_dialog(self):
        if not self.photos:
            return
        if self.view.mode == "crop":
            self.leave_crop(apply=True)
        self._flush_save()
        sel = self._selected_paths()
        shown = self._visible_photos()  # 별점 필터가 있으면 '전체'는 필터에 맞는 사진
        label = "폴더 전체" if self.rating_filter is None else \
            "필터에 맞는 사진 전체 · " + next(l for l, _s, v in RATING_FILTERS if v == self.rating_filter)
        if not shown:
            self._flash("별점 필터에 맞는 사진이 없습니다")
            return
        dlg = ExportDialog(self, len(sel), len(shown), self.folder / "export", self.settings,
                           has_subfolders=bool(self.subfolders), all_label=label)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        targets = shown if v["all"] or not sel else sel
        self._run_export(targets, v)

    def _run_export(self, targets, v):
        prog = QProgressDialog("내보내는 중…", "취소", 0, len(targets), self)
        prog.setWindowTitle("내보내기")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setMinimumWidth(380)
        prog.setValue(0)
        thread = QThread(self)
        worker = ExportWorker(targets, v["out"], v["size"], v["quality"], "auto", base=self.folder)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_export_progress)
        worker.finished.connect(self._on_export_done)
        prog.canceled.connect(self._cancel_export)
        self._export = {"thread": thread, "worker": worker, "prog": prog, "opts": v}  # 참조 유지
        thread.start()

    def _on_export_progress(self, i, n, name):
        prog = self._export["prog"]
        prog.setValue(i)
        prog.setLabelText(f"{i + 1} / {n}   {name}" if name else "마무리 중…")

    def _cancel_export(self):
        self._export["worker"].cancelled = True

    def _on_export_done(self, ok, fail):
        ex = self._export
        ex["prog"].canceled.disconnect(self._cancel_export)  # 닫힐 때 나는 취소 신호 무시
        ex["prog"].close()
        ex["thread"].quit()
        ex["thread"].wait()
        v = ex["opts"]
        self._refresh_badges()
        dirs = sorted({Path(r["output"]).parent for r in ok})
        if v["out"] is not None:
            where, reveal = v["out"], v["out"]
        elif len(dirs) == 1:
            where, reveal = dirs[0], dirs[0]
        else:
            where, reveal = f"각 사진 폴더의 export ({len(dirs)}곳)", os.path.commonpath([str(d) for d in dirs])
        text = f"{len(ok)}장 저장 → {where}"
        if fail:
            text += "\n\n실패:\n" + "\n".join(f"{n}: {m}" for n, m in fail[:10])
            QMessageBox.warning(self, "내보내기", text)
        else:
            self._flash(text, 8)
        if v["reveal"] and ok:
            N.open_folder(reveal)

    def reveal_current(self):
        if self.current:
            N.reveal(self.current)

    # ================================================================== 창
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if not urls:
            return
        first = urls[0]
        if first.is_dir():
            self.open_folder(first)
        elif first.exists():
            self.open_folder(first.parent, select=first.absolute(), single=True)

    def closeEvent(self, e):
        ex = getattr(self, "_export", None)
        if ex and ex["thread"].isRunning():
            if QMessageBox.question(self, APP_NAME, "내보내기가 진행 중입니다. 지금 사진까지만 저장하고 닫을까요?") \
                    != QMessageBox.Yes:
                e.ignore()
                return
            ex["worker"].cancelled = True
            ex["thread"].quit()
            ex["thread"].wait(120000)
        if self.view.mode == "crop":
            self.leave_crop(apply=True)
        self.runner.stop()
        self._flush_save()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.render_thread.quit()
        self.render_thread.wait(3000)
        super().closeEvent(e)
