"""AI 노이즈 제거: SCUNet 사전학습 모델, PyTorch MPS(Mac GPU), 타일 처리.

가중치가 없으면 OpenCV 기반 일반 노이즈 감소로 대신하고 로그를 남긴다.
"""
from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np

from pipeline import color

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "scunet_color_real_psnr.pth"
TILE = 512
OVERLAP = 48
_model_cache = {}
_lock = threading.Lock()  # 모델 하나를 여러 스레드가 동시에 쓰지 않도록


def _device(name: str):
    import torch
    if name == "cpu":
        return torch.device("cpu")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _load(device_name: str):
    import torch
    from .scunet import SCUNet
    key = device_name
    if key not in _model_cache:
        dev = _device(device_name)
        net = SCUNet()
        net.load_state_dict(torch.load(MODEL_PATH, map_location="cpu", weights_only=True), strict=True)
        net.eval().to(dev)
        if dev.type == "mps":
            net.half()  # MPS에서 fp16이 약 2배 빠르고 오차는 8비트 1단계 미만
        _model_cache[key] = (net, dev)
    return _model_cache[key]


def _window(n, overlap):
    w = np.ones(n, np.float32)
    if overlap > 0:
        ramp = (np.arange(overlap, dtype=np.float32) + 0.5) / overlap
        w[:overlap] = ramp
        w[-overlap:] = ramp[::-1]
    return w


def _scunet(g: np.ndarray, device_name: str, log=print) -> np.ndarray:
    with _lock:
        return _scunet_locked(g, device_name, log)


def _scunet_locked(g: np.ndarray, device_name: str, log=print) -> np.ndarray:
    import torch
    net, dev = _load(device_name)
    h, w = g.shape[:2]
    out = np.zeros_like(g)
    acc = np.zeros((h, w, 1), np.float32)
    step = TILE - OVERLAP
    ys = list(range(0, max(h - TILE, 0) + 1, step)) or [0]
    xs = list(range(0, max(w - TILE, 0) + 1, step)) or [0]
    if ys[-1] + TILE < h:
        ys.append(h - TILE)
    if xs[-1] + TILE < w:
        xs.append(w - TILE)
    total = len(ys) * len(xs)
    with torch.inference_mode():
        for n, (y, x) in enumerate((y, x) for y in ys for x in xs):
            tile = g[y:y + TILE, x:x + TILE]
            th, tw = tile.shape[:2]
            t = torch.from_numpy(np.ascontiguousarray(tile.transpose(2, 0, 1)))[None].to(dev)
            t = t.to(next(net.parameters()).dtype)
            r = net(t).clamp_(0, 1)[0].permute(1, 2, 0).float().cpu().numpy()
            wy = _window(th, OVERLAP if th == TILE and h > TILE else 0)
            wx = _window(tw, OVERLAP if tw == TILE and w > TILE else 0)
            wt = (wy[:, None] * wx[None, :])[..., None]
            out[y:y + th, x:x + tw] += r * wt
            acc[y:y + th, x:x + tw] += wt
            if total > 8 and (n + 1) % max(1, total // 4) == 0:
                log(f"  AI 노이즈 제거 {n + 1}/{total} 타일")
    return out / np.maximum(acc, 1e-6)


def classic(g: np.ndarray, luminance: float = 50, chroma: float = 50, scale: float = 1.0) -> np.ndarray:
    """OpenCV 노이즈 감소 (일반 NR 및 대체용). g는 sRGB 감마."""
    ycc = cv2.cvtColor(g.astype(np.float32), cv2.COLOR_RGB2YCrCb)
    if luminance > 0:
        y = ycc[..., 0]
        d = max(3, int(round(3 + 6 * luminance / 100 * scale)) | 1)
        ycc[..., 0] = cv2.bilateralFilter(y, d, 0.01 + 0.07 * luminance / 100, d)
    if chroma > 0:
        sigma = max(0.5, (1 + 5 * chroma / 100) * scale)
        for c in (1, 2):
            ycc[..., c] = cv2.GaussianBlur(ycc[..., c], (0, 0), sigma)
    return np.clip(cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB), 0, 1)


def denoise_linear(lin: np.ndarray, strength: float = 100, device: str = "auto", log=print) -> np.ndarray:
    """선형 RGB를 받아 sRGB 감마 공간에서 노이즈를 제거하고 다시 선형으로 돌려준다.
    1.0을 넘는 하이라이트 정보는 그대로 보존한다."""
    g = color.srgb_encode(lin)
    if MODEL_PATH.exists():
        try:
            d = _scunet(g, device, log)
        except Exception as e:  # MPS 메모리 부족 등
            log(f"  AI 노이즈 제거 실패({e}), OpenCV로 대체")
            d = classic(g, 60, 60)
    else:
        log(f"  모델 없음({MODEL_PATH.name}), OpenCV 노이즈 감소로 대체")
        d = classic(g, 60, 60)
    s = np.float32(strength / 100.0)
    g2 = g + (d - g) * s
    return color.srgb_decode(g2) + np.maximum(lin - 1.0, 0)
