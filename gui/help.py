"""도움말 창: 사용법과 단축키, 앱 정보."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import theme as T
from .icon import draw_icon


def _link_label(url: str) -> QLabel:
    """누르면 브라우저로 여는 GitHub 링크."""
    text = url.removeprefix("https://")
    lab = QLabel(f'GitHub&nbsp;&nbsp;<a href="{url}" style="color:{T.ACCENT_HI}; text-decoration:none;">{text}</a>')
    lab.setTextFormat(Qt.RichText)
    lab.setOpenExternalLinks(True)
    lab.setStyleSheet(f"color: {T.TEXT3};")
    return lab


def _key(k: str) -> str:
    return f'<span style="background-color:{T.BG3}; color:{T.TEXT};">&nbsp;{k}&nbsp;</span>'


def _section(title: str, items: list[str]) -> str:
    rows = "".join(f'<li style="margin-bottom:4px;">{t}</li>' for t in items)
    return (f'<p style="color:{T.ACCENT_HI}; font-size:14px; font-weight:600; margin-top:16px; margin-bottom:4px;">'
            f'{title}</p><ul style="margin-left:-20px; color:{T.TEXT};">{rows}</ul>')


SHORTCUTS = [
    ("⌘O", "폴더 열기"), ("G", "그리드 보기"), ("E", "편집 · 완료"), ("← →", "이전 · 다음 사진"),
    ("1  2  3", "별점 매기기 (그리드에서는 선택한 사진 모두)"), ("0", "별점 지우기"),
    ("Esc", "뒤로 (편집 → 보기 → 그리드)"), ("R", "자르기·회전"), ("\\", "보정 전·후 비교"),
    ("X", "자르기 중 가로·세로 바꾸기"), ("Enter", "자르기 완료 · 그리드에서 한 장 보기"),
    ("⌘Z  ⇧⌘Z", "실행 취소 · 다시 실행"), ("⇧⌘C  ⇧⌘V", "설정 복사 · 붙여넣기"), ("⌘K", "AI 어시스턴트"),
    ("⌘E", "내보내기"), ("⇧⌘R", "Finder에서 보기"), ("⌘⌫", "휴지통으로 이동 (선택한 사진)"),
    ("⌘+  ⌘−", "그리드: 썸네일 크게 · 작게 / 한 장·편집: 확대 · 축소 (스크롤도)"), ("⌘0", "화면에 맞추기"),
    ("⌘,", "설정 (카메라 톤 기본값 · 편집 화면 썸네일 위치)"), ("⌘?", "도움말"),
]


def help_html(formats: str) -> str:
    keys = "".join(f'<tr><td style="padding:3px 14px 3px 0;">{_key(k)}</td>'
                   f'<td style="color:{T.TEXT2}; padding:3px 0;">{d}</td></tr>' for k, d in SHORTCUTS)
    return "".join([
        _section("시작하기", [
            f"{_key('⌘O')} 폴더 열기, 또는 폴더·사진을 창에 끌어다 놓으세요. 하위 폴더의 사진까지 함께 열립니다 "
            "(보기 메뉴 › 하위 폴더 포함).",
            "처음 화면의 최근 폴더 옆 <b>×</b>는 목록에서만 지웁니다 (폴더와 사진은 그대로).",
            f"지원 형식: {formats}",
            "폴더 이름 옆 <b>×</b>로 폴더를 닫고 처음 화면으로 돌아갑니다.",
            "원본 사진은 절대 바뀌지 않습니다. 보정값은 사진 옆 <b>.lumiq.json</b> 파일(예: DSC_1236.NEF.lumiq.json)에 "
            "저장되고 언제든 되돌릴 수 있어요. 사진과 함께 옮기면 보정값도 따라갑니다 "
            "(직접 휴지통으로 옮길 때만 사진 파일이 움직입니다).",
        ]),
        _section("보기", [
            f"{_key('G')} <b>그리드</b>: 사진 격자. 더블클릭이나 {_key('Enter')}로 크게 봅니다.",
            f"<b>한 장</b>: 큰 사진과 아래 필름스트립. {_key('←')} {_key('→')}로 넘기고 {_key('Esc')}로 그리드.",
            f"<b>확대</b>(한 장·편집): 마우스 스크롤, 트랙패드 벌리기, {_key('⌘+')} {_key('⌘−')}, 더블클릭(맞춤 ↔ 100%). "
            f"아래에 원본 대비 %로 보이고(100% = 원본 한 픽셀이 화면 한 픽셀), 확대 중에는 끌어서 이동, {_key('⌘0')}로 맞춤. "
            "보이는 크기만 바뀌고 사진은 그대로예요. 화면용 미리보기를 키워 보여 주므로 크게 확대하면 실제보다 흐립니다.",
            "⌘·⇧를 누르고 클릭하면 여러 장을 고를 수 있어요 (붙여넣기·내보내기 대상).",
            f"<b>별점</b>: {_key('1')} {_key('2')} {_key('3')}으로 매기고 {_key('0')}으로 지웁니다. 한 장 보기에서는 "
            "사진 이름 옆 별을 눌러도 돼요. 원본 파일은 바뀌지 않습니다.",
            "<b>별점 필터</b>(오른쪽 위 ☆ 버튼 · 보기 메뉴): ★ 1개 이상 · 2개 이상 · 3개 · 별점 없는 사진만 보기. "
            "필터를 켠 채 내보내기의 '전체'는 필터에 맞는 사진만입니다.",
            "썸네일의 주황 점 = 보정함, 초록 체크 = 내보냄, 핀 = 위치(GPS) 있음, 왼쪽 아래 별 = 별점.",
            "그리드 오른쪽 위 <b>보기 옵션</b>(또는 그리드 빈 곳 오른쪽 클릭): 맞춤 / 정사각형(꽉 채우기), "
            f"크기 {_key('⌘+')} {_key('⌘−')}, 파일 이름 표시.",
        ]),
        _section("오른쪽 클릭 메뉴", [
            "사진을 오른쪽 클릭하면 크게 보기·편집, <b>별점</b>, <b>위치(GPS) 추가</b>, 설정 복사·붙여넣기, Finder에서 보기, "
            "내보내기, <b>휴지통으로 이동</b>.",
            "여러 장을 고른 채 오른쪽 클릭하면 선택한 사진 모두에 별점 · 위치 추가 · 휴지통으로 이동.",
            "<b>위치 추가</b>: 좌표(37.5665, 126.9780)나 지도 링크를 붙여넣거나, 최근 위치·위치가 있는 다른 사진에서 "
            "가져옵니다. 원본 파일은 바뀌지 않고, 내보낸 JPEG에 기록됩니다.",
            f"<b>휴지통으로 이동</b>({_key('⌘⌫')}): Finder 휴지통에서 되살릴 수 있어요. 보정값도 함께 옮기고 "
            "내보낸 JPEG는 그대로 둡니다. 숨겨진 RAW+JPEG 쌍의 JPG도 함께 옮길지 고를 수 있어요.",
        ]),
        _section("편집", [
            f"{_key('E')} 또는 <b>편집</b> 버튼. 끝나면 <b>보기</b> 버튼({_key('E')} · {_key('Esc')}) — 보정을 바꿨으면 "
            "저장 / 저장 안 함(편집 전으로) / 취소를 묻습니다 (편집 메뉴에서 묻지 않게 할 수 있음).",
            "슬라이더를 움직이면 바로 저장됩니다. 이름이나 슬라이더를 더블클릭하면 기본값.",
            "<b>자동 보정</b>: 노출·화이트밸런스·톤을 자동으로 (인물은 얼굴 밝기 우선). 켜면 나오는 "
            "<b>자동 밝기</b>로 어둡게↔밝게 — 섀도·하이라이트·검정·대비까지 함께 다시 맞춥니다.",
            "<b>카메라 톤</b>(RAW): 니콘 액티브 D-라이팅·픽처 컨트롤은 RAW에 적용되지 않아 카메라 JPEG보다 어둡게 "
            "보입니다. 켜면 RAW 안의 카메라 JPEG 밝기·채도에 맞춰 기본 톤을 잡습니다. 사진마다 켜고 끌 수 있고, 기본값은 "
            f"<b>설정</b>({_key('⌘,')})에서 정합니다.",
            "프리셋 · 라이트룸 xmp · LUT로 색감을 입히고, 마음에 드는 색감은 프리셋으로 저장하세요.",
            "<b>프리셋 가져오기</b>(프리셋 옆 ↓ 버튼 · 파일 메뉴): LUMIQ 프리셋(.yaml)이나 라이트룸 프리셋(.xmp)을 "
            "목록에 추가합니다. 여러 개를 한 번에 고를 수 있어요.",
            "<b>프리셋 삭제</b>(프리셋 옆 휴지통 버튼 · 편집 메뉴): 내가 만든·가져온 프리셋은 휴지통으로, 기본 프리셋은 "
            "목록에서 숨깁니다 (같은 창에서 다시 보이기).",
            f"{_key('R')} 자르기·회전 (틀 안 = 이동, 모서리 = 크기, 틀 밖 = 회전), "
            f"{_key(chr(92))} 보정 전·후 비교. 사진을 누르고 있으면 보정 전.",
            f"{_key('⇧⌘C')} 설정 복사 → 다른 사진을 골라 {_key('⇧⌘V')} 붙여넣기.",
        ]),
        _section("AI 어시스턴트", [
            f"{_key('⌘K')} \"좀 더 화사하게\", \"필름 느낌으로\"처럼 말로 요청하면 Claude가 지금 보고 있는 사진의 "
            "보정값을 바꿉니다.",
            "바뀐 값은 카드로 보여 주고 <b>되돌리기</b>로 한 번에 취소할 수 있어요.",
            "Claude Code(터미널의 claude)가 설치·로그인되어 있어야 합니다.",
        ]),
        _section("내보내기", [
            f"{_key('⌘E')} 선택한 사진 또는 전체를 JPEG로. 크기·품질을 고릅니다.",
            "기본 위치는 사진 폴더의 export/ (하위 폴더 사진은 각 폴더의 export/). 같은 이름이면 _1, _2를 붙여요.",
        ]),
        f'<p style="color:{T.ACCENT_HI}; font-size:14px; font-weight:600; margin-top:16px; margin-bottom:6px;">'
        f'단축키</p><table cellspacing="0">{keys}</table>',
        f'<p style="color:{T.TEXT3}; margin-top:12px;">E·G는 한글 입력 상태(ㄷ·ㅎ)나 Shift를 눌러도 동작합니다.</p>',
    ])


class HelpDialog(QDialog):
    def __init__(self, parent, app_name: str, slogan: str, formats: str, url: str):
        super().__init__(parent)
        self.setWindowTitle(f"{app_name} 사용법")
        self.resize(620, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 16, 16)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        pm = QPixmap.fromImage(draw_icon(128))
        pm.setDevicePixelRatio(2)
        logo.setPixmap(pm)
        head.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel(T.wordmark(f"{app_name} 사용법"))
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet(f"font-size: 19px; font-weight: 700; color: {T.TEXT};")
        sub = QLabel(slogan)
        sub.setStyleSheet(f"color: {T.ACCENT_HI}; letter-spacing: 1px;")
        col.addStretch(1)
        col.addWidget(title)
        col.addWidget(sub)
        col.addStretch(1)
        head.addLayout(col)
        head.addStretch(1)
        lay.addLayout(head)
        body = QLabel(help_html(formats))
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        body.setStyleSheet(f"color: {T.TEXT}; font-size: 13px;")
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 10, 0)
        hl.addWidget(body)
        hl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)
        row = QHBoxLayout()
        row.addWidget(_link_label(url))
        row.addStretch(1)
        ok = QPushButton("닫기")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)


# 앱 정보 창의 브랜드 소개 (Brand Identity 1.0을 줄여 정리: 이름의 뜻 + 핵심 가치 세 가지를 두 줄로)
NAME_PARTS = [("LUMI", T.TEXT, "빛과 이미지의 아름다움 — 밝기 · 색감 · 분위기"),
              ("Q", T.ACCENT_HI, "Quality — 사진의 품질과 완성도")]
INTRO = ("사진의 빛과 색, 노출과 디테일을 분석해 어울리는 보정을 찾고\n"
         "자동 보정으로 빠르게, 원하는 만큼 직접 다듬어 완성합니다.")
PRODUCT_LINE = "Intelligent Photo Editing"


class AboutDialog(QDialog):
    """앱 메뉴의 'LUMIQ Studio 정보': 이름·슬로건·이름의 뜻·소개·버전·GitHub 저장소."""

    def __init__(self, parent, app_name: str, slogan: str, slogan_en: str, formats: str, version: str, url: str):
        super().__init__(parent)
        self.setWindowTitle(f"{app_name} 정보")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 28, 40, 20)
        lay.setSpacing(4)
        logo = QLabel()
        pm = QPixmap.fromImage(draw_icon(192))
        pm.setDevicePixelRatio(2)
        logo.setPixmap(pm)
        title = QLabel(T.wordmark(app_name))
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {T.TEXT}; margin-top: 8px;")
        ver = QLabel(f"{PRODUCT_LINE}  ·  버전 {version}")
        ver.setStyleSheet(f"color: {T.TEXT3}; letter-spacing: 0.5px;")
        sub = QLabel(slogan)
        sub.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {T.TEXT}; margin-top: 16px;")
        sub_en = QLabel(slogan_en)
        sub_en.setStyleSheet(f"color: {T.ACCENT_HI}; letter-spacing: 1px;")
        for w in (logo, title, ver, sub, sub_en):
            lay.addWidget(w, 0, Qt.AlignHCenter)
        lay.addSpacing(16)
        card = QFrame()
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 12, 18, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for r, (part, color, meaning) in enumerate(NAME_PARTS):
            name = QLabel(part)
            name.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {color};")
            text = QLabel(meaning)
            text.setStyleSheet(f"color: {T.TEXT2};")
            grid.addWidget(name, r, 0, Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(text, r, 1)
        grid.setColumnStretch(1, 1)
        lay.addWidget(card)
        lay.addSpacing(10)
        intro = QLabel(INTRO)
        intro.setAlignment(Qt.AlignCenter)
        intro.setStyleSheet(f"color: {T.TEXT2};")
        lay.addWidget(intro)
        lay.addSpacing(14)
        desc = QLabel(f"{formats}  ·  Claude Code 연동")
        desc.setStyleSheet(f"color: {T.TEXT3}; font-size: 11px;")
        lay.addWidget(desc, 0, Qt.AlignHCenter)
        link = _link_label(url)
        link.setStyleSheet(link.styleSheet() + " margin-top: 4px;")
        lay.addWidget(link, 0, Qt.AlignHCenter)
        lay.addSpacing(16)
        ok = QPushButton("닫기")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        lay.addWidget(ok, 0, Qt.AlignHCenter)
