"""Deterministic, offline natural-language commands for Layerly text layers."""
import copy
import re

COLORS = {
    'red':'#ff0000','blue':'#0000ff','green':'#008000','black':'#000000',
    'white':'#ffffff','yellow':'#ffff00','orange':'#ffa500','purple':'#800080',
    'pink':'#ffc0cb','gray':'#808080','grey':'#808080','gold':'#ffd700',
    'navy':'#000080','cyan':'#00ffff','magenta':'#ff00ff',
}

class CommandError(ValueError):
    pass

def _target(layers, selected_id, prompt):
    if re.search(r'\b(all|every)\s+(?:the\s+)?text\b', prompt, re.I):
        return layers
    if selected_id:
        return [layer for layer in layers if layer['id'] == selected_id]
    m = re.search(r'\b(?:heading|headline|title)\b', prompt, re.I)
    if m:
        # Avoid silently editing the wrong text if no explicit selection exists.
        raise CommandError('Select the heading or title layer first.')
    if len(layers) == 1:
        return layers
    raise CommandError('Select a text layer first, or say "all text".')

def apply_command(prompt, layers, selected_layer_id=None, canvas_width=None):
    """Return (updated_layers, explanation). Does not mutate input."""
    updated = copy.deepcopy(layers)
    target = _target(updated, selected_layer_id, prompt)
    if not target:
        raise CommandError('There are no text layers to edit.')
    p = prompt.strip()
    color_match = re.search(r'(?:#(?:[0-9a-f]{6})\b|\b(?:'+'|'.join(COLORS)+r')\b)', p, re.I)
    if color_match and re.search(r'\b(colou?r|make|turn|set)\b', p, re.I):
        raw = color_match.group().lower()
        color = COLORS.get(raw, raw)
        for layer in target: layer['color'] = color
        return updated, f'Changed {len(target)} text layer(s) to {color}.'
    replace = re.search(r'\b(?:replace|change)\s+["“\'](.+?)["”\']\s+(?:with|to)\s+["“\'](.+?)["”\']\s*$', p, re.I)
    if replace:
        before, after = replace.groups()
        hits = 0
        for layer in target:
            if before in layer['text']:
                layer['text'] = layer['text'].replace(before, after)
                hits += 1
        if not hits: raise CommandError('The text to replace was not found in the target layer(s).')
        return updated, f'Replaced text in {hits} layer(s).'
    set_text = re.search(r'\b(?:set|change|update)\s+(?:the\s+)?(?:selected\s+)?text\s+to\s+["“\'](.+?)["”\']\s*$', p, re.I)
    if set_text:
        for layer in target: layer['text'] = set_text.group(1)
        return updated, f'Updated {len(target)} text layer(s).'
    size = re.search(r'\b(?:font\s+size|size)\s+(?:to\s+)?(\d{1,4})\b', p, re.I)
    if size:
        n = int(size.group(1))
        if not 1 <= n <= 2000: raise CommandError('Font size must be between 1 and 2000.')
        for layer in target: layer['font_size'] = n
        return updated, f'Set font size to {n}.'
    if re.search(r'\b(bigger|larger|increase|smaller|decrease)\b', p, re.I):
        grow = bool(re.search(r'\b(bigger|larger|increase)\b', p, re.I))
        for layer in target:
            old = layer['font_size']
            layer['font_size'] = min(2000, max(1, round(old * (1.2 if grow else 0.8))))
        return updated, f'{"Increased" if grow else "Decreased"} font size.'
    rotation = re.search(r'\brotate\b.*?(-?\d+(?:\.\d+)?)\s*(?:degrees?|°)?\b', p, re.I)
    if rotation:
        angle = float(rotation.group(1))
        if abs(angle) > 360: raise CommandError('Rotation must be between -360 and 360 degrees.')
        for layer in target: layer['rotation'] = angle
        return updated, f'Rotated {len(target)} layer(s) to {angle:g} degrees.'
    alignment = re.search(r'\b(?:align|alignment|center|centre)\b.*?\b(left|right|center|centre)\b|\b(center|centre)\s+(?:the\s+)?(?:selected\s+)?text\b', p, re.I)
    if alignment:
        align = next((x for x in alignment.groups() if x), 'center').lower().replace('centre','center')
        for layer in target: layer['text_align'] = align
        return updated, f'Aligned {len(target)} text layer(s) {align}.'
    if re.search(r'\b(bold|italic)\b', p, re.I):
        bold = bool(re.search(r'\bbold\b', p, re.I))
        italic = bool(re.search(r'\bitalic\b', p, re.I))
        for layer in target:
            if bold: layer['font_weight'] = 'bold'
            if italic: layer['font_style'] = 'italic'
        return updated, 'Updated text styling.'
    raise CommandError('Unsupported command. Try changing color, size, text, alignment, rotation, bold, or italic.')
