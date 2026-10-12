import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import numpy as np
from PIL import Image

import app as backend
from background_service import repair_background
from layer_utils import ocr_results_to_layers, validate_layers
from ocr_service import normalize_results, OCRService, OCRProcessingError, OCRUnavailable


def predictions(text='SALE', score=.98):
    return [{'rec_texts': [text], 'rec_scores': np.array([score]),
             'rec_polys': np.array([[[10, 10], [70, 10], [70, 30], [10, 30]]])}]


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in [('UPLOAD_DIR', self.root / 'uploads'),
                            ('PROCESSED_DIR', self.root / 'processed')]:
            patcher = patch.object(backend, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = backend.app.test_client()
        self.lines = normalize_results(predictions(), 100, 60)

    def upload(self, fmt='PNG'):
        stream = io.BytesIO()
        image = Image.new('RGB', (100, 60), 'white')
        image.paste('black', (12, 12, 68, 28))
        image.save(stream, fmt)
        stream.seek(0)
        return self.client.post('/api/extract-text', data={'image': (stream, '../../poster.png')})

    def test_success_contract_and_cleaning(self):
        with patch.object(backend.ocr_service, 'extract', return_value=self.lines):
            for fmt in ('PNG', 'JPEG'):
                response = self.upload(fmt)
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(set(data), {'project_id', 'width', 'height', 'background_url', 'layers', 'warnings'})
                self.assertEqual((data['width'], data['height']), (100, 60))
                self.assertTrue(validate_layers(data['layers'])[0])
                self.assertEqual(data['layers'][0]['text'], 'SALE')
                self.assertEqual(data['warnings'], [])
                cleaned = self.root / 'processed' / data['project_id'] / 'cleaned.png'
                with Image.open(cleaned) as image:
                    self.assertGreater(np.array(image)[20, 40].mean(), 240)
                self.assertEqual(len(list((self.root / 'uploads' / data['project_id']).iterdir())), 1)

    def test_coordinates_and_rotation(self):
        layer = ocr_results_to_layers(self.lines, 100, 60)[0]
        self.assertEqual([layer[k] for k in ('x', 'y', 'width', 'height')], [10, 10, 60, 20])
        result = predictions()
        result[0]['rec_polys'] = [[[20, 10], [50, 40], [40, 50], [10, 20]]]
        layer = ocr_results_to_layers(normalize_results(result, 100, 60), 100, 60)[0]
        self.assertAlmostEqual(layer['rotation'], 45)
        self.assertEqual((layer['x'], layer['y']), (20, 10))
        self.assertAlmostEqual(layer['width'], 30 * 2**.5)

    def test_legacy_and_filtering(self):
        result = predictions()[0]
        legacy = [[(result['rec_polys'][0], ('SALE', .98))]]
        self.assertEqual(normalize_results(legacy, 100, 60, modern=False), self.lines)
        for text, score in [('', .99), ('SALE', .1), ('SALE', float('nan'))]:
            self.assertEqual(normalize_results(predictions(text, score), 100, 60), [])
        with self.assertRaises(ValueError):
            normalize_results([{'dt_polys': []}], 100, 60)

    def test_empty(self):
        with patch.object(backend.ocr_service, 'extract', return_value=[]):
            data = self.upload().get_json()
        self.assertEqual(data['layers'], [])
        self.assertTrue(data['warnings'])
        self.assertTrue((self.root / 'processed' / data['project_id'] / 'cleaned.png').exists())

    def test_invalid(self):
        self.assertEqual(self.client.post('/api/extract-text').status_code, 400)
        response = self.client.post('/api/extract-text', data={'image': (io.BytesIO(b'broken'), 'a.png')})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.upload('GIF').status_code, 400)
        with patch.object(backend, 'MAX_IMAGE_SIDE', 50):
            self.assertEqual(self.upload().status_code, 400)
        with patch.dict(backend.app.config, MAX_CONTENT_LENGTH=20):
            self.assertEqual(self.upload().status_code, 413)

    def test_failures_never_succeed(self):
        for error, status in [(OCRUnavailable('Models unavailable'), 503),
                              (OCRProcessingError('OCR failed'), 500)]:
            with patch.object(backend.ocr_service, 'extract', side_effect=error):
                response = self.upload()
                self.assertEqual(response.status_code, status)
                self.assertIn('error', response.get_json())
        with patch.object(backend.ocr_service, 'extract', return_value=self.lines), \
             patch.object(backend, 'repair_background', side_effect=OSError('disk')):
            self.assertEqual(self.upload().status_code, 500)

    def test_mask_is_local(self):
        rgb = np.full((60, 100, 3), 255, np.uint8)
        rgb[12:28, 12:68] = 0
        mask = repair_background(rgb, self.lines, self.root / 'clean.png')
        self.assertEqual(mask[9, 10], 255)
        self.assertEqual(mask[0, 0], 0)
        with Image.open(self.root / 'clean.png') as image:
            self.assertTrue(np.array_equal(np.array(image)[0], rgb[0]))

    def test_model_reused_and_errors_wrapped(self):
        service = OCRService()
        service._model = Mock()
        service._model.predict.return_value = predictions()
        for _ in range(2):
            self.assertEqual(len(service.extract(np.zeros((60, 100, 3), np.uint8))), 1)
        self.assertEqual(service._model.predict.call_count, 2)
        service._model.predict.side_effect = RuntimeError('inference')
        with self.assertRaises(OCRProcessingError):
            service.extract(np.zeros((60, 100, 3), np.uint8))

    def test_home_unchanged(self):
        self.assertEqual(self.client.get('/').status_code, 200)


if __name__ == '__main__':
    unittest.main()
