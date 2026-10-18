""".cube LUT 적용 (3D 삼선형 보간, 1D 지원), 강도(%) 조절. 입력은 sRGB 감마."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from .params import DATA, ROOT


def lut_dirs() -> list[Path]:
    """작업 폴더의 luts/(DATA)가 앱에 든 기본 LUT(ROOT)보다 우선."""
    return list(dict.fromkeys((DATA / "luts", ROOT / "luts")))


def lut_files() -> dict[str, Path]:
    """파일 이름 → 경로 (같은 이름이면 앞 폴더 우선)."""
    return {f.name: f for d in reversed(lut_dirs()) for f in d.glob("*.cube")}


def resolve(path: str) -> Path:
    p = Path(path).expanduser()
    cands = [p, *(base / p for base in dict.fromkeys((DATA, ROOT)))]
    cands += [d / name for d in lut_dirs() for name in (p, f"{p}.cube")]
    for cand in cands:
        if cand.exists():
            return cand
    raise FileNotFoundError(f"LUT 없음: {path} (luts/: {', '.join(sorted(lut_files()))})")


@lru_cache(maxsize=8)
def load_cube(path: str):
    size, kind = None, None
    dmin, dmax = np.zeros(3, np.float32), np.ones(3, np.float32)
    rows = []
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split()[0].upper()
        if key == "LUT_3D_SIZE":
            size, kind = int(line.split()[1]), "3d"
        elif key == "LUT_1D_SIZE":
            size, kind = int(line.split()[1]), "1d"
        elif key == "DOMAIN_MIN":
            dmin = np.array(line.split()[1:4], np.float32)
        elif key == "DOMAIN_MAX":
            dmax = np.array(line.split()[1:4], np.float32)
        elif key in ("TITLE", "LUT_3D_INPUT_RANGE", "LUT_1D_INPUT_RANGE"):
            continue
        else:
            try:
                rows.append([float(v) for v in line.split()[:3]])
            except ValueError:
                continue
    table = np.array(rows, np.float32)
    if kind == "3d":
        table = table.reshape(size, size, size, 3)  # [b][g][r], 빨강이 가장 빠르게 변함
    return kind, size, table, dmin, dmax


def _apply3d(img, table, n, dmin, dmax, chunk=1 << 20):
    flat = img.reshape(-1, 3)
    out = np.empty_like(flat)
    for s in range(0, len(flat), chunk):
        x = (flat[s:s + chunk] - dmin) / (dmax - dmin) * (n - 1)
        x = np.clip(x, 0, n - 1)
        i0 = np.minimum(x.astype(np.int32), n - 2)
        f = x - i0
        r0, g0, b0 = i0[:, 0], i0[:, 1], i0[:, 2]
        fr, fg, fb = f[:, :1], f[:, 1:2], f[:, 2:3]
        c = lambda db, dg, dr: table[b0 + db, g0 + dg, r0 + dr]
        c00 = c(0, 0, 0) * (1 - fr) + c(0, 0, 1) * fr
        c01 = c(0, 1, 0) * (1 - fr) + c(0, 1, 1) * fr
        c10 = c(1, 0, 0) * (1 - fr) + c(1, 0, 1) * fr
        c11 = c(1, 1, 0) * (1 - fr) + c(1, 1, 1) * fr
        c0 = c00 * (1 - fg) + c01 * fg
        c1 = c10 * (1 - fg) + c11 * fg
        out[s:s + chunk] = c0 * (1 - fb) + c1 * fb
    return out.reshape(img.shape)


def apply(g: np.ndarray, lut: dict | None, log=print) -> np.ndarray:
    if not lut or not lut.get("file"):
        return g
    strength = lut.get("strength", 100) / 100.0
    if strength <= 0:
        return g
    try:
        path = resolve(lut["file"])
    except FileNotFoundError as e:
        log(f"  {e}")
        return g
    kind, n, table, dmin, dmax = load_cube(str(path))
    if kind == "3d":
        res = _apply3d(np.clip(g, 0, 1), table, n, dmin, dmax)
    else:
        res = np.empty_like(g)
        xs = np.linspace(0, 1, n)
        for c in range(3):
            res[..., c] = np.interp((g[..., c] - dmin[c]) / (dmax[c] - dmin[c]), xs, table[:, c])
    return np.clip(g + (res - g) * np.float32(strength), 0, 1).astype(np.float32)
