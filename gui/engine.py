"""앱용 렌더링 엔진: 단계별 결과를 캐시해 슬라이더를 움직일 때 뒤 단계만 다시 계산한다.

  디코딩+렌즈 (사진마다)  →  기하+축소+AI 노이즈 제거 (기하 값마다)  →  렌더 (매번)
"""
from __future__ import annotations

import copy
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pipeline import color, export, geometry, params as P, runner, tone

WORK_EDGE = 1600  # 앱 미리보기 긴 변


@dataclass
class GeoEntry:
    lin: np.ndarray
    meta: object
    angle: float
    scale: float
    faces: list | None = None
    auto: dict = field(default_factory=dict)  # 밝기 선호값 → 자동 보정 결과
    before: np.ndarray | None = None  # 보정 전 (uint8)


@dataclass
class RenderResult:
    path: Path
    gen: int
    rgb: np.ndarray            # uint8 (h, w, 3)
    before: np.ndarray         # uint8
    applied: dict              # 실제 적용된 전체 값 (슬라이더 표시용)
    as_shot: tuple             # (색온도, 틴트)
    is_raw: bool
    faces: int
    auto_reasons: list = field(default_factory=list)
    angle: float = 0.0
    seconds: float = 0.0
    hist: np.ndarray | None = None
    logs: list = field(default_factory=list)
    full_frame: bool = False    # 자르기 도구용: 회전·크롭 없이 전체 프레임
    level_angle: float = 0.0    # 자동 수평이 찾은 각도
    scale: float = 1.0          # 미리보기 해상도 / 원본 해상도 (화면 확대율을 원본 대비 %로 보일 때)


def _key(d: dict, keys) -> str:
    return json.dumps({k: d.get(k) for k in keys}, sort_keys=True, default=str)


def to_u8(g: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.clip(g * 255.0 + 0.5, 0, 255).astype(np.uint8))


class Engine:
    def __init__(self, work_edge: int = WORK_EDGE, device: str = "auto"):
        self.work_edge = work_edge
        self.device = device
        self._decoded: OrderedDict = OrderedDict()
        self._geo: OrderedDict = OrderedDict()
        self._exif: dict = {}
        self._level: dict = {}

    # ---- EXIF ----
    def set_exif(self, data: dict):
        self._exif.update(data)

    def exif(self, path: Path) -> dict:
        key = str(Path(path).absolute())
        if key not in self._exif:
            self._exif.update(export.read_exif([Path(path)]))
            self._exif.setdefault(key, {})
        return self._exif[key]

    # ---- 캐시 ----
    def _cache_get(self, cache: OrderedDict, key, limit: int, make):
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        val = make()
        cache[key] = val
        while len(cache) > limit:
            cache.popitem(last=False)
        return val

    def decoded(self, path: Path, p: dict, logs: list):
        key = (str(path), p.get("lens"), bool(p.get("camera_match")))
        return self._cache_get(self._decoded, key, 3, lambda: runner.stage_decode(
            path, self.exif(path), p, half=True, log=logs.append))

    def prefetch(self, path: Path, edit: dict):
        try:
            merged, _ = runner.settings_for(path, {"params_for": lambda _: edit}, log=lambda m: None)
            self.decoded(path, P.validate(merged, warn=lambda m: None), [])
        except Exception:
            pass

    def geometry(self, path: Path, p: dict, logs: list) -> GeoEntry:
        key = (str(path), p.get("lens"), bool(p.get("camera_match")), _key(p, runner.GEOMETRY_KEYS),
               json.dumps(p.get("ai_denoise"), default=str), self.work_edge)

        def make():
            lin, meta = self.decoded(path, p, logs)
            out, angle, scale = runner.stage_geometry(lin, meta, p, work_edge=self.work_edge, device=self.device,
                                                      log=logs.append)
            return GeoEntry(out, meta, angle, scale)
        return self._cache_get(self._geo, key, 6, make)

    def level_angle(self, path: Path, p: dict, logs: list) -> float:
        key = (str(path), p.get("lens"), p.get("rotate90"), p.get("flip"))
        if key not in self._level:
            lin, _ = self.decoded(path, p, logs)
            self._level[key] = geometry.detect_level(geometry.rotate90_flip(lin, p.get("rotate90"), p.get("flip")))["angle"]
        return self._level[key]

    def forget(self, path: Path):
        for cache in (self._decoded, self._geo):
            for k in [k for k in cache if k[0] == str(path)]:
                cache.pop(k)

    # ---- 렌더 ----
    def settings(self, path: Path, edit: dict):
        """edit(앱/edits JSON 값)를 프리셋·사진별 yaml과 합친다. 반환: (merged, layers)"""
        merged, src = runner.settings_for(path, {"params_for": lambda _: edit}, log=lambda m: None)
        return merged, src["layers"]

    def render(self, path: Path, edit: dict, gen: int = 0, full_frame: bool = False) -> RenderResult:
        t0 = time.time()
        logs: list = []
        merged, layers = self.settings(path, edit)
        p = P.validate(merged, warn=logs.append)
        geo_p = p
        if full_frame:  # 자르기 도구: 90° 회전·반전만 하고 각도·크롭은 화면에서 그린다
            geo_p = {k: v for k, v in p.items() if k not in runner.GEOMETRY_KEYS or k in ("rotate90", "flip")}
            geo_p["auto_level"] = False
        geo = self.geometry(path, geo_p, logs)
        if runner.needs_faces(p) and geo.faces is None:
            geo.faces = runner.detect_faces(geo.lin, geo.meta)
        faces = geo.faces or []
        reasons = []
        if p.get("auto"):
            b = p.get("auto_brightness") or 0
            if b not in geo.auto:
                from ai import auto
                if len(geo.auto) > 12:  # 슬라이더를 끌 때 쌓이지 않게
                    geo.auto.clear()
                geo.auto[b] = auto.compute(geo.lin, geo.meta, faces, brightness=b)
            p = P.validate(runner.combine_auto(geo.auto[b]["params"], *layers), warn=lambda m: None)
            reasons = geo.auto[b]["reasons"]
        g = runner.render(geo.lin, geo.meta, p, faces, geo.scale, log=logs.append)
        g = runner.finish(g, p, None, output_sharpen=False, seed=runner.seed_for(path))
        rgb = to_u8(g)
        if geo.before is None:
            geo.before = to_u8(tone.to_display(geo.lin, geo.meta.is_raw))
        hist = np.stack([np.bincount(rgb[..., c].ravel(), minlength=256) for c in range(3)])
        as_shot = color.as_shot_temp_tint(geo.meta)
        return RenderResult(path=path, gen=gen, rgb=rgb, before=geo.before, applied=copy.deepcopy(p),
                            as_shot=as_shot, is_raw=geo.meta.is_raw, faces=len(faces), auto_reasons=reasons,
                            angle=geo.angle, seconds=round(time.time() - t0, 2), hist=hist, logs=logs,
                            full_frame=full_frame, scale=geo.scale,
                            level_angle=self.level_angle(path, p, logs) if full_frame else 0.0)
