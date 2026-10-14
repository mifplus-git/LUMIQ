"""카메라 톤 맞추기: RAW 안에 든 카메라 JPEG의 밝기·채도에 맞춰 RAW 기본 톤을 잡는다.

니콘의 액티브 D-라이팅·픽처 컨트롤은 RAW 데이터에 적용되지 않고 카메라 JPEG에만 들어간다 (RAW는 하이라이트를
지키려고 어둡게 찍힘). 그래서 사진마다 '앱의 기본 현상 밝기 → 카메라 JPEG 밝기' 커브를 찾아, 디코딩 직후의
선형 이미지에 밝기 배율로 적용하고, 채도도 카메라 JPEG의 평균에 맞춘다 (픽처 컨트롤).
이후 노출·자동 보정·슬라이더는 모두 이 위에서 동작한다.
전체 밝기 커브만 맞추므로 액티브 D-라이팅의 부분별 효과까지 똑같지는 않다.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np

from . import color, tone

MIN_THUMB = 600       # 이보다 작은 내장 JPEG는 믿지 않는다 (작은 썸네일만 있는 RAW)
FIT_EDGE = 480        # 비교할 때 줄이는 크기
_cache: dict = {}     # (경로, 수정 시각) → (선형 밝기 격자, 배율) 또는 None


def _display(x: np.ndarray) -> np.ndarray:
    """회색 선형값 → 앱 기본 현상의 화면 밝기 (tone.to_display와 같은 경로)."""
    g = np.repeat(np.asarray(x, np.float32)[:, None], 3, axis=1)[None]
    return tone.to_display(g, raw=True)[0, :, 0]


def _camera_jpeg(path: Path):
    """RAW 안의 카메라 JPEG를 RAW 디코딩과 같은 방향으로 (작게 디코딩). 없으면 None."""
    import rawpy
    from PIL import Image

    from .decode import _apply_flip
    with rawpy.imread(str(path)) as raw:
        flip = raw.sizes.flip
        try:
            th = raw.extract_thumb()
        except Exception:
            return None
    if th.format != rawpy.ThumbFormat.JPEG:
        return None
    im = Image.open(io.BytesIO(th.data))
    if max(im.size) < MIN_THUMB:
        return None
    im.draft("RGB", (FIT_EDGE * 2, FIT_EDGE * 2))  # JPEG를 처음부터 작게 디코딩 (빠름)
    cam = np.asarray(im.convert("RGB"), np.float32) / 255.0
    return _apply_flip(cam, flip)


def fit_lut(path: Path, lin: np.ndarray, log=print):
    """이 사진의 밝기 배율 표 (선형 밝기 격자, 배율). 카메라 JPEG가 없으면 None. 사진마다 한 번만 계산."""
    path = Path(path)
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return None
    if key in _cache:
        return _cache[key]
    lut = None
    try:
        cam = _camera_jpeg(path)
        if cam is None:
            log("  [카메라 톤] 내장 카메라 JPEG가 없어 건너뜀")
        else:
            app = color.resize_long(lin, FIT_EDGE)
            if abs(app.shape[0] / app.shape[1] - cam.shape[0] / cam.shape[1]) > 0.05:
                log("  [카메라 톤] 카메라 JPEG와 모양이 달라 건너뜀")
            else:
                import cv2
                cam = cv2.resize(cam, (app.shape[1], app.shape[0]), interpolation=cv2.INTER_AREA)
                grid, gain = _fit(color.luminance(app).ravel(), color.luminance(cam).ravel())
                lut = (grid, gain, _fit_saturation(apply(app, (grid, gain, 1.0)), cam))
    except Exception as e:  # 손상된 내장 JPEG 등: 카메라 톤 없이 처리
        log(f"  [카메라 톤] 건너뜀: {e}")
    _cache[key] = lut
    while len(_cache) > 64:
        _cache.pop(next(iter(_cache)))
    return lut


def _fit(y_lin: np.ndarray, c: np.ndarray):
    """앱 화면 밝기 D(y) → 카메라 밝기 c 커브를 구하고, 선형 밝기별 배율로 바꾼다."""
    grid = np.geomspace(1e-5, 4.0, 400).astype(np.float32)
    dg = _display(grid)
    d = np.interp(y_lin, grid, dg)
    edges = np.quantile(d, np.linspace(0, 1, 41))
    xs, ys = [0.0], [0.0]
    for a0, a1 in zip(edges[:-1], edges[1:]):
        m = (d >= a0) & (d <= a1)
        if m.sum() >= 30 and a1 > xs[-1] + 1e-4:
            xs.append(float(np.median(d[m])))
            ys.append(float(np.median(c[m])))
    xs.append(max(1.0, xs[-1] + 1e-3))
    ys.append(1.0)
    xs, ys = np.array(xs), np.maximum.accumulate(np.clip(ys, 0, 1))
    target_d = np.interp(dg, xs, ys)                 # 격자마다 원하는 화면 밝기
    target_lin = np.interp(target_d, dg, grid)       # 그 화면 밝기를 내는 선형값 (D의 역함수)
    gain = np.clip(target_lin / grid, 0.25, 16.0).astype(np.float32)
    return grid, gain


def _chroma(disp: np.ndarray) -> float:
    return float((disp.max(axis=2) - disp.min(axis=2)).mean())


def _saturate(lin: np.ndarray, k: float) -> np.ndarray:
    if k == 1.0:
        return lin
    y = color.luminance(lin)[..., None]
    return np.maximum(y + (lin - y) * k, 0).astype(np.float32)


def _fit_saturation(lin_small: np.ndarray, cam: np.ndarray) -> float:
    """화면 채도(평균 max−min)가 카메라 JPEG와 같아지는 배율 (0.8~1.8)."""
    target = _chroma(cam)
    best, best_err = 1.0, None
    for k in np.arange(0.8, 1.81, 0.05):
        err = abs(_chroma(tone.to_display(_saturate(lin_small, float(k)), raw=True)) - target)
        if best_err is None or err < best_err:
            best, best_err = float(k), err
    return round(best, 2)


def apply(lin: np.ndarray, lut) -> np.ndarray:
    """밝기 배율을 픽셀마다 곱하고(색 비율은 그대로) 채도 배율을 적용한다."""
    if lut is None:
        return lin
    grid, gain, sat = lut
    y = color.luminance(lin)
    g = np.interp(y, grid, gain).astype(np.float32)
    return _saturate((lin * g[..., None]).astype(np.float32), sat)
