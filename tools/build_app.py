#!/usr/bin/env python3
"""'LUMIQ Studio.app' 만들기: 앱 하나만으로 실행되는 독립 번들.

번들 안에 Python(python-build-standalone), .venv의 패키지, 코드, 기본 프리셋·LUT·모델, exiftool을 모두 넣는다.
그래서 프로젝트 폴더·.venv·Homebrew가 없어도 앱이 실행된다. 작업 데이터(previews/·.app_state.json·
저장한 프리셋)는 이 프로젝트 폴더를 그대로 쓴다 (폴더가 없으면 앱이 만든다).

  .venv/bin/python tools/build_app.py            # /Applications에 LUMIQ Studio.app 설치·등록
  .venv/bin/python tools/build_app.py ~/Applications

앱은 설치할 때의 코드 사본이다. 코드를 고친 뒤 앱에 반영하려면 다시 실행한다
(개발 중에는 .venv/bin/python app.py로 소스를 바로 실행). 패키지를 바꿨으면 .venv에 먼저 설치하고 다시 실행.

번들 구조 (Contents/):
  MacOS/LUMIQ Studio   앱 런처 (zsh)          MacOS/lumiq     CLI 런처 = main.py (작업 폴더의 ./lumiq 링크가 가리킴)
  MacOS/lumiq-python   앱 안 Python 실행 파일 사본 (Dock·메뉴 막대에 앱 이름과 아이콘이 나오도록)
  Resources/python/    독립형 Python 3.12 + site-packages
  Resources/app/       app.py main.py gui pipeline ai presets luts models CLAUDE.md
  Resources/exiftool/  exiftool (macOS 기본 perl로 실행)
"""
import csv
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NAME = "LUMIQ Studio"
BUNDLE_ID = "local.lumiq.studio"
# Finder의 "다음으로 열기"에 나오도록 등록하는 형식 (보기 역할)
IMAGE_UTIS = ["public.jpeg", "public.heic", "public.heif", "public.png", "org.webmproject.webp", "public.tiff",
              "public.camera-raw-image", "com.nikon.raw-image", "com.adobe.raw-image"]

# 독립형 Python (옮겨도 동작하는 빌드). .venv와 같은 3.12여야 패키지를 그대로 쓸 수 있다.
PY_RELEASE = "20261009"
PY_VERSION = "3.12.15"
PY_FILE = f"cpython-{PY_VERSION}+{PY_RELEASE}-aarch64-apple-darwin-install_only.tar.gz"
PY_SHA256 = "83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8"
PY_URL = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PY_RELEASE}/{quote(PY_FILE)}"
CACHE = Path.home() / "Library" / "Caches" / NAME

APP_FILES = ["app.py", "main.py", "CLAUDE.md"]
APP_DIRS = ["gui", "pipeline", "ai", "presets", "luts", "models"]

# PySide6는 앱이 쓰는 모듈과 그 Qt 프레임워크만 넣는다 (1.2GB → 약 100MB)
QT_MODULES = ["QtCore", "QtGui", "QtWidgets"]
QT_EXTRA = ["QtSvg"]  # SVG 아이콘·이미지 플러그인용
QT_PLUGINS = ["platforms", "imageformats", "styles", "iconengines"]
PYSIDE_KEEP = {"__init__.py", "__pycache__", "_config.py", "_git_pyside_version.py", "py.typed", "support"}
# 실행에 필요 없는 큰 것 (site-packages 기준 경로). pip은 독립형 Python에 이미 있다
SITE_DROP = {"PyObjCTest", "torch/include", "pip"}
SITE_DROP_DISTS = ("pip", "pyside6_addons", "pyside6_pdf", "pyside6_webengine")


def log(msg: str):
    print(msg, flush=True)


# ---------------------------------------------------------------- Python
def fetch_python() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    tgz = CACHE / PY_FILE
    if not tgz.exists():
        log(f"독립형 Python {PY_VERSION} 내려받는 중…")
        part = tgz.with_suffix(".part")
        subprocess.run(["curl", "-fL", "--retry", "2", "-o", str(part), PY_URL], check=True)
        part.rename(tgz)
    sha = subprocess.run(["shasum", "-a", "256", str(tgz)], capture_output=True, text=True, check=True).stdout.split()[0]
    if sha != PY_SHA256:
        tgz.unlink()
        sys.exit(f"내려받은 Python의 SHA256이 다릅니다 ({sha}). 다시 실행하세요.")
    return tgz


def install_python(res: Path) -> Path:
    with tarfile.open(fetch_python()) as tf:
        tf.extractall(res, filter="data")  # → res/python
    return res / "python"


# ---------------------------------------------------------------- 패키지
def _qt_deps(binary: Path) -> set[str]:
    out = subprocess.run(["otool", "-L", str(binary)], capture_output=True, text=True).stdout
    return set(re.findall(r"@rpath/(Qt\w+)\.framework/", out))


def _qt_closure(qt_lib: Path, seeds) -> set[str]:
    need, todo = set(), set(seeds)
    while todo:
        fw = todo.pop()
        if fw not in need:
            need.add(fw)
            todo |= _qt_deps(qt_lib / f"{fw}.framework" / "Versions" / "A" / fw)
    return need


def copy_pyside(src: Path, dst: Path):
    """PySide6에서 QT_MODULES와 그 의존 프레임워크·플러그인만 복사한다."""
    qt_src = src / "Qt"
    seeds = set(QT_EXTRA)
    for m in QT_MODULES:
        seeds |= _qt_deps(src / f"{m}.abi3.so")
    frameworks = _qt_closure(qt_src / "lib", seeds)
    dst.mkdir(parents=True)
    keep = PYSIDE_KEEP | {f"{m}.abi3.so" for m in QT_MODULES} | {p.name for p in src.glob("libpyside6.abi3.*")}
    for p in src.iterdir():
        if p.name in keep:
            (shutil.copytree(p, dst / p.name, symlinks=True) if p.is_dir() else shutil.copy2(p, dst / p.name))
    for fw in sorted(frameworks):
        shutil.copytree(qt_src / "lib" / f"{fw}.framework", dst / "Qt" / "lib" / f"{fw}.framework", symlinks=True)
    for cat in QT_PLUGINS:
        for p in sorted((qt_src / "plugins" / cat).glob("*.dylib")):
            if _qt_deps(p) <= frameworks:  # 넣지 않은 프레임워크가 필요한 플러그인(QtPdf 등)은 뺀다
                (dst / "Qt" / "plugins" / cat).mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst / "Qt" / "plugins" / cat / p.name)
    log(f"  PySide6: {', '.join(QT_MODULES)} + 프레임워크 {', '.join(sorted(frameworks))}")


def copy_site_packages(src: Path, dst: Path):
    drop = set(SITE_DROP)
    for info in src.glob("*.dist-info"):
        if info.name.split("-")[0].lower() in SITE_DROP_DISTS:
            drop.add(info.name)

    def ignore(d, names):
        rel = Path(d).relative_to(src)
        return [n for n in names if str(rel / n) in drop or (rel == Path(".") and n == "PySide6")
                or n == ".DS_Store"]

    shutil.copytree(src, dst, symlinks=True, ignore=ignore, dirs_exist_ok=True)
    copy_pyside(src / "PySide6", dst / "PySide6")


# ---------------------------------------------------------------- 코드·exiftool
def copy_app(dst: Path):
    dst.mkdir(parents=True)
    for f in APP_FILES:
        shutil.copy2(ROOT / f, dst / f)
    for d in APP_DIRS:
        if (ROOT / d).is_dir():
            shutil.copytree(ROOT / d, dst / d, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    for m in ("models/scunet_color_real_psnr.pth", "models/face_landmarker.task"):
        if not (dst / m).exists():
            log(f"  [경고] {m} 없음: 해당 기능(AI 노이즈 제거·얼굴 인식)은 대체 방식으로 동작")


def install_exiftool(dst: Path) -> bool:
    """Homebrew(또는 공식 배포본) exiftool을 번들에 복사하고 스크립트 옆 lib/를 쓰도록 고친다."""
    found = shutil.which("exiftool") or next((p for p in ("/opt/homebrew/bin/exiftool", "/usr/local/bin/exiftool")
                                              if Path(p).exists()), None)
    if not found:
        log("  [경고] exiftool 없음 (brew install exiftool 후 다시 빌드): 내보낼 때 EXIF 복사를 건너뜀")
        return False
    real = Path(os.path.realpath(found))
    lib = next((c for c in (real.parent.parent / "libexec" / "lib" / "perl5", real.parent / "lib")
                if (c / "Image" / "ExifTool.pm").exists()), None)
    if lib is None:
        log(f"  [경고] exiftool 라이브러리를 찾지 못함 ({real}): EXIF 복사를 건너뜀")
        return False
    (dst / "lib" / "File").mkdir(parents=True)
    shutil.copytree(lib / "Image", dst / "lib" / "Image")
    for f in (lib / "File").glob("RandomAccess.*"):
        shutil.copy2(f, dst / "lib" / "File" / f.name)
    script = real.read_text(encoding="utf-8")
    script = re.sub(r"\A#!\S*perl\S*", "#!/usr/bin/perl", script)  # macOS 기본 perl
    if "unshift @INC, $incDir;" not in script:  # Homebrew가 박아 넣은 고정 경로 → 스크립트 옆 lib/
        script = re.sub(r'^unshift @INC, "[^"\n]*";\n', "", script, flags=re.M)
        script = script.replace("    # load or disable config file", "    unshift @INC, $incDir;\n\n"
                                "    # load or disable config file", 1)
    (dst / "exiftool").write_text(script, encoding="utf-8")
    os.chmod(dst / "exiftool", 0o755)
    return True


# ---------------------------------------------------------------- 런처·아이콘·plist
LAUNCHER_HEAD = """#!/bin/zsh
# {name}: 앱 안의 Python으로 앱 안의 코드를 실행한다 (프로젝트 폴더·.venv·Homebrew 없이 동작). tools/build_app.py가 만듦
HERE="${{0:A:h}}"                  # 링크(작업 폴더의 ./lumiq)로 불러도 번들 안의 실제 위치
RES="${{HERE:h}}/Resources"
export LUMIQ_BUNDLE="${{HERE:h:h}}"
export LUMIQ_DATA="${{LUMIQ_DATA:-{data}}}"   # 작업 데이터 (previews/·.app_state.json)
export PATH="$RES/exiftool:$PATH"
unset PYTHONPATH
"""

# 런처(zsh)는 작업 데이터 폴더에 손대지 않는다 (만들기·cd는 app.py가). 데이터가 문서·데스크탑처럼 macOS가 접근을
# 묻는 폴더에 있을 때, zsh와 앱 안 Python이 번갈아 접근하면 macOS가 같은 앱으로 기억하지 못해 실행할 때마다 다시 묻는다
APP_LAUNCHER = LAUNCHER_HEAD + """LOG="$HOME/Library/Logs/{name}.log"
export PYTHONHOME="$RES/python"     # MacOS/의 사본이 Resources/python의 표준 라이브러리를 찾도록 (app.py가 바로 지움)
exec "$HERE/lumiq-python" -s -B "$RES/app/app.py" "$@" >>"$LOG" 2>&1
"""

CLI_LAUNCHER = LAUNCHER_HEAD + """exec "$RES/python/bin/python3.12" -E -s -B "$RES/app/main.py" "$@"
"""


def build_icns(dst: Path):
    from PySide6.QtGui import QGuiApplication
    from gui.icon import draw_icon
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for base in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = base * scale
                name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
                draw_icon(px).save(str(iconset / name))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dst)], check=True)


def write_plist(path: Path):
    plist = {
        "CFBundleName": NAME,
        "CFBundleDisplayName": NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundleExecutable": NAME,
        "CFBundleIconFile": "AppIcon",
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.photography",
        "CFBundleDocumentTypes": [
            {"CFBundleTypeName": "Folder", "CFBundleTypeRole": "Viewer", "LSItemContentTypes": ["public.folder"]},
            {"CFBundleTypeName": "Image", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
             "LSItemContentTypes": IMAGE_UTIS},
        ],
    }
    with open(path, "wb") as f:
        plistlib.dump(plist, f)


def self_test(app: Path):
    """프로젝트·.venv·Homebrew를 쓰지 않는 환경(PATH 최소, 빈 작업 폴더)에서 번들만으로 돌아가는지 확인."""
    macos = app / "Contents" / "MacOS"
    with tempfile.TemporaryDirectory() as tmp:
        env = {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LUMIQ_DATA": tmp,
               "QT_QPA_PLATFORM": "offscreen"}
        r = subprocess.run([str(macos / "lumiq"), "--help"], capture_output=True, text=True, env=env, cwd="/")
        if r.returncode != 0:
            sys.exit(f"자체 점검 실패 (CLI):\n{r.stderr[-2000:]}")
        code = ("import os, sys, shutil, torch, cv2, rawpy, lensfunpy, pillow_heif, mediapipe;"
                "from PySide6.QtWidgets import QApplication; a = QApplication([]);"
                "sys.path.insert(0, os.environ['LUMIQ_BUNDLE'] + '/Contents/Resources/app');"
                "from pipeline.params import DATA, ROOT; import gui.window;"
                "assert str(DATA) == os.environ['LUMIQ_DATA'], DATA;"
                "print(ROOT, '|', shutil.which('exiftool'), '|', torch.backends.mps.is_available())")
        # 앱 런처가 주는 환경 그대로 (app.py가 하는 것처럼 PYTHONHOME은 시작 직후 지움)
        res = app / "Contents" / "Resources"
        env |= {"PYTHONHOME": str(res / "python"), "LUMIQ_BUNDLE": str(app),
                "PATH": f"{res / 'exiftool'}:{env['PATH']}"}
        r = subprocess.run([str(macos / "lumiq-python"), "-s", "-B", "-c",
                            "import os; os.environ.pop('PYTHONHOME'); " + code],
                           capture_output=True, text=True, env=env, cwd="/")
        if r.returncode != 0:
            sys.exit(f"자체 점검 실패 (앱):\n{r.stderr[-3000:]}")
        root, exiftool, mps = (s.strip() for s in r.stdout.strip().splitlines()[-1].split("|"))
        log(f"  자체 점검 통과: 코드 {root}, exiftool {exiftool or '없음'}, MPS {mps}")


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        sys.exit("독립 앱 번들은 Apple Silicon Mac에서만 만듭니다. Windows는 README의 'Windows' 설치 안내대로 "
                 "소스에서 실행하세요 (python app.py)")
    if sys.version_info[:2] != (3, 12):
        sys.exit(".venv/bin/python으로 실행하세요 (Python 3.12 패키지를 번들에 복사합니다)")
    site = Path(sysconfig.get_path("purelib"))
    target_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path("/Applications")
    app = target_dir / f"{NAME}.app"
    work = target_dir / f".{NAME}.app.building"  # 다 만든 뒤 바꿔치기 (중간에 실패해도 기존 앱은 그대로)
    if work.exists():
        shutil.rmtree(work)
    contents = work / "Contents"
    macos, res = contents / "MacOS", contents / "Resources"
    macos.mkdir(parents=True)
    res.mkdir(parents=True)
    try:
        log("1/5 Python")
        py = install_python(res)
        log("2/5 패키지 (.venv에서 복사)")
        copy_site_packages(site, py / "lib" / "python3.12" / "site-packages")
        log("3/5 코드·프리셋·LUT·모델·exiftool")
        copy_app(res / "app")
        install_exiftool(res / "exiftool")
        shutil.copy2(py / "bin" / "python3.12", macos / "lumiq-python")
        for path, text in ((macos / NAME, APP_LAUNCHER), (macos / "lumiq", CLI_LAUNCHER)):
            path.write_text(text.format(name=NAME, data=ROOT), encoding="utf-8")
            os.chmod(path, 0o755)
        build_icns(res / "AppIcon.icns")
        write_plist(contents / "Info.plist")
        log("4/5 바이트코드 컴파일")
        subprocess.run([str(py / "bin" / "python3.12"), "-E", "-s", "-m", "compileall", "-q", "-j", "0",
                        str(res / "app"), str(py / "lib" / "python3.12")], capture_output=True)
        log("5/5 자체 점검")
        self_test(work)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    if app.exists():
        shutil.rmtree(app)
    work.rename(app)
    # Launchpad·Spotlight에 바로 보이도록 등록
    lsregister = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework"
                  "/Support/lsregister")
    if Path(lsregister).exists():
        subprocess.run([lsregister, "-f", str(app)], check=False)
    size = subprocess.run(["du", "-sh", str(app)], capture_output=True, text=True).stdout.split()[0]
    log(f"생성: {app} ({size}) · 작업 데이터: {ROOT}")


if __name__ == "__main__":
    main()
