#!/usr/bin/env python3
"""luts/*.cube 만들기 (33³, sRGB 감마 입력 → 출력). 색감을 고치려면 아래 함수를 바꾸고 다시 실행.

  .venv/bin/python tools/make_luts.py            # 전부 (film.cube는 건드리지 않음)
  .venv/bin/python tools/make_luts.py warm_film  # 하나만

앱의 LUT 목록에는 파일 머리의 '# LABEL' 한글 이름이 보인다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "luts"
N = 33
LUMA = np.array([0.2126, 0.7152, 0.0722])


# ---------------------------------------------------------------- 도구
def curve(points):
    """단조 3차 보간 커브 (PCHIP). points: [(x, y), ...] 0~1"""
    xs, ys = (np.array(v, float) for v in zip(*points))
    h, d = np.diff(xs), np.diff(ys) / np.diff(xs)
    m = np.zeros_like(xs)
    m[0], m[-1] = d[0], d[-1]
    for k in range(1, len(xs) - 1):
        if d[k - 1] * d[k] > 0:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])

    def f(x):
        x = np.clip(x, xs[0], xs[-1])
        i = np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2)
        t = (x - xs[i]) / h[i]
        return ((2 * t ** 3 - 3 * t ** 2 + 1) * ys[i] + (t ** 3 - 2 * t ** 2 + t) * h[i] * m[i]
                + (-2 * t ** 3 + 3 * t ** 2) * ys[i + 1] + (t ** 3 - t ** 2) * h[i] * m[i + 1])
    return f


def luma(c):
    return c @ LUMA


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def channels(c, r=None, g=None, b=None):
    out = c.copy()
    for i, pts in enumerate((r, g, b)):
        if pts:
            out[..., i] = curve(pts)(c[..., i])
    return out


def tone(c, pts):
    """밝기 커브: 밝기 차이만큼 더한다 (곱하면 검정을 들 때 어두운 원색이 튀므로)."""
    y = luma(c)
    return c + (curve(pts)(y) - y)[..., None]


def saturation(c, s):
    y = luma(c)[..., None]
    return y + (c - y) * s


def tint(c, color, amount, mask):
    """밝기는 두고 색만 color 방향으로 민다. mask: 0~1 (영역)"""
    col = np.array(color, float)
    return c + (col - col @ LUMA)[None] * (amount * mask)[..., None]


def shadows(c, lo=0.0, hi=0.55):
    return 1 - smooth(lo, hi, luma(c))


def highlights(c, lo=0.45, hi=1.0):
    return smooth(lo, hi, luma(c))


def mids(c):
    y = luma(c)
    return np.clip(1 - np.abs(y - 0.5) * 2, 0, 1)


def rgb2hsv(c):
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mx, mn = c.max(-1), c.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rc = np.where(nz, (mx - r) / np.where(nz, d, 1), 0)
    gc = np.where(nz, (mx - g) / np.where(nz, d, 1), 0)
    bc = np.where(nz, (mx - b) / np.where(nz, d, 1), 0)
    h = np.where(r == mx, bc - gc, np.where(g == mx, 2 + rc - bc, 4 + gc - rc))
    h = np.where(nz, (h / 6) % 1, 0) * 360
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return np.stack([h, s, mx], -1)


def hsv2rgb(hsv):
    h, s, v = hsv[..., 0] / 60 % 6, hsv[..., 1], hsv[..., 2]
    i = np.floor(h).astype(int)
    f = h - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    sel = [np.stack(x, -1) for x in ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))]
    out = np.zeros(hsv.shape)
    for k in range(6):
        out = np.where((i == k)[..., None], sel[k], out)
    return out


def hue_adjust(c, center, width=35, hue=0.0, sat=1.0, val=0.0):
    """center(°) 부근 색만: hue(° 이동), sat(배수), val(밝기 더하기). 무채색은 거의 안 바뀜."""
    hsv = rgb2hsv(c)
    dist = np.abs((hsv[..., 0] - center + 180) % 360 - 180)
    w = np.exp(-(dist / width) ** 2) * np.clip(hsv[..., 1] * 3, 0, 1)
    hsv[..., 0] = (hsv[..., 0] + hue * w) % 360
    hsv[..., 1] = np.clip(hsv[..., 1] * (1 + (sat - 1) * w), 0, 1)
    hsv[..., 2] = np.clip(hsv[..., 2] + val * w, 0, 1)
    return hsv2rgb(hsv)


# ---------------------------------------------------------------- 색감
def warm_film(c):
    """따뜻한 인물 필름: 살짝 들린 검정, 크림빛 하이라이트, 차분한 초록."""
    c = channels(c, r=[(0, .035), (.25, .27), (.5, .535), (.75, .78), (1, .975)],
                 g=[(0, .03), (.25, .255), (.5, .51), (.75, .76), (1, .965)],
                 b=[(0, .055), (.25, .25), (.5, .48), (.75, .72), (1, .925)])
    c = hue_adjust(c, 105, 40, hue=-8, sat=0.8)
    c = hue_adjust(c, 220, 40, sat=0.9)
    return saturation(c, 0.93)


def cool_film(c):
    """시원한 필름: 청록 그림자, 깨끗한 하이라이트, 청록으로 기운 초록."""
    c = channels(c, r=[(0, .02), (.25, .23), (.5, .5), (.75, .77), (1, .985)],
                 g=[(0, .035), (.25, .26), (.5, .51), (.75, .765), (1, .98)],
                 b=[(0, .055), (.25, .27), (.5, .51), (.75, .75), (1, .965)])
    c = hue_adjust(c, 110, 40, hue=10, sat=0.88)
    c = hue_adjust(c, 0, 25, sat=1.05)
    return saturation(c, 0.95)


def teal_orange(c):
    """영화 같은 틸·오렌지: 그림자는 청록, 밝은 곳과 피부는 주황."""
    c = tone(c, [(0, .02), (.25, .22), (.5, .5), (.75, .78), (1, .985)])
    c = tint(c, (0.0, 0.55, 0.62), 0.11, shadows(c))
    c = tint(c, (1.0, 0.62, 0.3), 0.08, highlights(c))
    c = hue_adjust(c, 220, 35, hue=-15, sat=1.1)
    c = hue_adjust(c, 110, 40, hue=25, sat=0.8)
    return c


def matte_fade(c):
    """매트 페이드: 바랜 검정, 낮은 대비, 부드러운 색."""
    c = tone(c, [(0, .10), (.2, .245), (.5, .52), (.8, .80), (1, .93)])
    c = tint(c, (1.0, 0.85, 0.7), 0.03, mids(c))
    return saturation(c, 0.78)


def golden_hour(c):
    """골든아워: 금빛 하이라이트, 자줏빛 그림자, 따뜻한 주황·노랑."""
    c = tint(c, (1.0, 0.72, 0.3), 0.10, highlights(c, 0.3, 1.0))
    c = tint(c, (0.5, 0.32, 0.5), 0.04, shadows(c))
    c = hue_adjust(c, 35, 30, sat=1.12)
    c = hue_adjust(c, 220, 40, sat=0.85)
    return tone(c, [(0, .02), (.25, .235), (.5, .51), (.75, .77), (1, .98)])


def pastel_bloom(c):
    """파스텔 블룸: 밝은 중간톤, 분홍 하이라이트, 민트빛 초록."""
    c = tone(c, [(0, .06), (.25, .32), (.5, .58), (.75, .82), (1, .97)])
    c = tint(c, (1.0, 0.75, 0.86), 0.05, highlights(c))
    c = tint(c, (0.6, 0.55, 0.85), 0.04, shadows(c))
    c = hue_adjust(c, 110, 40, hue=8, sat=0.8, val=0.03)
    c = hue_adjust(c, 330, 30, sat=1.1)
    return saturation(c, 0.85)


def neon_night(c):
    """네온 나이트: 깊은 검정, 청록 그림자, 분홍빛 조명, 파랑·보라 강조."""
    c = tone(c, [(0, 0), (.15, .12), (.5, .5), (.85, .88), (1, 1)])
    c = tint(c, (0.0, 0.45, 0.68), 0.10, shadows(c))
    c = tint(c, (1.0, 0.45, 0.8), 0.06, highlights(c))
    c = hue_adjust(c, 30, 20, hue=8, sat=0.85)
    c = hue_adjust(c, 225, 35, sat=1.2)
    c = hue_adjust(c, 290, 35, sat=1.2)
    return hue_adjust(c, 110, 40, hue=15, sat=0.8)


def snow_clean(c):
    """맑은 설경: 푸른 그림자, 깨끗하고 밝은 흰색, 차분한 색."""
    c = tint(c, (0.35, 0.5, 0.78), 0.07, shadows(c))
    c = tint(c, (0.92, 0.96, 1.0), 0.03, highlights(c))
    c = tone(c, [(0, .02), (.25, .24), (.5, .52), (.8, .84), (1, .995)])
    return saturation(c, 0.9)


def autumn_amber(c):
    """가을 앰버: 올리브로 물든 초록, 진한 빨강·주황, 따뜻한 빛."""
    c = hue_adjust(c, 115, 45, hue=-25, sat=0.7)
    c = hue_adjust(c, 60, 25, hue=-6, sat=1.1)
    c = hue_adjust(c, 20, 25, sat=1.15, val=-0.03)
    c = tint(c, (1.0, 0.75, 0.4), 0.06, highlights(c))
    c = tint(c, (0.48, 0.36, 0.26), 0.04, shadows(c))
    return tone(c, [(0, .02), (.25, .23), (.5, .5), (.75, .77), (1, .985)])


def summer_aqua(c):
    """여름 아쿠아: 투명한 바다색, 진한 하늘, 따뜻한 피부와 모래."""
    c = hue_adjust(c, 188, 25, hue=-3, sat=1.25)
    c = hue_adjust(c, 225, 30, hue=-8, sat=1.15, val=-0.03)
    c = hue_adjust(c, 30, 25, sat=1.05)
    c = hue_adjust(c, 110, 35, hue=10, sat=1.05)
    c = tint(c, (0.2, 0.62, 0.7), 0.04, shadows(c))
    return tone(c, [(0, .02), (.5, .5), (.85, .88), (1, .99)])


def mono_film(c):
    """흑백 필름: 빨강 필터 느낌(하늘이 짙음), 부드러운 S 커브, 살짝 따뜻한 종이색."""
    y = c @ np.array([0.45, 0.45, 0.10])
    y = curve([(0, .04), (.2, .17), (.5, .5), (.8, .83), (1, .97)])(y)
    out = np.stack([y, y, y], -1)
    return tint(out, (1.0, 0.9, 0.75), 0.025, np.clip(1 - np.abs(y - 0.55) * 2, 0, 1))


LOOKS = {
    "warm_film": ("따뜻한 필름", warm_film),
    "cool_film": ("시원한 필름", cool_film),
    "teal_orange": ("시네마 틸·오렌지", teal_orange),
    "matte_fade": ("매트 페이드", matte_fade),
    "golden_hour": ("골든아워", golden_hour),
    "pastel_bloom": ("파스텔 블룸", pastel_bloom),
    "neon_night": ("네온 나이트", neon_night),
    "snow_clean": ("맑은 설경", snow_clean),
    "autumn_amber": ("가을 앰버", autumn_amber),
    "summer_aqua": ("여름 아쿠아", summer_aqua),
    "mono_film": ("흑백 필름", mono_film),
}


def write_cube(name: str, label: str, fn):
    x = np.linspace(0, 1, N)
    b, g, r = np.meshgrid(x, x, x, indexing="ij")  # .cube 순서: 빨강이 가장 빠르게 변함
    out = np.clip(fn(np.stack([r, g, b], -1)), 0, 1).reshape(-1, 3)
    head = [f'TITLE "{name}"', f"# LABEL {label}", f"# {fn.__doc__.strip()}",
            "# tools/make_luts.py로 생성 (sRGB 입력)", f"LUT_3D_SIZE {N}", "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    body = "\n".join(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in out)
    path = OUT / f"{name}.cube"
    path.write_text("\n".join(head) + "\n" + body + "\n", encoding="utf-8")
    return path


def main():
    names = sys.argv[1:] or list(LOOKS)
    OUT.mkdir(exist_ok=True)
    for n in names:
        label, fn = LOOKS[n]
        print("생성:", write_cube(n, label, fn).relative_to(ROOT), "—", label)


if __name__ == "__main__":
    main()
