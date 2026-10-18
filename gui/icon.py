"""앱 아이콘 (LQ 글자). 실행 중 Dock 아이콘과 .app 번들 아이콘에 같이 쓴다."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath


def draw_icon(size: int = 1024) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 1024
    # macOS 아이콘 격자: 824px 둥근 사각형
    body = QRectF(100 * s, 100 * s, 824 * s, 824 * s)
    bg = QLinearGradient(body.topLeft(), body.bottomLeft())
    bg.setColorAt(0, QColor("#2a2a2e"))
    bg.setColorAt(1, QColor("#121214"))
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(body, 185 * s, 185 * s)
    # L(LUMI, 빛)은 흰색, Q(Quality, 품질과 완성도)는 앱 강조색 그라데이션
    f = QFont("Avenir Next")
    f.setWeight(QFont.DemiBold)
    f.setPixelSize(max(int(400 * s), 1))
    l_path, q_path = QPainterPath(), QPainterPath()
    l_path.addText(0, 0, f, "L")
    q_path.addText(QFontMetricsF(f).horizontalAdvance("L") - 14 * s, 0, f, "Q")
    br = l_path.united(q_path).boundingRect()
    dx, dy = body.center().x() - br.center().x(), body.center().y() - br.center().y()
    l_path.translate(dx, dy)
    q_path.translate(dx, dy)
    p.setBrush(QColor("#f5f5f7"))
    p.drawPath(l_path)
    qb = q_path.boundingRect()
    amber = QLinearGradient(qb.topLeft(), qb.bottomRight())
    amber.setColorAt(0, QColor("#ffc070"))
    amber.setColorAt(1, QColor("#f0883e"))
    p.setBrush(amber)
    p.drawPath(q_path)
    p.end()
    return img
