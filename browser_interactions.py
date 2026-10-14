"""Real Playwright pointer events and exported-pixel stacking checks."""
import json
import numpy as np
from PIL import Image


def verify_interactions(page, folder):
    def snapshot():
        return page.evaluate('testCanvas.toJSON(["layerId", "confidence"])')

    def restore(button, expected):
        page.locator(button).click()
        page.wait_for_function('(v) => JSON.stringify(testCanvas.toJSON(["layerId", "confidence"])) === v',
                               arg=json.dumps(expected, separators=(',', ':')))

    def point(control=None):
        return page.evaluate('''(control) => {
          const c=testCanvas, o=c.getActiveObject(), r=c.upperCanvasEl.getBoundingClientRect();
          o.setCoords();
          const p=control ? o.oCoords[control] : fabric.util.transformPoint(o.getCenterPoint(), c.viewportTransform);
          return {x:r.left+p.x, y:r.top+p.y};
        }''', control)

    def drag(start, dx, dy):
        page.mouse.move(start['x'], start['y'])
        page.mouse.down()
        page.mouse.move(start['x']+dx, start['y']+dy, steps=12)
        page.mouse.up()

    page.locator('.layer-select').first.click()
    page.locator('#fit').click()
    page.locator('#zoomOut').click()
    page.locator('#zoomOut').click()
    before = snapshot()
    old = page.evaluate('({x:testCanvas.getActiveObject().left, y:testCanvas.getActiveObject().top, z:testCanvas.getZoom()})')
    center = point()
    blank = page.evaluate('''() => {const r=testCanvas.upperCanvasEl.getBoundingClientRect();return {x:r.left+8,y:r.bottom-8};}''')
    page.mouse.click(blank['x'], blank['y'])
    page.mouse.click(center['x'], center['y'])
    assert page.evaluate('!!testCanvas.getActiveObject()')
    assert not page.evaluate('testCanvas.getActiveObject().isEditing')
    drag(point(), 32, 18)
    moved = snapshot()
    pos = page.evaluate('({x:testCanvas.getActiveObject().left, y:testCanvas.getActiveObject().top})')
    assert abs(pos['x']-old['x']-32/old['z']) < 2
    assert abs(pos['y']-old['y']-18/old['z']) < 2
    restore('#undo', before)
    restore('#redo', moved)
    before = snapshot()
    scale = page.evaluate('testCanvas.getActiveObject().scaleX')
    drag(point('br'), 28, 20)
    resized = snapshot()
    assert abs(page.evaluate('testCanvas.getActiveObject().scaleX')-scale) > .01
    restore('#undo', before)
    restore('#redo', resized)
    before = snapshot()
    angle = page.evaluate('testCanvas.getActiveObject().angle')
    drag(point('mtr'), 35, 10)
    rotated = snapshot()
    assert abs(page.evaluate('testCanvas.getActiveObject().angle')-angle) > 1
    restore('#undo', before)
    restore('#redo', rotated)
    page.locator('#textContent').fill('Moved and edited')
    page.locator('#textContent').blur()
    assert page.evaluate('testCanvas.getActiveObject().text') == 'Moved and edited'

    # Overlap identical glyphs in two colors to verify export draw order.
    for selector, value in [('#rotation','0'), ('#posX','80'), ('#posY','100'), ('#textColor','#ff0000')]:
        page.locator(selector).fill(value)
        page.locator(selector).dispatch_event('change')
    source = page.evaluate('testCanvas.getActiveObject().toObject(["layerId", "confidence"])')
    before = snapshot()
    page.locator('#duplicateText').click()
    page.wait_for_function('(id) => testCanvas.getActiveObject().layerId !== id', arg=source['layerId'])
    duplicate = page.evaluate('testCanvas.getActiveObject().toObject(["layerId", "confidence"])')
    for key in ('text','fontFamily','fontWeight','fontSize','fill','scaleX','scaleY','angle','styles'):
        assert duplicate[key] == source[key], key
    assert duplicate['left'] == source['left']+16
    assert duplicate['top'] == source['top']+16
    added = snapshot()
    restore('#undo', before)
    restore('#redo', added)
    page.locator('.layer-select').first.click()
    page.locator('#textContent').fill('Independent duplicate')
    page.locator('#textContent').blur()
    assert page.evaluate('(id) => testCanvas.getObjects().find(o=>o.layerId===id).text', source['layerId']) == source['text']
    page.locator('#textContent').fill(source['text'])
    page.locator('#textContent').blur()
    for selector, value in [('#posX',str(source['left'])), ('#posY',str(source['top'])), ('#textColor','#0000ff')]:
        page.locator(selector).fill(value)
        page.locator(selector).dispatch_event('change')
    background = snapshot()['backgroundImage']
    for button, index in [('#sendBack',0), ('#bringForward',1), ('#bringFront',len(snapshot()['objects'])-1), ('#sendBackward',len(snapshot()['objects'])-2)]:
        before = snapshot()
        page.locator(button).click()
        assert page.evaluate('testCanvas.getObjects().indexOf(testCanvas.getActiveObject())') == index
        reordered = snapshot()
        restore('#undo', before)
        restore('#redo', reordered)
        assert snapshot()['backgroundImage'] == background

    frames = {}
    for button, color in [('#bringFront','blue'), ('#sendBack','red')]:
        page.locator(button).click()
        with page.expect_download() as downloaded:
            page.locator('#export').click()
        target = folder / f'order-{color}.png'
        downloaded.value.save_as(target)
        with Image.open(target) as image:
            assert image.size == (800,360)
            rgb = np.array(image.convert('RGB'))
            frames[color] = rgb
            blue = ((rgb[:,:,2]>180)&(rgb[:,:,0]<80)).sum()
            red = ((rgb[:,:,0]>180)&(rgb[:,:,2]<80)).sum()
            assert (blue > 100 if color == 'blue' else red > 100), (color,red,blue)
    blue_top = (frames['blue'][:,:,2]>180)&(frames['blue'][:,:,0]<80)
    red_top = (frames['red'][:,:,0]>180)&(frames['red'][:,:,2]<80)
    assert (blue_top & red_top).sum() > 200, 'Overlapping glyph pixels must change with draw order'
    print('PASS: actual mouse drag/resize/rotate, edit after moving, transform history, independent duplication, four reorder controls and exported pixel stacking', flush=True)


def verify_drop(page, poster):
    import base64
    data = page.evaluate_handle('''({encoded,name,type}) => {
      const dt=new DataTransfer(); dt.items.add(new File([Uint8Array.from(atob(encoded),c=>c.charCodeAt(0))],name,{type})); return dt;
    }''', dict(encoded=base64.b64encode(poster.read_bytes()).decode(), name='dropped.png', type='image/png'))
    page.locator('#dropZone').dispatch_event('dragenter', {'dataTransfer':data})
    assert 'dragging' in page.locator('#dropZone').get_attribute('class')
    page.locator('#dropZone').dispatch_event('drop', {'dataTransfer':data})
    page.wait_for_function('document.getElementById("fileDetails").textContent.includes("dropped.png")')
    assert 'dragging' not in page.locator('#dropZone').get_attribute('class')
    invalid = page.evaluate_handle('''() => {const d=new DataTransfer();d.items.add(new File(['bad'],'bad.txt',{type:'text/plain'}));return d;}''')
    page.locator('#dropZone').dispatch_event('drop', {'dataTransfer':invalid})
    assert 'PNG or JPEG' in page.locator('#uploadMessage').inner_text()
    # Replacing the preview through the picker continues to use the same validator.
    page.locator('#fileInput').set_input_files(str(poster))
    page.wait_for_function('document.getElementById("fileDetails").textContent.includes("poster.png")')
    jpeg = poster.with_suffix('.jpg')
    with Image.open(poster) as image:
        image.save(jpeg)
    jpg_data = page.evaluate_handle('''(encoded) => {
      const dt=new DataTransfer(); dt.items.add(new File([Uint8Array.from(atob(encoded),c=>c.charCodeAt(0))],'dropped.jpg',{type:'image/jpeg'})); return dt;
    }''', base64.b64encode(jpeg.read_bytes()).decode())
    page.locator('#dropZone').dispatch_event('drop', {'dataTransfer':jpg_data})
    page.wait_for_function('document.getElementById("fileDetails").textContent.includes("dropped.jpg")')
    page.locator('#fileInput').set_input_files(str(poster))
    page.wait_for_function('document.getElementById("fileDetails").textContent.includes("poster.png")')
    print('PASS: browser DataTransfer drop, visual feedback, invalid file error and picker replacement', flush=True)
