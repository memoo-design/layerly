"""Optional real-browser integration checks: python browser_command_checks.py.
Requires test-only Playwright and installed Edge; OCR models must be available.
"""
import tempfile
import threading
import json
import argparse
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from app import app
from browser_interactions import verify_interactions, verify_drop


def main(browser_name='msedge'):
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
            browser = (playwright.firefox.launch(headless=True) if browser_name == 'firefox'
                       else playwright.chromium.launch(channel=browser_name, headless=True))
            context = browser.new_context(accept_downloads=True, ignore_https_errors=True, viewport={'width':1440,'height':1000})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='domcontentloaded', timeout=90000)
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
            verify_drop(page, upload)
            page.locator('#extract').click()
            page.locator('#editor').wait_for(state='visible', timeout=300000)
            assert page.evaluate('testCanvas.getObjects().length') >= 2
            page.locator('.layer-select').filter(has_text='SUMMER SALE').click()
            heading = page.evaluate('testCanvas.getActiveObject().layerId')
            initial = page.evaluate('testCanvas.toJSON(["layerId", "confidence"])')
            original_background = initial['backgroundImage']
            original_ids = [item['layerId'] for item in initial['objects']]
            with page.expect_download() as downloaded:
                page.locator('#export').click()
            downloaded.value.save_as(folder / 'initial.png')
            with Image.open(folder / 'initial.png') as image:
                rendered = np.array(image.convert('RGB'))[:180]
                reference = np.array(poster)[:180]
                def ink_box(rgb):
                    ys, xs = np.where((rgb < 100).all(axis=2))
                    return np.array([xs.min(),ys.min(),xs.max(),ys.max()])
                position_error = int(np.abs(ink_box(rendered)-ink_box(reference)).max())
                assert position_error <= 12, ('Rendered heading drift', position_error)
                print('PASS: initial editable heading ink bounds within', position_error, 'pixels of source', flush=True)

            def command(text, success=True):
                page.locator('#commandPrompt').fill(text)
                page.locator('#applyCommand').click()
                kind = 'success' if success else 'error'
                page.wait_for_function('() => ["success", "error"].includes(document.getElementById("commandMessage").dataset.kind)')
                actual = page.locator('#commandMessage').get_attribute('data-kind')
                assert actual == kind, (text, page.locator('#commandMessage').inner_text(), errors)

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
            with page.expect_download() as downloaded:
                page.locator('#export').click()
            downloaded.value.save_as(folder / 'white.png')
            with Image.open(folder / 'white.png') as image:
                assert np.array(image.convert('RGB')).min() > 240, 'Original dark text must not reappear under editable layers'
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
            # Each edit must restore actual canvas data, including deletion and AI edits.
            def history_click(button, expected):
                page.locator(button).click()
                page.wait_for_function('(expected) => JSON.stringify(testCanvas.toJSON(["layerId", "confidence"])) === expected',
                    arg=json.dumps(expected, separators=(',', ':')))

            page.locator('.layer-select').filter(has_text='SUMMER MEGA SALE').click()
            before = current()
            command('Increase the title font size.')
            enlarged = current()
            history_click('#undo', before)
            history_click('#redo', enlarged)
            command('Remove the bottom text.')
            removed = current()
            assert len(removed['objects']) == len(enlarged['objects']) - 1
            history_click('#undo', enlarged)
            history_click('#redo', removed)
            history_click('#undo', enlarged)
            page.locator('.layer-select').filter(has_text='Open today').click()
            command("Change the subtitle to 'Welcome to Layerly'.")
            assert page.locator('#textContent').input_value() == 'Welcome to Layerly'
            for selector, value in [('#textContent', 'Edited manually'), ('#posX', '100'),
                                    ('#posY', '210'), ('#fontSize', '25'),
                                    ('#layerWidth', '240'), ('#layerHeight', '40'),
                                    ('#rotation', '-10'), ('#textColor', '#008000'),
                                    ('#lineHeight', '1.5'), ('#charSpacing', '60')]:
                before = current()
                page.locator(selector).fill(value)
                page.locator(selector).dispatch_event('change')
                page.locator(selector).blur()
                edited = current()
                assert edited != before, selector
                history_click('#undo', before)
                history_click('#redo', edited)
            for selector, value in [('#fontFamily', 'Georgia'), ('#alignment', 'right')]:
                before = current()
                page.locator(selector).select_option(value)
                page.wait_for_function('(v) => testCanvas.getActiveObject()[v[0]] === v[1]',
                    arg=['fontFamily' if selector == '#fontFamily' else 'textAlign', value])
                edited = current()
                history_click('#undo', before)
                history_click('#redo', edited)
            before = current()
            page.locator('#addText').click()
            added = current()
            history_click('#undo', before)
            history_click('#redo', added)
            page.locator('.layer-select').filter(has_text='New text').click()
            page.locator('#deleteText').click()
            history_click('#undo', added)
            history_click('#redo', before)
            print('PASS: manual text, position, size, color, font, alignment, add/delete history; original text absent from export', flush=True)
            before = current()
            page.locator('#zoomIn').click()
            page.locator('#zoomOut').click()
            page.locator('#zoomLabel').click()
            assert page.evaluate('testCanvas.getZoom()') == 1
            assert current() == before
            page.locator('#fit').click()
            with page.expect_download() as downloaded:
                page.locator('#export').click()
            downloaded.value.save_as(folder / 'after-zoom.png')
            with Image.open(folder / 'after-zoom.png') as image:
                assert image.size == (800, 360)
            verify_interactions(page, folder)
            # A tab retains decoded pixels even if the server background is gone.
            page.route('**/api/projects/**/background*', lambda route: route.fulfill(status=404, json={'error':'expired'}))
            page.locator('#textColor').fill('#00ff00')
            page.locator('#textColor').dispatch_event('change')
            page.locator('#undo').click()
            page.wait_for_function('!document.getElementById("properties").disabled')
            with page.expect_download() as downloaded:
                page.locator('#export').click()
            downloaded.value.save_as(folder / 'expired-session.png')
            with Image.open(folder / 'expired-session.png') as image:
                assert image.size == (800,360)
                assert (np.array(image.convert('RGB')) < 100).any()
            page.unroute('**/api/projects/**/background*')
            print('PASS: history and export retain decoded background after lease expiry', flush=True)
            page.set_viewport_size({'width':390, 'height':844})
            assert page.locator('#applyCommand').is_visible()
            assert page.locator('#properties').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            print('PASS: AI edit/delete undo-redo, subtitle, zoom-independent export, mobile layout', flush=True)
            artifacts = Path('verification') / browser_name
            artifacts.mkdir(parents=True, exist_ok=True)
            for filename in ('initial.png', 'blue.png', 'white.png', 'after-zoom.png', 'order-blue.png', 'order-red.png', 'expired-session.png'):
                shutil.copyfile(folder / filename, artifacts / filename)
            page.screenshot(path=str(artifacts / 'mobile.png'), full_page=True)
            (artifacts / 'result.json').write_text(json.dumps(dict(browser=browser_name, version=browser.version,
                page_errors=errors, workflow='passed', pointer_gestures='passed', export_pixel_checks='passed',
                heading_bounds_max_error_px=position_error), indent=2))
            browser.close()
    finally:
        server.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=['msedge','chrome','firefox'], default='msedge')
    main(parser.parse_args().browser)
