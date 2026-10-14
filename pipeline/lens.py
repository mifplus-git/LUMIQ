"""렌즈 보정: lensfun으로 왜곡, 비네팅, 색수차(TCA) 보정.

프로필이 없으면 건너뛰고 로그를 남긴다.
"""
from __future__ import annotations

import cv2
import numpy as np

try:
    import lensfunpy
    _DB = lensfunpy.Database()
except Exception:  # lensfun 미설치
    lensfunpy = None
    _DB = None


def find_profile(exif: dict):
    """(camera, lens) 또는 (None, 사유)."""
    if _DB is None:
        return None, "lensfunpy 없음"
    make, model = exif.get("Make"), exif.get("Model")
    lens_model = exif.get("LensModel") or exif.get("LensID") or exif.get("Lens")
    if not (make and model and lens_model):
        return None, "EXIF에 카메라/렌즈 정보 없음"
    cams = _DB.find_cameras(make, model)
    if not cams:
        return None, f"카메라 프로필 없음: {make} {model}"
    lenses = _DB.find_lenses(cams[0], None, str(lens_model))
    if not lenses:
        return None, f"렌즈 프로필 없음: {lens_model}"
    return (cams[0], lenses[0]), None


def _num(v, default):
    try:
        return float(str(v).split()[0])
    except (TypeError, ValueError):
        return default


def correct(lin: np.ndarray, exif: dict, log=print) -> np.ndarray:
    prof, why = find_profile(exif)
    if prof is None:
        log(f"  렌즈 보정 건너뜀: {why}")
        return lin
    cam, lens = prof
    h, w = lin.shape[:2]
    focal = _num(exif.get("FocalLength"), lens.min_focal)
    aperture = _num(exif.get("FNumber") or exif.get("Aperture"), lens.min_aperture or 4.0)
    distance = _num(exif.get("FocusDistance"), 10.0) or 10.0
    mod = lensfunpy.Modifier(lens, cam.crop_factor, w, h)
    mod.initialize(focal, aperture, distance, pixel_format=np.float32)
    out = np.ascontiguousarray(lin, dtype=np.float32)
    mod.apply_color_modification(out)  # 비네팅 (제자리)
    coords = mod.apply_subpixel_geometry_distortion()
    if coords is not None:
        chans = [cv2.remap(out[..., c], coords[..., c, :].astype(np.float32), None,
                           cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT) for c in range(3)]
        out = np.dstack(chans)
    return np.maximum(out, 0)
