# Layerly: Flask poster text editor

A runnable HTML/CSS/vanilla JavaScript frontend adapted from the supplied Layerly website sample. Preserves its purple palette, DM Sans/Manrope typography, landing/upload flow and three-column editor. Version one edits text only. No React, TypeScript, Vite, Tailwind, object extraction, login, billing or image generation.

## Folder structure

- `app.py`
- `requirements.txt`
- `templates/index.html`
- `static/css/style.css`
- `static/js/editor.js`
- `README.md`

## Install and run

Use Python 3.10 (64-bit) with the CPU PaddlePaddle runtime. From this folder:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Then:

```bash
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. The Flask development server binds to localhost. The normal Extract Text flow runs local PaddleOCR and OpenCV background repair. The first extraction downloads model weights and can take several minutes; subsequent requests reuse the model. The separate labelled demo uses a synthetic background and preset text without analysing uploads.

## Dependencies

- Flask 3.1.2, PaddleOCR 3.7.0, PaddlePaddle CPU 3.3.1, OpenCV contrib 4.10.0.84, Pillow and NumPy in requirements.txt. OpenCV matches the PaddleX OCR dependency to avoid conflicting cv2 wheels.
- Bootstrap CSS 5.3.3 from jsDelivr, imported in the template. Uses responsive form controls; the sample's custom responsive grids preserve its layout. Bootstrap JavaScript is unnecessary here.
- Fabric.js 5.3.0 from cdnjs, imported before editor.js with ordered deferred scripts.
- Google Fonts: DM Sans 400/500/600/700 and Manrope 500/600/700/800, imported in style.css as in the supplied design. Font service revisions are not pinned; local system fonts are available as fallbacks. For exact font reproducibility, self-host licensed font files and change the CSS import to @font-face.

The CDN dependencies require internet. For offline use, download these exact versions into static/vendor and change the template imports to Flask static URLs. A missing Fabric library produces an error rather than pretending the editor works.

## Backend contract

The pipeline is implemented in `ocr_service.py`, `background_service.py`, and `app.py`. The frontend transport is the separate `requestTextExtraction(file, signal)` function in editor.js, also exposed as `window.LayerlyAPI.requestTextExtraction`. It sends `POST /api/extract-text` with multipart FormData field `image`. Do not manually set Content-Type: the browser supplies the boundary.

Return HTTP 200 with JSON like this:

```json
{
  "project_id": "poster-001",
  "width": 1200,
  "height": 1500,
  "background_url": "/static/generated/poster-001-clean.png",
  "layers": [
    {
      "id": "headline",
      "text": "BEYOND\nTHE ORDINARY",
      "x": 120,
      "y": 540,
      "width": 960,
      "height": 260,
      "rotation": 0,
      "font_size": 110,
      "font_family": "Arial",
      "color": "#ffffff",
      "confidence": 0.94
    }
  ],
  "warnings": ["Heading font is approximated; review its appearance."]
}
```

All numeric coordinates, box sizes and font sizes use original-image pixels. x/y denote the top-left text box anchor, with clockwise rotation in degrees around that anchor. confidence is 0–1; color is a six-digit hex string. Layer IDs and project_id are nonempty strings. Layers arrive in drawing order, bottom to top; the panel lists the topmost first. Optional font_weight, font_style and text_align initialize styling, otherwise normal/normal/left are used. Treat OCR quadrilaterals as the backend's responsibility: convert them to this box contract.

The background MUST have the detected text removed and its missing areas repaired, while retaining original dimensions. A relative same-origin URL is preferred. External URLs need anonymous CORS permission for browser access and export. The frontend validates the image dimensions and exportability. It cannot prove that the backend actually removed text: this is a backend contract you must honour. Never return the original flattened image as background_url.

If background_url is absent, the app returns to the original-image preview with a full-reconstruction-not-ready explanation. It does not overlay detected text on the original. A broken background URL, invalid JSON, mismatched dimensions, HTTP errors, unavailable service and timeouts also produce visible errors. Backend warnings appear in the editor. An empty layers array is allowed if a valid cleaned background exists.

For errors return non-2xx status and `{"error":"Human-readable explanation"}`. Reconstruction requests time out after 5 minutes and can be cancelled; cancellation aborts the browser request but may not stop server-side processing.

## Editor behavior

- Fabric Textbox layers allow selection from canvas or panel, double-click typing, movement, wrapping-width adjustment with side handles, scaling with corner handles and rotation with the top handle.
- Properties change content, font, size, color, alignment, bold/italic, x/y, scaled width/height and angle. Width/height inputs scale the box, including its glyphs; the side handles change wrapping width instead.
- Backend box height is preserved with vertical scaling because Fabric calculates native height from font metrics. This and substitute fonts can approximate original typography; review the warnings and adjust as needed.
- Hide/show and delete affect export. Hidden text can still be selected through the panel and shown again. New text starts white and may need a different color on light backgrounds.
- Undo/redo retains up to 100 canvas snapshots including typography, transforms, visibility, additions and deletions. Content changes are coalesced after 350 ms or blur. Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z act on the canvas when an input is not focused. Input and direct text editing use their own native editing behavior; a completed canvas text edit becomes a history entry.
- Zoom changes viewport and preview dimensions only. PNG export loads an isolated canvas at original dimensions with an identity viewport and no retina multiplier, so zoom and display density do not change export dimensions. Hidden layers and editing controls are omitted.
- Desktop has the original three-column layout. Small screens stack the canvas above the panels; all controls stay available.
- Editing is in memory for the current tab, with no server autosave or project persistence. Export the PNG before leaving. This frontend does not perform OCR, text removal or repair.
- Images: PNG/JPEG, maximum 20 MB, 12,000 pixels per side and 50 megapixels for client resource limits. At most 500 returned layers, 10,000 characters per layer and font size 1–2,000 pixels.

## Manual checklist

1. Run Flask. Upload PNG and JPEG through both the chooser and drag-and-drop. Check the original preview, filename and dimensions. Reject nonimages and files over 20 MB.
2. Click Extract Text. Confirm recognized text is editable over the repaired background. The request must include the `image` field.
3. Check the API returns a repaired background plus text. Check that only the cleaned background appears under editable text. Try missing/broken background_url, wrong dimensions, invalid JSON, a server error and slow/cancelled requests. No case should show duplicated original text.
4. Open the labelled demo for frontend-only checks. Confirm its demo banner. Select a layer from the canvas and the panel. Double-click text and edit it; also use the Content property.
5. Change font, size, color, left/center/right alignment and bold/italic. Drag text, resize with corners and sides, rotate, and adjust numeric x/y/width/height/rotation. Confirm selection and properties stay synchronized.
6. Add a layer. Hide it, show it and delete it. Undo/redo each action, including text, style, resize, movement and rotation. After undo, make a new change and verify the old redo branch is discarded.
7. Zoom out, zoom in and use Fit. Export at several zoom levels. Verify each downloaded PNG has the original width and height and the same content, without selection handles or hidden text.
8. Test portrait, landscape and small images; check the layout on desktop and a narrow phone viewport. Verify both layer and property panels remain accessible.

## Bottom AI text command bar

The bottom panel follows the supplied sample's AI panel, prompt box, purple Apply button and suggestion chips. Its selection indicator shows the current layer's text and ID. Enter submits; Shift+Enter adds a newline. Processing, success and error messages appear below the prompt. Commands record one undo step and refresh the properties panel. They change Fabric text properties without replacing or regenerating the background.

Normal projects call `window.LayerlyAPI.requestTextEdit(payload, signal)` at `POST /api/edit-text`. The supplied Flask route honestly returns HTTP 501 until you implement the interpreter. Keep AI credentials and model calls on the server. Validate target IDs, allowed properties and values on the server as well as the client. Never execute model-generated code.

Example request:

```json
{
  "project_id": "poster-001",
  "prompt": "Change the text color to blue",
  "selected_layer_id": "headline",
  "width": 1200,
  "height": 1500,
  "layers": [{
    "id": "headline", "text": "Summer Sale",
    "x": 120, "y": 540, "width": 960, "height": 130,
    "rotation": 0, "scale_x": 1, "scale_y": 1,
    "font_size": 110, "font_family": "Arial", "color": "#ffffff",
    "font_weight": "normal", "font_style": "normal",
    "text_align": "left", "visible": true
  }]
}
```

`layers` contains every current text layer, including hidden layers, in original pixels. Width and height here are Fabric's unscaled text box dimensions; scale_x/scale_y preserve user transformations. Selected ID is null when there is no selection.

Return HTTP 200 with structured patches, using existing IDs:

```json
{
  "changes": [{"id": "headline", "properties": {"color": "#0000ff"}}],
  "message": "Text color updated."
}
```

Allowed properties: text (up to 10,000 characters), color (six-digit hex), font_size (1–2000), font_family (Arial, DM Sans, Manrope, Georgia, Times New Roman, Courier New), font_weight (normal/bold), font_style (normal/italic), text_align (left/center/right/justify), x, y (finite values within ±100,000), rotation (±360 degrees), visible (boolean), and position (`"center"`). Center positions the rotated, scaled bounding box at the poster center; do not combine it with x/y. Omitted properties retain their values. No add/delete/background patches are accepted by this endpoint. Any invalid patch rejects the entire response before changes apply. The optional server message is not displayed; the client reports the actual number of modified layers.

Default target is the selected layer. An explicit all/every/each text request allows all layers. Heading commands target a single layer whose ID is heading, headline or title; if that is ambiguous, the user must select it and say selected text. Return a non-2xx response with `{"error":"Select the heading layer first."}` for unclear instructions. With no selection and no explicit target, the frontend asks for a selection without sending the request. Requests time out after 30 seconds. If the poster changes during a request, its response is rejected and the user can resubmit.

Only the existing synthetic **DEMO MODE** project uses a local rule parser. The bar labels it `DEMO MODE · Local rule parser, no AI service`. Normal uploaded projects never fall back to that parser. Demo examples:

- Change the selected text color to blue.
- Change all text colors to white.
- Make the heading bold.
- Increase the selected text size to 48.
- Replace the selected text with Summer Sale.
- Move the selected text to the center.

Additional manual checks:

1. In demo mode, select a layer and submit each example by Apply and Enter. Check the selection indicator, canvas, and properties. Other layers and background must remain unchanged for selected-layer commands.
2. Undo/redo each command. For an all-text command, verify every layer changes together as one history action.
3. Deselect text on the canvas and submit an unclear command. Confirm the selection request. Submit an explicit all-text command and verify it works.
4. In a normal reconstructed project, confirm `/api/edit-text` receives JSON with prompt, selected ID, dimensions and current layers. With the supplied route, confirm an unavailable message and unchanged canvas.
5. Mock a valid response, then unknown IDs, duplicate IDs, extra layer targets, invalid colors/sizes and unsupported properties. Invalid responses must apply no partial edits.
6. Simulate a slow request. Check Processing, disabled Apply, timeout, and rejection if the poster was edited while waiting. Export after a command at different zooms and confirm original dimensions.


## Local OCR and background repair

The service lazily initializes one CPU PP-OCRv5 model per server process, serializes inference, and reads 3.x `rec_texts`, `rec_scores`, and `rec_polys`. A compatibility adapter also supports existing 2.x installations, though requirements select 3.7.0 with PaddlePaddle 3.3.1. Document rotation/unwarping are disabled to preserve poster coordinates. Rotated quadrilaterals become angled text boxes; perspective and curved text are approximate.

Original uploaded bytes are retained at `static/uploads/<project_id>/original.<ext>`. EXIF orientation is applied before inference. Transparent pixels are composited onto white. Recognition polygons are expanded by two pixels and repaired with OpenCV Telea inpainting (radius 3), saved to `static/processed/<project_id>/cleaned.png`. Only accepted recognition regions are erased. Empty recognition returns a separately saved background and an informational warning.

PowerShell configuration (set before starting Flask):

```powershell
$env:OCR_CONFIDENCE_THRESHOLD = "0.5"
$env:OCR_LANG = "en"
.\.venv\Scripts\python.exe app.py
```

Install directly without activating the environment:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -v
```

Model downloads need internet on first use and write to Paddle's user cache. Runtime inference is local and free. A missing runtime/model raises HTTP 503; inference or repair failures raise HTTP 500. Cancellation stops the browser request, not work already running on the server. The Flask debug reloader creates a new model when the process restarts.

Typography, color, and font size are estimates. Polygon inpainting works best on plain backgrounds and can blur photographs, gradients, or graphics behind text. Undetected or confidence-filtered text remains flattened in the background. Large images consume substantial CPU and memory. Uploads and processed files remain on disk until manually removed; this local editor has no retention scheduler.

`test_extraction.py` uses mocked OCR predictions with real Pillow/OpenCV image processing. Existing edit API and layer utility checks also run through unittest discovery. Browser editing/export and real model inference require separate smoke checks; unit tests do not prove either.

API reference: [PaddleOCR 3.x OCR pipeline documentation](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/OCR.html). Constructor and result fields were also checked against the downloaded 3.7.0 / PaddleX 3.7.2 package sources.
