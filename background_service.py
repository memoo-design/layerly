"""Polygon-based local text removal. No resizing or coordinate transforms."""
import cv2
import numpy as np
from PIL import Image


def repair_background(rgb, lines, destination, padding=2, radius=3):
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    for line in lines:
        polygon = np.rint(line['polygon']).astype(np.int32)
        cv2.fillPoly(mask, [polygon], 255)
    if padding:
        mask = cv2.dilate(mask, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * padding + 1, 2 * padding + 1)))
    cleaned = cv2.inpaint(rgb, mask, radius, cv2.INPAINT_TELEA) if mask.any() else rgb.copy()
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(cleaned).save(destination, 'PNG')
    return mask


def estimate_colors(rgb, lines):
    """Estimate contrasting glyph color inside each polygon; typography is approximate."""
    for line in lines:
        polygon = np.rint(line['polygon']).astype(np.int32)
        x, y, w, h = cv2.boundingRect(polygon)
        crop = rgb[y:y+h, x:x+w]
        mask = np.zeros(crop.shape[:2], np.uint8)
        cv2.fillPoly(mask, [polygon - [x, y]], 255)
        pixels = crop[mask > 0]
        background = np.median(pixels, axis=0)
        distance = np.linalg.norm(pixels.astype(float) - background, axis=1)
        ink = pixels[distance >= max(1, np.percentile(distance, 80))]
        if not len(ink):
            ink = pixels
        color = np.median(ink, axis=0).astype(int)
        line['color'] = '#%02x%02x%02x' % tuple(color)
