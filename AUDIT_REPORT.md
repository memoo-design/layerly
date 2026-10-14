# Layerly project audit — 2026-10-14

## Initial architecture and audit

The existing application uses Flask with three routes: GET `/`, POST
`/api/extract-text`, and POST `/api/edit-text`. Vanilla JavaScript manages a Fabric
canvas, Bootstrap/custom CSS and a single Jinja template. PaddleOCR/PaddlePaddle
run locally on CPU under a process-wide inference lock. Pillow decodes and
normalizes uploads; OpenCV Telea inpainting removes detected text polygons.
There is no configured remote AI integration or credential requirement: commands
are parsed deterministically. A separate, clearly marked synthetic demo exists.
Export is entirely browser-side; there is no backend export endpoint or database.

Existing upload validation checks decoded format, pixel dimensions and byte size,
uses UUID directories, handles EXIF orientation, and composites transparency onto
white. OCR normalizes 2.x/3.x recognition polygons and confidence, with lazy model
initialization and error responses. Fabric snapshots implement bounded history.
The browser loads a separate repaired background and exports an isolated canvas
at original resolution. Requests and returned patches are validated, and stale
command responses are rejected. Text is inserted via textContent, not HTML.

Baseline: 28 unittest cases passed, plus import-time assertions in the two older
test modules. pytest was initially unavailable. Existing uncommitted modifications
in layer_utils.py, test_commands.py and browser_command_checks.py were preserved.

| Feature | Initial status | Final status | Changes / evidence |
|---|---|---|---|
| Poster upload | PARTIALLY IMPLEMENTED | WORKING | Existing PNG/JPEG validation, picker, preview, replacement and drag/drop retained |
| PaddleOCR | NOT VERIFIED | WORKING | Existing real CPU pipeline retained; normalized polygon tests pass |
| Text layers | PARTIALLY IMPLEMENTED | WORKING | Existing selection, content, typography, geometry, add/delete and visibility retained |
| Background restoration | PARTIALLY IMPLEMENTED | PARTIALLY IMPLEMENTED | Real polygon inpainting retained; local mask/clean-image tests pass; complex reconstruction remains approximate |
| AI prompt bar | PARTIALLY IMPLEMENTED | WORKING | Added relative title size wording, subtitle targeting, deletion patches and quoted punctuation handling; honest local-parser label |
| Undo/redo | NOT VERIFIED | WORKING | Extended browser checks for command changes and actual layer deletion |
| Canvas controls | PARTIALLY IMPLEMENTED | WORKING | Added 100% reset via zoom percentage button; existing fit and zoom retained |
| Export | NOT VERIFIED | WORKING | Extended pixel/dimension validation after zoom |
| Frontend UI | PARTIALLY IMPLEMENTED | WORKING | Preserved design; added mobile overflow checks |
| Backend APIs | PARTIALLY IMPLEMENTED | WORKING | Disabled default debug mode; extended command contract tests |

Priority order: establish baseline; repair requested command gaps without replacing
the existing pipeline; verify real extraction and export; expand browser history,
zoom and mobile checks; document reproducible test commands and limitations.

## Known practical limits

- Telea inpainting cannot reconstruct unknown artwork perfectly. It can smear
  textures, gradients and photographs. Unrecognized/low-confidence text remains
  flattened. Font identity and glyph geometry are approximations.
- Subtitle semantics cannot be inferred reliably from OCR. Select the subtitle
  unless its layer has an explicit subtitle role. Bottom targets use the lowest
  anchor; ties need selection. Heading targets use a unique largest displayed
  font or explicit role; ambiguity is rejected.
- Duplicate/reorder controls were not part of the existing implementation.
- Uploaded originals and cleaned PNGs persist under static directories; URLs are
  unguessable UUIDs, not access control. This is a local editor, not a multiuser
  service. Existing files are never automatically deleted.
- Large posters can consume substantial CPU/RAM despite upload limits. Cancellation
  stops the browser request but does not interrupt an active Paddle inference.
- External CSS/fonts/Fabric require network access. Edits are held in the current
  tab and are not persisted to a server project store.

## Verification and final changes

Final run results and modified-file descriptions are recorded below after testing.

### Final verification results

- Baseline: 28 unittest cases passed; older import-time assertions also passed.
- Final pytest run: **33 passed, 0 failed, 0 skipped**, plus **20 passed subtests**.
  Five added pytest cases cover requested wording, deletion identity/immutability
  and ambiguous targeting. Extraction failure tests now also assert that no
  uploaded original is retained. Older import-time assertions run at collection.
- `node --check static/js/editor.js`: passed.
- `python -m pip check`: passed; no broken requirements.
- `git diff --check`: passed (only Git Windows line-ending notices).
- Final real Edge/Playwright workflow: passed with no page JavaScript errors.
  A live Werkzeug server used real cached PaddleOCR models, not mocked extraction.
  PNG upload recognized SUMMER SALE and Open today. Selecting the heading and
  changing it to blue yielded an actual downloaded 800x360 PNG containing blue
  glyph pixels. Making all text white yielded a PNG whose RGB channels were all
  above 240, confirming original dark text was absent on this plain background.
- Browser checks verified bold, color, size, replacement, rotation, centering,
  selection/property synchronization, manual layers without OCR confidence,
  rejected ambiguous/unsupported commands, invalid patch atomicity and injected
  setter-failure rollback. Existing IDs and repaired background were retained.
- Full canvas snapshots matched across undo/redo for manual content, x/y, font
  size, scaled width/height, rotation, color, family, alignment, additions,
  deletions, command size changes and command deletions.
- Zoom in/out/reset/fit preserved object data; exported PNG dimensions remained
  800x360. A 390x844 viewport showed properties and command controls without page
  horizontal overflow. No claim is made about every device/browser combination.
- Initial restricted browser execution failed to load the external Fabric CDN;
  rerunning with approved network access succeeded. The final expanded run passed.
  The CDN URL is pinned to 5.3.0, but the loaded bundle reports `fabric.version`
  as 5.1.0; this discrepancy was observed, not hidden or substituted in testing.
- An intermediate new regression test failed on punctuation after quoted text;
  the parser correction resolved it and the final suite passed.

### Files modified or created in this audit

| File | Purpose |
|---|---|
| ai_edit_service.py | Subtitle/bottom targeting, relative size wording, actual removal, ID-based deletion patches and quoted punctuation handling |
| app.py | Save original only after processing succeeds; disable default debug; remove unused import |
| static/js/editor.js | Validate/apply deletion patches through existing history, honest command label, 100% zoom reset |
| templates/index.html | Matching command labels and accessible zoom reset button |
| test_audit.py (new) | Command regressions and targeting/deletion tests |
| test_extraction.py | Failed processing does not retain uploaded originals |
| browser_command_checks.py | Real OCR/export, original-text absence, property/history, deletion, zoom and mobile checks; existing edits preserved |
| requirements-dev.txt (new) | Separate pytest/Playwright development dependencies |
| AI_COMMAND_BAR_INTEGRATION.md | Replace stale installation/sample instructions with the actual integrated API contract |
| README.md | Current setup, test commands and audit link |
| AUDIT_REPORT.md (new) | Architecture, feature matrix, changes, test evidence and limitations |

`layer_utils.py` and `test_commands.py` had pre-existing uncommitted edits; this
audit did not overwrite or modify those edits. Browser test runs created UUID
upload/processed artifacts under the existing ignored output paths. No existing
user data, configuration, uploads or dependency declarations were deleted.

### Remaining verification and limitations

The core workflow is verified end to end on a synthetic plain-background poster
using real OCR and browser downloads. Complex photographic poster restoration,
rotated real-image recognition, multilingual models, mouse drag/resize handles,
drag-and-drop upload gestures, and browsers other than Edge were not manually
validated in this run. Rotation geometry, JPEG decoding, EXIF orientation,
transparent images, invalid images, model reuse and error paths have automated
coverage. There are no missing paid services or credentials required for the
implemented local workflow.

Successful-file retention remains manual; no automatic deletion policy was
introduced. A filesystem failure after a cleaned image is written can leave an
orphaned cleaned output. Text appearance and restoration remain approximate,
and the app does not support arbitrary generative prompts. Duplicate/reorder
controls remain outside the existing supported feature set. These are explicit
limits rather than simulated or silently successful features.

## Follow-up report

The subsequent implementation resolves several limitations listed above. See
[LIMITATIONS_REPORT.md](LIMITATIONS_REPORT.md) for the current lifecycle, controls,
restoration/typography improvements, language checks and browser evidence. This
file retains the initial audit's historical results.
