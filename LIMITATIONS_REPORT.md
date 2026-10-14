# Layerly follow-up: remaining limitations

This report supersedes the remaining-work section of `AUDIT_REPORT.md`.
Changes extend the existing Flask/Fabric/PaddleOCR architecture; no paid API,
frontend framework, or production dependency was added.

## File lifecycle and access

New original uploads are decoded in memory and are **not saved**. Only the repaired
PNG is stored, under `instance/projects/<random UUID>/cleaned.png` by default.
SQLite records ownership, a SHA-256 hash of a separate 256-bit capability token,
and an expiration time. Knowing a project ID alone does not grant image access.
Background responses use `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
Do not share capability URLs. Werkzeug request logs redact tokens; any separately
configured reverse proxy must also avoid logging query tokens.

`LAYERLY_RETENTION_SECONDS` defaults to **86400 (24 hours)**, with a 300-second
minimum. GET/background and authenticated POST/heartbeat renew this sliding lease.
The current editor tab sends a heartbeat every minute and on returning to the tab.
After the last renewal, cleanup runs every minute while the server is running.
The first request after startup also sweeps expired records. SQLite survives
restarts. A manual/scheduled sweep is available:

```powershell
.venv\Scripts\python.exe -m flask --app app cleanup-projects
```

Set `LAYERLY_STORAGE_DIR` before starting Flask to change the private store location.
Do not place it under a separately exposed web directory. These are environment
variables; the app does not automatically load a `.env` file.

Reads, renewals, writes, and cleanup use SQLite write transactions so another
worker cannot delete an image while it is being read. Responses send already-read
bytes. Creation records ownership before writing, so interrupted creation remains
eligible for cleanup. Cleanup validates UUID paths, rejects symlinks/redirected
paths, and unlinks only the registered `cleaned.png`; it never recursively removes
directories or unregistered files. Unknown files are preserved.

Suspended/offline tabs can outlive the server lease. Already-loaded background
pixels are reused by undo/redo and export; reopening an expired URL requires a new
upload. Previous versions' unregistered files in `static/uploads` and
`static/processed` are not automatically deleted. Their public routes are blocked;
they require explicit manual review because they lack ownership/retention records.

## Restoration and typography

Masks retain OCR polygon geometry and use an adaptive 2–3 pixel margin. For smooth
surroundings, a locally fitted RGB plane identifies foreground glyphs and restores
the underlying flat/gradient surface. For separated ink on texture, color masks
limit Telea inpainting to glyph strokes. Ambiguous or very large regions fall back
to padded polygons. Pixels outside the final mask remain unchanged. None of these
methods can infer arbitrary artwork hidden by text or reliably distinguish text
from similarly colored overlapping design elements.

Reproducible visual fixtures include a flat field, gradient, periodic texture, and
multicolor pattern, all with a nearby magenta design line. Run
`python imaging_examples.py`; inspect `verification/restoration-comparison.png`
and `verification/restoration-metrics.json`. Error is measured against the known
clean source inside the old polygon mask (RGB mean absolute error, 0–255 scale):

| Fixture | Old repair MAE | New repair MAE | Old / new mask pixels |
|---|---:|---:|---:|
| Plain | 1.817 | 0.000 | 14192 / 8893 |
| Gradient | 1.728 | 0.305 | 14192 / 8884 |
| Texture | 8.399 | 2.682 | 14192 / 7580 |
| Multicolor pattern | 15.243 | 1.915 | 14192 / 7636 |

These controlled cases demonstrate improvement, not universal photographic
reconstruction quality. `real_poster_check.py PATH` also runs genuine OCR and
restoration on a supplied local poster and produces a comparison without altering
the source. There is no clean-reference error metric for an existing real poster.

Typography estimates compare rectified observed glyph masks with locally installed
Arial, Georgia, Times New Roman, and Courier New candidates (including available
bold variants). Low-confidence matches, non-ASCII scripts and long lines retain
the existing fallback. On machines without these fonts, matching is skipped.
Detected glyph bounds reduce OCR padding; the browser measures actual rendered
ink to position/scale editable text. This is approximate font matching, not exact
font identification. Each OCR line remains independent and left-anchored; semantic
paragraph alignment and original multiline spacing cannot reliably be inferred.
Line and letter spacing now have editable controls and participate in history.

## Language configuration

PaddleOCR 3.7.0's installed PP-OCRv5 mapping was inspected directly. `OCR_LANG`
defaults to `en`; restart the process after changing it. Supported configuration
choices are `en`, `fr`, `de`, `es`, `pt`, `it`, `ar`, `ur`, `fa`, `hi`, `ru`, `ch`,
`chinese_cht`, `japan`, `korean`, `th`, `el`, `te`, and `ta`. Invalid values return
a clear service error before model initialization. Only the configured model is
loaded; there is no per-request model pool or automatic language detection.

English was tested through the browser workflow. One additional Latin mobile
recognizer was downloaded for the explicit multilingual checks, reusing the
installed detector. With that recognizer, these samples matched exactly:

| Sample | Recognition confidence |
|---|---:|
| French: Bonjour été café | 0.994598 |
| Spanish: Oferta mañana café | 0.999398 |
| German: Grüße schöne Welt | 0.998844 |

These are representative smoke tests, not broad accuracy benchmarks. Other
configured scripts, including Arabic/Urdu and CJK, remain **untested**. Selecting
them can download their own model on first use; none was downloaded speculatively.
Run `python multilingual_checks.py` to reproduce the Latin samples.

## Verification

The final Python run passed **48 tests**, with **0 failures, 0 skips**, plus **20
passed subtests**. JavaScript syntax and dependency consistency checks passed.
Tests cover file expiration, restart/renewal, unauthorized access, traversal,
unrelated-file protection, cleanup locking, token-log redaction, image masks,
white/rotated text, font candidates, invalid languages, and all earlier API tests.

Edge 155.0.4283.45 and Chrome 148.0.7778.181 ran real PaddleOCR and the full browser
workflow. Evidence lives in `verification/msedge/result.json` and
`verification/chrome/result.json`, with actual downloaded PNGs. Both browser runs
exercise PNG/JPEG DataTransfer drops and picker replacement, selection, pointer
dragging at reduced zoom, corner resizing, rotation, editing after movement,
transformation undo/redo, commands, duplication, four reorder actions, spacing
controls, mobile overflow checks, and original-resolution exports. Pixel tests
verify changed text color, disappearance of original dark text, and overlapping
glyph color changes when layer order changes. A blocked background URL simulates
an expired/offline session and confirms history/export can use decoded pixels.

The first gesture test incorrectly clicked an already-selected textbox into editing
mode. Correcting the selection sequence let real drags pass; no coordinate workaround
was introduced. Real OCR also caught a NumPy scalar in estimated font size; native
float conversion fixed the JSON error. A new font-size test allows a documented
10% estimate tolerance because nominal em size and thresholded glyph height differ.
Independent browser ink-bound checks verify actual placement. On the English
heading fixture, tightening the glyph box reduced maximum bound error from 11px
to 3px in the final Edge and Chrome runs. Both final runs completed with no page
JavaScript errors. A transient CDN navigation timeout occurred in an earlier Edge
attempt; the successful final run used a 90-second page-load allowance. Ordinary
favicon 404s and an optional Paddle ccache warning were observed; final OCR/API
requests did not produce unhandled Flask exceptions.

The real photographic poster check found 38 text regions at 1024x1536. Final masks
covered 10.08% of pixels, with all pixels outside the mask unchanged. Visual
inspection found better removal of gradient lettering after adding conservative
fallbacks, but smearing, residual edge/shadow marks and damaged overlapping flourishes
remain around some stylized lettering. The photographs and distant design elements
remain intact outside the mask. This is explicitly not pixel-perfect restoration.

| Limitation | Root cause | Changes implemented | Tests performed | Final status | Remaining constraints |
|---|---|---|---|---|---|
| Background restoration | Whole-region inpainting destroys texture; a single color misses gradient glyphs | Adaptive polygon-constrained glyph masks, robust local gradient fit, conservative coverage check and Telea fallback | Four known-reference fixtures, rotated white glyphs, real photographic poster, visual inspection, browser exports | IMPROVED WITH KNOWN LIMITATIONS | Hidden artwork, overlapping ornaments, shadows and undetected text cannot be reconstructed reliably |
| Typography | Generic font and line-box scaling; detector padding | Local candidate/weight matching, tighter observed ink bounds, browser glyph measurement, editable line/letter spacing | Arial regular/bold and Georgia fixtures; native JSON checks; browser property/history and exported bounds | IMPROVED WITH KNOWN LIMITATIONS | Limited installed candidates; no exact font identification, semantic alignment or automatic multiline reconstruction |
| Upload cleanup | Public files had no ownership registry or expiration | Private store, unpredictable IDs and tokens, SQLite lease registry, heartbeat, automatic safe sweep and CLI, no saved originals | Expiration, renewals, restart, transaction blocking, traversal/auth denial, unknown files, expired-session browser export | FIXED AND VERIFIED | Unregistered legacy files intentionally preserved; suspended tabs can expire; proxy logging must protect tokens |
| Mouse drag/resize/rotate | Missing real gesture coverage | Real pointer tests at reduced zoom, transformation history and export checks | Edge and Chrome Playwright mouse events | FIXED AND VERIFIED | Desktop mouse tested; touch/stylus and physical devices not covered |
| Drag-and-drop | Existing handler lacked verified feedback/loading coverage | Preview loading state and consistent picker/drop validation; existing drop handler retained | PNG/JPEG DataTransfer events, drag class, invalid text file, picker replacement in both browsers | FIXED AND VERIFIED | OS file-manager drag gesture itself is simulated by browser DataTransfer |
| Multilingual OCR | Only English model had been exercised; invalid config errors were generic | Explicit validated language choices, fixed per-process model, Latin sample script | Real English, French, Spanish, German samples; unsupported-language error test | IMPROVED WITH KNOWN LIMITATIONS | Other scripts are configured but untested; no automatic language detection |
| Duplicate/reorder | No controls or action handlers | Independent styled duplicate with UUID/offset; forward/backward/front/back; history/export integration | Styling/identity checks, independent edit, undo/redo, object order and overlapping export pixel checks | FIXED AND VERIFIED | 500-layer cap; background stays outside editable stack |
| Chrome and Edge compatibility | Browser evidence was previously limited | Parameterized shared workflow and saved artifacts | Real installed Chrome and Edge, no page JavaScript errors | FIXED AND VERIFIED | CDN/font network access still required; not every browser version/device tested |
| Firefox compatibility | Firefox and Playwright Firefox runtime absent | Harness accepts `--browser firefox` when installed | Local executable/runtime availability inspection | NOT RESOLVED | Firefox was not installed or downloaded and is not claimed as tested |

## Files changed in this follow-up

- `project_store.py`, `app.py`, `.gitignore`: private lifecycle, authenticated image
  serving/heartbeat, cleanup, log redaction and ignored runtime storage.
- `background_service.py`: glyph masks, robust background fit, coverage checks,
  adaptive padding, bounded estimation memory and stream output.
- `typography_service.py`, `layer_utils.py`, `ocr_service.py`: font/weight and ink
  estimates, layer metadata, validated language configuration.
- `static/js/editor.js`, `templates/index.html`: duplicate/order/spacing controls,
  history and export integration, preview state, lease renewal and decoded-background
  reuse. Existing visual identity and architecture are retained.
- `test_project_store.py`, `test_imaging.py`, `test_extraction.py`: lifecycle,
  imaging/typography/language regressions and updated private-storage contract.
- `browser_command_checks.py`, `browser_interactions.py`: real browser gestures,
  duplication/order, expiry resilience, typography bounds and saved artifacts.
- `imaging_examples.py`, `multilingual_checks.py`, `real_poster_check.py`,
  `verification/`: reproducible local image/recognition evaluations and evidence.
- `README.md`, `AUDIT_REPORT.md`, `LIMITATIONS_REPORT.md`: configuration, retention,
  test instructions and current limitations. Earlier uncommitted changes remain.

Existing user uploads and unrelated files were not deleted. No subscriptions,
credentials, paid services or new production dependencies are required.
