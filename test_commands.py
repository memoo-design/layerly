import copy
import json
import unittest
from unittest.mock import patch
import numpy as np
from app import app
from ai_edit_service import apply_command, CommandError
from layer_utils import normalize_edit_layers, ocr_results_to_layers


def sample():
    return [dict(id='ocr-heading', text='SUMMER SALE', x=30, y=40, width=300, height=60,
                 rotation=0, font_size=48, font_family='Arial', color='#000000',
                 font_weight='normal', font_style='normal', scale_x=1.2, scale_y=1,
                 text_align='left', visible=True, confidence=.97),
            dict(id='body', text='Open today', x=20, y=150, width=180, height=30,
                 rotation=0, font_size=20, font_family='Arial', color='#123456',
                 font_weight='normal', font_style='normal', text_align='left', visible=True)]


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.layers = sample()

    def post(self, prompt='Blue text', selected='ocr-heading', layers=None, **kwargs):
        return self.client.post('/api/edit-text', json=dict(project_id='p', prompt=prompt,
            selected_layer_id=selected, layers=self.layers if layers is None else layers,
            width=800, **kwargs))

    def test_optional_confidence(self):
        for value in ('missing', None, .83, 0, 1):
            with self.subTest(value=value):
                layer = copy.deepcopy(self.layers[0])
                if value == 'missing':
                    layer.pop('confidence')
                else:
                    layer['confidence'] = value
                result = self.post(layers=[layer])
                self.assertEqual(result.status_code, 200, result.json)
                self.assertEqual(result.json['layers'][0].get('confidence'), layer.get('confidence'))
                self.assertNotIn('confidence', result.json['changes'][0]['properties'])

    def test_numpy_confidence(self):
        for number in (np.float32(.8), np.float64(.9), np.int64(1)):
            self.layers[0]['confidence'] = number
            normalized = normalize_edit_layers(self.layers)
            self.assertIs(type(normalized[0]['confidence']), float)
            json.dumps(normalized, allow_nan=False)
        with patch('app.apply_command', return_value=(self.layers, 'Normalized')):
            response = self.post(layers=sample())
            self.assertEqual(response.status_code, 200)
            json.loads(response.data, parse_constant=lambda value: self.fail(value))
        line = dict(text='SALE', confidence=np.float32(.8), bbox=dict(x=1,y=1,width=40,height=10))
        self.assertIsInstance(ocr_results_to_layers([line], 100, 100)[0]['confidence'], float)

    def test_invalid_confidence(self):
        for value in ('0.8', 'invalid', True, float('nan'), float('inf'), -float('inf'), -.1, 1.1):
            with self.subTest(value=value):
                self.layers[0]['confidence'] = value
                response = self.post()
                self.assertEqual(response.status_code, 400)
                self.assertIn('Confidence', response.json['error'])

    def test_required_numeric_validation_retained(self):
        for key in ('x', 'y', 'font_size', 'rotation', 'width'):
            layers = sample()
            layers[0][key] = None
            self.assertEqual(self.post(layers=layers).status_code, 400)

    def test_requested_commands(self):
        cases = [('Blue text', 'color', '#0000ff'), ('Bold heading', 'font_weight', 'bold'),
                 ('Change title color to red', 'color', '#ff0000'),
                 ('Make heading bigger', 'font_size', 57.6),
                 ('Change SALE to MEGA SALE', 'text', 'SUMMER MEGA SALE'),
                 ('Rotate selected text 15 degrees', 'rotation', 15),
                 ('CHANGE THE TITLE COLOUR TO RED!', 'color', '#ff0000')]
        for prompt, key, value in cases:
            with self.subTest(prompt=prompt):
                result = self.post(prompt)
                self.assertEqual(result.status_code, 200, result.json)
                self.assertEqual(result.json['changes'], [{'id':'ocr-heading', 'properties':{key:value}}])
                self.assertEqual(result.json['layers'][1], self.layers[1])

    def test_all_layers(self):
        for prompt in ('All text white', 'Change every text color to white', 'Each text layer white'):
            result = self.post(prompt, selected=None)
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(len(result.json['changes']), 2)
            self.assertTrue(all(layer['color'] == '#ffffff' for layer in result.json['layers']))

    def test_center_scaled_rotated_bounds(self):
        self.layers[0].update(rotation=15, bounds={'left':10, 'width':360})
        result = self.post('Center selected text')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['changes'][0]['properties'], {'x':240})
        self.assertEqual(result.json['layers'][0]['y'], 40)

    def test_heading_target_overrides_unrelated_selection(self):
        result = self.post('Bold heading', selected='body')
        self.assertEqual(result.json['changes'][0]['id'], 'ocr-heading')

    def test_heading_ambiguity(self):
        self.layers[1]['font_size'] = 48
        result = self.post('Bold heading', selected=None)
        self.assertEqual(result.status_code, 422)
        self.assertIn('ambiguous', result.json['error'])

    def test_missing_selection(self):
        for command in ('Blue text', 'Center selected text', 'Rotate selected text 15 degrees'):
            self.assertEqual(self.post(command, selected=None).status_code, 422)

    def test_explicit_named_heading(self):
        self.layers[1]['role'] = 'title'
        result = self.post('Bold heading', selected=None)
        self.assertEqual(result.json['changes'][0]['id'], 'body')

    def test_content_target_and_ambiguity(self):
        result = self.post('Change SALE to MEGA SALE', selected=None)
        self.assertEqual(result.status_code, 200)
        self.layers[1]['text'] = 'sale'
        result = self.post('Change SALE to MEGA SALE', selected=None)
        self.assertEqual(result.status_code, 422)
        result = self.post('Change SALE to MEGA SALE', selected='body')
        self.assertEqual(result.json['changes'][0]['id'], 'body')

    def test_replacement_literal(self):
        result = self.post('Change SALE to all text blue', selected=None)
        self.assertEqual(result.json['changes'], [{'id':'ocr-heading', 'properties':{'text':'SUMMER all text blue'}}])

    def test_failed_command_does_not_mutate(self):
        original = copy.deepcopy(self.layers)
        for command in ('Delete all graphics', 'Blue text and delete background', 'Rotate selected text 999 degrees'):
            with self.assertRaises(CommandError):
                apply_command(command, self.layers, 'ocr-heading')
            self.assertEqual(self.layers, original)
            response = self.post(command)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('changes', response.json)

    def test_preserves_metadata_and_geometry(self):
        self.layers[0]['metadata'] = {'source':'ocr'}
        original = copy.deepcopy(self.layers)
        result = self.post('Blue text')
        after = result.json['layers'][0]
        for key, value in original[0].items():
            if key != 'color':
                self.assertEqual(after[key], value, key)
        self.assertEqual(self.layers, original)
        self.assertEqual(result.json['project_id'], 'p')
        self.assertTrue(result.is_json)

    def test_unknown_id_and_noop(self):
        self.assertEqual(self.post(selected='missing').status_code, 400)
        result = self.post('Black text')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['changes'], [])
        self.assertEqual(result.json['message'], 'No changes needed.')


if __name__ == '__main__':
    unittest.main()
