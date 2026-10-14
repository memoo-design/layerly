"""Approximate matching against installed fonts, never exact font identification."""
import os
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=1)
def candidates():
    root = Path(os.getenv('WINDIR', 'C:/Windows')) / 'Fonts'
    options = [('Arial', 'normal', 'arial.ttf'), ('Arial', 'bold', 'arialbd.ttf'),
               ('Georgia', 'normal', 'georgia.ttf'), ('Georgia', 'bold', 'georgiab.ttf'),
               ('Times New Roman', 'normal', 'times.ttf'), ('Times New Roman', 'bold', 'timesbd.ttf'),
               ('Courier New', 'normal', 'cour.ttf')]
    return [(family, weight, str(root / name)) for family, weight, name in options if (root / name).exists()]


def estimate_typography(rgb, lines):
    for line in lines:
        text = line['text']
        # Matching unsupported scripts or very long lines with Latin fonts is unreliable.
        if not text.isascii() or len(text) > 160 or not candidates():
            continue
        points = np.asarray(line['polygon'], np.float32)
        width = np.linalg.norm(points[1]-points[0])
        height = np.linalg.norm(points[3]-points[0])
        w, h = min(1024, max(2, round(width))), min(256, max(2, round(height)))
        transform = cv2.getPerspectiveTransform(points, np.float32([[0,0], [w-1,0], [w-1,h-1], [0,h-1]]))
        crop = cv2.warpPerspective(rgb, transform, (w, h))
        ink = np.array([int(line['color'][i:i+2], 16) for i in (1,3,5)])
        observed = (np.linalg.norm(crop.astype(float)-ink, axis=2) < 60).astype(np.uint8)*255
        ys, xs = np.where(observed)
        if not len(xs) or not .015 < len(xs)/(w*h) < .8:
            continue
        observed = observed[ys.min():ys.max()+1, xs.min():xs.max()+1]
        ink_height = height * observed.shape[0] / h
        target = cv2.resize(observed, (256, 64)) > 100
        best = None
        for family, weight, path in candidates():
            font = ImageFont.truetype(path, 80)
            box = font.getbbox(text)
            fw, fh = box[2]-box[0], box[3]-box[1]
            if min(fw, fh) <= 0:
                continue
            rendered = Image.new('L', (fw, fh))
            ImageDraw.Draw(rendered).text((-box[0], -box[1]), text, font=font, fill=255)
            candidate = cv2.resize(np.array(rendered), (256,64)) > 100
            iou = (candidate & target).sum()/max(1, (candidate | target).sum())
            ratio_error = abs(np.log((fw/fh)/(observed.shape[1]/observed.shape[0])))
            score = iou - .15*ratio_error
            if best is None or score > best[0]:
                best = (score, family, weight, 80*ink_height/fh)
        if best and best[0] >= .35:
            # OCR polygons include detector padding. Align editable ink to the
            # observed glyph extent while keeping the full polygon for removal.
            anchor = points[0] + (points[1]-points[0])*(xs.min()/w) + (points[3]-points[0])*(ys.min()/h)
            line['oriented_box'] = dict(x=float(anchor[0]), y=float(anchor[1]),
                width=float(width*observed.shape[1]/w), height=float(ink_height))
            line['typography'] = dict(font_family=best[1], font_weight=best[2],
                font_size=round(float(min(2000, max(1, best[3]))), 2), line_height=1.0,
                char_spacing=0, typography_match=round(float(best[0]), 3), fit_ink=True)
