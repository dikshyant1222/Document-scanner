import base64

import cv2
import streamlit as st

from docu_scanner import resize_image


EDITOR_HTML = """
<div class="editor-shell">
  <div class="photo-stage">
    <img class="photo" alt="Uploaded document with editable page corners" draggable="false">
    <svg class="outline" aria-hidden="true"><polygon></polygon></svg>
    <button type="button" class="corner" data-index="0" aria-label="Top-left document corner">1</button>
    <button type="button" class="corner" data-index="1" aria-label="Top-right document corner">2</button>
    <button type="button" class="corner" data-index="2" aria-label="Bottom-right document corner">3</button>
    <button type="button" class="corner" data-index="3" aria-label="Bottom-left document corner">4</button>
  </div>
  <p class="editor-hint" role="status">Drag the numbered handles, or focus one and use arrow keys. Shift + arrow moves 10 pixels.</p>
</div>
"""

EDITOR_CSS = """
.editor-shell { padding: 18px; color: var(--st-text-color); font-family: inherit; }
.photo-stage { position: relative; margin: 0 auto; width: 100%; }
.photo { display: block; width: 100%; height: 100%; border-radius: 8px; }
.outline { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.outline polygon { fill: #22c55e18; stroke: #16a34a; stroke-width: 2; vector-effect: non-scaling-stroke; }
.corner { position: absolute; width: 30px; height: 30px; border: 2px solid white; border-radius: 50%; background: #15803d; color: white; font-weight: bold; transform: translate(-50%, -50%); cursor: grab; touch-action: none; padding: 0; box-shadow: 0 1px 5px #0008; }
.corner:active { cursor: grabbing; }
.corner:focus-visible { outline: 3px solid #f59e0b; outline-offset: 3px; }
.editor-hint { font-size: 0.8rem; line-height: 1.5; margin: 22px 0 0; opacity: 0.8; }
"""

EDITOR_JS = r"""
export default function(component) {
  const { data, parentElement, setStateValue } = component;
  const stage = parentElement.querySelector('.photo-stage');
  const photo = parentElement.querySelector('.photo');
  const outline = parentElement.querySelector('.outline');
  const polygon = outline.querySelector('polygon');
  const handles = [...parentElement.querySelectorAll('.corner')];
  const hint = parentElement.querySelector('.editor-hint');
  let points = data.corners.map(point => [...point]);
  let activeHandle = null;
  let startPoints = null;
  let keyboardStart = null;
  const listeners = [];
  const listen = (target, name, handler) => {
    target.addEventListener(name, handler);
    listeners.push(() => target.removeEventListener(name, handler));
  };
  const clamp = value => Math.min(1, Math.max(0, value));
  const snapshot = () => points.map(point => [...point]);
  const changed = previous => JSON.stringify(previous) !== JSON.stringify(points);
  const commit = previous => {
    if (previous && changed(previous)) setStateValue('corners', snapshot());
  };
  const render = () => {
    polygon.setAttribute('points', points.map(point =>
      (point[0] * (data.width - 1)) + ',' + (point[1] * (data.height - 1))).join(' '));
    handles.forEach((handle, index) => {
      handle.style.left = (points[index][0] * 100) + '%';
      handle.style.top = (points[index][1] * 100) + '%';
      handle.setAttribute('aria-description',
        'Image position ' + Math.round(points[index][0] * (data.width - 1)) + ', ' +
        Math.round(points[index][1] * (data.height - 1)));
    });
  };
  photo.src = data.image;
  stage.style.aspectRatio = data.width + ' / ' + data.height;
  stage.style.maxWidth = (600 * data.width / data.height) + 'px';
  outline.setAttribute('viewBox', '0 0 ' + (data.width - 1) + ' ' + (data.height - 1));
  render();
  handles.forEach((handle, index) => {
    listen(handle, 'pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      handle.focus({ preventScroll: true });
      activeHandle = index;
      startPoints = snapshot();
      handle.setPointerCapture(event.pointerId);
    });
    listen(handle, 'pointermove', event => {
      if (activeHandle !== index) return;
      const bounds = stage.getBoundingClientRect();
      if (bounds.width <= 0 || bounds.height <= 0) return;
      points[index] = [
        clamp((event.clientX - bounds.left) / bounds.width),
        clamp((event.clientY - bounds.top) / bounds.height),
      ].map(value => Number(value.toFixed(8)));
      render();
    });
    listen(handle, 'pointerup', event => {
      if (activeHandle !== index) return;
      const previous = startPoints;
      activeHandle = null;
      startPoints = null;
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      hint.textContent = 'Corner updated. Click Apply changes to regenerate the scan.';
      commit(previous);
    });
    listen(handle, 'pointercancel', () => {
      if (activeHandle !== index) return;
      points = startPoints;
      activeHandle = null;
      startPoints = null;
      render();
    });
    listen(handle, 'keydown', event => {
      const directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
      if (!(event.key in directions)) return;
      event.preventDefault();
      if (!keyboardStart) keyboardStart = snapshot();
      const direction = directions[event.key];
      const step = event.shiftKey ? 10 : 1;
      points[index] = [
        clamp(points[index][0] + direction[0] * step / (data.width - 1)),
        clamp(points[index][1] + direction[1] * step / (data.height - 1)),
      ];
      render();
    });
    const finishKeyboard = () => {
      const previous = keyboardStart;
      keyboardStart = null;
      commit(previous);
    };
    listen(handle, 'keyup', event => {
      if (event.key.startsWith('Arrow')) finishKeyboard();
    });
    listen(handle, 'blur', finishKeyboard);
  });
  return () => listeners.forEach(remove => remove());
}
"""

COMPARISON_HTML = """
<div class="comparison-shell">
  <div class="comparison-stage">
    <img class="before" alt="Page before cleanup" draggable="false">
    <img class="after" alt="Applied scan after cleanup" draggable="false">
    <span class="label before-label">Before cleanup</span>
    <span class="label after-label">Applied scan</span>
    <div class="divider" aria-hidden="true"><span>↔</span></div>
  </div>
  <input class="split-range" type="range" min="0" max="100" value="50" aria-label="Before and after comparison split">
</div>
"""

COMPARISON_CSS = """
.comparison-shell { font-family: inherit; }
.comparison-stage { position: relative; width: 100%; margin: 0 auto; overflow: hidden; border-radius: 8px; touch-action: none; cursor: ew-resize; }
.comparison-stage img { display: block; width: 100%; height: 100%; }
.after { position: absolute; inset: 0; }
.label { position: absolute; top: 12px; background: #000b; color: white; padding: 5px 9px; border-radius: 5px; font-size: 0.75rem; pointer-events: none; }
.before-label { left: 12px; }
.after-label { right: 12px; }
.divider { position: absolute; top: 0; bottom: 0; width: 2px; background: white; transform: translateX(-1px); pointer-events: none; box-shadow: 0 0 3px #0008; }
.divider span { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; color: #111; border-radius: 50%; padding: 7px; box-shadow: 0 1px 5px #0008; }
.split-range { display: block; width: 100%; margin: 18px 0 8px; accent-color: #15803d; }
"""

COMPARISON_JS = r"""
export default function(component) {
  const { data, parentElement } = component;
  const shell = parentElement.querySelector('.comparison-shell');
  const stage = parentElement.querySelector('.comparison-stage');
  const before = parentElement.querySelector('.before');
  const after = parentElement.querySelector('.after');
  const divider = parentElement.querySelector('.divider');
  const range = parentElement.querySelector('.split-range');
  let dragging = false;
  const listeners = [];
  const listen = (target, name, handler) => {
    target.addEventListener(name, handler);
    listeners.push(() => target.removeEventListener(name, handler));
  };
  const update = value => {
    const position = Math.min(100, Math.max(0, Number(value)));
    after.style.clipPath = 'inset(0 0 0 ' + position + '%)';
    divider.style.left = position + '%';
    range.value = String(position);
    shell.dataset.position = String(position);
  };
  before.src = data.before;
  after.src = data.after;
  stage.style.aspectRatio = data.width + ' / ' + data.height;
  stage.style.maxWidth = (600 * data.width / data.height) + 'px';
  update(shell.dataset.position ?? 50);
  listen(range, 'input', () => update(range.value));
  const fromPointer = event => {
    const bounds = stage.getBoundingClientRect();
    if (bounds.width > 0) update(100 * (event.clientX - bounds.left) / bounds.width);
  };
  listen(stage, 'pointerdown', event => {
    if (event.button !== 0) return;
    dragging = true;
    stage.setPointerCapture(event.pointerId);
    fromPointer(event);
  });
  listen(stage, 'pointermove', event => { if (dragging) fromPointer(event); });
  listen(stage, 'pointerup', event => {
    dragging = false;
    if (stage.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId);
  });
  listen(stage, 'pointercancel', () => { dragging = false; });
  return () => listeners.forEach(remove => remove());
}
"""

_corner_component = st.components.v2.component(
    'scan_rescue_corner_editor', html=EDITOR_HTML, css=EDITOR_CSS, js=EDITOR_JS,
)
_comparison_component = st.components.v2.component(
    'scan_rescue_comparison', html=COMPARISON_HTML, css=COMPARISON_CSS, js=COMPARISON_JS,
)


def image_data_uri(image, *, bgr=False):
    preview = resize_image(image, 1000)
    if preview.ndim == 3 and not bgr:
        preview = cv2.cvtColor(preview, cv2.COLOR_RGB2BGR)
    encoded, payload = cv2.imencode('.png', preview)
    if not encoded:
        raise ValueError('Could not prepare the image preview.')
    return 'data:image/png;base64,' + base64.b64encode(payload.tobytes()).decode('ascii')


def corner_editor(image_uri, corners, image_shape, *, key):
    height, width = image_shape[:2]
    return _corner_component(
        data={'image': image_uri, 'corners': corners, 'width': width, 'height': height},
        default={'corners': corners},
        on_corners_change=lambda: None,
        key=key,
    ).corners


def compare_scans(before_uri, after_uri, image_shape, *, key):
    height, width = image_shape[:2]
    _comparison_component(
        data={'before': before_uri, 'after': after_uri, 'width': width, 'height': height},
        key=key,
    )
