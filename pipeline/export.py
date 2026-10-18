"""Export: 8비트 JPEG, sRGB ICC 포함, exiftool로 원본 EXIF 전체 복사(GPS 유지, edit.json의 gps가 있으면 그 위치로)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

# Windows에서 한글 등 비ASCII 파일 이름을 exiftool이 제대로 열도록 (다른 OS는 원래 UTF-8)
UTF8 = ["-charset", "filename=utf8"] if sys.platform == "win32" else []

_SRGB_ICC = None


def srgb_icc() -> bytes:
    global _SRGB_ICC
    if _SRGB_ICC is None:
        _SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    return _SRGB_ICC


def to_u8(g: np.ndarray, seed: int = 0) -> np.ndarray:
    """디더링으로 8비트 변환 시 하늘 같은 그라데이션의 계단 현상을 줄인다."""
    rng = np.random.default_rng(seed)
    d = (rng.random(g.shape[:2], dtype=np.float32) - rng.random(g.shape[:2], dtype=np.float32))[..., None]
    return np.clip(g * 255.0 + 0.5 + d * 0.5, 0, 255).astype(np.uint8)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def save_jpeg(g: np.ndarray, path: Path, quality: int = 92) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(to_u8(g))
    img.save(path, "JPEG", quality=int(quality), icc_profile=srgb_icc(),
             subsampling=0 if quality >= 90 else 2, optimize=True)
    return path


def copy_exif(src: Path, dst: Path, log=print) -> bool:
    if not shutil.which("exiftool"):
        log("  exiftool 없음: EXIF 복사 건너뜀 (brew install exiftool)")
        return False
    h, w = Image.open(dst).size[::-1]
    cmd = ["exiftool", *UTF8, "-q", "-q", "-overwrite_original", "-TagsFromFile", str(src),
           "-all:all", "--ICC_Profile:all", "--PreviewImage", "--ThumbnailImage", "--JpgFromRaw",
           "-Orientation=1", "-n", f"-ExifImageWidth={w}", f"-ExifImageHeight={h}",
           "-Software=LUMIQ Studio", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        log(f"  EXIF 복사 실패: {r.stderr.strip()}")
        return False
    return True


def write_gps(dst: Path, gps: dict, log=print) -> bool:
    """앱·edit.json에서 추가한 위치를 내보낸 JPEG에 기록한다 (원래 GPS 태그는 지우고 새로). 원본은 건드리지 않는다."""
    try:
        lat, lon = float(gps["lat"]), float(gps["lon"])
    except (KeyError, TypeError, ValueError):
        log(f"  [경고] gps 형식 오류 무시: {gps} (예: {{\"lat\": 37.5665, \"lon\": 126.978}})")
        return False
    if not shutil.which("exiftool"):
        log("  exiftool 없음: 위치 기록 건너뜀 (brew install exiftool)")
        return False
    cmd = ["exiftool", *UTF8, "-q", "-q", "-overwrite_original", "-GPS:all=", "-GPSVersionID=2.3.0.0",
           f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
           f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        log(f"  위치 기록 실패: {r.stderr.strip()}")
        return False
    return True


def read_exif(paths: list[Path]) -> dict:
    """exiftool -j 한 번으로 여러 파일의 EXIF를 읽는다. {파일경로: dict}"""
    if not paths or not shutil.which("exiftool"):
        return {}
    tags = ["-Make", "-Model", "-LensModel", "-LensID", "-Lens", "-FocalLength", "-FNumber",
            "-ExposureTime", "-ISO", "-DateTimeOriginal", "-WhiteBalance", "-FocusDistance",
            "-ExposureCompensation", "-Orientation", "-GPSPosition", "-ImageSize"]
    out = {}
    for i in range(0, len(paths), 200):
        chunk = paths[i:i + 200]
        r = subprocess.run(["exiftool", *UTF8, "-j", *tags, *map(str, chunk)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        try:
            for d in json.loads(r.stdout or "[]"):
                out[str(Path(d["SourceFile"]).absolute())] = d
        except json.JSONDecodeError:
            pass
    return out
