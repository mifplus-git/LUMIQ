"""색·글꼴·스타일과 선 아이콘. 앱 전체가 이 값만 쓴다."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap

# 색 (어두운 중성 회색 + 아이콘과 같은 앰버 강조색 하나)
BG0 = "#121213"      # 사진 캔버스
BG1 = "#1b1b1d"      # 옆 패널
BG2 = "#232326"      # 카드·머리줄
BG3 = "#2d2d31"      # 입력·호버
LINE = "#2f2f33"
TEXT = "#ececee"
TEXT2 = "#a3a3a8"
TEXT3 = "#6c6c72"
ACCENT = "#f0883e"
ACCENT_HI = "#ffa25c"
ACCENT_DIM = "#5a3a22"
GOOD = "#5cc98a"
STAR = "#f5c443"       # 별점
RADIUS = 8


def wordmark(text: str) -> str:
    """브랜드 표기: LUMIQ의 Q(Quality, 품질과 완성도)만 강조색으로. QLabel 리치 텍스트용."""
    return text.replace("LUMIQ", f'LUMI<span style="color:{ACCENT_HI};">Q</span>', 1)


def qc(hex_or_color, alpha: int | None = None) -> QColor:
    c = QColor(hex_or_color)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def palette() -> QPalette:
    pal = QPalette()
    for role, col in ((QPalette.Window, BG1), (QPalette.WindowText, TEXT), (QPalette.Base, BG0),
                      (QPalette.AlternateBase, BG2), (QPalette.Text, TEXT), (QPalette.Button, BG3),
                      (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#1a1006"),
                      (QPalette.ToolTipBase, BG3), (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, TEXT3),
                      (QPalette.Mid, LINE), (QPalette.Dark, BG0), (QPalette.Light, BG3)):
        pal.setColor(role, QColor(col))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        pal.setColor(QPalette.Disabled, role, QColor(TEXT3))
    return pal


# QSpinBox/QAbstractSpinBox에는 스타일시트를 걸지 않는다 (Qt 6.12에서 버튼 없는 스핀박스 입력칸이 1px로 줄어듦)
STYLESHEET = f"""
QMainWindow, QWidget#Panel {{ background: {BG1}; }}
QWidget#Canvas {{ background: {BG0}; }}
QToolTip {{ background: {BG3}; color: {TEXT}; border: 1px solid {LINE}; padding: 4px 6px; }}
QLabel#Muted {{ color: {TEXT2}; }}
QLabel#Faint {{ color: {TEXT3}; font-size: 11px; }}
QLabel#Title {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
QLabel#SectionTitle {{ color: {TEXT2}; font-size: 12px; font-weight: 600; }}
QFrame#Card {{ background: {BG2}; border-radius: {RADIUS}px; }}
QFrame#Divider {{ background: {LINE}; max-height: 1px; min-height: 1px; border: none; }}
QPushButton {{ background: {BG3}; color: {TEXT}; border: none; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ background: #38383d; }}
QPushButton:pressed {{ background: #2a2a2e; }}
QPushButton:disabled {{ color: {TEXT3}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #1d1206; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {ACCENT_HI}; }}
QPushButton#Ghost {{ background: transparent; color: {TEXT2}; padding: 4px 8px; }}
QPushButton#Ghost:hover {{ background: {BG3}; color: {TEXT}; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 5px; color: {TEXT2}; }}
QToolButton:hover {{ background: {BG3}; color: {TEXT}; }}
QToolButton:checked {{ background: {ACCENT_DIM}; color: {ACCENT_HI}; }}
QToolButton:disabled {{ color: {TEXT3}; }}
QComboBox {{ background: {BG3}; color: {TEXT}; border: none; border-radius: 6px; padding: 5px 10px; }}
QComboBox:hover {{ background: #38383d; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {BG2}; color: {TEXT}; border: 1px solid {LINE};
    selection-background-color: {ACCENT_DIM}; selection-color: {TEXT}; outline: none; padding: 4px; }}
QLineEdit#Value {{ background: transparent; border: none; color: {TEXT2}; padding: 0; }}
QLineEdit#Value:focus {{ background: {BG0}; color: {TEXT}; border-radius: 4px; }}
QLineEdit#Field, QPlainTextEdit#Field {{ background: {BG0}; color: {TEXT}; border: 1px solid {LINE};
    border-radius: 8px; padding: 6px 8px; selection-background-color: {ACCENT_DIM}; }}
QLineEdit#Field:focus, QPlainTextEdit#Field:focus {{ border-color: {ACCENT}; }}
QCheckBox {{ color: {TEXT}; spacing: 6px; }}
QCheckBox::indicator {{ width: 28px; height: 16px; border-radius: 8px; background: {BG3}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}
QCheckBox:disabled {{ color: {TEXT3}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a3a3f; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a4a50; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}
QListView {{ background: {BG1}; border: none; outline: none; }}
QListView#Grid {{ background: {BG0}; padding: 14px 18px; }}
QListView#Filmstrip {{ background: {BG0}; border-top: 1px solid {LINE}; padding: 4px 10px; }}
QTabBar::tab {{ background: transparent; color: {TEXT3}; padding: 4px 10px; border-radius: 5px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {BG3}; color: {TEXT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabWidget::pane {{ border: none; }}
QStatusBar {{ background: {BG1}; color: {TEXT3}; font-size: 11px; border-top: 1px solid {LINE}; }}
QStatusBar::item {{ border: none; }}
QSplitter::handle {{ background: {LINE}; }}
QMenu {{ background: {BG2}; color: {TEXT}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 5px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QProgressDialog QLabel {{ color: {TEXT}; }}
QProgressBar {{ background: {BG3}; border: none; border-radius: 3px; height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""


# ---------------------------------------------------------------- 선 아이콘

def _pen(p: QPainter, color, w=1.6):
    pen = QPen(QColor(color), w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)


def _draw(name: str, p: QPainter, color):
    """24×24 격자 기준 선 아이콘."""
    _pen(p, color)
    if name == "folder":
        path = QPainterPath()
        path.moveTo(3.5, 7)
        path.lineTo(3.5, 18.5)
        path.lineTo(20.5, 18.5)
        path.lineTo(20.5, 8.5)
        path.lineTo(11.5, 8.5)
        path.lineTo(9.5, 5.5)
        path.lineTo(3.5, 5.5)
        path.closeSubpath()
        p.drawPath(path)
    elif name in ("undo", "redo"):
        if name == "redo":
            p.translate(24, 0)
            p.scale(-1, 1)
        path = QPainterPath()
        path.moveTo(8, 9)
        path.lineTo(15, 9)
        path.cubicTo(18.5, 9, 20, 11.5, 20, 13.75)
        path.cubicTo(20, 16, 18.5, 18.5, 15, 18.5)
        path.lineTo(10, 18.5)
        p.drawPath(path)
        p.drawPolyline([QPointF(10.5, 5.5), QPointF(7, 9), QPointF(10.5, 12.5)])
    elif name == "copy":
        p.drawRoundedRect(QRectF(8, 8, 11.5, 11.5), 2, 2)
        p.drawPolyline([QPointF(5, 15.5), QPointF(4.5, 15.5), QPointF(4.5, 4.5), QPointF(15.5, 4.5), QPointF(15.5, 5)])
    elif name == "paste":
        p.drawRoundedRect(QRectF(5.5, 5.5, 13, 15), 2, 2)
        p.drawRoundedRect(QRectF(9, 3.5, 6, 3.5), 1.2, 1.2)
        p.drawLine(QPointF(9, 12), QPointF(15, 12))
        p.drawLine(QPointF(9, 15.5), QPointF(13.5, 15.5))
    elif name == "crop":
        p.drawPolyline([QPointF(7, 3.5), QPointF(7, 17), QPointF(20.5, 17)])
        p.drawPolyline([QPointF(3.5, 7), QPointF(17, 7), QPointF(17, 20.5)])
    elif name == "compare":
        p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
        p.drawLine(QPointF(12, 3), QPointF(12, 21))
        path = QPainterPath()
        path.addRect(QRectF(12, 5, 8.5, 14))
        p.fillPath(path, QColor(color).lighter(60))
    elif name == "export":
        p.drawPolyline([QPointF(8, 9), QPointF(12, 5), QPointF(16, 9)])
        p.drawLine(QPointF(12, 5), QPointF(12, 15))
        p.drawPolyline([QPointF(5.5, 13), QPointF(5.5, 19.5), QPointF(18.5, 19.5), QPointF(18.5, 13)])
    elif name == "sparkle":
        def star(cx, cy, r):
            path = QPainterPath()
            path.moveTo(cx, cy - r)
            path.quadTo(cx, cy, cx + r, cy)
            path.quadTo(cx, cy, cx, cy + r)
            path.quadTo(cx, cy, cx - r, cy)
            path.quadTo(cx, cy, cx, cy - r)
            p.drawPath(path)
        star(10, 13, 7)
        star(18, 6, 3.2)
    elif name in ("rotl", "rotr"):
        if name == "rotr":
            p.translate(24, 0)
            p.scale(-1, 1)
        p.drawArc(QRectF(5, 5, 14, 14), 90 * 16, 270 * 16)
        p.drawPolyline([QPointF(12, 2.5), QPointF(9, 5), QPointF(12, 7.5)])
    elif name == "flip":
        p.drawLine(QPointF(12, 3), QPointF(12, 21))
        p.drawPolygon([QPointF(9, 6), QPointF(9, 18), QPointF(3.5, 18)])
        path = QPainterPath()
        path.addPolygon([QPointF(15, 6), QPointF(15, 18), QPointF(20.5, 18)])
        path.closeSubpath()
        p.fillPath(path, QColor(color))
    elif name == "reset":
        p.drawArc(QRectF(5, 5, 14, 14), 30 * 16, 300 * 16)
        p.drawPolyline([QPointF(19.5, 4), QPointF(18.5, 8.5), QPointF(14, 7.5)])
    elif name == "level":
        p.drawLine(QPointF(3, 15), QPointF(21, 15))
        p.drawRoundedRect(QRectF(6, 8, 12, 4.5), 2.2, 2.2)
        p.drawEllipse(QPointF(12, 10.25), 1.2, 1.2)
    elif name == "swap":
        p.drawRoundedRect(QRectF(4, 8, 9, 12), 1.5, 1.5)
        p.drawRoundedRect(QRectF(9, 4, 11, 8), 1.5, 1.5)
    elif name == "check":
        p.drawPolyline([QPointF(5, 12.5), QPointF(10, 17.5), QPointF(19.5, 7)])
    elif name == "close":
        p.drawLine(QPointF(6, 6), QPointF(18, 18))
        p.drawLine(QPointF(18, 6), QPointF(6, 18))
    elif name == "send":
        path = QPainterPath()
        path.moveTo(12, 19)
        path.lineTo(12, 6)
        p.drawPath(path)
        p.drawPolyline([QPointF(6.5, 11), QPointF(12, 5.5), QPointF(17.5, 11)])
    elif name == "stop":
        path = QPainterPath()
        path.addRoundedRect(QRectF(7, 7, 10, 10), 2, 2)
        p.fillPath(path, QColor(color))
    elif name == "plus":
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "import":
        p.drawPolyline([QPointF(8, 11), QPointF(12, 15), QPointF(16, 11)])
        p.drawLine(QPointF(12, 4.5), QPointF(12, 15))
        p.drawPolyline([QPointF(5.5, 13), QPointF(5.5, 19.5), QPointF(18.5, 19.5), QPointF(18.5, 13)])
    elif name == "minus":
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "save":
        p.drawRoundedRect(QRectF(4.5, 4.5, 15, 15), 2.5, 2.5)
        p.drawRect(QRectF(8, 4.5, 8, 5))
        p.drawRoundedRect(QRectF(8, 13, 8, 6.5), 1, 1)
    elif name == "sliders":
        for y, x in ((7, 9), (12, 15), (17, 7)):
            p.drawLine(QPointF(4, y), QPointF(20, y))
            path = QPainterPath()
            path.addEllipse(QPointF(x, y), 2.2, 2.2)
            p.fillPath(path, QColor(color))
    elif name == "grid":
        for x in (4.5, 13):
            for y in (4.5, 13):
                p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1.5, 1.5)
    elif name == "photo":
        p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
        p.drawPolyline([QPointF(6, 16.5), QPointF(10, 12), QPointF(13, 15), QPointF(15.5, 12.5), QPointF(18, 15.5)])
        p.drawEllipse(QPointF(15.5, 9), 1.3, 1.3)
    elif name == "help":
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        path = QPainterPath()
        path.moveTo(9.6, 9.6)
        path.cubicTo(9.6, 8.1, 10.7, 7.2, 12, 7.2)
        path.cubicTo(13.4, 7.2, 14.5, 8.1, 14.5, 9.5)
        path.cubicTo(14.5, 11.2, 12, 11.4, 12, 13.4)
        p.drawPath(path)
        dot = QPainterPath()
        dot.addEllipse(QPointF(12, 16.4), 1.05, 1.05)
        p.fillPath(dot, QColor(color))
    elif name == "chevron":
        p.drawPolyline([QPointF(8, 10), QPointF(12, 14), QPointF(16, 10)])
    elif name == "finder":
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 3, 3)
        p.drawLine(QPointF(12, 4), QPointF(11, 20))
        p.drawArc(QRectF(7.5, 11, 9, 5), 200 * 16, 140 * 16)
    elif name == "tiles":  # 그리드 보기 옵션: 크고 작은 칸
        p.drawRoundedRect(QRectF(3.5, 4.5, 10, 15), 1.8, 1.8)
        p.drawRoundedRect(QRectF(16, 4.5, 4.5, 6.5), 1.2, 1.2)
        p.drawRoundedRect(QRectF(16, 13, 4.5, 6.5), 1.2, 1.2)
    elif name == "pin":
        path = QPainterPath()
        path.moveTo(12, 20.5)
        path.cubicTo(7.5, 15.5, 5.5, 12.5, 5.5, 9.5)
        path.cubicTo(5.5, 5.8, 8.4, 3.5, 12, 3.5)
        path.cubicTo(15.6, 3.5, 18.5, 5.8, 18.5, 9.5)
        path.cubicTo(18.5, 12.5, 16.5, 15.5, 12, 20.5)
        p.drawPath(path)
        p.drawEllipse(QPointF(12, 9.5), 2.4, 2.4)
    elif name in ("star", "star_fill"):  # 별점 필터 (켜져 있으면 채운 별)
        path = QPainterPath()
        for i in range(10):
            a = math.radians(-90 + 36 * i)
            r = 9 if i % 2 == 0 else 3.9
            pt = QPointF(12 + r * math.cos(a), 12.8 + r * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)
        if name == "star_fill":
            p.fillPath(path, QColor(color))
    elif name == "trash":
        p.drawLine(QPointF(4.5, 6.5), QPointF(19.5, 6.5))
        p.drawPolyline([QPointF(9.5, 6.5), QPointF(9.5, 4), QPointF(14.5, 4), QPointF(14.5, 6.5)])
        p.drawPolyline([QPointF(6.5, 6.5), QPointF(7.5, 20), QPointF(16.5, 20), QPointF(17.5, 6.5)])
        p.drawLine(QPointF(10.5, 10), QPointF(10.5, 16.5))
        p.drawLine(QPointF(13.5, 10), QPointF(13.5, 16.5))


def icon(name: str, color: str = TEXT2, size: int = 18, active: str | None = None) -> QIcon:
    """size px 아이콘. 레티나용 2배 해상도로 그린다."""
    ic = QIcon()
    for mode, col in ((QIcon.Normal, color), (QIcon.Active, TEXT), (QIcon.Disabled, TEXT3),
                      (QIcon.Selected, active or ACCENT_HI)):
        for state, c in ((QIcon.Off, col), (QIcon.On, active or ACCENT_HI)):
            pm = QPixmap(size * 2, size * 2)
            pm.fill(Qt.transparent)
            pm.setDevicePixelRatio(2)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.scale(size / 24, size / 24)
            _draw(name, p, c)
            p.end()
            ic.addPixmap(pm, mode, state)
    return ic


def spinner_angle(t: float) -> float:
    return (t * 360) % 360


def ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * min(max(t, 0), 1))
