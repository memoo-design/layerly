"""Opt-in real Latin-model smoke checks; uses one mobile recognizer and cached detector."""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from ocr_service import OCRService


def main():
    root = Path('verification')
    root.mkdir(exist_ok=True)
    service = OCRService('fr')
    results = []
    for language, text in [('French', 'Bonjour été café'), ('Spanish', 'Oferta mañana café'), ('German', 'Grüße schöne Welt')]:
        image = Image.new('RGB', (1000, 180), 'white')
        ImageDraw.Draw(image).text((35, 40), text, fill='black', font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 56))
        image.save(root / f'ocr-{language.lower()}.png')
        lines = service.extract(np.array(image)[:,:,::-1].copy())
        actual = ' '.join(line['text'] for line in lines)
        record = dict(language=language, expected=text, actual=actual, exact=actual == text,
                      confidence=[line['confidence'] for line in lines])
        results.append(record)
        print(json.dumps(record, ensure_ascii=True), flush=True)
    (root / 'multilingual.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    assert all(result['exact'] for result in results), 'Some samples did not match exactly; see multilingual.json'


if __name__ == '__main__':
    main()
