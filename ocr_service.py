"""Lazy, process-wide CPU PaddleOCR service (3.x and legacy 2.x)."""
import math
import os
from importlib.metadata import version
from threading import Lock

import numpy as np


class OCRUnavailable(RuntimeError):
    pass


class OCRProcessingError(RuntimeError):
    pass


def normalize_results(results, width, height, threshold=0.5, modern=True):
    """Normalize recognition polygons, never detection-only polygons, to pixels."""
    candidates = []
    if modern:
        for result in results:
            if not hasattr(result, 'get'):
                result = result.json
            result = result.get('res', result)
            texts, scores, polys = (result.get(k) for k in ('rec_texts', 'rec_scores', 'rec_polys'))
            if texts is None or scores is None or polys is None:
                raise ValueError('Unsupported PaddleOCR prediction structure.')
            if not len(texts) == len(scores) == len(polys):
                raise ValueError('Mismatched PaddleOCR recognition arrays.')
            candidates.extend(zip(texts, scores, polys))
    else:
        for page in results or []:
            for polygon, recognition in page or []:
                candidates.append((recognition[0], recognition[1], polygon))
    lines = []
    for text, score, polygon in candidates:
        try:
            score = float(score)
            points = np.asarray(polygon, dtype=float)
            if not isinstance(text, str) or not text.strip() or len(text) > 10000:
                continue
            if not math.isfinite(score) or not threshold <= score <= 1:
                continue
            if points.shape != (4, 2) or not np.isfinite(points).all():
                continue
            points[:, 0] = np.clip(points[:, 0], 0, width - 1)
            points[:, 1] = np.clip(points[:, 1], 0, height - 1)
            # Paddle orders corners top-left, top-right, bottom-right, bottom-left.
            edge = points[1] - points[0]
            w = float(np.linalg.norm(edge))
            h = float(np.linalg.norm(points[3] - points[0]))
            side = points[3] - points[0]
            area = abs(float(edge[0] * side[1] - edge[1] * side[0]))
            if min(w, h) < 1 or area < 1:
                continue
            lines.append(dict(text=text.strip(), confidence=score,
                bbox=[dict(x=float(x), y=float(y)) for x, y in points],
                polygon=points.tolist(), rotation=math.degrees(math.atan2(edge[1], edge[0])),
                oriented_box=dict(x=float(points[0, 0]), y=float(points[0, 1]), width=w, height=h)))
        except (TypeError, ValueError, OverflowError):
            continue
    return lines


class OCRService:
    def __init__(self):
        self._model = None
        self._lock = Lock()
        self._modern = True

    def extract(self, bgr, threshold=0.5):
        if not 0 <= threshold <= 1:
            raise ValueError('OCR confidence threshold must be between 0 and 1.')
        # Paddle predictors are not shared concurrently across Flask threads.
        with self._lock:
            if self._model is None:
                try:
                    from paddleocr import PaddleOCR
                    major = int(version('paddleocr').split('.')[0])
                    self._modern = major == 3
                    if major == 3:
                        self._model = PaddleOCR(device='cpu', lang=os.getenv('OCR_LANG', 'en'),
                            ocr_version='PP-OCRv5',
                            use_doc_orientation_classify=False, use_doc_unwarping=False,
                            use_textline_orientation=False)
                    elif major == 2:
                        self._model = PaddleOCR(use_gpu=False, lang=os.getenv('OCR_LANG', 'en'),
                                               use_angle_cls=True, show_log=False)
                    else:
                        raise RuntimeError('Supported PaddleOCR versions are 2.x and 3.x.')
                except Exception as exc:
                    raise OCRUnavailable('PaddleOCR could not initialize. Check the installed CPU runtime and model downloads in the server log.') from exc
            try:
                results = (self._model.predict(bgr, text_rec_score_thresh=threshold) if self._modern
                           else self._model.ocr(bgr, cls=True))
                return normalize_results(results, bgr.shape[1], bgr.shape[0], threshold, self._modern)
            except Exception as exc:
                raise OCRProcessingError('PaddleOCR processing failed. See the server log for details.') from exc


ocr_service = OCRService()
