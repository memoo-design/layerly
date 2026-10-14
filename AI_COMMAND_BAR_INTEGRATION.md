# Layerly command bar integration

The command bar is already integrated in `app.py`, `ai_edit_service.py` and
`static/js/editor.js`. Do not replace the application with an older sample.
This is a deterministic local parser, not a generative AI service.

POST `/api/edit-text` accepts a JSON object containing `project_id`, `prompt`,
`layers`, optional `selected_layer_id`, and canvas `width` (needed for centering).
Layers use original-image coordinates plus optional scale and bounding metadata.
OCR confidence is preserved when present and is optional for manual layers.

Success returns `project_id`, `layers`, `message`, and `changes`. A change is either
`{"id":"layer-id","properties":{"color":"#0000ff"}}` or
`{"id":"layer-id","delete":true}`. The frontend validates the entire response,
applies it to existing Fabric objects, and commits one history snapshot. It does
not replace the background. Stale responses are rejected. Invalid requests return
400; unsupported or ambiguous commands return 422 with an `error` string.

Supported examples:

- Change the heading color to blue.
- Increase the title font size.
- Move the heading to the center.
- Make all text bold.
- Change the subtitle to 'Welcome to Layerly'.
- Remove the bottom text.
- Make the selected text smaller.
- Set selected text size to 72.
- Change SALE to MEGA SALE.
- Rotate selected text 15 degrees.
- Align text right.

Heading/title resolves an explicit role or unique largest displayed font. Subtitle
requires an explicit role or selection because OCR does not infer semantics.
Bottom text means the lowest anchor, with selection required for ties. Generic
text commands require selection; `all text` explicitly targets every layer.
Quoted replacement contents are literal, including words resembling commands.
Removal actually deletes editable text objects and is undoable.

The synthetic demo retains its separate, smaller browser-only parser. Its label
and error messages distinguish it from normal uploaded projects.

Run `.venv\Scripts\python.exe -m pytest -q` and
`.venv\Scripts\python.exe browser_command_checks.py` for API and real-browser
verification. See `AUDIT_REPORT.md` for test results and remaining limits.
