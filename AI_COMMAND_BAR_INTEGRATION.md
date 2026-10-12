# Layerly AI command bar integration

Replace your project's `app.py` with the provided updated file (back up your existing file first), and add `ai_edit_service.py` beside it. This version is based on the provided `app.py` and preserves its OCR endpoint. If Codex changed your `app.py` after the uploaded snapshot, **do not overwrite it**; instead import `apply_command, CommandError` and replace only the existing `/api/edit-text` route's HTTP 501 return with the new call.

## Frontend API request

Send a POST to `/api/edit-text` with:

```json
{
  "project_id": "id-returned-from-extract-text",
  "prompt": "make the selected text blue",
  "selected_layer_id": "selected-layer-id",
  "layers": ["your current serialized layer objects"]
}
```

The response on success is `{"project_id":"...", "layers":[...], "message":"..."}`. On error it returns `{"error":"..."}` and status 400 or 422.

Example browser-side transport (adapt to your existing editor state and Fabric serialization):

```js
async function requestAiTextEdit({projectId, prompt, selectedLayerId, layers}) {
  const response = await fetch('/api/edit-text', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      project_id: projectId,
      prompt,
      selected_layer_id: selectedLayerId ?? null,
      layers
    })
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'AI edit failed');
  return result;
}
```

Use your editor's **existing** layer-to-Fabric renderer to apply `result.layers` to the canvas and synchronize the layers panel. Capture an undo-history snapshot before applying the returned layers. Never replace the cleaned background or rasterize the text. Disable the submit button while a request is in flight. Display `result.message` on success and the returned error on failure.

## Supported commands

- `make the selected text blue`, `change all text color to #123abc`
- `make the selected text larger` / `smaller`
- `set font size to 72`
- `change text to "MEGA SALE"`
- `replace "SALE" with "DEALS"`
- `rotate selected text 15 degrees`
- `align text left`, `center the selected text`
- `make the selected text bold`, `make the selected text italic`

This is a **rule-based offline interpreter**, not a generative LLM. It does not interpret arbitrary creative requests. With multiple layers, select one first or say `all text`. A heading/title reference without a selected layer returns an error instead of guessing.

## Verification

Run `python -m py_compile app.py ai_edit_service.py` and start Flask. The backend module was syntax checked and sample commands exercised, but full Flask/frontend integration could not be tested here because the current frontend files were not supplied.
