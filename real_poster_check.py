"""Evaluate a supplied local poster without copying it to public storage."""
import argparse
import json
import hashlib
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from background_service import estimate_colors, repair_background
from ocr_service import OCRService


def main(path):
    root = Path('verification')
    root.mkdir(exist_ok=True)
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
    rgb = np.array(image)
    digest = hashlib.sha256(rgb.tobytes()).hexdigest()
    cache = root/'real-poster-ocr.json'
    saved = json.loads(cache.read_text()) if cache.exists() else {}
    lines = saved['lines'] if saved.get('digest') == digest else OCRService().extract(rgb[:,:,::-1].copy())
    cache.write_text(json.dumps(dict(digest=digest, lines=lines), indent=2))
    estimate_colors(rgb, lines)
    mask = repair_background(rgb, lines, root/'real-poster-restored.png')
    Image.fromarray(mask).save(root/'real-poster-mask.png')
    with Image.open(root/'real-poster-restored.png') as restored:
        assert restored.size == image.size
        assert np.array_equal(np.array(restored)[mask==0], rgb[mask==0])
        comparison = Image.new('RGB', (image.width*2,image.height))
        comparison.paste(image,(0,0))
        comparison.paste(restored,(image.width,0))
        comparison.save(root/'real-poster-comparison.png')
    result = dict(regions=len(lines), dimensions=image.size, unchanged_outside_mask=True,
                  masked_fraction=float((mask>0).mean()), methods=[l['restoration_method'] for l in lines])
    (root/'real-poster-result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    main(parser.parse_args().path)
