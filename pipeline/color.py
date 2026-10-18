"""색공간 공용 함수: sRGB 감마, 휘도, 색온도(K)·틴트 ↔ 색도, 화이트밸런스 행렬."""
from __future__ import annotations

import cv2
import numpy as np

SRGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
XYZ_TO_SRGB = np.linalg.inv(SRGB_TO_XYZ)
BRADFORD = np.array([
    [0.8951, 0.2664, -0.1614],
    [-0.7502, 1.7135, 0.0367],
    [0.0389, -0.0685, 1.0296],
])
D65_XY = (0.31271, 0.32902)
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
TINT_SCALE = 1 / 3000.0  # 틴트 1 단위당 Duv 변화


def srgb_encode(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055).astype(np.float32)


def srgb_decode(g: np.ndarray) -> np.ndarray:
    g = np.clip(g, 0.0, 1.0)
    return np.where(g <= 0.04045, g / 12.92, np.power((g + 0.055) / 1.055, 2.4)).astype(np.float32)


def luminance(rgb: np.ndarray) -> np.ndarray:
    return (rgb @ LUMA).astype(np.float32)


def apply_matrix(img: np.ndarray, m: np.ndarray) -> np.ndarray:
    return (img.reshape(-1, 3) @ m.T.astype(np.float32)).reshape(img.shape)


def resize_long(img: np.ndarray, long_edge: int, interp=cv2.INTER_AREA) -> np.ndarray:
    h, w = img.shape[:2]
    s = long_edge / max(h, w)
    if s >= 1:
        return img
    return cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=interp)


def guided_filter(guide: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    """회색조 가이드 필터 (He et al.). 경계를 지키는 흐림."""
    k = (2 * r + 1, 2 * r + 1)
    mean = lambda x: cv2.boxFilter(x, -1, k, borderType=cv2.BORDER_REFLECT)
    mi, mp = mean(guide), mean(src)
    cov = mean(guide * src) - mi * mp
    var = mean(guide * guide) - mi * mi
    a = cov / (var + eps)
    b = mp - a * mi
    return mean(a) * guide + mean(b)


def smooth_base(lum: np.ndarray, radius_frac: float, eps: float = 0.01, work: int = 1024) -> np.ndarray:
    """저해상도에서 가이드 필터로 큰 반경의 밝기 바탕층을 구해 원래 크기로 올린다."""
    h, w = lum.shape
    small = resize_long(lum, work)
    r = max(1, int(radius_frac * max(small.shape)))
    base = guided_filter(small, small, r, eps)
    if small.shape != lum.shape:
        base = cv2.resize(base, (w, h), interpolation=cv2.INTER_LINEAR)
    return base.astype(np.float32)


# ---- 색온도 ----

def _planck_xy(t: float):
    """Kim et al. 근사식, 1667~25000K."""
    t = float(np.clip(t, 1667, 25000))
    if t <= 4000:
        x = -0.2661239e9 / t**3 - 0.2343589e6 / t**2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t**3 + 2.1070379e6 / t**2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    return x, y


def _xy_to_uv(x, y):
    d = -2 * x + 12 * y + 3
    return 4 * x / d, 6 * y / d


def _uv_to_xy(u, v):
    d = 2 * u - 8 * v + 4
    return 3 * u / d, 2 * v / d


def _locus_uv_normal(t: float):
    u0, v0 = _xy_to_uv(*_planck_xy(t))
    u1, v1 = _xy_to_uv(*_planck_xy(t + 1))
    tu, tv = u1 - u0, v1 - v0
    n = np.array([-tv, tu]) / np.hypot(tu, tv)
    if n[1] < 0:  # 위쪽(초록 방향)이 +
        n = -n
    return np.array([u0, v0]), n


def temp_tint_to_xy(temp: float, tint: float):
    """라이트룸 방식 틴트: +는 마젠타 보정 → 광원을 초록 쪽(+Duv)으로 가정."""
    uv, n = _locus_uv_normal(temp)
    uv = uv + n * (tint * TINT_SCALE)
    return _uv_to_xy(*uv)


def xy_to_temp_tint(x: float, y: float):
    target = np.array(_xy_to_uv(x, y))
    temps = np.geomspace(1667, 25000, 400)
    d = [np.linalg.norm(np.array(_xy_to_uv(*_planck_xy(t))) - target) for t in temps]
    i = int(np.argmin(d))
    lo, hi = temps[max(i - 1, 0)], temps[min(i + 1, len(temps) - 1)]
    for _ in range(40):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        f = lambda t: np.linalg.norm(np.array(_xy_to_uv(*_planck_xy(t))) - target)
        if f(m1) < f(m2):
            hi = m2
        else:
            lo = m1
    t = (lo + hi) / 2
    uv, n = _locus_uv_normal(t)
    duv = float(np.dot(target - uv, n))
    return float(t), duv / TINT_SCALE


def camera_neutral_xy(cam_xyz: np.ndarray, wb_mult) -> tuple:
    neutral = 1.0 / np.maximum(np.array(wb_mult[:3], dtype=np.float64), 1e-6)
    xyz = np.linalg.solve(cam_xyz, neutral)
    s = xyz.sum()
    return float(xyz[0] / s), float(xyz[1] / s)


def as_shot_temp_tint(meta):
    t, tint = xy_to_temp_tint(*meta.shot_xy)
    return round(t), round(tint)


def _xy_to_XYZ(x, y):
    return np.array([x / y, 1.0, (1 - x - y) / y])


def _cat(src_xy, dst_xy):
    s = BRADFORD @ _xy_to_XYZ(*src_xy)
    d = BRADFORD @ _xy_to_XYZ(*dst_xy)
    return np.linalg.inv(BRADFORD) @ np.diag(d / s) @ BRADFORD


def wb_matrix(as_shot_xy, temp: float, tint: float) -> np.ndarray:
    """촬영 시 화이트밸런스로 렌더된 선형 sRGB를 (temp, tint) 기준으로 다시 맞추는 3×3 행렬."""
    target_xy = temp_tint_to_xy(temp, tint)
    m = XYZ_TO_SRGB @ _cat(target_xy, D65_XY) @ _cat(D65_XY, as_shot_xy) @ SRGB_TO_XYZ
    # 회색 밝기는 유지 (노출과 분리)
    gray = m @ np.ones(3)
    return m / float(LUMA @ gray)
