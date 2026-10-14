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

## Text command bar

The existing command bar uses a deterministic local interpreter at `POST /api/edit-text`. It does not use a paid service or a general-purpose language model. Normal uploaded projects use Flask; the labelled synthetic demo retains its separate limited parser.

Supported examples (case insensitive):

- `Blue text` changes selected text; selection is required.
- `Bold heading` and `Make heading bigger` target the heading.
- `All text white` changes every editable text layer, including hidden layers.
- `Change title color to red` targets the title.
- `Change SALE to MEGA SALE` replaces matching words in a unique layer, or a matching selected layer. Replacement text is literal, even if it contains words such as "all text".
- `Center selected text` centers horizontally using Fabric's scaled, rotated bounds and preserves y.
- `Rotate selected text 15 degrees` sets its rotation.
- `Change selected text size to 48`, `Make selected text italic`, and `Align selected text right` are also supported.

Explicit heading/title IDs or roles take priority. OCR layers have generated IDs, so a unique largest displayed font is used when no semantic role exists. If multiple candidate headings or matching text layers remain, the command asks for a selection. A generic selected-text command never guesses a layer when none is selected. Complex multi-action instructions and unsupported commands return an error without changes.

### Edit snapshot contract

The browser sends `project_id`, `prompt`, `selected_layer_id`, canvas `width`/`height`, and `layers`. Each layer contains its existing ID, text, x/y, unscaled width/height, rotation, scale_x/scale_y, typography, color, visibility, and original-coordinate horizontal bounds. `confidence` is optional OCR metadata: absent and null are accepted during editing. Present confidence must be a finite number from 0 through 1. Strings, booleans, NaN, infinity, and out-of-range values are rejected. Supported NumPy numbers are converted to native Python numbers before JSON output. Other geometry remains required and validated.

The response contains `project_id`, `message`, `changes`, and normalized `layers` for snapshot compatibility. The editor applies only `changes`, for example:

```json
{"changes": [{"id": "existing-layer-id", "properties": {"color": "#0000ff"}}]}
```

Only changed user-editable properties are returned in patches; confidence is never an editing instruction. IDs, background, confidence, scale factors, visibility and unrelated properties remain intact. The frontend maps snake_case fields to Fabric properties, validates the entire response before mutation, rejects stale results, updates existing objects, refreshes controls, and records one undo step. Character style overrides for the changed formatting property are cleared. Runtime setter failures roll back partially applied edits. No-op commands return an empty changes array and "No changes needed."

The original error came from `currentLayers()` omitting confidence while `validate_layers()` required it. A second mismatch returned full layers to a frontend expecting changes. Both contracts are now synchronized; confidence is still required in OCR extraction responses.

### Command regression checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
node --check static/js/editor.js
```

For optional browser tests (Playwright is a test-only dependency, not an application requirement):

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe browser_command_checks.py
```

The browser script uses installed Microsoft Edge headlessly, cached or downloadable PaddleOCR models, the existing Fabric CDN asset, and a temporary Flask server. It runs real upload/extraction, commands, PNG download and pixel checks, failure atomicity, and manual layers without confidence. The pinned CDN asset path is Fabric 5.3.0; that bundle reports `fabric.version` as 5.1.0 at runtime. Tests exercise the actual loaded implementation.

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

If the default model host stalls on first setup, set `$env:PADDLE_PDX_MODEL_SOURCE = "bos"` in PowerShell before starting Flask to use Paddle's alternative official download host. Cached weights are reused.


## Verified in this workspace

Python 3.10.11, PaddleOCR 3.7.0, PaddlePaddle 3.3.1, PaddleX 3.7.2, NumPy 2.2.6, OpenCV 4.10.0 and Pillow 12.3.0 were installed and checked. `pip check` passes. Windows inference required disabling optional oneDNN/MKLDNN acceleration (`enable_mkldnn=False`), which is set in the service.

All 12 extraction tests pass, together with existing layer and edit API validation checks. JavaScript syntax validation passes. A real CPU Flask extraction of an 800x300 synthetic poster recognized ?SUMMER SALE? with confidence 0.999628 and produced a separate, entirely white repaired PNG with the original black lettering removed. Browser selection, editing, and PNG export were not exercised in an automated browser; use the manual checklist above. The concurrent command-bar implementation was preserved; its old no-selection test now expects HTTP 422 instead of the former placeholder 501.


Command-bar fix verification: all 28 unittest cases passed, including existing extraction/inpainting regressions. The real browser flow recognized a synthetic two-line poster, changed the selected heading to blue, exported an 800x360 PNG containing blue glyphs, and changed all text to white. Other requested commands, error atomicity, manual layers without confidence, unchanged IDs/background, and property-panel updates were checked in the same browser workflow.

## October 2026 audit update

See [AUDIT_REPORT.md](AUDIT_REPORT.md) for the current feature matrix, changes,
verification evidence and limitations. Earlier verification notes above describe
previous sessions; the audit report records the latest run.

Use the project Python 3.10 virtual environment (`.venv\Scripts\python.exe` on
Windows). The default system Python may be a different, unsupported runtime.
Install test tools with `python -m pip install -r requirements-dev.txt`.
Run `python -m pytest -q`, `node --check static/js/editor.js`, and optionally
`python browser_command_checks.py` (requires Edge, network access to CDN assets,
and installed/cached Paddle models).

The command bar is labeled as a local parser. It now supports relative title
size instructions, selected subtitle replacement and actual layer removal with
undo/redo. Click the zoom percentage to reset to 100%. Flask debug mode is disabled
unless `FLASK_DEBUG=1`. Originals are saved only after successful OCR/restoration;
successful projects still remain on disk until manually removed.

## Follow-up: retention, typography and interaction verification

The current behavior and detailed test evidence are documented in
[LIMITATIONS_REPORT.md](LIMITATIONS_REPORT.md). It supersedes the earlier retention
and missing-controls notes above.

- Originals are processed in memory. Private repaired backgrounds expire after
  24 hours without renewal; active editor tabs renew every minute. Configure
  `LAYERLY_RETENTION_SECONDS` (minimum 300) and `LAYERLY_STORAGE_DIR` before startup.
- Cleanup is automatic while the server runs and resumes on the first request
  after restart. `python -m flask --app app cleanup-projects` performs a safe sweep.
- Old unregistered files are preserved but no longer publicly served by Flask.
- Duplicate, forward/backward, front/back, line spacing and letter spacing controls
  use the existing undo/redo history and are preserved in PNG exports.
- Restoration uses adaptive glyph masks and local gradient reconstruction where
  reliable, with Telea/polygon fallbacks. Installed fonts are compared approximately;
  glyph bounds are measured for positioning. Review complex posters before export.
- `OCR_LANG` is checked at startup of inference. English is the default. French,
  Spanish and German samples were tested with one Latin mobile recognizer; other
  supported configuration values are documented but are not claimed as verified.

Additional verification commands:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe browser_command_checks.py --browser msedge
.venv\Scripts\python.exe browser_command_checks.py --browser chrome
.venv\Scripts\python.exe imaging_examples.py
.venv\Scripts\python.exe multilingual_checks.py
```

The browser harness also accepts `--browser firefox` if a Playwright-compatible
Firefox runtime is installed. This workspace has Chrome and Edge; Firefox was
unavailable. Browser PNGs, recognition results and visual examples are saved in
`verification/`. The real-poster artifacts contain local project poster content;
they are not uploaded anywhere.
