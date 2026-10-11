
from pathlib import Path
import uuid

from flask import Flask, jsonify, render_template, request, url_for
from PIL import Image, UnidentifiedImageError

from layer_utils import validate_layers


app = Flask(__name__)

# Maximum upload size: 20 MB plus a small allowance.
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024 + 64 * 1024

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
    """
    Receive and validate a poster.

    OCR is not connected yet. The endpoint currently saves
    the image and returns its dimensions and background URL.
    """

    uploaded_file = request.files.get("image")

    if uploaded_file is None or not uploaded_file.filename:
        return jsonify(
            error="Please upload a poster image."
        ), 400

    try:
        # Inspect the uploaded image.
        with Image.open(uploaded_file.stream) as image:
            image_format = image.format
            width, height = image.size
            image.verify()

        # Check the actual image format.
        if image_format not in ALLOWED_FORMATS:
            return jsonify(
                error="Unsupported image format. Use JPEG, PNG, or WEBP."
            ), 400

        # Check image dimensions.
        if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
            return jsonify(
                error="Image dimensions cannot exceed 12,000 pixels per side."
            ), 400

        if width * height > MAX_IMAGE_PIXELS:
            return jsonify(
                error="Image cannot exceed 50 megapixels."
            ), 400

        # Create the upload folder if it does not exist.
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # Generate a unique filename.
        filename = f"{uuid.uuid4().hex}{ALLOWED_FORMATS[image_format]}"
        destination = UPLOAD_DIR / filename

        # Save the uploaded image.
        uploaded_file.stream.seek(0)
        uploaded_file.save(destination)

    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ):
        return jsonify(
            error="The uploaded file is not a valid, readable image."
        ), 400

    # Generate an ID for this upload.
    project_id = uuid.uuid4().hex

    background_url = url_for(
        "static",
        filename=f"uploads/{filename}",
        _external=True,
    )

    # Temporary response until OCR and background repair are integrated.
    return jsonify(
        project_id=project_id,
        width=width,
        height=height,
        background_url=background_url,
        layers=[],
        warnings=[
            "OCR is not connected yet; no text layers were extracted.",
            "The original poster is being used as the background.",
            "Text removal and background repair are not implemented yet.",
        ],
    ), 200


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

    # Inputs passed validation, but AI editing is not implemented.
    return jsonify(
        error=(
            "Request validation passed, but AI text editing "
            "is not connected yet."
        )
    ), 501


@app.errorhandler(413)
def too_large(_error):
    """Return a readable error when an upload exceeds the limit."""
    return jsonify(
        error="The uploaded image exceeds the 20 MB limit."
    ), 413


if __name__ == "__main__":
    app.run(debug=True)