"""Reproducible visual comparisons: known clean image, input, mask, old/new repair."""
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw
from background_service import repair_background
from test_imaging import sample


def main():
    root = Path('verification')
    root.mkdir(exist_ok=True)
    results = []
    rows = []
    for kind in ('plain','gradient','texture','complex'):
        clean, rgb, lines = sample(kind)
        old_mask = np.zeros(rgb.shape[:2], np.uint8)
        cv2.fillPoly(old_mask, [np.array(lines[0]['polygon'], np.int32)], 255)
        old_mask = cv2.dilate(old_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5)))
        old = cv2.inpaint(rgb, old_mask, 3, cv2.INPAINT_TELEA)
        mask = repair_background(rgb, lines, root / f'{kind}-restored.png')
        new = np.array(Image.open(root / f'{kind}-restored.png'))
        Image.fromarray(rgb).save(root / f'{kind}-input.png')
        Image.fromarray(clean).save(root / f'{kind}-reference.png')
        Image.fromarray(mask).save(root / f'{kind}-mask.png')
        scope = old_mask > 0
        results.append(dict(kind=kind, method=lines[0]['restoration_method'],
            old_mask_pixels=int(scope.sum()), new_mask_pixels=int((mask>0).sum()),
            old_mae=float(np.abs(old.astype(float)-clean)[scope].mean()),
            new_mae=float(np.abs(new.astype(float)-clean)[scope].mean())))
        row = Image.new('RGB', (2500, 210), 'white')
        for i, (label, pixels) in enumerate([('Reference',clean),('Poster',rgb),('Mask',np.repeat(mask[:,:,None],3,axis=2)),('Old polygon repair',old),('New repair',new)]):
            row.paste(Image.fromarray(pixels), (500*i,30))
            ImageDraw.Draw(row).text((500*i+8,8), f'{kind}: {label}', fill='black')
        rows.append(row)
    contact = Image.new('RGB', (2500,840), 'white')
    for i,row in enumerate(rows):
        contact.paste(row,(0,210*i))
    contact.save(root / 'restoration-comparison.png')
    (root / 'restoration-metrics.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
