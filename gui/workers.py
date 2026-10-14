"""백그라운드 작업: 썸네일, EXIF, 미리보기 렌더(가장 최근 요청만), export."""
from __future__ import annotations

import copy
import io
import threading
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from PySide6.QtGui import QImage

from pipeline import export, files, runner
from pipeline.decode import is_raw, open_image

THUMB_EDGE = 320


def _pil_thumb(data_or_path, flip: int = 0):
    from PIL import ImageOps
    im = open_image(io.BytesIO(data_or_path) if isinstance(data_or_path, bytes) else data_or_path)
    im.draft("RGB", (THUMB_EDGE, THUMB_EDGE))
    im = ImageOps.exif_transpose(im) if not flip else im
    im = im.convert("RGB")
    im.thumbnail((THUMB_EDGE, THUMB_EDGE))
    if flip == 3:
        im = im.rotate(180, expand=True)
    elif flip == 6:
        im = im.rotate(-90, expand=True)
    elif flip == 5:
        im = im.rotate(90, expand=True)
    return np.asarray(im)


def make_thumb(path: Path) -> QImage | None:
    """RAW는 내장 JPEG 미리보기를 써서 빠르게 만든다."""
    try:
        if is_raw(path):
            import rawpy
            with rawpy.imread(str(path)) as raw:
                flip = raw.sizes.flip
                th = raw.extract_thumb()
            if th.format == rawpy.ThumbFormat.JPEG:
                arr = _pil_thumb(th.data, flip)
            else:
                from PIL import Image
                im = Image.fromarray(th.data)
                im.thumbnail((THUMB_EDGE, THUMB_EDGE))
                arr = np.asarray(im.convert("RGB"))
        else:
            arr = _pil_thumb(str(path))
        arr = np.ascontiguousarray(arr)
        h, w = arr.shape[:2]
        return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    except Exception:
        return None


class ThumbSignals(QObject):
    done = Signal(str, QImage)


class ThumbJob(QRunnable):
    def __init__(self, path: Path, signals: ThumbSignals):
        super().__init__()
        self.path, self.signals = path, signals

    def run(self):
        img = make_thumb(self.path)
        if img is not None:
            self.signals.done.emit(str(self.path), img)


class ExifSignals(QObject):
    done = Signal(dict)


class ExifJob(QRunnable):
    def __init__(self, paths: list[Path], signals: ExifSignals):
        super().__init__()
        self.paths, self.signals = paths, signals

    def run(self):
        try:
            self.signals.done.emit(export.read_exif(self.paths))
        except Exception:
            pass


class RenderWorker(QObject):
    """전용 스레드에서 돈다. 요청이 몰리면 가장 최근 것만 처리한다."""
    finished = Signal(object)
    failed = Signal(str, int, str)
    busy = Signal(bool)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self._lock = threading.Lock()
        self._request = None
        self._prefetch = None

    def submit(self, path: Path, edit: dict, gen: int, full_frame: bool = False):
        with self._lock:
            self._request = (path, copy.deepcopy(edit), gen, full_frame)

    def submit_prefetch(self, path: Path, edit: dict):
        with self._lock:
            self._prefetch = (path, copy.deepcopy(edit))

    @Slot()
    def wake(self):
        while True:
            with self._lock:
                req, self._request = self._request, None
            if req is None:
                break
            path, edit, gen, full = req
            self.busy.emit(True)
            try:
                self.finished.emit(self.engine.render(path, edit, gen, full))
            except Exception as e:
                traceback.print_exc()
                self.failed.emit(str(path), gen, f"{type(e).__name__}: {e}")
        self.busy.emit(False)
        with self._lock:
            pf, self._prefetch = self._prefetch, None
        if pf:
            self.engine.prefetch(*pf)


class ExportWorker(QObject):
    progress = Signal(int, int, str)
    log = Signal(str)
    finished = Signal(list, list)  # (성공 결과, 실패 [(파일, 메시지)])

    def __init__(self, paths: list[Path], out_dir: Path | None, size: int | None, quality: int, device: str,
                 base: Path | None = None):
        """out_dir이 None이면 사진마다 그 폴더의 export/에, 정했으면 base 기준 하위 폴더 구조를 유지해 저장."""
        super().__init__()
        self.paths, self.out_dir, self.size, self.quality, self.device = paths, out_dir, size, quality, device
        self.base = base
        self.cancelled = False

    @Slot()
    def run(self):
        ok, fail = [], []
        exif_all = export.read_exif(self.paths)
        for i, path in enumerate(self.paths):
            if self.cancelled:
                break
            self.progress.emit(i, len(self.paths), path.name)
            try:
                settings, origin = runner.settings_for(path, {"params_for": files.load_edit}, log=self.log.emit)
                r = runner.process(path, settings, exif_all.get(str(path), {}), preview=False,
                                   out_dir=files.export_dir_for(path, self.out_dir, self.base),
                                   size=self.size, quality=self.quality,
                                   device=self.device, layers=origin["layers"], log=self.log.emit)
                ok.append(r)
            except Exception as e:
                traceback.print_exc()
                fail.append((path.name, f"{type(e).__name__}: {e}"))
        self.progress.emit(len(self.paths), len(self.paths), "")
        self.finished.emit(ok, fail)
