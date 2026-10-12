
from pathlib import Path
import uuid
import os
from io import BytesIO

import numpy as np

from flask import Flask, jsonify, render_template, request, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

from layer_utils import validate_layers, ocr_results_to_layers
from ai_edit_service import apply_command, CommandError
from ocr_service import ocr_service, OCRUnavailable, OCRProcessingError
from background_service import repair_background, estimate_colors


app = Flask(__name__)

# Maximum upload size: 20 MB plus a small allowance.
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024 + 64 * 1024

app.config["OCR_CONFIDENCE_THRESHOLD"] = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "0.5"))
PROCESSED_DIR = Path(app.static_folder) / "processed"

UPLOAD_DIR = Path(app.static_folder) / "uploads"

ALLOWED_FORMATS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}

MAX_IMAGE_SIDE = 12000
MAX_IMAGE_PIXELS = 50_000_000


@app.get("/")
def index():
    """Display the poster editor."""
    return render_template("index.html")


@app.post("/api/extract-text")
def extract_text():
    """Validate, recognize, remove text, and return editable layers."""
    uploaded_file = request.files.get("image")
    if uploaded_file is None or not uploaded_file.filename:
        return jsonify(error="Please upload a poster image."), 400
    payload = uploaded_file.stream.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        return jsonify(error="The uploaded image exceeds the 20 MB limit."), 413
    try:
        with Image.open(BytesIO(payload)) as image:
            image_format = image.format
            width, height = image.size
            if image_format not in ALLOWED_FORMATS:
                return jsonify(error="Unsupported image format. Use JPEG, PNG, or WEBP."), 400
            if max(width, height) > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
                return jsonify(error="Use an image up to 12,000 pixels per side and 50 megapixels."), 400
            image.verify()
        with Image.open(BytesIO(payload)) as image:
            image = ImageOps.exif_transpose(image)
            # Composite transparent posters onto white, matching the editor canvas.
            rgba = image.convert("RGBA")
            base = Image.new("RGBA", rgba.size, "white")
            base.alpha_composite(rgba)
            rgb = np.array(base.convert("RGB"))
            width, height = base.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return jsonify(error="The uploaded file is not a valid, readable image."), 400

    project_id = uuid.uuid4().hex
    try:
        original_dir = UPLOAD_DIR / project_id
        original_dir.mkdir(parents=True, exist_ok=True)
        (original_dir / ("original" + ALLOWED_FORMATS[image_format])).write_bytes(payload)
        lines = ocr_service.extract(rgb[:, :, ::-1].copy(), app.config["OCR_CONFIDENCE_THRESHOLD"])
        if len(lines) > 500:
            return jsonify(error="More than 500 text regions were detected. Please crop the poster and retry."), 422
        estimate_colors(rgb, lines)
        layers = ocr_results_to_layers(lines, width, height)
        destination = PROCESSED_DIR / project_id / "cleaned.png"
        repair_background(rgb, lines, destination)
    except OCRUnavailable as exc:
        app.logger.exception("OCR initialization failed")
        return jsonify(error=str(exc)), 503
    except OCRProcessingError as exc:
        app.logger.exception("OCR inference failed")
        return jsonify(error=str(exc)), 500
    except Exception:
        app.logger.exception("Poster processing failed")
        return jsonify(error="Poster processing or background repair failed. See the server log for details."), 500
    return jsonify(project_id=project_id, width=width, height=height,
        background_url=url_for("static", filename=f"processed/{project_id}/cleaned.png"),
        layers=layers, warnings=[] if layers else [
            "No text met the OCR confidence threshold. You can add your own text."])


@app.post("/api/edit-text")
def edit_text():
    """
    Validate a text-editing request.

    Actual AI prompt interpretation and text editing
    will be connected later.
    """

    data = request.get_json(silent=True)

    # Ensure the request contains a JSON object.
    if not isinstance(data, dict):
        return jsonify(
            error="A JSON request body is required."
        ), 400

    project_id = data.get("project_id")
    prompt = data.get("prompt")
    layers = data.get("layers")
    selected_layer_id = data.get("selected_layer_id")

    # Validate the project ID.
    if not isinstance(project_id, str) or not project_id.strip():
        return jsonify(
            error="A valid project_id is required."
        ), 400

    # Validate the editing prompt.
    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify(
            error="Please enter an editing prompt."
        ), 400

    if len(prompt) > 2000:
        return jsonify(
            error="Prompt cannot exceed 2000 characters."
        ), 400

    # Validate the layers collection.
    if not isinstance(layers, list):
        return jsonify(
            error="Layers must be a list."
        ), 400

    valid, message = validate_layers(layers)

    if not valid:
        return jsonify(error=message), 400

    # If a layer was selected, ensure it exists in the request.
    if selected_layer_id is not None:
        if not isinstance(selected_layer_id, str):
            return jsonify(
                error="Invalid selected layer ID."
            ), 400

        if not any(
            layer["id"] == selected_layer_id
            for layer in layers
        ):
            return jsonify(
                error="Selected layer was not found."
            ), 400

    try:
        edited_layers, explanation = apply_command(prompt, layers, selected_layer_id)
    except CommandError as exc:
        return jsonify(error=str(exc)), 422

    valid, message = validate_layers(edited_layers)
    if not valid:
        return jsonify(error=message), 422
    return jsonify(project_id=project_id, layers=edited_layers, message=explanation), 200


@app.errorhandler(413)
def too_large(_error):
    """Return a readable error when an upload exceeds the limit."""
    return jsonify(
        error="The uploaded image exceeds the 20 MB limit."
    ), 413


if __name__ == "__main__":
    app.run(debug=True)