#!/usr/bin/env python3
"""LUMIQ Studio 앱 실행 — 빛을 이해하고, 사진을 완성하다.

  .venv/bin/python app.py              # 마지막에 연 폴더로 시작
  .venv/bin/python app.py ~/Photos/0901
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
# 앱 번들 런처가 앱 안 Python에만 준 값. 자식 프로세스(claude 등)로 넘기지 않는다
os.environ.pop("PYTHONHOME", None)
if os.environ.get("LUMIQ_BUNDLE") and os.environ.get("LUMIQ_DATA"):
    # 앱 번들: 작업 데이터 폴더에서 실행 (AI 패널의 claude와 ./lumiq가 이 폴더를 쓴다).
    # 런처가 아니라 여기서 해야 macOS 폴더 접근 허용이 한 번으로 기억된다 (tools/build_app.py 참고)
    os.makedirs(os.environ["LUMIQ_DATA"], exist_ok=True)
    os.chdir(os.environ["LUMIQ_DATA"])


def _set_mac_app_name(name: str):
    """메뉴 막대에 'Python' 대신 앱 이름이 보이도록 (pyobjc가 있을 때만)."""
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = name
    except Exception:
        pass


def _dark_palette(app):
    from gui import theme
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.STYLESHEET)
    f = app.font()
    f.setPointSizeF(12.5)
    app.setFont(f)


def main():
    from gui.window import APP_NAME
    _set_mac_app_name(APP_NAME)
    from pathlib import Path

    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QApplication

    class App(QApplication):
        """Finder에서 폴더/사진을 앱 아이콘에 끌어다 놓으면 macOS가 FileOpen 이벤트로 알려준다."""
        window = None
        pending = None

        def event(self, e):
            if e.type() == QEvent.FileOpen:
                p = Path(e.file())
                if self.window is None:
                    self.pending = p
                elif p.is_dir():
                    self.window.open_folder(p)
                elif p.exists():
                    self.window.open_folder(p.parent, select=p.absolute(), single=True)
                return True
            return super().event(e)

    app = App(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("lumiq")
    app.setStyle("Fusion")
    _dark_palette(app)

    from gui.icon import draw_icon
    app.setWindowIcon(QIcon(QPixmap.fromImage(draw_icon(512))))

    from gui.window import MainWindow
    folder = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-psn") else None
    w = MainWindow(folder)
    app.window = w
    if app.pending:
        p = app.pending
        w.open_folder(p if p.is_dir() else p.parent, select=None if p.is_dir() else p.absolute(),
                      single=not p.is_dir())
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
