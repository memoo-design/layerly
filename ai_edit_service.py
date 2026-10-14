"""Deterministic local text commands. Parse completely before mutating a copy."""
import copy
import math
import re

from layer_utils import _number

COLORS = {
    'red': '#ff0000', 'blue': '#0000ff', 'green': '#008000', 'black': '#000000',
    'white': '#ffffff', 'yellow': '#ffff00', 'orange': '#ffa500', 'purple': '#800080',
    'pink': '#ffc0cb', 'gray': '#808080', 'grey': '#808080', 'gold': '#ffd700',
    'navy': '#000080', 'cyan': '#00ffff', 'magenta': '#ff00ff',
}
EDITABLE_FIELDS = ('text', 'color', 'font_size', 'font_family', 'font_weight',
                   'font_style', 'text_align', 'x', 'y', 'rotation', 'visible')
SUBJECT = r"(?:the\s+)?(?:selected\s+text|(?:all|every|each)\s+(?:the\s+)?text(?:\s+layers?)?|all\s+layers|heading|headline|title|subtitle|bottom\s+text|text)"


class CommandError(ValueError):
    pass


def _target(layers, selected_id, subject):
    if re.search(r'\bsubtitle\b', subject, re.I):
        candidates = [l for l in layers if l.get('role') == 'subtitle' or l['id'] == 'subtitle']
        if len(candidates) == 1:
            return candidates
        selected = [l for l in layers if l['id'] == selected_id]
        if selected:
            return selected
        raise CommandError('Select the subtitle first; OCR does not identify semantic subtitles.')
    if re.search(r'\bbottom\s+text\b', subject, re.I):
        lowest = max((l['y'] for l in layers), default=None)
        candidates = [l for l in layers if l['y'] == lowest]
        if len(candidates) == 1:
            return candidates
        selected = [l for l in candidates if l['id'] == selected_id]
        if selected:
            return selected
        raise CommandError('The bottom text is ambiguous. Select the intended layer.')
    if re.search(r"\b(all|every|each)\b", subject, re.I):
        if not layers:
            raise CommandError('There are no text layers to edit.')
        return layers
    if re.search(r"\b(heading|headline|title)\b", subject, re.I):
        named = [layer for layer in layers if any(
            str(layer.get(key, '')).lower() in ('heading', 'headline', 'title')
            for key in ('id', 'role'))]
        candidates = named
        if not candidates and layers:
            # OCR has no semantic role: a unique largest displayed font is the heading.
            largest = max(layer['font_size'] * layer.get('scale_y', 1) for layer in layers)
            candidates = [layer for layer in layers if math.isclose(
                layer['font_size'] * layer.get('scale_y', 1), largest)]
        selected = [layer for layer in candidates if layer['id'] == selected_id]
        if len(candidates) == 1:
            return candidates
        if selected:
            return selected
        raise CommandError('The heading/title is ambiguous. Select the intended heading and retry.')
    selected = [layer for layer in layers if layer['id'] == selected_id]
    if not selected:
        raise CommandError('Select a text layer first, or say "all text".')
    return selected


def _unquote(text):
    text = text.strip()
    if len(text) >= 3 and text[-1] in '.!' and (text[0], text[-2]) in [('"', '"'), ("'", "'"), ('\u201c', '\u201d')]:
        text = text[:-1]
    if len(text) >= 2 and (text[0], text[-1]) in [('"', '"'), ("'", "'"), ('\u201c', '\u201d')]:
        return text[1:-1]
    return text


def apply_command(prompt, layers, selected_layer_id=None, canvas_width=None):
    """Return updated snapshots and feedback without changing input or OCR metadata."""
    updated = copy.deepcopy(layers)
    p = prompt.strip().rstrip('.!')
    subject, properties, action = None, {}, None
    removal = re.fullmatch(rf'(?:remove|delete)\s+({SUBJECT})', p, re.I)
    if removal:
        ids = {l['id'] for l in _target(updated, selected_layer_id, removal[1])}
        return [l for l in updated if l['id'] not in ids], f'Removed {len(ids)} text layer(s).'
    # Parse replacement before formatting: words inside replacement text are literal.
    replace = re.fullmatch(r'(?:replace|change|set|update)\s+(.+?)\s+(?:with|to)\s+(.+)', prompt.strip(), re.I)
    if replace and not re.search(r'\b(colou?rs?|(?:font\s+)?size)\b', replace[1], re.I):
        before, after = _unquote(replace[1]), _unquote(replace[2])
        if len(after) > 10000:
            raise CommandError('Text cannot exceed 10,000 characters.')
        if re.fullmatch(SUBJECT, before, re.I):
            target = _target(updated, selected_layer_id, before)
            for layer in target:
                layer['text'] = after
        else:
            if not before:
                raise CommandError('Specify the text to replace.')
            pattern = re.compile((r'(?<!\w)' if before[0].isalnum() else '') + re.escape(before)
                                 + (r'(?!\w)' if before[-1].isalnum() else ''), re.I)
            matches = [layer for layer in updated if pattern.search(layer['text'])]
            selected = [layer for layer in matches if layer['id'] == selected_layer_id]
            target = selected or matches
            if not target:
                raise CommandError('The text to replace was not found.')
            if len(target) != 1:
                raise CommandError('That text matches multiple layers. Select the intended layer and retry.')
            target[0]['text'] = pattern.sub(lambda _: after, target[0]['text'])
        return updated, f'Updated text in {len(target)} layer(s).'

    color = '(?:' + '|'.join(COLORS) + r'|#[0-9a-f]{6})'
    match = re.fullmatch(rf'(?:(?:change|set|make|turn)\s+)?({SUBJECT})(?:\s+colou?rs?)?\s+(?:to\s+)?({color})', p, re.I)
    reverse_color = re.fullmatch(rf'({color})\s+({SUBJECT})', p, re.I)
    if match or reverse_color:
        subject, value = (match[1], match[2]) if match else (reverse_color[2], reverse_color[1])
        properties['color'] = COLORS.get(value.lower(), value.lower())
    else:
        match = re.fullmatch(rf'(?:make\s+)?({SUBJECT})\s+(bold|italic)', p, re.I)
        reverse = re.fullmatch(rf'(bold|italic)\s+({SUBJECT})', p, re.I)
        if match or reverse:
            subject, style = (match[1], match[2]) if match else (reverse[2], reverse[1])
            properties['font_weight' if style.lower() == 'bold' else 'font_style'] = style.lower()
        else:
            match = re.fullmatch(rf'(?:make\s+)?({SUBJECT})\s+(bigger|larger|smaller)', p, re.I)
            increase = re.fullmatch(rf'(increase|decrease)\s+(?:the\s+)?(?:font\s+)?size\s+of\s+({SUBJECT})', p, re.I)
            direct_increase = re.fullmatch(rf'(increase|decrease)\s+({SUBJECT})\s+(?:font\s+)?size', p, re.I)
            increase = increase or direct_increase
            size = re.fullmatch(rf'(?:set|change|increase)\s+({SUBJECT})\s+(?:font\s+)?size\s+(?:to\s+)?(\d+(?:\.\d+)?)', p, re.I)
            rotation = re.fullmatch(rf'rotate\s+({SUBJECT})\s+(?:by\s+|to\s+)?(-?\d+(?:\.\d+)?)(?:\s*(?:degrees?|\u00b0))?', p, re.I)
            center = re.fullmatch(rf'(?:center|centre)\s+({SUBJECT})(?:\s+horizontally)?|move\s+({SUBJECT})\s+to\s+(?:the\s+)?cent(?:er|re)', p, re.I)
            align = re.fullmatch(rf'align\s+({SUBJECT})\s+(left|right|center|centre)', p, re.I)
            if match or increase:
                subject = match[1] if match else increase[2]
                action = 'grow' if (match and match[2].lower() != 'smaller') or (increase and increase[1].lower() == 'increase') else 'shrink'
            elif size:
                subject = size[1]
                value = float(size[2])
                if not 1 <= value <= 2000:
                    raise CommandError('Font size must be between 1 and 2000.')
                properties['font_size'] = value
            elif rotation:
                subject = rotation[1]
                value = float(rotation[2])
                if not -360 <= value <= 360:
                    raise CommandError('Rotation must be between -360 and 360 degrees.')
                properties['rotation'] = value
            elif center:
                subject, action = center[1] or center[2], 'center'
            elif align:
                subject = align[1]
                properties['text_align'] = align[2].lower().replace('centre', 'center')
            else:
                raise CommandError('Unsupported command. Try "Blue text", "Bold heading", "All text white", or "Change SALE to MEGA SALE".')

    target = _target(updated, selected_layer_id, subject)
    for layer in target:
        layer.update(properties)
        if action in ('grow', 'shrink'):
            layer['font_size'] = min(2000, max(1, round(layer['font_size'] * (1.2 if action == 'grow' else .8), 2)))
        elif action == 'center':
            if not _number(canvas_width) or canvas_width <= 0:
                raise CommandError('A positive canvas width is required to center text.')
            if 'bounds' in layer:
                bounds = layer['bounds']
                layer['x'] += canvas_width / 2 - bounds['left'] - bounds['width'] / 2
            else:
                angle = math.radians(layer['rotation'])
                dx = layer['width'] * layer.get('scale_x', 1) * math.cos(angle)
                dy = layer['height'] * layer.get('scale_y', 1) * math.sin(angle)
                layer['x'] = canvas_width / 2 - (dx - dy) / 2
    return updated, f'Updated {len(target)} text layer(s).'


def layer_changes(before, after):
    """Return only user-editable properties; OCR metadata and geometry are retained."""
    changes = []
    remaining = {layer['id']: layer for layer in after}
    for old in before:
        if old['id'] not in remaining:
            changes.append({'id': old['id'], 'delete': True})
            continue
        new = remaining[old['id']]
        properties = {key: new[key] for key in EDITABLE_FIELDS
                      if key in new and new[key] != old.get(key)}
        if properties:
            changes.append({'id': old['id'], 'properties': properties})
    return changes
