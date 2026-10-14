"""Regressions found during the complete project audit."""
import copy
import pytest
from app import app
from ai_edit_service import apply_command, layer_changes, CommandError
from test_commands import sample


@pytest.mark.parametrize('prompt,key,value', [
    ('Increase the title font size.', 'font_size', 57.6),
    ('Decrease the title font size.', 'font_size', 38.4),
    ("Change the subtitle to 'Welcome to Layerly'.", 'text', 'Welcome to Layerly'),
])
def test_requested_wording(prompt, key, value):
    layers = sample()
    selected = 'body' if 'subtitle' in prompt else 'ocr-heading'
    result = app.test_client().post('/api/edit-text', json=dict(
        project_id='test', prompt=prompt, layers=layers, selected_layer_id=selected))
    assert result.status_code == 200, result.json
    assert result.json['changes'] == [{'id': selected, 'properties': {key: value}}]


def test_deletion_patch_does_not_shift_other_layer_ids():
    layers = sample()
    before = copy.deepcopy(layers)
    updated, _ = apply_command('Remove the bottom text.', layers)
    assert updated == layers[:1]
    assert layer_changes(layers, updated) == [{'id': 'body', 'delete': True}]
    updated, _ = apply_command('Delete selected text', layers, 'ocr-heading')
    assert updated == layers[1:]
    assert layer_changes(layers, updated) == [{'id': 'ocr-heading', 'delete': True}]
    assert layers == before


def test_ambiguous_subtitle_and_bottom_rejected():
    layers = sample()
    with pytest.raises(CommandError, match='subtitle'):
        apply_command("Change the subtitle to 'Welcome'", layers)
    layers[1]['y'] = layers[0]['y']
    with pytest.raises(CommandError, match='ambiguous'):
        apply_command('Remove bottom text', layers)
