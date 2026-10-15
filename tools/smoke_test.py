#!/usr/bin/env python3
"""설치 확인: 테스트 사진을 만들어 CLI(정보·내보내기)와 앱 창을 실제로 띄워 본다. 어느 OS에서나 같은 명령.

  .venv/bin/python tools/smoke_test.py          (Windows: .venv\\Scripts\\python tools\\smoke_test.py)
  .venv/bin/python tools/smoke_test.py --strict # 모델·exiftool이 없어도 실패로 (GitHub Actions 설치 확인)

사진·미리보기·내보내기 결과는 임시 폴더에만 쓰고 끝나면 지운다. 앱 창은 화면에 띄우지 않고(offscreen) 열며,
앱 설정(최근 폴더 등)은 원래대로 되돌린다. 문제가 있으면 종료 코드 1.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ["numpy", "cv2", "PIL", "yaml", "rawpy", "pillow_heif", "lensfunpy", "torch", "einops", "mediapipe",
            "PySide6"]
PHOTO = "테스트 사진.jpg"  # 한글·공백이 든 이름으로 경로 처리까지 확인
MODELS = ["scunet_color_real_psnr.pth", "face_landmarker.task"]

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def check(ok: bool, text: str) -> bool:
    print(f"  {'✓' if ok else '✗'} {text}")
    return ok


def run_cli(args, env) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "main.py"), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def main(strict: bool = False) -> int:
    print(f"LUMIQ 설치 확인 · Python {sys.version.split()[0]} · {sys.platform}")
    ok = True

    def optional(good: bool, text: str):
        """없어도 실행은 되는 것 (exiftool·모델): 평소에는 ! 로 알리고, --strict면 실패."""
        nonlocal ok
        if good or strict:
            ok = check(good, text) and ok
        else:
            print(f"  ! {text}")
    print("패키지")
    for name in PACKAGES:
        try:
            mod = importlib.import_module(name)
            check(True, f"{name} {getattr(mod, '__version__', '')}".rstrip())
        except Exception as e:  # noqa: BLE001 — 어떤 이유로든 못 불러오면 실패로 보고
            ok = check(False, f"{name}: {e}") and ok
    exiftool = shutil.which("exiftool")
    optional(bool(exiftool), f"exiftool {exiftool or '없음 (EXIF·위치 기록과 렌즈 보정이 빠짐)'}")
    for name in MODELS:
        have = (ROOT / "models" / name).exists()
        optional(have, f"models/{name}" + ("" if have else " 없음 (OpenCV 방식으로 대체)"))

    tmp = Path(tempfile.mkdtemp(prefix="lumiq_check_"))
    try:
        photos = tmp / "사진 폴더"
        photos.mkdir()
        import numpy as np
        from PIL import Image
        y, x = np.mgrid[0:600, 0:900]
        img = np.stack([x / 900 * 200 + 30, y / 600 * 180 + 40, (x + y) / 1500 * 150 + 60], -1).astype("uint8")
        Image.fromarray(img).save(photos / PHOTO, quality=90)
        env = {**os.environ, "LUMIQ_DATA": str(tmp / "data")}

        print("CLI")
        r = run_cli([str(photos / PHOTO), "--info"], env)
        try:
            info = json.loads(r.stdout)
            ok = check(r.returncode == 0 and info.get("file") == PHOTO, "--info") and ok
        except json.JSONDecodeError:
            ok = check(False, f"--info: {(r.stderr or r.stdout).strip()[-400:]}") and ok
        r = run_cli([str(photos / PHOTO), "--preview"], env)
        ok = check(r.returncode == 0 and (tmp / "data" / "previews" / "테스트 사진.jpg").exists(),
                   "--preview" + ("" if r.returncode == 0 else f": {r.stderr.strip()[-400:]}")) and ok
        r = run_cli([str(photos / PHOTO), "--preview", "--ai-denoise"], env)
        log = r.stdout + r.stderr
        if r.returncode != 0 or "실패" in log:
            ok = check(False, f"AI 노이즈 제거: {log.strip()[-400:]}") and ok
        else:
            optional("대체" not in log, "AI 노이즈 제거 " + ("(OpenCV로 대체됨)" if "대체" in log else "(SCUNet)"))
        r = run_cli([str(photos), "--auto", "--size", "600", "--out", str(tmp / "out")], env)
        out = list((tmp / "out").glob("*.jpg")) if (tmp / "out").exists() else []
        ok = check(r.returncode == 0 and len(out) == 1,
                   "자동 보정 + 내보내기" + ("" if out else f": {(r.stderr or r.stdout).strip()[-400:]}")) and ok

        print("앱 창")
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--gui", str(photos)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**env, "QT_QPA_PLATFORM": "offscreen"}, timeout=180)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith("  ")]
        print("\n".join(lines) if lines else f"  ✗ {(r.stderr or r.stdout).strip()[-600:]}")
        ok = r.returncode == 0 and ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("모두 정상입니다." if ok else "문제가 있습니다. 위의 ✗ 항목을 확인하세요.")
    return 0 if ok else 1


def gui_check(folder: str) -> int:
    """앱 창을 열어 사진 한 장이 보정되어 그려지는지, 단축키가 OS에 맞는지 확인 (자식 프로세스에서)."""
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    from gui import native as N
    from gui import window as W
    from gui.help import AboutDialog, HelpDialog

    st = QSettings("lumiq", W.APP_NAME)
    saved = {k: st.value(k) for k in st.allKeys()}
    state = {"ok": False, "waited": 0}
    try:
        w = W.MainWindow(folder)
        w.show()

        def poll():
            state["waited"] += 250
            if w.result is None and state["waited"] < 60000:
                QTimer.singleShot(250, poll)
                return
            good = check(len(w.photos) == 1 and w.result is not None,
                         f"사진 {len(w.photos)}장 열기 · 보정 화면 그리기 ({state['waited'] / 1000:.1f}초)")
            keys = {a.text(): a.shortcut().toString(QKeySequence.NativeText)
                    for m in w.menuBar().actions() for a in m.menu().actions() if not a.shortcut().isEmpty()}
            # 메뉴에 실제로 걸린 키가 화면 안내(native.key_text)와 같은지
            want = {"폴더 열기…": "Ctrl+O", "설정…": "Ctrl+,", "휴지통으로 이동": N.TRASH_KEY}
            got = {name: keys.get(name) for name in want}
            good = check(all(got[n] == N.key_text(k) for n, k in want.items()),
                         "단축키: " + ", ".join(f"{n.rstrip('…')} {got[n]}" for n in want)) and good
            HelpDialog(w, W.APP_NAME, W.SLOGAN_EN, W.FORMATS, W.GITHUB_URL)
            AboutDialog(w, W.APP_NAME, W.SLOGAN, W.SLOGAN_EN, W.FORMATS, W.VERSION, W.LINKS)
            state["ok"] = check(True, "사용법·정보 창") and good
            w.close()
            app.quit()

        QTimer.singleShot(250, poll)
        app.exec()
    finally:
        st2 = QSettings("lumiq", W.APP_NAME)
        st2.clear()
        for k, v in saved.items():
            st2.setValue(k, v)
        st2.sync()
    return 0 if state["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--gui":
        sys.exit(gui_check(sys.argv[2]))
    sys.exit(main(strict="--strict" in sys.argv[1:]))
