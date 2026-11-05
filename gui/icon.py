"""앱 아이콘: Desk 시리즈 공통 그림(DR). 실행 중 Dock 아이콘과 .app 번들 아이콘에 같이 쓴다.
그림은 gui/assets/icon-*.png — Desk 시리즈 아이콘 규격으로 만든 것을 복사해 둔다. 64px 이상은 DR + RAW, 그보다 작으면 DR만."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

FOLDER = Path(__file__).resolve().parent / "assets"


def draw_icon(size: int = 1024) -> QImage:
    name = "icon-1024.png" if size >= 64 else "icon-48.png"
    img = QImage(str(FOLDER / name)).convertToFormat(QImage.Format_ARGB32)
    return img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
