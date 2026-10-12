
import math
import re
import uuid
import copy
from numbers import Real, Integral


def _number(value):
    """Return True for finite numbers, excluding booleans."""
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _get_box(line):
    """
    Accept either:
    bbox = {"x": 10, "y": 20, "width": 100, "height": 30}

    or a polygon:
    bbox = [{"x": 10, "y": 20}, ...]
    """
    bbox = line.get("bbox")

    if isinstance(bbox, dict):
        keys = ("x", "y", "width", "height")
        if not all(_number(bbox.get(k)) for k in keys):
            raise ValueError("Invalid bounding box coordinates.")

        x, y, width, height = (float(bbox[k]) for k in keys)

    elif isinstance(bbox, list) and len(bbox) >= 4:
        if not all(
            isinstance(p, dict)
            and _number(p.get("x"))
            and _number(p.get("y"))
            for p in bbox
        ):
            raise ValueError("Invalid bounding polygon.")

        xs = [float(p["x"]) for p in bbox]
        ys = [float(p["y"]) for p in bbox]

        x = min(xs)
        y = min(ys)
        width = max(xs) - x
        height = max(ys) - y

    else:
        raise ValueError("OCR result is missing a valid bbox.")

    if (
        not all(math.isfinite(v) for v in (x, y, width, height))
        or x < 0 or y < 0
        or width <= 0 or height <= 0
    ):
        raise ValueError("Invalid text position or dimensions.")

    return x, y, width, height


def ocr_results_to_layers(ocr_lines, image_width, image_height):
    """
    Convert generic OCR line results into the frontend's
    editable text-layer format.

    Each OCR line needs:
    {"text": "Example", "bbox": {...}, "confidence": 0.98}
    """
    if (
        not isinstance(image_width, int)
        or isinstance(image_width, bool)
        or image_width <= 0
        or not isinstance(image_height, int)
        or isinstance(image_height, bool)
        or image_height <= 0
    ):
        raise ValueError("Image dimensions must be positive integers.")

    if not isinstance(ocr_lines, list):
        raise ValueError("OCR results must be a list.")

    layers = []

    for line in ocr_lines:
        if not isinstance(line, dict):
            raise ValueError("Each OCR result must be an object.")

        text = line.get("text")
        if not isinstance(text, str) or not text.strip():
            continue

        x, y, width, height = _get_box(line)

        if x + width > image_width or y + height > image_height:
            raise ValueError("OCR bounding box exceeds image dimensions.")

        confidence = line.get("confidence", 0.0)
        if not _number(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1.")

        rotation = line.get("rotation", 0)
        if not _number(rotation):
            raise ValueError("Invalid text rotation.")
        if "oriented_box" in line:
            x, y, width, height = _get_box({"bbox": line["oriented_box"]})
        color = line.get("color", "#ffffff")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
            raise ValueError("Invalid text color.")
        layers.append({
            "id": uuid.uuid4().hex,
            "text": text.strip(),
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "rotation": rotation,
            "font_size": max(1, min(2000, round(height * 0.8))),
            "font_family": "Arial",
            "color": color,
            "confidence": float(confidence),
            "font_weight": "normal",
            "font_style": "normal",
            "text_align": "left",
        })

    return layers


def validate_layers(layers, require_confidence=True):
    """Validate layers against the frontend's expected fields."""
    if not isinstance(layers, list):
        return False, "Layers must be a list."

    seen_ids = set()
    required_numbers = (
        "x", "y", "width", "height",
        "rotation", "font_size",
    )

    for layer in layers:
        if not isinstance(layer, dict):
            return False, "Every layer must be an object."

        layer_id = layer.get("id")
        if not isinstance(layer_id, str) or not layer_id.strip():
            return False, "Every layer needs a string ID."

        if layer_id in seen_ids:
            return False, "Layer IDs must be unique."
        seen_ids.add(layer_id)

        if not isinstance(layer.get("text"), str):
            return False, "Layer text must be a string."

        for field in required_numbers:
            if not _number(layer.get(field)):
                return False, f"Invalid numeric field: {field}."

        if layer["width"] <= 0 or layer["height"] <= 0:
            return False, "Layer width and height must be positive."

        if not 0 < layer["font_size"] <= 2000:
            return False, "Font size must be between 1 and 2000."

        confidence = layer.get("confidence")
        if confidence is not None or require_confidence:
            if not _number(confidence):
                return False, "Confidence must be a finite number between 0 and 1, or omitted during editing."
            if not 0 <= confidence <= 1:
                return False, "Confidence must be between 0 and 1."
        for key in ("scale_x", "scale_y"):
            if key in layer and (not _number(layer[key]) or layer[key] <= 0):
                return False, f"{key} must be a positive finite number."
        if "bounds" in layer:
            bounds = layer["bounds"]
            if (not isinstance(bounds, dict) or not _number(bounds.get("left"))
                    or not _number(bounds.get("width")) or bounds["width"] <= 0):
                return False, "Layer bounds must contain finite left and positive width values."
        if len(layer["text"]) > 10000:
            return False, "Layer text cannot exceed 10,000 characters."

        if not isinstance(layer.get("font_family"), str) or not layer["font_family"].strip():
            return False, "Font family is required."

        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(layer.get("color", ""))):
            return False, "Color must be a six-digit hex value."

    return True, "All layers are valid."

def normalize_edit_layers(layers):
    """Copy edit snapshots; OCR confidence is optional, never fabricated."""
    valid, message = validate_layers(layers, require_confidence=False)
    if not valid:
        raise ValueError(message)
    if len(layers) > 500:
        raise ValueError("At most 500 text layers can be edited at once.")

    def native(value):
        if isinstance(value, Real) and not isinstance(value, bool):
            if not math.isfinite(value):
                raise ValueError("Layer metadata must not contain NaN or infinity.")
            return int(value) if isinstance(value, Integral) else float(value)
        if isinstance(value, dict):
            return {key: native(item) for key, item in value.items()}
        if isinstance(value, list):
            return [native(item) for item in value]
        return value

    return native(copy.deepcopy(layers))
