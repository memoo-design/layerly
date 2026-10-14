/* Fabric.js 5.3.0. OCR, text removal and repair are backend responsibilities. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = { file: null, originalUrl: null, width: 0, height: 0, canvas: null,
    zoom: 1, history: [], index: -1, restoring: false, busy: false, demo: false,
    request: null, uploadToken: 0, textTimer: null, noticeTimer: null, commandBusy: false, projectId: null };
  const custom = ['layerId', 'confidence'];
  let leaseUrl = null;
  async function renewLease() {
    if (!leaseUrl) return;
    try {
      const response = await fetch(leaseUrl, { method: 'POST', referrerPolicy: 'no-referrer' });
      if (!response.ok) { leaseUrl = null; notify('The stored background expired. Export your current canvas before closing this tab; upload again to start a new session.'); }
    } catch (_) { /* Retry after a transient connection loss. */ }
  }
  setInterval(renewLease, 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) renewLease(); });
  const fonts = ['Arial', 'DM Sans', 'Manrope', 'Georgia', 'Times New Roman', 'Courier New'];
  function notify(message) {
    $('notice').textContent = message; $('notice').hidden = false;
    clearTimeout(state.noticeTimer); state.noticeTimer = setTimeout(() => { $('notice').hidden = true; }, 8000);
  }
  function screen(name) {
    if (state.busy && name !== 'processing') return;
    document.querySelectorAll('.screen').forEach(el => { el.hidden = el.id !== name; });
    if (name === 'editor') requestAnimationFrame(() => fit());
    else window.scrollTo(0, 0);
  }
  document.querySelectorAll('[data-screen]').forEach(el => el.addEventListener('click', () => screen(el.dataset.screen)));
  function message(text) { $('uploadMessage').textContent = text; $('uploadMessage').hidden = !text; }
  const imageFrom = (url, cors = false) => new Promise((resolve, reject) => {
    const image = new Image(); if (cors) image.crossOrigin = 'anonymous';
    image.onload = () => resolve(image); image.onerror = () => reject(new Error('The image could not be loaded. Check the image URL and CORS settings.'));
    image.src = url;
  });
  function validDimensions(w, h) {
    return Number.isInteger(w) && Number.isInteger(h) && w > 0 && h > 0 && w <= 12000 && h <= 12000 && w * h <= 50000000;
  }
  async function upload(file) {
    if (!file || state.busy) return;
    const token = ++state.uploadToken;
    if (!['image/png', 'image/jpeg'].includes(file.type)) { message('Choose a PNG or JPEG image.'); return; }
    if (file.size > 20 * 1024 * 1024) { message('Choose an image smaller than 20 MB.'); return; }
    const url = URL.createObjectURL(file);
    message('Loading image preview…'); $('extract').disabled = true; $('dropZone').setAttribute('aria-busy', 'true');
    try {
      const img = await imageFrom(url);
      if (token !== state.uploadToken) { URL.revokeObjectURL(url); return; }
      if (!validDimensions(img.naturalWidth, img.naturalHeight)) throw new Error('Use an image up to 12,000 pixels per side and 50 megapixels.');
      if (state.originalUrl) URL.revokeObjectURL(state.originalUrl);
      state.originalUrl = url; state.file = file;
      $('originalPreview').src = url; $('originalPreview').hidden = false; $('uploadEmpty').hidden = true;
      $('dropZone').classList.add('has-image'); $('fileDetails').textContent = `${file.name} · ${img.naturalWidth} × ${img.naturalHeight} px`;
      $('chooseFile').textContent = 'Replace image'; $('extract').disabled = false; message('');
    } catch (err) { URL.revokeObjectURL(url); if (token === state.uploadToken) message(err.message); }
    finally { if (token === state.uploadToken) { $('dropZone').setAttribute('aria-busy', 'false'); $('extract').disabled = !state.file; } }
  }
  $('chooseFile').onclick = () => $('fileInput').click();
  $('fileInput').onchange = e => { upload(e.target.files[0]); e.target.value = ''; };
  ['dragenter', 'dragover'].forEach(type => $('dropZone').addEventListener(type, e => { e.preventDefault(); $('dropZone').classList.add('dragging'); }));
  ['dragleave', 'drop'].forEach(type => $('dropZone').addEventListener(type, e => { e.preventDefault(); $('dropZone').classList.remove('dragging'); }));
  $('dropZone').addEventListener('drop', e => upload(e.dataTransfer.files[0]));
  // Extraction transport. Replace endpoint/headers here when needed.
  async function requestTextExtraction(file, signal) {
    const form = new FormData(); form.append('image', file);
    let response;
    try { response = await fetch('/api/extract-text', { method: 'POST', body: form, signal }); }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new Error('Cannot reach the extraction backend. Start Flask and connect POST /api/extract-text.');
    }
    let data;
    try { data = await response.json(); }
    catch (_) { throw new Error(`The backend returned HTTP ${response.status} without a valid JSON response.`); }
    if (!response.ok) throw new Error(typeof data.error === 'string' ? data.error : `Extraction failed (HTTP ${response.status}).`);
    return data;
  }
  window.LayerlyAPI = Object.freeze({ requestTextExtraction, requestTextEdit });
  function validateResponse(data) {
    if (!data || typeof data !== 'object') throw new Error('The backend response must be a JSON object.');
    if (!data.background_url) throw new Error('Full reconstruction is not ready: the backend did not return a cleaned background. This is the original-image preview; no editable text has been overlaid.');
    if (!validDimensions(data.width, data.height) || !Array.isArray(data.layers) || data.layers.length > 500) throw new Error('The backend returned invalid dimensions or layers.');
    if (typeof data.project_id !== 'string' || !data.project_id) throw new Error('The backend response is missing project_id.');
    if (typeof data.background_url !== 'string') throw new Error('background_url must be a URL string.');
    const url = new URL(data.background_url, window.location.href);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('The background URL must use HTTP or HTTPS.');
    if (data.warnings !== undefined && (!Array.isArray(data.warnings) || data.warnings.some(w => typeof w !== 'string'))) throw new Error('warnings must be an array of strings.');
    const ids = new Set();
    data.layers.forEach(layer => {
      if (!layer || typeof layer.id !== 'string' || !layer.id || ids.has(layer.id) || typeof layer.text !== 'string') throw new Error('Each text layer needs a unique string id and text.');
      ids.add(layer.id);
      ['x', 'y', 'width', 'height', 'rotation', 'font_size', 'confidence'].forEach(key => {
        if (typeof layer[key] !== 'number' || !Number.isFinite(layer[key])) throw new Error(`Layer ${layer.id}: ${key} must be a finite number.`);
      });
      if (layer.width <= 0 || layer.height <= 0 || layer.font_size <= 0 || layer.font_size > 2000 || layer.confidence < 0 || layer.confidence > 1 || layer.text.length > 10000) throw new Error(`Layer ${layer.id}: invalid size, confidence or text length.`);
      if (typeof layer.font_family !== 'string' || !layer.font_family.trim() || typeof layer.color !== 'string' || !/^#[0-9a-f]{6}$/i.test(layer.color)) throw new Error(`Layer ${layer.id}: provide a font family and a six-digit hex color.`);
    });
    return { ...data, background_url: url.href };
  }
  $('extract').onclick = async () => {
    if (!state.file || state.busy) return;
    state.request = new AbortController(); state.busy = true;
    $('processingPreview').src = state.originalUrl; screen('processing');
    const timeout = setTimeout(() => state.request?.abort('timeout'), 300000);
    try {
      const data = validateResponse(await requestTextExtraction(state.file, state.request.signal));
      const original = await imageFrom(state.originalUrl);
      if (data.width !== original.naturalWidth || data.height !== original.naturalHeight) throw new Error('The backend dimensions do not match the original poster. Coordinates must use original-image pixels.');
      await buildProject(data, false, state.request.signal);
      state.busy = false; screen('editor');
    } catch (err) {
      const reason = state.request?.signal.reason;
      state.busy = false; screen('upload');
      message(err.name === 'AbortError' ? (reason === 'timeout' ? 'The backend did not finish within 5 minutes. Your original preview is retained; try again.' : 'Extraction cancelled. Your original preview is retained.') : err.message);
    } finally { clearTimeout(timeout); state.request = null; state.busy = false; }
  };
  $('cancel').onclick = () => state.request?.abort('cancel');
  function canvas() {
    if (!window.fabric) throw new Error('Fabric.js could not load. Check your connection or serve the pinned library locally.');
    if (state.canvas) return state.canvas;
    const c = new fabric.Canvas('posterCanvas', { preserveObjectStacking: true, selection: false, backgroundColor: 'white' });
    fabric.Object.prototype.set({ borderColor: '#6652e8', cornerColor: '#ffffff', cornerStrokeColor: '#6652e8', transparentCorners: false, cornerStyle: 'rect', cornerSize: 9, padding: 3 });
    state.canvas = c;
    ['selection:created', 'selection:updated', 'selection:cleared'].forEach(event => c.on(event, sync));
    c.on('object:modified', () => { commit(); sync(); });
    c.on('text:editing:exited', () => { commit(); sync(); });
    c.on('text:changed', () => { syncProperties(); });
    return c;
  }
  async function loadFonts(layers) {
    const warnings = [];
    for (const font of new Set(layers.map(l => l.font_family))) {
      try {
        await document.fonts.load(`16px "${font.replace(/["\\]/g, '')}"`);
        if (!document.fonts.check(`16px "${font.replace(/["\\]/g, '')}"`)) warnings.push(`Font ${font} is unavailable; browser fallback may change the appearance.`);
      } catch (_) { warnings.push(`Could not load ${font}; a fallback font will be used.`); }
    }
    return warnings;
  }
  async function buildProject(data, demo, signal) {
    // Preload and verify before replacing the current editor project.
    const background = await imageFrom(data.background_url, !demo);
    if (background.naturalWidth !== data.width || background.naturalHeight !== data.height) throw new Error('The cleaned background dimensions must match the original image.');
    // Test exportability early. Cross-origin images must allow anonymous CORS.
    const probe = document.createElement('canvas'); probe.width = probe.height = 1;
    probe.getContext('2d').drawImage(background, 0, 0, 1, 1);
    try { probe.toDataURL(); } catch (_) { throw new Error('The cleaned background cannot be exported. Serve it from Flask or enable anonymous CORS.'); }
    const fontWarnings = await loadFonts(data.layers);
    if (signal?.aborted) throw new DOMException('Request cancelled', 'AbortError');
    const c = canvas(); clearTimeout(state.textTimer); state.textTimer = null;
    leaseUrl = !demo && new URL(data.background_url, location.href).pathname.startsWith('/api/projects/') ? data.background_url : null;
    state.restoring = true; c.clear(); state.width = data.width; state.height = data.height; state.demo = demo; state.projectId = data.project_id; commandMessage('');
    c.setBackgroundImage(new fabric.Image(background, { originX: 'left', originY: 'top', left: 0, top: 0, crossOrigin: demo ? null : 'anonymous' }), () => c.requestRenderAll());
    data.layers.forEach(layer => {
      const object = new fabric.Textbox(layer.text, { layerId: layer.id, confidence: layer.confidence,
        left: layer.x, top: layer.y, width: layer.width, angle: layer.rotation,
        originX: 'left', originY: 'top', fontSize: layer.font_size, fontFamily: layer.font_family,
        fill: layer.color, fontWeight: layer.font_weight || 'normal', fontStyle: layer.font_style || 'normal',
        textAlign: layer.text_align || 'left', lineHeight: layer.line_height || 1.16,
        charSpacing: layer.char_spacing || 0, splitByGrapheme: false });
      // Fabric computes text height from font metrics. Preserve the backend box height.
      object.scaleX = layer.width / Math.max(1, object.width);
      object.scaleY = layer.height / Math.max(1, object.height);
      if (layer.fit_ink && !layer.text.includes('\n')) fitInk(object, layer);
      object.setCoords(); c.add(object);
    });
    state.restoring = false; state.history = []; state.index = -1; commit();
    $('projectName').textContent = demo ? 'Beyond the Ordinary · Demo' : state.file.name;
    $('projectStatus').textContent = demo ? 'DEMO MODE · Synthetic data, no extraction' : `Project ${data.project_id} · Edits are not saved to the server`;
    $('backgroundLabel').textContent = demo ? 'Synthetic demo background' : 'Background is repaired';
    $('modeLabel').textContent = demo ? 'DEMO MODE · Preset text on a synthetic background' : 'Reconstructed text editor';
    $('dimensions').textContent = `${data.width} × ${data.height} px`;
    $('warnings').replaceChildren();
    const warnings = [...(data.warnings || []), ...fontWarnings];
    if (data.layers.length) warnings.push('Text appearance is approximate: font metrics and detected box heights may differ from the original. Review before export.');
    if (!data.layers.length && !warnings.length) warnings.push('No text layers were detected. You can add your own text.');
    warnings.forEach(text => { const p = document.createElement('p'); p.textContent = text; $('warnings').append(p); });
    if (c.getObjects().length) c.setActiveObject(c.getObjects()[0]); sync();
  }
  function fitInk(object, layer) {
    // Measure actual glyph pixels rather than Fabric's line box and leading.
    const measure = document.createElement('canvas').getContext('2d');
    measure.font = `${object.fontWeight} 100px "${object.fontFamily}"`;
    const width = Math.ceil(measure.measureText(object.text).width + 8);
    if (width > 4096) return;
    const probe = new fabric.StaticCanvas(null, { width: width + 32, height: 240, enableRetinaScaling: false });
    try {
      probe.add(new fabric.Textbox(object.text, { left: 16, top: 16, width, fontSize: 100,
        fontFamily: object.fontFamily, fontWeight: object.fontWeight, fill: '#000000', lineHeight: 1 }));
      probe.renderAll();
      const pixels = probe.contextContainer.getImageData(0, 0, width+32, 240).data;
      let x0 = width+32, y0 = 240, x1 = 0, y1 = 0;
      for (let y=0; y<240; y++) for (let x=0; x<width+32; x++) {
        if (pixels[(y*(width+32)+x)*4+3] > 32) { x0=Math.min(x0,x); x1=Math.max(x1,x); y0=Math.min(y0,y); y1=Math.max(y1,y); }
      }
      if (x1 <= x0 || y1 <= y0) return;
      const sy = layer.height/(y1-y0+1), sx = layer.width/(x1-x0+1), angle = layer.rotation*Math.PI/180;
      object.set({ fontSize: Math.min(2000, 100*sy), width: width*sy, scaleX: sx/sy, scaleY: 1,
        left: layer.x - (x0-16)*sx*Math.cos(angle) + (y0-16)*sy*Math.sin(angle),
        top: layer.y - (x0-16)*sx*Math.sin(angle) - (y0-16)*sy*Math.cos(angle) });
    } finally { probe.dispose(); }
  }
  function snapshot() { return JSON.stringify(state.canvas.toJSON(custom)); }
  function commit() {
    clearTimeout(state.textTimer); state.textTimer = null;
    if (!state.canvas || state.restoring) return;
    const json = snapshot(); if (state.history[state.index] === json) return;
    state.history = state.history.slice(0, state.index + 1); state.history.push(json);
    if (state.history.length > 100) state.history.shift(); state.index = state.history.length - 1; historyButtons();
  }
  function historyButtons() {
    $('undo').disabled = state.restoring || state.index <= 0;
    $('redo').disabled = state.restoring || state.index >= state.history.length - 1;
  }
  function history(direction) {
    if (state.restoring || !state.canvas) return;
    if (state.canvas.getActiveObject()?.isEditing) state.canvas.getActiveObject().exitEditing();
    if (state.textTimer) commit();
    const next = state.index + direction; if (next < 0 || next >= state.history.length) return;
    state.restoring = true; $('properties').disabled = true; state.index = next; historyButtons();
    const selected = state.canvas.getActiveObject()?.layerId;
    const background = state.canvas.backgroundImage, saved = JSON.parse(state.history[next]);
    delete saved.backgroundImage;
    state.canvas.loadFromJSON(saved, () => {
      // Backgrounds never change within a project's history. Reuse decoded pixels
      // so an offline tab or an expired server lease cannot erase its background.
      state.canvas.setBackgroundImage(background, () => state.canvas.requestRenderAll());
      state.restoring = false; setZoom(state.zoom); const object = state.canvas.getObjects().find(o => o.layerId === selected);
      if (object) state.canvas.setActiveObject(object); sync(); historyButtons();
    });
  }
  $('undo').onclick = () => history(-1); $('redo').onclick = () => history(1);
  function active() { return state.canvas?.getActiveObject(); }
  function sync() { renderLayers(); syncProperties(); historyButtons(); syncCommandTarget(); }
  function renderLayers() {
    const list = $('layerList'); list.replaceChildren();
    const objects = state.canvas?.getObjects() || []; $('layerCount').textContent = `${objects.length} layers`;
    [...objects].reverse().forEach(object => {
      const row = document.createElement('div'); row.className = 'layer-row' + (object === active() ? ' active' : '');
      const thumb = document.createElement('span'); thumb.className = 'layer-thumb'; thumb.textContent = 'T';
      const select = document.createElement('button'); select.className = 'layer-select layer-name';
      const name = document.createElement('b'); name.textContent = object.text || 'Empty text';
      const info = document.createElement('small'); info.textContent = object.visible ? 'Text' : 'Text · Hidden'; select.append(name, info);
      select.onclick = () => { state.canvas.setActiveObject(object); state.canvas.requestRenderAll(); sync(); };
      const toggle = document.createElement('button'); toggle.className = 'eye-button'; toggle.textContent = object.visible ? 'Hide' : 'Show'; toggle.setAttribute('aria-label', `${toggle.textContent} ${object.text || 'text layer'}`);
      toggle.onclick = () => { if (state.restoring) return; object.visible = !object.visible; state.canvas.requestRenderAll(); commit(); sync(); };
      row.append(thumb, select, toggle); list.append(row);
    });
  }
  function syncProperties() {
    const o = active(); $('properties').disabled = !o || state.restoring; $('selectHint').hidden = !!o;
    if (!o) return;
    if (document.activeElement !== $('textContent')) $('textContent').value = o.text;
    if (![...$('fontFamily').options].some(option => option.value === o.fontFamily)) { const option = new Option(o.fontFamily, o.fontFamily); $('fontFamily').add(option); }
    $('fontFamily').value = o.fontFamily; $('fontSize').value = Number(o.fontSize.toFixed(1)); $('alignment').value = o.textAlign;
    $('lineHeight').value = o.lineHeight; $('charSpacing').value = o.charSpacing;
    const color = typeof o.fill === 'string' && /^#[0-9a-f]{6}$/i.test(o.fill) ? o.fill : '#000000';
    $('textColor').value = color; $('colorHex').textContent = color.toUpperCase();
    $('posX').value = Number(o.left.toFixed(1)); $('posY').value = Number(o.top.toFixed(1));
    $('layerWidth').value = Number((o.width * o.scaleX).toFixed(1)); $('layerHeight').value = Number((o.height * o.scaleY).toFixed(1)); $('rotation').value = Number(o.angle.toFixed(1));
    [['bold', o.fontWeight === 'bold' || Number(o.fontWeight) >= 600], ['italic', o.fontStyle === 'italic']].forEach(([id, on]) => { $(id).classList.toggle('active', on); $(id).setAttribute('aria-pressed', String(on)); });
    $('visibility').textContent = o.visible ? 'Hide layer' : 'Show layer';
    $('confidence').textContent = typeof o.confidence === 'number' ? `OCR confidence: ${Math.round(o.confidence * 100)}%` : 'Manually added text';
  }
  function modify(properties, record = true) {
    if (state.restoring || !active()) return;
    const object = active(); object.set(properties); object.setCoords(); state.canvas.requestRenderAll();
    if (record) commit(); sync();
  }
  $('textContent').oninput = e => {
    if (e.target.value.length > 10000) { notify('Keep each text layer below 10,000 characters.'); return; }
    modify({ text: e.target.value, styles: {} }, false);
    clearTimeout(state.textTimer); state.textTimer = setTimeout(commit, 350);
  };
  $('textContent').onblur = commit;
  $('fontFamily').onchange = async e => {
    const o = active(), font = e.target.value;
    await loadFonts([{ font_family: font }]); if (active() === o) modify({ fontFamily: font });
  };
  const numeric = (id, fn, min = -Infinity, max = Infinity) => {
    $(id).onchange = e => {
      const value = Number(e.target.value);
      if (!e.target.value.trim() || !Number.isFinite(value) || value < min || value > max) { notify('Enter a valid value for this property.'); syncProperties(); return; }
      if (active()) modify(fn(value, active()));
    };
  };
  numeric('fontSize', value => ({ fontSize: value }), 1, 2000);
  numeric('lineHeight', value => ({ lineHeight: value }), .5, 3);
  numeric('charSpacing', value => ({ charSpacing: value }), -100, 1000);
  numeric('posX', value => ({ left: value })); numeric('posY', value => ({ top: value }));
  numeric('layerWidth', (value, o) => ({ scaleX: value / o.width }), 1);
  numeric('layerHeight', (value, o) => ({ scaleY: value / o.height }), 1);
  numeric('rotation', value => ({ angle: value }));
  $('alignment').onchange = e => modify({ textAlign: e.target.value });
  $('textColor').onchange = e => modify({ fill: e.target.value });
  $('bold').onclick = () => { const o = active(); if (o) modify({ fontWeight: o.fontWeight === 'bold' || Number(o.fontWeight) >= 600 ? 'normal' : 'bold' }); };
  $('italic').onclick = () => { const o = active(); if (o) modify({ fontStyle: o.fontStyle === 'italic' ? 'normal' : 'italic' }); };
  $('visibility').onclick = () => { if (active()) modify({ visible: !active().visible }); };
  $('deleteText').onclick = () => { if (!active() || state.restoring) return; state.canvas.remove(active()); commit(); sync(); };
  $('duplicateText').onclick = () => {
    if (!active() || state.restoring) return;
    if (state.canvas.getObjects().length >= 500) { notify('At most 500 text layers are supported.'); return; }
    const original = active(), projectId = state.projectId;
    original.clone(copy => {
      if (state.restoring || projectId !== state.projectId) return;
      copy.set({ layerId: crypto.randomUUID(), left: original.left + 16, top: original.top + 16 });
      state.canvas.add(copy); state.canvas.setActiveObject(copy); copy.setCoords(); commit(); sync();
    }, custom);
  };
  for (const [id, method] of Object.entries({bringForward: 'bringForward', sendBackward: 'sendBackwards', bringFront: 'bringToFront', sendBack: 'sendToBack'})) {
    $(id).onclick = () => {
      if (!active() || state.restoring) return;
      state.canvas[method](active()); state.canvas.requestRenderAll(); commit(); sync();
    };
  }
  $('addText').onclick = () => {
    if (!state.canvas || state.restoring) return;
    if (state.canvas.getObjects().length >= 500) { notify('At most 500 text layers are supported.'); return; }
    const o = new fabric.Textbox('New text', { layerId: `text-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      left: state.width * .1, top: state.height * .1, width: state.width * .6,
      fontSize: Math.max(12, Math.round(state.width / 20)), fontFamily: 'Arial', fill: '#ffffff' });
    state.canvas.add(o); state.canvas.setActiveObject(o); commit(); sync();
  };
  function commandMessage(text, kind = '') {
    $('commandMessage').textContent = text; $('commandMessage').dataset.kind = kind;
  }
  function syncCommandTarget() {
    const o = active();
    $('commandTarget').textContent = o ? `Selected: ${o.text.slice(0, 70) || 'Empty text'} (${o.layerId})` : 'Selected: no text layer';
    $('commandMode').textContent = state.demo ? 'DEMO MODE · Local rule parser, no AI service' : 'Local command parser · No AI service';
  }
  function currentLayers() {
    return state.canvas.getObjects().map(o => {
      if (o.confidence != null && (typeof o.confidence !== 'number' || !Number.isFinite(o.confidence) || o.confidence < 0 || o.confidence > 1)) {
        throw new Error('OCR confidence must be a finite number between 0 and 1, or absent.');
      }
      const bounds = o.getBoundingRect(true, true);
      return { id: o.layerId, text: o.text, confidence: o.confidence ?? null,
        x: o.left, y: o.top, width: o.width, height: o.height, rotation: o.angle,
        scale_x: o.scaleX, scale_y: o.scaleY, font_size: o.fontSize, font_family: o.fontFamily,
        color: o.fill, font_weight: o.fontWeight, font_style: o.fontStyle,
        text_align: o.textAlign, visible: o.visible,
        bounds: { left: bounds.left, width: bounds.width } };
    });
  }

  async function requestTextEdit(payload, signal) {
    let response;
    try { response = await fetch('/api/edit-text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal }); }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new Error('AI text editing is unavailable. Cannot reach POST /api/edit-text. No layers were changed.');
    }
    let data;
    try { data = await response.json(); }
    catch (_) { throw new Error(`The text-edit backend returned invalid JSON (HTTP ${response.status}).`); }
    if (!response.ok) throw new Error(typeof data.error === 'string' ? data.error : `AI text editing failed (HTTP ${response.status}).`);
    return data;
  }
  function commandScope(prompt, selectedId, layers) {
    // Replacement wording is content, not a target instruction.
    if (/^replace\b/i.test(prompt)) prompt = prompt.split(/\s+with\s+/i)[0];
    if (/\b(all|every|each)\s+(?:the\s+)?text(?:\s+layers?)?\b|\ball\s+layers\b/i.test(prompt)) return layers.map(l => l.id);
    if (/\bheading\b/i.test(prompt)) {
      const headings = layers.filter(l => /^(heading|headline|title)$/i.test(l.id));
      if (headings.length === 1) return [headings[0].id];
      throw new Error('Select a heading layer and refer to the selected text. The heading target is unclear.');
    }
    if (!selectedId) throw new Error('Select a text layer first, or explicitly request all text layers.');
    return [selectedId];
  }
  function demoTextEdit(payload, targets) {
    const prompt = payload.prompt.trim(), p = prompt.replace(/[.!]$/, '');
    let properties;
    const color = p.match(/^(?:change|set)\s+(?:(?:the\s+)?selected\s+)?(?:(?:all|every|each)\s+)?(?:the\s+)?text\s+colou?rs?\s+to\s+(blue|white|red|black|green|purple|#[0-9a-f]{6})$/i);
    const size = p.match(/^(?:increase|change|set)\s+(?:the\s+)?(?:selected\s+)?text\s+size\s+to\s+(\d+(?:\.\d+)?)$/i);
    const wording = p.match(/^replace\s+(?:the\s+)?(?:selected\s+)?text\s+with\s+(.+)$/i);
    if (color) properties = { color: ({ blue: '#0000ff', white: '#ffffff', red: '#ff0000', black: '#000000', green: '#008000', purple: '#800080' })[color[1].toLowerCase()] || color[1] };
    else if (/^make\s+(?:the\s+)?(?:heading|(?:selected\s+)?text)\s+bold$/i.test(p)) properties = { font_weight: 'bold' };
    else if (size) properties = { font_size: Number(size[1]) };
    else if (wording) properties = { text: wording[1] };
    else if (/^move\s+(?:the\s+)?(?:selected\s+)?text\s+to\s+(?:the\s+)?cent(?:er|re)$/i.test(p)) properties = { position: 'center' };
    else throw new Error('Demo parser does not understand this command. Try one of the documented examples.');
    return { changes: targets.map(id => ({ id, properties })), message: 'Demo command applied.' };
  }
  function validateTextChanges(data, targets) {
    if (!data || !Array.isArray(data.changes) || data.changes.length > 500) throw new Error('The backend must return a changes array.');
    const ids = new Set();
    const names = { text: 'text', color: 'fill', font_size: 'fontSize', font_family: 'fontFamily', font_weight: 'fontWeight', font_style: 'fontStyle', text_align: 'textAlign', x: 'left', y: 'top', rotation: 'angle', visible: 'visible' };
    return data.changes.map(change => {
      const object = state.canvas.getObjects().find(o => o.layerId === change?.id);
      if (!object || ids.has(change.id) || !targets.includes(change.id)) throw new Error('The backend returned an unknown, duplicate or unauthorized layer target. No changes applied.');
      ids.add(change.id);
      if (change.delete === true && Object.keys(change).every(key => ['id', 'delete'].includes(key))) return { object, update: {}, remove: true };
      const props = change.properties;
      if (!props || typeof props !== 'object' || Array.isArray(props) || !Object.keys(props).length) throw new Error('Each change needs a nonempty properties object.');
      const update = {};
      for (const [key, value] of Object.entries(props)) {
        let valid = false;
        if (key === 'text') valid = typeof value === 'string' && value.length <= 10000;
        else if (key === 'color') valid = typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
        else if (key === 'font_size') valid = Number.isFinite(value) && value >= 1 && value <= 2000;
        else if (key === 'font_family') valid = typeof value === 'string' && fonts.includes(value);
        else if (key === 'font_weight') valid = ['normal', 'bold'].includes(value);
        else if (key === 'font_style') valid = ['normal', 'italic'].includes(value);
        else if (key === 'text_align') valid = ['left', 'center', 'right', 'justify'].includes(value);
        else if (['x', 'y'].includes(key)) valid = Number.isFinite(value) && Math.abs(value) <= 100000;
        else if (key === 'rotation') valid = Number.isFinite(value) && Math.abs(value) <= 360;
        else if (key === 'visible') valid = typeof value === 'boolean';
        else if (key === 'position') valid = value === 'center';
        if (!valid) throw new Error(`Invalid or unsupported text property: ${key}. No changes applied.`);
        if (key !== 'position') update[names[key]] = value;
      }
      if (Object.hasOwn(update, 'text')) update.styles = {};
      else if (['fill', 'fontSize', 'fontFamily', 'fontWeight', 'fontStyle'].some(key => Object.hasOwn(update, key))) {
        // Character-level styles must not override the requested layer-wide style.
        update.styles = JSON.parse(JSON.stringify(object.styles || {}));
        Object.values(update.styles).forEach(line => Object.values(line).forEach(style => {
          Object.keys(update).forEach(key => { if (key !== 'styles') delete style[key]; });
        }));
      }
      if (props.position && ['x', 'y'].some(key => Object.hasOwn(props, key))) throw new Error('Return center positioning or x/y, not both.');
      return { object, update, center: props.position === 'center' };
    });
  }
  async function applyCommand(event) {
    event.preventDefault();
    if (state.commandBusy || state.restoring || !state.canvas) return;
    const prompt = $('commandPrompt').value.trim();
    if (!prompt) { commandMessage('Enter a text editing instruction.', 'error'); return; }
    if (active()?.isEditing) active().exitEditing();
    if (state.textTimer) commit();
    const selectedId = active()?.layerId || null;
    let layers, targets;
    try {
      layers = currentLayers();
      // The server resolves normal-project targets once, using the submitted snapshot.
      targets = state.demo ? commandScope(prompt, selectedId, layers) : layers.map(layer => layer.id);
    }
    catch (error) { commandMessage(error.message, 'error'); return; }
    const before = snapshot(), projectId = state.projectId;
    state.commandBusy = true; $('applyCommand').disabled = true; $('commandForm').setAttribute('aria-busy', 'true');
    commandMessage(state.demo ? 'Processing demo command…' : 'Processing instruction…', 'processing');
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const payload = { project_id: projectId, prompt, selected_layer_id: selectedId, width: state.width, height: state.height, layers };
      const result = state.demo ? demoTextEdit(payload, targets) : await requestTextEdit(payload, controller.signal);
      if (projectId !== state.projectId || snapshot() !== before || (active()?.layerId || null) !== selectedId || state.restoring) throw new Error('The poster changed while the command was processing. Submit the command again.');
      const changes = validateTextChanges(result, targets);
      // Validate the complete response before touching any layer. Background is never changed.
      const backups = changes.map(({ object, update }) => ({ object,
        values: Object.fromEntries([...new Set([...Object.keys(update), 'left', 'top', 'width', 'height'])].map(key => [key, object.get(key)])) }));
      try {
        changes.forEach(({ object, update, center }) => {
          object.set(update);
          if (center) {
            const box = object.getBoundingRect(true, true);
            object.set({ left: object.left + state.width / 2 - box.left - box.width / 2,
              top: object.top + state.height / 2 - box.top - box.height / 2 });
          }
          object.setCoords();
        });
        changes.filter(change => change.remove).forEach(({ object }) => state.canvas.remove(object));
      } catch (error) {
        backups.forEach(({ object, values }) => { object.set(values); object.setCoords(); });
        state.canvas.requestRenderAll();
        throw new Error('The text update could not be applied. No changes applied.');
      }
      state.canvas.requestRenderAll(); commit(); sync();
      commandMessage(changes.length ? `${state.demo ? 'Demo: ' : ''}Updated ${changes.length} text layer${changes.length === 1 ? '' : 's'}.` : 'No changes needed.', 'success');
    } catch (error) { commandMessage(error.name === 'AbortError' ? 'AI text editing timed out. No changes applied.' : error.message, 'error'); }
    finally { clearTimeout(timeout); state.commandBusy = false; $('applyCommand').disabled = false; $('commandForm').setAttribute('aria-busy', 'false'); }
  }
  $('commandForm').onsubmit = applyCommand;
  $('commandPrompt').onkeydown = event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('commandForm').requestSubmit(); }
  };
  document.querySelectorAll('[data-command]').forEach(button => button.onclick = () => { $('commandPrompt').value = button.dataset.command; $('commandPrompt').focus(); });
  function setZoom(zoom) {
    if (!state.canvas) return;
    state.zoom = Math.max(.02, Math.min(4, zoom));
    state.canvas.setDimensions({ width: Math.round(state.width * state.zoom), height: Math.round(state.height * state.zoom) });
    state.canvas.setViewportTransform([state.zoom, 0, 0, state.zoom, 0, 0]); state.canvas.calcOffset(); state.canvas.requestRenderAll();
    $('zoomLabel').textContent = `${Math.round(state.zoom * 100)}%`;
  }
  function fit() {
    if (!state.canvas || $('editor').hidden) return;
    const stage = $('canvasStage'); setZoom(Math.min((stage.clientWidth - 48) / state.width, (stage.clientHeight - 48) / state.height, 1));
  }
  $('zoomOut').onclick = () => setZoom(state.zoom / 1.2); $('zoomIn').onclick = () => setZoom(state.zoom * 1.2); $('fit').onclick = fit;
  $('zoomLabel').onclick = () => setZoom(1);
  window.addEventListener('resize', () => { if (state.canvas && !$('editor').hidden) state.canvas.calcOffset(); });
  $('export').onclick = async () => {
    if (!state.canvas || state.restoring) return;
    if (active()?.isEditing) active().exitEditing(); if (state.textTimer) commit();
    $('export').disabled = true; $('export').textContent = 'Exporting…';
    const exportWidth = state.width, exportHeight = state.height;
    const exportName = state.demo ? 'layerly-demo.png' : `${state.file.name.replace(/\.[^.]+$/, '')}-edited.png`;
    const saved = state.canvas.toJSON(custom), background = state.canvas.backgroundImage;
    delete saved.backgroundImage;
    let output;
    try {
      await document.fonts.ready;
      // Isolated canvas has original pixel dimensions and identity viewport.
      output = new fabric.StaticCanvas(null, { width: exportWidth, height: exportHeight, enableRetinaScaling: false });
      await new Promise(resolve => output.loadFromJSON(saved, resolve));
      if (background) output.setBackgroundImage(new fabric.Image(background.getElement(), background.toObject()), () => {});
      output.setViewportTransform([1, 0, 0, 1, 0, 0]); output.renderAll();
      const blob = await new Promise(resolve => output.lowerCanvasEl.toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('The browser could not create the PNG.');
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = exportName;
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
      notify(`PNG exported at ${exportWidth} × ${exportHeight} pixels.`);
    } catch (err) { notify(`Export failed: ${err.message}`); }
    finally { output?.dispose(); $('export').disabled = false; $('export').textContent = '↓ Download PNG'; }
  };
  document.addEventListener('keydown', e => {
    if ($('editor').hidden || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || active()?.isEditing) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); history(e.shiftKey ? 1 : -1); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); history(1); }
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); $('deleteText').click(); }
  });
  $('demo').onclick = async () => {
    if (state.busy) return;
    $('demo').disabled = true;
    try {
      const base = document.createElement('canvas'); base.width = 1200; base.height = 1500;
      const ctx = base.getContext('2d'); const gradient = ctx.createLinearGradient(0, 0, 1200, 1500);
      gradient.addColorStop(0, '#17172b'); gradient.addColorStop(1, '#332b4a'); ctx.fillStyle = gradient; ctx.fillRect(0, 0, 1200, 1500);
      const orb = ctx.createRadialGradient(930, 380, 10, 930, 380, 510);
      orb.addColorStop(0, '#d0a4ff'); orb.addColorStop(.4, '#8262ed'); orb.addColorStop(.75, '#384cdf'); orb.addColorStop(1, '#384cdf00'); ctx.fillStyle = orb; ctx.fillRect(0, 0, 1200, 1500);
      const layer = (id, text, x, y, width, height, font_size) => ({ id, text, x, y, width, height, rotation: 0, font_size, font_family: 'Manrope', color: '#ffffff', confidence: 1, font_weight: 'bold' });
      await buildProject({ project_id: 'synthetic-demo', width: 1200, height: 1500, background_url: base.toDataURL(),
        layers: [layer('brand', 'NX Studio', 120, 120, 450, 48, 38), layer('heading', 'BEYOND\nTHE ORDINARY', 120, 540, 1000, 260, 115), layer('date', '24–26', 120, 1190, 450, 66, 54), layer('month', 'OCTOBER / 2026', 120, 1280, 600, 35, 27)],
        warnings: ['Demo only: this background is generated locally without text; the editable layers are preset. No uploaded image is analysed.'] }, true);
      screen('editor');
    } catch (err) { message(err.message); }
    finally { $('demo').disabled = false; }
  };
})();
