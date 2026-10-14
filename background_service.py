"""Polygon-based local text removal. No resizing or coordinate transforms."""
import cv2
import numpy as np
from PIL import Image


def text_mask(rgb, lines, padding=None):
    """Prefer glyph masks; only use polygon fill when foreground is ambiguous.

    A low-residual plane fitted outside the polygon models flat/gradient artwork.
    On textured backgrounds use a separated ink-color cluster, or conservatively
    fall back to the polygon. No pixels outside a small polygon margin are touched.
    """
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    surfaces = []
    for line in lines:
        polygon = np.rint(line['polygon']).astype(np.int32)
        x, y, w, h = cv2.boundingRect(polygon)
        margin = 6
        x0, y0 = max(0, x-margin), max(0, y-margin)
        x1, y1 = min(rgb.shape[1], x+w+margin), min(rgb.shape[0], y+h+margin)
        crop = rgb[y0:y1, x0:x1]
        region = np.zeros(crop.shape[:2], np.uint8)
        cv2.fillPoly(region, [polygon-[x0, y0]], 255)
        pad = max(2, min(3, round(min(w, h) * .05))) if padding is None else padding
        allowed = cv2.dilate(region, np.ones((2*pad+1, 2*pad+1), np.uint8))
        if region.size > 2_000_000:
            mask[y0:y1, x0:x1] |= allowed
            line['restoration_method'] = 'large polygon fallback with Telea'
            continue
        ring = (cv2.dilate(allowed, np.ones((7, 7), np.uint8)) > 0) & (allowed == 0)
        yy, xx = np.indices(region.shape)
        design = np.stack([np.ones_like(xx), xx / max(w, 1), yy / max(h, 1)], axis=-1)
        foreground, surface = allowed.copy(), None
        if ring.sum() >= 12:
            samples = design[ring][::max(1, int(ring.sum()/2000))]
            colors = crop[ring][::max(1, int(ring.sum()/2000))].astype(float)
            coefficients = np.linalg.lstsq(samples, colors, rcond=None)[0]
            # Nearby ornaments can contaminate a small part of the ring. Fit
            # its dominant surface without letting those outliers drive it.
            for _ in range(3):
                residual = np.linalg.norm(samples @ coefficients - colors, axis=1)
                keep = residual <= np.percentile(residual, 80)
                coefficients = np.linalg.lstsq(samples[keep], colors[keep], rcond=None)[0]
            error = np.linalg.norm(samples @ coefficients - colors, axis=1)
            predicted = np.clip(design @ coefficients, 0, 255)
            if np.percentile(error, 80) < 8:
                distance = np.linalg.norm(crop.astype(float)-predicted, axis=2)
                foreground = ((distance > max(10, np.percentile(error, 80)*2)) & (allowed > 0)).astype(np.uint8)*255
                surface = predicted.astype(np.uint8)
                line['restoration_method'] = 'local gradient with glyph mask'
            elif 'color' in line:
                ink = np.array([int(line['color'][i:i+2], 16) for i in (1, 3, 5)])
                candidate = (np.linalg.norm(crop.astype(float)-ink, axis=2) < 40) & (region > 0)
                occupancy = candidate.sum() / max(1, (region > 0).sum())
                if .02 < occupancy < .65 and np.linalg.norm(ink-np.median(colors, axis=0)) > 60:
                    # A color cluster is safe only when it accounts for most
                    # high-contrast foreground. Multi-color/outlined lettering
                    # otherwise needs the complete polygon to avoid duplicates.
                    distance = np.linalg.norm(crop.astype(float)-predicted, axis=2)
                    contrasting = (distance > max(35, np.percentile(error, 80)*2)) & (region > 0)
                    covered = cv2.dilate(candidate.astype(np.uint8), np.ones((5,5), np.uint8)) > 0
                    if contrasting.sum() and (covered & contrasting).sum()/contrasting.sum() >= .92:
                        foreground = candidate.astype(np.uint8)*255
                        line['restoration_method'] = 'color glyph mask with Telea'
        if surface is None and 'restoration_method' not in line:
            line['restoration_method'] = 'polygon fallback with Telea'
        foreground = cv2.dilate(foreground, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*pad+1, 2*pad+1)))
        foreground[allowed == 0] = 0
        mask[y0:y1, x0:x1] |= foreground
        if surface is not None:
            surfaces.append((x0, y0, surface, foreground))
    return mask, surfaces


def repair_background(rgb, lines, destination, padding=None, radius=3):
    mask, surfaces = text_mask(rgb, lines, padding)
    cleaned = cv2.inpaint(rgb, mask, radius, cv2.INPAINT_TELEA) if mask.any() else rgb.copy()
    for x, y, surface, foreground in surfaces:
        crop = cleaned[y:y+surface.shape[0], x:x+surface.shape[1]]
        crop[foreground > 0] = surface[foreground > 0]
    if hasattr(destination, 'parent'):
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
        pixels = pixels[::max(1, len(pixels)//100000)]
        background = np.median(pixels, axis=0)
        distance = np.linalg.norm(pixels.astype(float) - background, axis=1)
        ink = pixels[distance >= max(1, np.percentile(distance, 80))]
        if not len(ink):
            ink = pixels
        color = np.median(ink, axis=0).astype(int)
        line['color'] = '#%02x%02x%02x' % tuple(color)
