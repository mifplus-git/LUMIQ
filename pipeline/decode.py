"""사진 읽기.

- RAW(NEF 등): rawpy(LibRaw)로 선형 RGB(sRGB 원색, float32)로 디코딩
- JPG/HEIC/PNG/WebP/TIFF: EXIF 회전·ICC를 반영해 sRGB로 읽은 뒤 선형으로 변환
  (HEIC·HEIF는 pillow-heif로 연다. 회전은 디코딩 때 적용되고 EXIF 방향은 1로 바뀐다)
"""
from __future__ import annotations

import functools

import numpy as np

from . import color

RAW_EXTS = {".nef", ".nrw", ".dng", ".cr2", ".cr3", ".arw", ".raf", ".orf", ".rw2"}
HEIF_EXTS = {".heic", ".heif"}
RASTER_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"} | HEIF_EXTS
IMAGE_EXTS = RAW_EXTS | RASTER_EXTS
HALF_MIN_EDGE = 2048  # 빠른 디코딩(half)이라도 긴 변을 이보다 작게 줄이지 않는다


def is_raw(path) -> bool:
    return str(path).lower().endswith(tuple(RAW_EXTS))


@functools.cache
def enable_heif() -> bool:
    """PIL.Image.open이 HEIC·HEIF(아이폰 사진)를 열 수 있게 한다. pillow-heif가 없으면 False."""
    try:
        import pillow_heif
    except ImportError:
        return False
    pillow_heif.register_heif_opener()
    return True


def open_image(path):
    """PIL로 사진 열기 (HEIC 포함)."""
    from PIL import Image
    if str(path).lower().endswith(tuple(HEIF_EXTS)) and not enable_heif():
        raise RuntimeError("HEIC를 열려면 pillow-heif가 필요합니다 (.venv/bin/pip install pillow-heif)")
    return Image.open(path)


class RawMeta:
    is_raw = True

    def __init__(self, raw, half: bool):
        self.camera_wb = [float(x) for x in raw.camera_whitebalance]
        self.daylight_wb = [float(x) for x in raw.daylight_whitebalance]
        self.cam_xyz = np.array(raw.rgb_xyz_matrix[:3], dtype=np.float64)
        self.sizes = raw.sizes
        self.decode_scale = 0.5 if half else 1.0
        cw = raw.sizes.crop_width or raw.sizes.width
        ch = raw.sizes.crop_height or raw.sizes.height
        self.full_size = (ch, cw) if raw.sizes.flip in (5, 6) else (cw, ch)  # (가로, 세로)

    @property
    def shot_xy(self):
        """촬영 시 화이트밸런스의 광원 색도."""
        return color.camera_neutral_xy(self.cam_xyz, self.camera_wb)


class RasterMeta:
    """JPG 등: 이미 화이트밸런스가 적용된 사진이라 기준 광원을 D65(현재 상태)로 둔다.
    그래서 색온도는 촬영 시 값 대신 '현재 = 약 6500K' 기준의 상대 조정이 된다."""
    is_raw = False
    shot_xy = color.D65_XY

    def __init__(self, decode_scale: float, full_size):
        self.decode_scale = decode_scale
        self.full_size = full_size


def _sensor_crop(img: np.ndarray, sizes, half: bool) -> np.ndarray:
    """LibRaw 출력의 가장자리 여백을 카메라 기준 크기(Z6: 6048×4024)로 자른다."""
    cw, ch = sizes.crop_width, sizes.crop_height
    if not cw or not ch:
        return img
    s = 2 if half else 1
    x0, y0 = sizes.crop_left_margin // s, sizes.crop_top_margin // s
    w, h = cw // s, ch // s
    if y0 + h <= img.shape[0] and x0 + w <= img.shape[1]:
        return img[y0:y0 + h, x0:x0 + w]
    return img


def _apply_flip(img: np.ndarray, flip: int) -> np.ndarray:
    # LibRaw flip 코드: 3=180°, 5=반시계 90°, 6=시계 90°
    if flip == 3:
        return img[::-1, ::-1]
    if flip == 5:
        return np.rot90(img, 1)
    if flip == 6:
        return np.rot90(img, -1)
    return img


def _decode_raw(path, half: bool):
    import rawpy
    with rawpy.imread(str(path)) as raw:
        meta = RawMeta(raw, half)
        rgb = raw.postprocess(
            gamma=(1, 1),
            no_auto_bright=True,
            output_bps=16,
            use_camera_wb=True,
            output_color=rawpy.ColorSpace.sRGB,
            highlight_mode=rawpy.HighlightMode.Blend,
            user_flip=0,
            half_size=half,
        )
    img = rgb.astype(np.float32) / 65535.0
    img = _sensor_crop(img, meta.sizes, half)
    img = _apply_flip(img, meta.sizes.flip)
    return np.ascontiguousarray(img), meta


def _to_srgb_pil(im):
    """내장 ICC가 sRGB가 아니면(Display P3, Adobe RGB 등) sRGB로 변환."""
    from PIL import ImageCms
    icc = im.info.get("icc_profile")
    if icc:
        try:
            import io
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            desc = ImageCms.getProfileDescription(src) or ""
            if "srgb" not in desc.lower():
                im = ImageCms.profileToProfile(im, src, ImageCms.createProfile("sRGB"), outputMode="RGB")
        except Exception:
            pass
    return im


def _decode_raster(path, half: bool):
    from PIL import ImageOps
    suffix = str(path).lower()
    if suffix.endswith((".tif", ".tiff", ".png")):
        import cv2
        arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYCOLOR)
        if arr is not None and arr.dtype == np.uint16:  # 16비트는 OpenCV로 정밀도 유지
            arr = arr[..., :3][..., ::-1] if arr.ndim == 3 else np.dstack([arr] * 3)
            g = arr.astype(np.float32) / 65535.0
            full = (g.shape[1], g.shape[0])
            if half and max(g.shape[:2]) // 2 >= HALF_MIN_EDGE:
                g = color.resize_long(g, max(g.shape[:2]) // 2)
            return np.ascontiguousarray(color.srgb_decode(g)), RasterMeta(0.5 if half else 1.0, full)
    with open_image(path) as im:
        full = im.size
        if im.getexif().get(0x0112, 1) in (5, 6, 7, 8):  # 90° 회전된 사진
            full = (full[1], full[0])
        if half and im.format == "JPEG" and max(im.size) // 2 >= HALF_MIN_EDGE:
            im.draft("RGB", (im.width // 2, im.height // 2))  # DCT 단계에서 축소 → 빠름
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L", "RGBA", "I;16"):
            im = im.convert("RGB")
        im = _to_srgb_pil(im)
        im = im.convert("RGB")
        g = np.asarray(im, dtype=np.float32) / 255.0
    scale = max(g.shape[:2]) / max(full)
    if half and scale > 0.6 and max(g.shape[:2]) // 2 >= HALF_MIN_EDGE:
        g = color.resize_long(g, max(g.shape[:2]) // 2)
        scale /= 2
    return np.ascontiguousarray(color.srgb_decode(g)), RasterMeta(scale, full)


def decode(path, half: bool = False):
    """선형 RGB float32(백색=1.0)와 메타데이터. RAW는 화이트밸런스가 촬영 시 값."""
    if is_raw(path):
        return _decode_raw(path, half)
    return _decode_raster(path, half)
