"""앱 UI 부품: 슬라이더 행, 섹션, 히스토그램, 썸네일 카드·필름스트립, 별점, 사진 뷰(크롭·회전 포함)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListView, QSizePolicy, QStyle,
                               QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from pipeline import geometry as G

from . import theme as T

HUE_STOPS = [(0, "#ff4d4d"), (0.17, "#ffd84d"), (0.33, "#4dd96b"), (0.5, "#4dd9d9"), (0.67, "#4d6bff"),
             (0.83, "#d94dd9"), (1, "#ff4d4d")]
TEMP_STOPS = [(0, "#4f86e8"), (0.5, "#cfcfcf"), (1, "#e8b43a")]
TINT_STOPS = [(0, "#4fbf5c"), (0.5, "#cfcfcf"), (1, "#d05ad0")]


# ---------------------------------------------------------------- dict 도우미

def get_nested(d: dict, dotted: str, default=None):
    cur = d
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def set_nested(d: dict, dotted: str, value):
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        if not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def del_nested(d: dict, dotted: str):
    keys = dotted.split(".")
    stack = []
    cur = d
    for k in keys[:-1]:
        if not isinstance(cur.get(k), dict):
            return
        stack.append((cur, k))
        cur = cur[k]
    cur.pop(keys[-1], None)
    for parent, k in reversed(stack):  # 빈 dict 정리
        if parent[k] == {}:
            parent.pop(k)


# ---------------------------------------------------------------- 슬라이더

class TrackSlider(QWidget):
    """얇은 트랙 + 원형 손잡이. 기준값(0 또는 기본값)에서 현재값까지 강조색으로 채운다."""
    valueChanged = Signal(int)
    doubleClicked = Signal()

    def __init__(self, stops=None):
        super().__init__()
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.pos_ = 500
        self.origin = 500
        self.stops = stops
        self._down = False
        self._hover = False

    def isSliderDown(self):
        return self._down

    def setValue(self, v: int):
        v = int(min(max(v, 0), 1000))
        if v != self.pos_:
            self.pos_ = v
            self.update()

    def value(self):
        return self.pos_

    def _x(self, pos):
        m = 7
        return m + (self.width() - 2 * m) * pos / 1000

    def _pos_at(self, x):
        m = 7
        return int(round(min(max((x - m) / max(self.width() - 2 * m, 1), 0), 1) * 1000))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._down = True
            self._set_from(e.position().x())

    def mouseMoveEvent(self, e):
        if self._down:
            self._set_from(e.position().x())

    def mouseReleaseEvent(self, e):
        self._down = False
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()

    def wheelEvent(self, e):
        e.ignore()  # 패널 스크롤을 방해하지 않도록

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def _set_from(self, x):
        v = self._pos_at(x)
        if v != self.pos_:
            self.pos_ = v
            self.update()
            self.valueChanged.emit(v)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy = self.height() / 2
        x0, x1 = self._x(0), self._x(1000)
        track = QRectF(x0, cy - 1.5, x1 - x0, 3)
        if self.stops:
            g = QLinearGradient(x0, 0, x1, 0)
            for t, c in self.stops:
                g.setColorAt(t, T.qc(c, 200 if self.isEnabled() else 70))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(track, 1.5, 1.5)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(T.qc("#3a3a3f"))
            p.drawRoundedRect(track, 1.5, 1.5)
            a, b = sorted((self._x(self.origin), self._x(self.pos_)))
            if b - a > 0.5:
                p.setBrush(T.qc(T.ACCENT if self.isEnabled() else T.TEXT3))
                p.drawRoundedRect(QRectF(a, cy - 1.5, b - a, 3), 1.5, 1.5)
            p.setBrush(T.qc("#55555b"))
            p.drawEllipse(QPointF(self._x(self.origin), cy), 1.6, 1.6)
        r = 7.0 if (self._down or self._hover) else 6.0
        p.setPen(QPen(T.qc(T.BG1), 2))
        p.setBrush(T.qc(T.TEXT if self.isEnabled() else T.TEXT3))
        p.drawEllipse(QPointF(self._x(self.pos_), cy), r, r)


class ValueEdit(QLineEdit):
    """숫자 표시·입력. ↑↓로 미세 조정(Shift는 10배)."""
    edited = Signal(float)

    def __init__(self, step: float, decimals: int):
        super().__init__()
        self.setObjectName("Value")
        self.step, self.decimals = step, decimals
        self.setFixedWidth(54)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.editingFinished.connect(self._commit)
        self._shown = None

    def show_value(self, v: float):
        if self.hasFocus():
            return
        self._shown = v
        self.setText(self._fmt(v))

    def _fmt(self, v):
        if self.decimals == 0:
            return f"{int(round(v))}"
        return f"{v:.{self.decimals}f}"

    def _commit(self):
        try:
            v = float(self.text().replace("+", "").replace("K", "").replace("°", "").strip())
        except ValueError:
            if self._shown is not None:
                self.setText(self._fmt(self._shown))
            return
        self.edited.emit(v)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Up, Qt.Key_Down):
            try:
                v = float(self.text())
            except ValueError:
                v = self._shown or 0
            d = self.step * (10 if e.modifiers() & Qt.ShiftModifier else 1)
            v = v + d if e.key() == Qt.Key_Up else v - d
            self.setText(self._fmt(v))
            self.edited.emit(v)
            return
        if e.key() == Qt.Key_Escape:
            if self._shown is not None:
                self.setText(self._fmt(self._shown))
            self.clearFocus()
            return
        super().keyPressEvent(e)
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.clearFocus()


class SliderRow(QWidget):
    """이름 · 슬라이더 · 값. 이름이나 슬라이더를 더블클릭하면 기본값(프리셋/자동)으로 되돌린다."""
    changed = Signal(str, object)
    reset = Signal(str)

    def __init__(self, key: str, label: str, lo: float, hi: float, step: float = 1, decimals: int = 0,
                 default: float = 0, kelvin: bool = False, stops=None, suffix: str = ""):
        super().__init__()
        self.key, self.lo, self.hi, self.step, self.decimals = key, lo, hi, step, decimals
        self.default = default
        self.kelvin = kelvin  # 색온도: 미레드 단위로 움직여 자연스럽게
        self._value = default
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.label = QLabel(label)
        self.label.setFixedWidth(70)
        self.label.setToolTip("더블클릭: 기본값으로")
        self.label.mouseDoubleClickEvent = lambda e: self.reset.emit(self.key)
        self.slider = TrackSlider(stops)
        self.edit = ValueEdit(step, decimals)
        lay.addWidget(self.label)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.edit)
        self.slider.valueChanged.connect(self._from_slider)
        self.slider.doubleClicked.connect(lambda: self.reset.emit(self.key))
        self.edit.edited.connect(self._from_edit)
        self.slider.origin = self._to_pos(default)  # 채움 시작점 (색온도는 촬영 시 값으로 나중에 바꿈)
        self.set_value(default)
        self.set_overridden(False)

    def _to_pos(self, v: float) -> int:
        if self.kelvin:
            m0, m1 = 1e6 / self.lo, 1e6 / self.hi
            t = (m0 - 1e6 / max(v, 1)) / (m0 - m1)
            return int(round(min(max(t, 0), 1) * 1000))
        return int(round((v - self.lo) / (self.hi - self.lo) * 1000))

    def _from_pos(self, pos: int) -> float:
        t = pos / 1000
        if self.kelvin:
            m0, m1 = 1e6 / self.lo, 1e6 / self.hi
            return round(1e6 / (m0 - t * (m0 - m1)) / 50) * 50
        v = self.lo + t * (self.hi - self.lo)
        return round(round(v / self.step) * self.step, self.decimals)

    def _emit(self, v):
        self.changed.emit(self.key, int(v) if self.decimals == 0 else v)

    def _from_slider(self, pos):
        v = self._from_pos(pos)
        if v == self._value:
            return
        self._value = v
        self.edit.show_value(v)
        self._emit(v)

    def _from_edit(self, v):
        v = round(min(max(v, self.lo), self.hi), self.decimals)
        self.edit.show_value(v)
        if v == self._value:
            return
        self._value = v
        self.slider.setValue(self._to_pos(v))
        self._emit(v)

    def set_value(self, v):
        """밖에서 값 표시만 바꿈 (신호 없음). 드래그·입력 중이면 건드리지 않는다."""
        if v is None:
            v = self.default
        if self.slider.isSliderDown() or self.edit.hasFocus():
            return
        v = min(max(float(v), self.lo), self.hi)
        self._value = round(v, self.decimals)
        self.slider.setValue(self._to_pos(v))
        self.edit.show_value(v)

    def set_origin(self, v):
        """채움 기준점 (색온도는 촬영 시 값)."""
        self.slider.origin = self._to_pos(v)
        self.slider.update()

    def set_overridden(self, on: bool):
        """edits에 직접 지정된 값이면 이름을 밝게."""
        self._overridden = on
        self._style_label()

    def set_ai(self, on: bool):
        """AI가 방금 바꾼 값이면 이름을 강조색으로."""
        self._ai = on
        self.label.setToolTip("AI가 바꾼 값 · 더블클릭: 기본값으로" if on else "더블클릭: 기본값으로")
        self._style_label()

    def _style_label(self):
        if getattr(self, "_ai", False):
            self.label.setStyleSheet(f"color: {T.ACCENT_HI}; font-weight: 600;")
        elif getattr(self, "_overridden", False):
            self.label.setStyleSheet(f"color: {T.TEXT};")
        else:
            self.label.setStyleSheet(f"color: {T.TEXT2};")


# ---------------------------------------------------------------- 섹션

class Section(QWidget):
    """제목줄을 눌러 접고 편다. 제목줄 오른쪽의 ↺는 이 섹션 값을 모두 기본값으로."""
    reset_clicked = Signal()

    def __init__(self, title: str, expanded: bool = True, resettable: bool = True):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QWidget()
        self.header.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(2, 10, 0, 8)
        hl.setSpacing(4)
        self.chev = QLabel()
        self.title = QLabel(title)
        self.title.setObjectName("SectionTitle")
        hl.addWidget(self.title)
        hl.addStretch(1)
        self.reset_btn = QToolButton()
        self.reset_btn.setIcon(T.icon("reset", T.TEXT3, 14))
        self.reset_btn.setToolTip(f"{title} 초기화")
        self.reset_btn.setVisible(resettable)
        self.reset_btn.clicked.connect(self.reset_clicked.emit)
        hl.addWidget(self.reset_btn)
        hl.addWidget(self.chev)
        self.header.mousePressEvent = lambda e: self.toggle()
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(2, 0, 0, 10)
        self.body_layout.setSpacing(2)
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {T.LINE};")
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        lay.addWidget(line)
        self.keys: list[str] = []
        self._expanded = not expanded
        self.toggle()

    def expand(self):
        if not self._expanded:
            self.toggle()

    def toggle(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        pm = T.icon("chevron", T.TEXT3, 14).pixmap(14, 14)
        if not self._expanded:
            from PySide6.QtGui import QTransform
            pm = pm.transformed(QTransform().rotate(-90), Qt.SmoothTransformation)
        self.chev.setPixmap(pm)

    def add(self, w):
        self.body_layout.addWidget(w)
        if isinstance(w, SliderRow):
            self.keys.append(w.key)
        return w


# ---------------------------------------------------------------- 히스토그램

class Histogram(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(118)
        self.data = None
        self.caption = ""

    def set_data(self, hist):
        self.data = hist
        self.update()

    def set_caption(self, text: str):
        self.caption = text
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(T.qc(T.BG2))
        p.drawRoundedRect(card, T.RADIUS, T.RADIUS)
        r = card.adjusted(10, 10, -10, -28)
        p.setPen(QPen(T.qc("#ffffff", 14), 1))
        for i in range(1, 4):
            x = r.left() + r.width() * i / 4
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        if self.data is not None:
            h = self.data.astype(float)
            h[:, 0] = h[:, 1]
            h[:, -1] = h[:, -2]
            peak = max(float(h[:, 2:-2].max()), 1.0)
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            for c, col in enumerate(("#d9534f", "#4cb86a", "#4a7fe0")):
                path = QPainterPath(QPointF(r.left(), r.bottom()))
                for i in range(0, 256, 2):
                    x = r.left() + i / 255 * r.width()
                    y = r.bottom() - math.sqrt(min(h[c, i] / peak, 1.0)) * (r.height() - 2)
                    path.lineTo(QPointF(x, y))
                path.lineTo(QPointF(r.right(), r.bottom()))
                path.closeSubpath()
                p.fillPath(path, T.qc(col, 150))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            total = max(float(self.data[0].sum()), 1.0)
            for side, frac in (("lo", self.data[:, 0].sum() / total / 3), ("hi", self.data[:, 255].sum() / total / 3)):
                if frac > 0.002:
                    x = r.left() if side == "lo" else r.right()
                    tri = QPainterPath()
                    d = 7 if side == "lo" else -7
                    tri.moveTo(x, r.top())
                    tri.lineTo(x + d, r.top())
                    tri.lineTo(x, r.top() + 7)
                    tri.closeSubpath()
                    p.fillPath(tri, T.qc("#7aa7ff" if side == "lo" else "#ffffff"))
        if self.caption:
            f = p.font()
            f.setPointSizeF(11)
            p.setFont(f)
            p.setPen(T.qc(T.TEXT2))
            p.drawText(QRectF(card.left() + 10, card.bottom() - 24, card.width() - 20, 18),
                       Qt.AlignLeft | Qt.AlignVCenter, self.caption)


# ---------------------------------------------------------------- 별점

def star_path(c: QPointF, r: float) -> QPainterPath:
    """가운데 c, 바깥 반지름 r인 별."""
    path = QPainterPath()
    for i in range(10):
        a = math.radians(-90 + 36 * i)
        rr = r if i % 2 == 0 else r * 0.43
        pt = QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a) + r * 0.08)  # 무게중심을 가운데로
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


class StarRating(QWidget):
    """한 장 보기 아래 별점 1~3. 별을 누르면 그 별점, 지금 별점을 다시 누르면 지운다."""
    rated = Signal(int)
    N, R, GAP = 3, 6.5, 18

    def __init__(self):
        super().__init__()
        self.value = 0
        self._hover = 0
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.GAP * self.N + 4, 22)
        self.setToolTip("별점  ·  1 2 3 키로 매기고 0으로 지웁니다")

    def set_value(self, v: int):
        self.value = v
        self.update()

    def _star_at(self, x: float) -> int:
        i = int((x - 2) // self.GAP) + 1
        return i if 1 <= i <= self.N else 0

    def mouseMoveEvent(self, e):
        h = self._star_at(e.position().x())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e):
        self._hover = 0
        self.update()

    def mousePressEvent(self, e):
        i = self._star_at(e.position().x())
        if e.button() == Qt.LeftButton and i:
            self.rated.emit(0 if i == self.value else i)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shown = self._hover or self.value
        for i in range(1, self.N + 1):
            path = star_path(QPointF(2 + self.GAP * (i - 0.5), self.height() / 2), self.R)
            if i <= shown:
                p.fillPath(path, T.qc(T.STAR, 150 if self._hover and self._hover != self.value else 255))
            else:
                p.setPen(QPen(T.qc(T.TEXT3), 1.1))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)


# ---------------------------------------------------------------- 썸네일 카드

class ThumbDelegate(QStyledItemDelegate):
    """둥근 썸네일 + 파일 이름 + 상태 배지(보정함: 주황 점, 내보냄: 초록 체크, 위치 있음: 핀, 왼쪽 아래 별점).
    같은 목록을 왼쪽 패널·그리드·필름스트립이 크기만 달리해 함께 그린다.
    fill이면 칸을 꽉 채우도록 가운데를 잘라 그린다 (그리드의 정사각형 보기)."""
    W, H = 168, 138

    def __init__(self, parent=None, w: int = W, h: int = H, names: bool = True, fill: bool = False,
                 pins: bool = True):
        super().__init__(parent)
        self.W, self.H, self.names, self.fill, self.pins = w, h, names, fill, pins

    def configure(self, w: int, h: int, names: bool, fill: bool):
        self.W, self.H, self.names, self.fill = w, h, names, fill

    def sizeHint(self, option, index):
        return QSize(self.W, self.H)

    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        pad = (6, 4) if self.names else (3, 3)
        r = QRectF(option.rect).adjusted(pad[0], pad[1], -pad[0], -pad[1])
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if selected or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(T.qc(T.BG3 if selected else T.BG2))
            p.drawRoundedRect(r, 8, 8)
        if self.names:
            img_area = QRectF(r.left() + 8, r.top() + 8, r.width() - 16, r.height() - 36)
        else:
            img_area = r.adjusted(5, 5, -5, -5)
        ic = index.data(Qt.DecorationRole)
        pm = ic.pixmap(QSize(320, 320)) if ic is not None else QPixmap()
        if not pm.isNull():
            if self.fill:  # 칸을 꽉 채우고 넘치는 부분은 가운데 기준으로 잘라 낸다
                tr = img_area
                s = max(tr.width() / pm.width(), tr.height() / pm.height())
                sw, sh = tr.width() / s, tr.height() / s
                src = QRectF((pm.width() - sw) / 2, (pm.height() - sh) / 2, sw, sh)
            else:
                s = min(img_area.width() / pm.width(), img_area.height() / pm.height())
                w, h = pm.width() * s, pm.height() * s
                tr = QRectF(img_area.center().x() - w / 2, img_area.center().y() - h / 2, w, h)
                src = QRectF(pm.rect())
            path = QPainterPath()
            path.addRoundedRect(tr, 5, 5)
            p.setClipPath(path)
            p.drawPixmap(tr, pm, src)
            p.setClipping(False)
            if selected:
                p.setPen(QPen(T.qc(T.ACCENT), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(tr.adjusted(-1, -1, 1, 1), 6, 6)
            badges = index.data(Qt.UserRole + 1) or {}
            bx = tr.right() - 6
            if badges.get("exported"):
                c = QPointF(bx - 5, tr.top() + 11)
                p.setPen(Qt.NoPen)
                p.setBrush(T.qc(T.GOOD))
                p.drawEllipse(c, 7, 7)
                p.setPen(QPen(T.qc("#0d2015"), 1.6))
                p.drawPolyline([c + QPointF(-3, 0), c + QPointF(-1, 2.5), c + QPointF(3.2, -2.5)])
                bx -= 18
            if badges.get("edited"):
                p.setPen(QPen(T.qc("#000000", 120), 1))
                p.setBrush(T.qc(T.ACCENT))
                p.drawEllipse(QPointF(bx - 5, tr.top() + 11), 4.5, 4.5)
                bx -= 14
            if badges.get("gps") and self.pins:
                self._paint_pin(p, QPointF(bx - 5, tr.top() + 11))
            if badges.get("rating"):
                self._paint_stars(p, tr, int(badges["rating"]), 3.6 if not self.names else 5.0)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(T.qc(T.BG2))
            p.drawRoundedRect(img_area, 5, 5)
        if not self.names:
            p.restore()
            return
        name = index.data(Qt.DisplayRole) or ""
        f = QFont(option.font)
        f.setPointSizeF(11)
        p.setFont(f)
        p.setPen(T.qc(T.TEXT if selected else T.TEXT2))
        text_r = QRectF(r.left() + 6, r.bottom() - 26, r.width() - 12, 20)
        p.drawText(text_r, Qt.AlignCenter, p.fontMetrics().elidedText(name, Qt.ElideMiddle, int(text_r.width())))
        p.restore()

    @staticmethod
    def _paint_stars(p: QPainter, tr: QRectF, n: int, r: float):
        """별점: 사진 왼쪽 아래, 어두운 바탕 위에 노란 별 n개."""
        gap, pad = r * 2 + 1.5, 3.5
        box = QRectF(tr.left() + 5, tr.bottom() - 5 - (r * 2 + pad * 2), n * gap - 1.5 + pad * 2, r * 2 + pad * 2)
        p.setPen(Qt.NoPen)
        p.setBrush(T.qc("#000000", 140))
        p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        for i in range(n):
            p.fillPath(star_path(QPointF(box.left() + pad + r + i * gap, box.center().y()), r), T.qc(T.STAR))

    @staticmethod
    def _paint_pin(p: QPainter, c: QPointF):
        """위치 있음: 어두운 원 위의 작은 지도 핀."""
        p.setPen(Qt.NoPen)
        p.setBrush(T.qc("#000000", 140))
        p.drawEllipse(c, 7, 7)
        head = QPointF(c.x(), c.y() - 1.4)
        pin = QPainterPath()
        pin.moveTo(c.x(), c.y() + 4.4)
        pin.lineTo(c.x() - 2.5, c.y() - 0.2)
        pin.lineTo(c.x() + 2.5, c.y() - 0.2)
        pin.closeSubpath()
        pin.addEllipse(head, 2.8, 2.8)
        pin.setFillRule(Qt.WindingFill)
        p.fillPath(pin, T.qc(T.TEXT))
        p.setBrush(T.qc("#000000", 200))
        p.drawEllipse(head, 1.0, 1.0)


class Filmstrip(QListView):
    """뷰어 아래 한 줄 썸네일. 세로 휠도 가로로 넘긴다."""

    def wheelEvent(self, e):
        d = e.angleDelta()
        if abs(d.y()) > abs(d.x()):
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - d.y())
            e.accept()
            return
        super().wheelEvent(e)


# ---------------------------------------------------------------- 사진 뷰

class ImageView(QWidget):
    """사진을 창에 맞춰 보여준다. 누르고 있는 동안 보정 전 사진.
    확대: 화면에 보이는 크기만 바꾼다. 배율은 원본 대비 %로 보인다 (100% = 원본 한 픽셀이 화면 한 픽셀).
    스크롤·트랙패드 벌리기로 확대·축소, 더블클릭은 맞춤 ↔ 100%, 확대 중에는 끌어서 이동.
    비교 모드: 세로선을 좌우로 끌어 왼쪽 보정 전 / 오른쪽 보정 후를 나눠 본다.
    crop 모드: 라이트룸처럼 틀 안을 끌면 이동, 모서리·변을 끌면 크기, 틀 밖을 끌면 회전."""
    hold = Signal(bool)
    clicked_empty = Signal()
    crop_changed = Signal(float)   # 각도
    crop_commit = Signal()         # 더블클릭/Enter
    zoom_changed = Signal(float)   # 맞춤 대비 배율

    HANDLE = 14
    PERCENTS = (10, 12.5, 100 / 6, 25, 100 / 3, 50, 200 / 3, 100, 150, 200, 300, 400)  # ⌘+ ⌘−가 고르는 원본 대비 %
    MAX_PERCENT = 400

    def __init__(self):
        super().__init__()
        self.setObjectName("Canvas")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(QSize(420, 320))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.image: QImage | None = None
        self.before: QImage | None = None
        self.compare = False
        self.split = 0.5          # 비교선 위치 (사진 가로 0~1)
        self._splitting = False
        self.badge = ""
        self.busy = False
        self._busy_t0 = 0.0
        self._anim = QTimer(self, interval=16, timeout=self.update)
        # crop 상태 (기준 사진 픽셀, 사진 중앙 기준 좌표)
        self.mode = "view"
        self.base: QImage | None = None
        self.W = self.H = 1
        self.angle = 0.0
        self.rect_ = (0.0, 0.0, 1.0, 1.0)  # cx, cy, cw, ch
        self.base_rect = self.rect_         # 회전할 때 기준 (회전으로 줄어든 뒤 되돌리면 다시 커지도록)
        self.lock: float | None = None
        self._drag = None
        # 확대: 맞춤 크기의 몇 배로 볼지, 화면 가운데에 올 사진 위치(0~1)
        self.zoom = 1.0
        self.focus = QPointF(0.5, 0.5)
        self._pan = None  # 끌어서 이동: (누른 곳, 그때의 focus)
        self.src_scale = 0.0  # 보이는 이미지 해상도 / 원본 해상도 (0이면 모름: %를 계산하지 않음)

    # ---- 일반 표시
    def set_image(self, img: QImage | None):
        resized = (img.size() if img is not None else None) != (self.image.size() if self.image is not None else None)
        self.image = img
        self.update()
        if resized:  # 크롭 등으로 크기가 바뀌면 원본 대비 %도 바뀐다
            self.zoom_changed.emit(self.zoom)

    def set_before(self, img: QImage | None):
        self.before = img
        self.update()

    def set_compare(self, on: bool):
        self.compare = on
        self._update_cursor()
        self.update()

    def _update_cursor(self):
        if self.mode == "crop":
            return
        if self.compare:
            self.setCursor(Qt.SplitHCursor)
        elif self.zoom > 1.0 and self.image is not None:
            self.setCursor(Qt.ClosedHandCursor if self._pan else Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def _fit_rect(self) -> QRectF:
        area = QRectF(self.rect()).adjusted(28, 28, -28, -28)
        iw, ih = self.image.width(), self.image.height()
        s = min(area.width() / iw, area.height() / ih)
        w, h = iw * s, ih * s
        return QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)

    def _image_rect(self) -> QRectF:
        fit = self._fit_rect()
        if self.zoom == 1.0:
            return fit
        w, h = fit.width() * self.zoom, fit.height() * self.zoom
        if self.zoom < 1.0:
            return QRectF(fit.center().x() - w / 2, fit.center().y() - h / 2, w, h)
        self._clamp_focus(w, h)
        return QRectF(self.width() / 2 - self.focus.x() * w, self.height() / 2 - self.focus.y() * h, w, h)

    def _clamp_focus(self, w: float, h: float):
        """사진이 화면보다 크면 가장자리 밖으로 빈 곳이 생기지 않게, 작으면 가운데에."""
        fx = min(max(self.focus.x(), self.width() / 2 / w), 1 - self.width() / 2 / w) if w > self.width() else 0.5
        fy = min(max(self.focus.y(), self.height() / 2 / h), 1 - self.height() / 2 / h) if h > self.height() else 0.5
        self.focus = QPointF(fx, fy)

    def set_source_scale(self, scale: float):
        """미리보기가 원본의 몇 배 해상도인지 (원본 대비 %를 계산할 때)."""
        if scale != self.src_scale:
            self.src_scale = scale
            self.zoom_changed.emit(self.zoom)

    def fit_percent(self) -> float | None:
        """맞춤 크기일 때 원본 대비 % (화면의 실제 픽셀 기준, 레티나 포함)."""
        if self.image is None or self.src_scale <= 0:
            return None
        orig_w = self.image.width() / self.src_scale
        return self._fit_rect().width() * self.devicePixelRatioF() / orig_w * 100

    def percent(self) -> float | None:
        fp = self.fit_percent()
        return None if fp is None else fp * self.zoom

    def _max_zoom(self) -> float:
        fp = self.fit_percent()
        return max(8.0, self.MAX_PERCENT / fp) if fp else 8.0

    def set_percent(self, pct: float, anchor: QPointF | None = None):
        fp = self.fit_percent()
        if fp:
            self.set_zoom(pct / fp, anchor)

    def set_zoom(self, z: float, anchor: QPointF | None = None):
        """배율을 바꾼다 (1 = 맞춤). anchor 아래의 사진 위치가 그대로 있도록 (없으면 화면 가운데 기준)."""
        if self.image is None or self.mode == "crop":
            return
        z = min(max(z, 0.5), self._max_zoom())
        fp = self.fit_percent()
        if abs(z - 1.0) < 0.03:  # 맞춤·100% 근처에 붙는다
            z = 1.0
        elif fp and abs(z * fp - 100) < 2.5:
            z = 100 / fp
        old = self._image_rect()
        a = anchor if anchor is not None else QPointF(self.width() / 2, self.height() / 2)
        u = min(max((a.x() - old.left()) / old.width(), 0.0), 1.0)
        v = min(max((a.y() - old.top()) / old.height(), 0.0), 1.0)
        self.zoom = z
        if z > 1.0:
            fit = self._fit_rect()
            w, h = fit.width() * z, fit.height() * z
            left, top = a.x() - u * w, a.y() - v * h
            self.focus = QPointF((self.width() / 2 - left) / w, (self.height() / 2 - top) / h)
        else:
            self.focus = QPointF(0.5, 0.5)
        self._update_cursor()
        self.update()
        self.zoom_changed.emit(self.zoom)

    def zoom_step(self, d: int, anchor: QPointF | None = None):
        """⌘+ ⌘−: 원본 대비 25 · 33 · 50 · 67 · 100 · 200% 같은 단계로 한 칸 (맞춤을 지나가면 맞춤에 멈춘다)."""
        fp = self.fit_percent()
        if not fp:
            return self.set_zoom(self.zoom * (1.25 if d > 0 else 0.8), anchor)
        cur = fp * self.zoom
        if d > 0:
            nxt = next((x for x in self.PERCENTS if x > cur * 1.01), self.MAX_PERCENT)
        else:
            nxt = next((x for x in reversed(self.PERCENTS) if x < cur * 0.99), self.PERCENTS[0])
        if (cur < fp * 0.99 < nxt) or (nxt < fp * 0.99 < cur * 0.99) or (cur > fp * 1.01 > nxt):
            nxt = fp  # 맞춤 크기를 건너뛰지 않는다
        self.set_zoom(nxt / fp, anchor)

    def toggle_zoom(self, anchor: QPointF | None = None):
        """더블클릭: 맞춤 ↔ 100% (원본 크기를 모르면 2배)."""
        fp = self.fit_percent()
        target = 100 / fp if fp and abs(fp - 100) > 2.5 else 2.0
        self.set_zoom(1.0 if self.zoom != 1.0 else target, anchor)

    def reset_zoom(self):
        if self.zoom != 1.0:
            self.zoom = 1.0
            self.focus = QPointF(0.5, 0.5)
            self._pan = None
            self._update_cursor()
            self.update()
            self.zoom_changed.emit(1.0)

    def _pan_by(self, dx: float, dy: float, start: QPointF | None = None):
        fit = self._fit_rect()
        w, h = fit.width() * self.zoom, fit.height() * self.zoom
        base = start if start is not None else self.focus
        self.focus = QPointF(base.x() - dx / w, base.y() - dy / h)
        self.update()

    def event(self, e):
        # 트랙패드: 두 손가락 벌리기·오므리기 = 확대·축소, 두 번 두드리기 = 맞춤 ↔ 2배
        if e.type() == QEvent.NativeGesture and self.mode != "crop" and self.image is not None:
            if e.gestureType() == Qt.ZoomNativeGesture:
                self.set_zoom(self.zoom * (1.0 + e.value()), e.position())
                return True
            if e.gestureType() == Qt.SmartZoomNativeGesture:
                self.toggle_zoom(e.position())
                return True
        return super().event(e)

    def wheelEvent(self, e):
        """스크롤 = 마우스 위치를 기준으로 확대·축소 (한 칸에 약 1.2배). 확대 중 가로 스크롤은 좌우 이동."""
        if self.mode == "crop" or self.image is None:
            return super().wheelEvent(e)
        d = e.angleDelta()
        if self.zoom > 1.0 and abs(d.x()) > abs(d.y()):
            px = e.pixelDelta()
            self._pan_by(px.x() if not px.isNull() else d.x() / 2, 0)
        elif d.y():
            self.set_zoom(self.zoom * 1.0015 ** d.y(), e.position())
        e.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.zoom_changed.emit(self.zoom)  # 창 크기가 바뀌면 맞춤 %도 바뀐다

    def _set_split_from(self, x: float):
        r = self._image_rect()
        self.split = min(max((x - r.left()) / max(r.width(), 1), 0.0), 1.0)
        self.update()

    def set_badge(self, text: str):
        self.badge = text
        self.update()

    def set_busy(self, on: bool):
        if on and not self.busy:
            self._busy_t0 = time.time()
            QTimer.singleShot(250, self._start_anim)  # 짧은 작업은 표시하지 않음
        self.busy = on
        if not on:
            self._anim.stop()
            self.update()

    def _start_anim(self):
        if self.busy:
            self._anim.start()

    # ---- crop 모드
    def enter_crop(self, base: QImage, angle: float, rect, lock):
        self.reset_zoom()
        self.mode = "crop"
        self.base = base
        self.W, self.H = base.width(), base.height()
        self.angle = angle
        self.rect_ = self.base_rect = rect
        self.lock = lock
        self.setFocus()
        self.update()

    def leave_crop(self):
        self.mode = "view"
        self.base = None
        self._drag = None
        self.setCursor(Qt.ArrowCursor)
        self._update_cursor()
        self.update()

    def crop_result(self):
        cx, cy, cw, ch = self.rect_
        return self.angle, G.pixels_to_rect(cx, cy, cw, ch, self.W, self.H)

    def _fits(self, cx, cy, cw, ch, angle=None):
        return G._fits(cx, cy, cw, ch, self.W, self.H, math.radians(self.angle if angle is None else angle))

    def set_angle(self, angle: float, emit=False):
        self.angle = max(-45.0, min(45.0, angle))
        cx, cy, cw, ch = self.base_rect
        self.rect_ = G.fit_rect(cx, cy, cw, ch, self.W, self.H, self.angle) if not self._fits(cx, cy, cw, ch) \
            else self.base_rect
        if emit:
            self.crop_changed.emit(self.angle)
        self.update()

    def set_lock(self, ratio: float | None):
        """비율 고정. None이면 자유."""
        self.lock = ratio
        if ratio:
            # 지금 틀과 같은 넓이로 비율만 바꾸고, 들어갈 수 있는 최대 크기를 넘지 않게
            cx, cy, cw, ch = self.rect_
            mw, mh = G.largest_rect(self.W, self.H, self.angle, ratio)
            nh = math.sqrt(cw * ch / ratio)
            nw = nh * ratio
            if nw > mw:
                nw, nh = mw, mh
            self.rect_ = self.base_rect = G.fit_rect(cx, cy, nw, nh, self.W, self.H, self.angle)
        self.update()

    def reset_crop(self, ratio: float | None):
        self.angle = 0.0
        self.lock = ratio
        r = ratio or self.W / self.H
        cw, ch = G.largest_rect(self.W, self.H, 0, r)
        self.rect_ = self.base_rect = (0.0, 0.0, cw, ch)
        self.crop_changed.emit(self.angle)
        self.update()

    # 좌표 변환
    def _view_scale(self):
        area = QRectF(self.rect()).adjusted(48, 40, -48, -40)
        return min(area.width() / self.W, area.height() / self.H), QPointF(area.center())

    def _to_view(self, x, y):
        s, c = self._view_scale()
        return QPointF(c.x() + x * s, c.y() + y * s)

    def _to_canvas(self, pt: QPointF):
        s, c = self._view_scale()
        return (pt.x() - c.x()) / s, (pt.y() - c.y()) / s

    def _crop_view_rect(self) -> QRectF:
        cx, cy, cw, ch = self.rect_
        a = self._to_view(cx - cw / 2, cy - ch / 2)
        b = self._to_view(cx + cw / 2, cy + ch / 2)
        return QRectF(a, b)

    def _hit(self, pt: QPointF) -> str:
        r = self._crop_view_rect()
        hs = self.HANDLE
        near = lambda a, b: abs(a - b) <= hs
        on_x = r.left() - hs <= pt.x() <= r.right() + hs
        on_y = r.top() - hs <= pt.y() <= r.bottom() + hs
        left, right = near(pt.x(), r.left()), near(pt.x(), r.right())
        top, bottom = near(pt.y(), r.top()), near(pt.y(), r.bottom())
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bottom and left:
            return "bl"
        if bottom and right:
            return "br"
        if left and on_y:
            return "l"
        if right and on_y:
            return "r"
        if top and on_x:
            return "t"
        if bottom and on_x:
            return "b"
        if r.contains(pt):
            return "move"
        return "rotate"

    CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
               "bl": Qt.SizeBDiagCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor,
               "b": Qt.SizeVerCursor, "move": Qt.SizeAllCursor, "rotate": Qt.CrossCursor}

    def _move(self, start, dx, dy):
        cx, cy, cw, ch = start
        # 가로를 먼저, 그다음 세로를 가능한 만큼 (틀이 가장자리를 따라 미끄러지듯)
        def search(fn):
            lo, hi = 0.0, 1.0
            if fn(1.0):
                return 1.0
            for _ in range(24):
                m = (lo + hi) / 2
                if fn(m):
                    lo = m
                else:
                    hi = m
            return lo
        tx = search(lambda t: self._fits(cx + dx * t, cy, cw, ch))
        nx = cx + dx * tx
        ty = search(lambda t: self._fits(nx, cy + dy * t, cw, ch))
        return nx, cy + dy * ty, cw, ch

    def _resize(self, start, handle, px, py):
        cx, cy, cw, ch = start
        left, right, top, bottom = cx - cw / 2, cx + cw / 2, cy - ch / 2, cy + ch / 2
        min_size = max(self.W, self.H) * 0.04
        if handle in ("tl", "tr", "bl", "br"):
            ax = right if "l" in handle else left
            ay = bottom if "t" in handle else top
            sx = -1 if "l" in handle else 1
            sy = -1 if "t" in handle else 1
            w = max((px - ax) * sx, min_size)
            h = max((py - ay) * sy, min_size)
            if self.lock:
                if w / h > self.lock:
                    h = w / self.lock
                else:
                    w = h * self.lock

            def rect_at(t):
                ww, hh = w * t, h * t
                return ax + sx * ww / 2, ay + sy * hh / 2, ww, hh
        else:
            if handle in ("l", "r"):
                ax = right if handle == "l" else left
                sx = -1 if handle == "l" else 1
                w = max((px - ax) * sx, min_size)
                h = w / self.lock if self.lock else ch

                def rect_at(t):
                    return ax + sx * w * t / 2, cy, w * t, h * t if self.lock else h
            else:
                ay = bottom if handle == "t" else top
                sy = -1 if handle == "t" else 1
                h = max((py - ay) * sy, min_size)
                w = h * self.lock if self.lock else cw

                def rect_at(t):
                    return cx, ay + sy * h * t / 2, w * t if self.lock else w, h * t
        if self._fits(*rect_at(1.0)):
            return rect_at(1.0)
        lo, hi = 0.0, 1.0
        for _ in range(24):
            m = (lo + hi) / 2
            if self._fits(*rect_at(m)):
                lo = m
            else:
                hi = m
        r = rect_at(lo)
        return r if r[2] >= min_size * 0.5 and r[3] >= min_size * 0.5 else start

    def mousePressEvent(self, e):
        if self.mode == "crop":
            if e.button() == Qt.LeftButton:
                pt = e.position()
                kind = self._hit(pt)
                self._drag = {"kind": kind, "start": pt, "rect": self.rect_, "angle": self.angle,
                              "base": self.base_rect}
                self.update()
            return
        if e.button() != Qt.LeftButton:  # 오른쪽 클릭은 메뉴 (customContextMenuRequested)
            return
        if self.image is None:
            self.clicked_empty.emit()
        elif self.compare and self.before is not None:
            self._splitting = True
            self._set_split_from(e.position().x())
        elif self.zoom > 1.0:  # 확대 중에는 끌어서 이동 (보정 전 보기 대신)
            self._pan = (e.position(), QPointF(self.focus))
            self._update_cursor()
        else:
            self.hold.emit(True)

    def mouseMoveEvent(self, e):
        if self.mode != "crop":
            if self._splitting:
                self._set_split_from(e.position().x())
            elif self._pan:
                start, focus = self._pan
                self._pan_by(e.position().x() - start.x(), e.position().y() - start.y(), focus)
            return
        pt = e.position()
        if not self._drag:
            self.setCursor(self.CURSORS[self._hit(pt)])
            return
        d = self._drag
        if d["kind"] == "rotate":
            s, c = self._view_scale()
            cc = self._to_view(0, 0)
            a0 = math.degrees(math.atan2(d["start"].y() - cc.y(), d["start"].x() - cc.x()))
            a1 = math.degrees(math.atan2(pt.y() - cc.y(), pt.x() - cc.x()))
            delta = (a1 - a0 + 180) % 360 - 180
            ang = d["angle"] + delta
            if abs(ang) < 0.25:
                ang = 0.0  # 0°에 살짝 붙음
            self.base_rect = d["base"]
            self.set_angle(round(ang, 2), emit=True)
            return
        x0, y0 = self._to_canvas(d["start"])
        x1, y1 = self._to_canvas(pt)
        if d["kind"] == "move":
            self.rect_ = self._move(d["rect"], x1 - x0, y1 - y0)
        else:
            self.rect_ = self._resize(d["rect"], d["kind"], x1, y1)
        self.base_rect = self.rect_
        self.update()

    def mouseReleaseEvent(self, e):
        if self.mode == "crop":
            self._drag = None
            self.update()
            return
        if self._splitting:
            self._splitting = False
            return
        if self._pan:
            self._pan = None
            self._update_cursor()
            return
        if e.button() == Qt.LeftButton and self.image is not None:
            self.hold.emit(False)

    def mouseDoubleClickEvent(self, e):
        if self.mode == "crop":
            if self._hit(e.position()) == "move":
                self.crop_commit.emit()
        elif e.button() == Qt.LeftButton and self.image is not None and not self.compare:
            self.hold.emit(False)  # 첫 클릭의 '보정 전'을 남기지 않는다
            self.toggle_zoom(e.position())

    def keyPressEvent(self, e):
        if self.mode == "crop" and e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.crop_commit.emit()
            return
        super().keyPressEvent(e)

    # ---- 그리기
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), T.qc(T.BG0))
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.mode == "crop" and self.base is not None:
            self._paint_crop(p)
        elif self.image is not None:
            target = self._image_rect()
            if self.zoom <= 1.0:
                for i, a in ((6, 18), (3, 26), (1, 40)):  # 은은한 그림자
                    p.setPen(Qt.NoPen)
                    p.setBrush(T.qc("#000000", a))
                    p.drawRoundedRect(target.adjusted(-i, -i + 2, i, i + 2), i, i)
            p.drawImage(target, self.image)
            if self.compare and self.before is not None:
                self._paint_split(p, target)
        if self.badge:
            f = p.font()
            f.setPointSizeF(11)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            br = QRectF(p.fontMetrics().boundingRect(self.badge)).adjusted(-10, -5, 10, 5)
            br.moveTopLeft(QPointF(20, 18))
            p.setPen(Qt.NoPen)
            p.setBrush(T.qc("#000000", 150))
            p.drawRoundedRect(br, br.height() / 2, br.height() / 2)
            p.setPen(T.qc(T.TEXT))
            p.drawText(br, Qt.AlignCenter, self.badge)
        if self.busy and self._anim.isActive():
            t = (time.time() - self._busy_t0) % 1.2 / 1.2
            w = self.width() * 0.3
            x = -w + (self.width() + w) * T.ease(t)
            g = QLinearGradient(x, 0, x + w, 0)
            g.setColorAt(0, T.qc(T.ACCENT, 0))
            g.setColorAt(0.5, T.qc(T.ACCENT, 230))
            g.setColorAt(1, T.qc(T.ACCENT, 0))
            p.fillRect(QRectF(x, 0, w, 2), g)

    def _paint_split(self, p: QPainter, target: QRectF):
        x = target.left() + target.width() * self.split
        p.save()
        p.setClipRect(QRectF(target.left(), target.top(), x - target.left(), target.height()))
        p.drawImage(target, self.before)
        p.restore()
        p.setPen(QPen(T.qc("#ffffff", 230), 1.5))
        p.drawLine(QPointF(x, target.top()), QPointF(x, target.bottom()))
        c = QPointF(x, target.center().y())
        p.setPen(QPen(T.qc("#000000", 60), 1))
        p.setBrush(T.qc("#ffffff"))
        p.drawEllipse(c, 15, 15)
        p.setPen(QPen(T.qc("#222222"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([c + QPointF(-3, -5), c + QPointF(-8, 0), c + QPointF(-3, 5)])
        p.drawPolyline([c + QPointF(3, -5), c + QPointF(8, 0), c + QPointF(3, 5)])
        f = p.font()
        f.setPointSizeF(11)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        for text, left in (("보정 전", True), ("보정 후", False)):
            br = QRectF(p.fontMetrics().boundingRect(text)).adjusted(-10, -5, 10, 5)
            if left:
                br.moveTopLeft(QPointF(target.left() + 12, target.top() + 12))
                visible = x - target.left() > br.width() + 20
            else:
                br.moveTopRight(QPointF(target.right() - 12, target.top() + 12))
                visible = target.right() - x > br.width() + 20
            if visible:
                p.setPen(Qt.NoPen)
                p.setBrush(T.qc("#000000", 150))
                p.drawRoundedRect(br, br.height() / 2, br.height() / 2)
                p.setPen(T.qc(T.TEXT))
                p.drawText(br, Qt.AlignCenter, text)

    def _paint_crop(self, p: QPainter):
        s, c = self._view_scale()
        p.save()
        p.translate(c)
        p.scale(s, s)
        p.rotate(self.angle)
        p.drawImage(QRectF(-self.W / 2, -self.H / 2, self.W, self.H), self.base)
        p.restore()
        r = self._crop_view_rect()
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        hole = QPainterPath()
        hole.addRect(r)
        p.fillPath(outside.subtracted(hole), T.qc("#000000", 165))
        # 격자: 평소 3분할, 회전 중에는 촘촘하게
        kind = self._drag["kind"] if self._drag else None
        n = 9 if kind == "rotate" else 3
        alpha = 110 if kind else 55
        p.setPen(QPen(T.qc("#ffffff", alpha), 1))
        for i in range(1, n):
            x = r.left() + r.width() * i / n
            y = r.top() + r.height() * i / n
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QPen(T.qc("#ffffff", 220), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        # 모서리 손잡이
        p.setPen(QPen(T.qc("#ffffff"), 3, Qt.SolidLine, Qt.SquareCap))
        L = 16
        for x, y, dx, dy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                             (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * L, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * L))
        for x, y, horiz in ((r.center().x(), r.top(), True), (r.center().x(), r.bottom(), True),
                            (r.left(), r.center().y(), False), (r.right(), r.center().y(), False)):
            if horiz:
                p.drawLine(QPointF(x - 9, y), QPointF(x + 9, y))
            else:
                p.drawLine(QPointF(x, y - 9), QPointF(x, y + 9))
        # 각도·크기 표시
        cw, ch = self.rect_[2], self.rect_[3]
        label = f"{self.angle:+.1f}°   {int(cw / self.W * 100)}% × {int(ch / self.H * 100)}%"
        f = p.font()
        f.setPointSizeF(11)
        p.setFont(f)
        br = QRectF(p.fontMetrics().boundingRect(label)).adjusted(-9, -4, 9, 4)
        br.moveCenter(QPointF(r.center().x(), r.bottom() + 20))
        p.setPen(Qt.NoPen)
        p.setBrush(T.qc("#000000", 170))
        p.drawRoundedRect(br, br.height() / 2, br.height() / 2)
        p.setPen(T.qc(T.TEXT))
        p.drawText(br, Qt.AlignCenter, label)
