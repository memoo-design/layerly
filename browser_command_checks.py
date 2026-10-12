"""Optional real-browser integration checks: python browser_command_checks.py.
Requires test-only Playwright and installed Edge; OCR models must be available.
"""
import tempfile
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from app import app


def main():
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
            folder = Path(folder)
            poster = Image.new('RGB', (800, 360), 'white')
            draw = ImageDraw.Draw(poster)
            draw.text((60, 70), 'SUMMER SALE', font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 70), fill='black')
            draw.text((60, 230), 'Open today', font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 30), fill='black')
            upload = folder / 'poster.png'
            poster.save(upload)
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context(accept_downloads=True, ignore_https_errors=True, viewport={'width':1440,'height':1000})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='domcontentloaded')
            page.wait_for_function('!!window.fabric', timeout=60000)
            print('Fabric runtime version:', page.evaluate('fabric.version'), flush=True)
            assert page.locator('script[src*="fabric.js/5.3.0"]').count() == 1
            # Test-only handle; the production editor continues to keep its state private.
            page.evaluate('''() => {
              const Original = fabric.Canvas;
              fabric.Canvas = class extends Original {
                constructor(...args) { super(...args); window.testCanvas = this; }
              };
            }''')
            page.locator('[data-screen="upload"]').first.click()
            page.locator('#fileInput').set_input_files(str(upload))
            page.locator('#extract').click()
            page.locator('#editor').wait_for(state='visible', timeout=300000)
            assert page.evaluate('testCanvas.getObjects().length') >= 2
            page.locator('.layer-select').filter(has_text='SUMMER SALE').click()
            heading = page.evaluate('testCanvas.getActiveObject().layerId')
            initial = page.evaluate('testCanvas.toJSON(["layerId", "confidence"])')
            original_background = initial['backgroundImage']
            original_ids = [item['layerId'] for item in initial['objects']]

            def command(text, success=True):
                page.locator('#commandPrompt').fill(text)
                page.locator('#applyCommand').click()
                kind = 'success' if success else 'error'
                page.wait_for_function('(kind) => document.getElementById("commandMessage").dataset.kind === kind', arg=kind)

            def current():
                return page.evaluate('testCanvas.toJSON(["layerId", "confidence"])')

            command('Blue text')
            assert page.evaluate('testCanvas.getActiveObject().fill') == '#0000ff'
            assert page.locator('#textColor').input_value() == '#0000ff'
            assert page.evaluate('testCanvas.getActiveObject().confidence') == next(o['confidence'] for o in initial['objects'] if o['layerId'] == heading)
            with page.expect_download() as downloaded:
                page.locator('#export').click()
            exported = folder / 'blue.png'
            downloaded.value.save_as(exported)
            with Image.open(exported) as image:
                assert image.size == (800, 360)
                pixels = np.array(image.convert('RGB'))
                assert ((pixels[:, :, 2] > 150) & (pixels[:, :, 0] < 80) & (pixels[:, :, 1] < 80)).any(), 'Export must contain blue glyphs'
            print('PASS: real upload -> PaddleOCR -> selected heading blue -> PNG with blue pixels', flush=True)

            command('All text white')
            assert page.evaluate('testCanvas.getObjects().every(o => o.fill === "#ffffff")')
            print('PASS: every editable layer becomes white', flush=True)
            command('Bold heading')
            assert page.evaluate('testCanvas.getActiveObject().fontWeight') == 'bold'
            command('Change title color to red')
            assert page.evaluate('testCanvas.getActiveObject().fill') == '#ff0000'
            old_size = page.evaluate('testCanvas.getActiveObject().fontSize')
            command('Make heading bigger')
            assert page.evaluate('testCanvas.getActiveObject().fontSize') > old_size
            command('Change SALE to MEGA SALE')
            assert page.evaluate('testCanvas.getActiveObject().text') == 'SUMMER MEGA SALE'
            command('Rotate selected text 15 degrees')
            assert page.evaluate('testCanvas.getActiveObject().angle') == 15
            old_top = page.evaluate('testCanvas.getActiveObject().top')
            command('Center selected text')
            bounds = page.evaluate('testCanvas.getActiveObject().getBoundingRect(true, true)')
            assert abs(bounds['left'] + bounds['width']/2 - 400) < .01
            assert page.evaluate('testCanvas.getActiveObject().top') == old_top
            print('PASS: bold, title color, size, replacement, rotation, horizontal centering', flush=True)

            before = current()
            command('Delete all graphics', success=False)
            assert current() == before
            assert page.evaluate('testCanvas.getActiveObject().layerId') == heading
            # A partially valid response must not apply even its first patch.
            page.route('**/api/edit-text', lambda route: route.fulfill(json={'changes':[
                {'id':heading, 'properties':{'color':'#0000ff'}},
                {'id':'unknown', 'properties':{'color':'#0000ff'}}]}))
            command('Blue text', success=False)
            assert current() == before
            page.unroute('**/api/edit-text')
            print('PASS: failed command and malformed response leave canvas/selection unchanged', flush=True)

            # Exercise rollback after the first object has already been updated.
            page.evaluate('''() => {
              const object = testCanvas.getObjects()[1], originalSet = object.set;
              object.set = function(key, value) {
                if (key && key.fill === '#0000ff') {
                  this.set = originalSet;
                  throw new Error('Injected setter failure');
                }
                return originalSet.call(this, key, value);
              };
            }''')
            command('All text blue', success=False)
            assert current() == before
            assert page.evaluate('testCanvas.getActiveObject().layerId') == heading
            print('PASS: runtime failure rolls back partially applied edits', flush=True)

            page.evaluate('testCanvas.discardActiveObject(); testCanvas.requestRenderAll()')
            command('Blue text', success=False)
            assert 'Select a text layer' in page.locator('#commandMessage').inner_text()
            page.locator('#addText').click()
            command('Blue text')
            assert page.evaluate('testCanvas.getActiveObject().fill') == '#0000ff'
            assert page.evaluate('testCanvas.getActiveObject().confidence == null')
            page.locator('#deleteText').click()
            after = current()
            assert [o['layerId'] for o in after['objects']] == original_ids
            assert after['backgroundImage'] == original_background
            assert not errors, errors
            print('PASS: manual layers without confidence, no duplicates, original background retained', flush=True)
            browser.close()
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
