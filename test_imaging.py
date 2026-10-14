import io
import copy
import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from background_service import estimate_colors, repair_background, text_mask
from typography_service import estimate_typography, candidates
from ocr_service import OCRService, OCRUnavailable


def sample(kind='plain', font_name='arial.ttf'):
    y, x = np.indices((180, 500))
    if kind == 'plain':
        rgb = np.full((180, 500, 3), 235, np.uint8)
    elif kind == 'gradient':
        rgb = np.stack([170+x*.1+y*.1, 200+x*.08, 230-y*.1+x*.03], axis=2).astype(np.uint8)
    elif kind == 'texture':
        rgb = np.repeat((210+15*np.sin(x*.2)+10*np.cos(y*.3))[:,:,None], 3, axis=2).astype(np.uint8)
    else:
        rgb = np.stack([100+70*np.sin(x*.035), 150+70*np.cos(y*.06), 150+70*np.sin((x+y)*.05)], axis=2).astype(np.uint8)
    clean = Image.fromarray(rgb)
    # Design detail immediately outside the OCR polygon must survive exactly.
    ImageDraw.Draw(clean).line((45,60,450,60), fill='#ff00ff', width=3)
    image = clean.copy()
    font_path = Path('C:/Windows/Fonts') / font_name
    if not font_path.exists():
        pytest.skip('Windows fixture font unavailable')
    font = ImageFont.truetype(str(font_path), 48)
    box = ImageDraw.Draw(image).textbbox((60,65), 'SUMMER SALE', font=font)
    ImageDraw.Draw(image).text((60,65), 'SUMMER SALE', font=font, fill='black')
    x0,y0,x1,y1 = box
    lines = [dict(text='SUMMER SALE', polygon=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]], color='#000000')]
    return np.array(clean), np.array(image), lines


@pytest.mark.parametrize('kind', ['plain','gradient','texture','complex'])
def test_masks_preserve_artwork(kind):
    clean, rgb, lines = sample(kind)
    out = io.BytesIO()
    mask = repair_background(rgb, lines, out)
    repaired = np.array(Image.open(out))
    assert np.array_equal(repaired[mask == 0], rgb[mask == 0])
    assert np.array_equal(repaired[59:62], clean[59:62])
    changed = np.any(rgb != clean, axis=2)
    assert (mask[changed] > 0).mean() > .98
    assert np.abs(repaired.astype(float)-clean).mean() < np.abs(rgb.astype(float)-clean).mean()
    if kind in ('plain','gradient'):
        assert np.abs(repaired.astype(float)-clean).mean() < 1


@pytest.mark.parametrize('name,family,weight', [('arial.ttf','Arial','normal'), ('arialbd.ttf','Arial','bold'), ('georgia.ttf','Georgia','normal')])
def test_local_font_estimation(name, family, weight):
    if not candidates():
        pytest.skip('Local comparison fonts unavailable')
    _, rgb, lines = sample(font_name=name)
    estimate_colors(rgb, lines)
    estimate_typography(rgb, lines)
    typography = lines[0]['typography']
    json.dumps(typography, allow_nan=False)
    assert typography['font_family'] == family
    assert typography['font_weight'] == weight
    # Visible glyph height is not the nominal em size; allow 10% for hinting
    # and antialias thresholds. Exported ink positions are tested in browsers.
    assert abs(typography['font_size'] - 48) <= 4.8


def test_unsupported_language_has_clear_error():
    with pytest.raises(OCRUnavailable, match='Unsupported OCR_LANG'):
        OCRService('not-a-language').extract(np.zeros((20,20,3), np.uint8))


def test_white_glyphs_and_rotated_polygon(tmp_path):
    import cv2
    rgb = np.full((100,160,3), 30, np.uint8)
    polygon = np.array([[40,20],[100,50],[90,70],[30,40]], np.int32)
    ink = np.array([[45,28],[85,48],[80,58],[40,38]], np.int32)
    cv2.fillPoly(rgb, [ink], (255,255,255))
    lines = [dict(polygon=polygon.tolist(), color='#ffffff')]
    mask = repair_background(rgb, lines, tmp_path/'clean.png')
    result = np.array(Image.open(tmp_path/'clean.png'))
    assert result.max() <= 31
    assert mask[20,100] == 0  # Inside axis-aligned rectangle, outside rotated polygon.
    assert np.array_equal(result[mask==0], rgb[mask==0])
