
from pathlib import Path
import os
import threading
import time
import logging
import re
from io import BytesIO

import numpy as np

from flask import Flask, jsonify, render_template, request, url_for, send_file, abort
from PIL import Image, ImageOps, UnidentifiedImageError

from layer_utils import ocr_results_to_layers, normalize_edit_layers
from ai_edit_service import apply_command, layer_changes, CommandError
from ocr_service import ocr_service, OCRUnavailable, OCRProcessingError
from background_service import repair_background, estimate_colors
from project_store import ProjectStore
from typography_service import estimate_typography


app = Flask(__name__)


class RedactProjectTokens(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'token=[^\s&"\x1b]+', 'token=[redacted]', record.getMessage())
        record.args = ()
        return True


logging.getLogger('werkzeug').addFilter(RedactProjectTokens())


@app.cli.command('cleanup-projects')
def cleanup_projects():
    """Remove only expired, registered temporary backgrounds."""
    print(f'Removed {project_store.cleanup()} expired projects.')

# Maximum upload size: 20 MB plus a small allowance.
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024 + 64 * 1024

app.config["OCR_CONFIDENCE_THRESHOLD"] = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "0.5"))
project_store = ProjectStore(os.getenv('LAYERLY_STORAGE_DIR', str(Path(app.instance_path) / 'projects')),
                             os.getenv('LAYERLY_RETENTION_SECONDS', '86400'))
_cleanup_started = False
_cleanup_lock = threading.Lock()


@app.before_request
def maintain_storage():
    global _cleanup_started
    # Old public artifacts are not migrated or deleted without ownership records.
    if request.path.startswith(('/static/uploads/', '/static/processed/')):
        abort(404)
    with _cleanup_lock:
        if not _cleanup_started:
            project_store.cleanup()
            def sweep():
                while True:
                    time.sleep(60)
                    try:
                        project_store.cleanup()
                    except Exception:
                        app.logger.exception('Temporary project cleanup failed')
            threading.Thread(target=sweep, daemon=True, name='layerly-cleanup').start()
            _cleanup_started = True


@app.route('/api/projects/<project_id>/background', methods=['GET', 'POST'])
def project_background(project_id):
    try:
        data = project_store.access(project_id, request.args.get('token', ''), read=request.method == 'GET')
    except (FileNotFoundError, ValueError):
        return jsonify(error='This project expired or access was denied. Upload the poster again.'), 404
    response = (send_file(BytesIO(data), mimetype='image/png') if request.method == 'GET'
                else jsonify(retention_seconds=project_store.retention))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

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

    try:
        lines = ocr_service.extract(rgb[:, :, ::-1].copy(), app.config["OCR_CONFIDENCE_THRESHOLD"])
        if len(lines) > 500:
            return jsonify(error="More than 500 text regions were detected. Please crop the poster and retry."), 422
        estimate_colors(rgb, lines)
        estimate_typography(rgb, lines)
        layers = ocr_results_to_layers(lines, width, height)
        destination = BytesIO()
        repair_background(rgb, lines, destination)
        # Originals are not needed after extraction and never reach disk.
        project_id, token = project_store.create(destination.getvalue())
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
        background_url=url_for("project_background", project_id=project_id, token=token),
        layers=layers, warnings=[] if layers else [
            "No text met the OCR confidence threshold. You can add your own text."])


@app.post("/api/edit-text")
def edit_text():
    """Validate edit snapshots and return atomic property patches for existing layers."""

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

    try:
        layers = normalize_edit_layers(layers)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

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
        edited_layers, explanation = apply_command(prompt, layers, selected_layer_id, canvas_width=data.get("width"))
    except CommandError as exc:
        return jsonify(error=str(exc)), 422

    try:
        edited_layers = normalize_edit_layers(edited_layers)
    except ValueError as exc:
        return jsonify(error=str(exc)), 422
    changes = layer_changes(layers, edited_layers)
    return jsonify(project_id=project_id, changes=changes, layers=edited_layers,
                   message=explanation if changes else "No changes needed."), 200


@app.errorhandler(413)
def too_large(_error):
    """Return a readable error when an upload exceeds the limit."""
    return jsonify(
        error="The uploaded image exceeds the 20 MB limit."
    ), 413


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
