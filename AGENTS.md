# Scan Rescue Studio Instructions

Local Python 3.11+ document scanner using OpenCV and Streamlit. Keep document
processing local, private, and in memory. Never commit uploads, generated scans,
personal documents, model weights, caches, environments, or other large binary
artifacts.

## Essential paths

- `app.py`: upload validation, session state, automatic scan preview, and PNG
  download.
- `docu_scanner.py`: reusable OpenCV pipeline and CLI. Importing it must not
  parse arguments, read files, or open windows.
- `tests/`: regression and OpenCode workflow tests.
- `requirements.txt`: minimal runtime dependencies.
- `README.md`: user-facing setup, behavior, limits, and features.
- `scan_widgets.py`: legacy component code not used by the simplified app;
  change it only when explicitly requested.
- `CV and YOLO/segmentation.py`: isolated experiment, not scanner runtime;
  change it only when explicitly requested.
- `.opencode/`, `opencode.jsonc`, and this file: agent workflow configuration.

## OpenCode workflow

- Full is the default. `sol-orchestrator` uses
  `AgentRouter-openai-gateway/gpt-6.1-sol#medium`, delegates every implementation
  edit to `sol-implementer` using
  `AgentRouter-openai-gateway/gpt-5.6-sol#medium`, reviews integration, and
  personally runs final verification. If that implementer profile is missing or
  mismatched, stop and report the blocker; do not substitute another agent.
- Only the user may select Quick with `/quick`. Quick is for small, bounded,
  low-risk work performed directly. For security-sensitive work, upload
  validation/privacy changes, or coordinated cross-module changes, stop before
  editing and ask the user to select Full with `/full`.
- Existing sessions do not auto-switch. Use the updated `/full <task>` or start a
  fresh session when the stored agent/model is stale. Do not self-switch modes,
  agents, or models.
- The definitions in `.opencode/agents/` and `.opencode/commands/` are the source
  of truth for detailed permissions. Higher-priority session instructions still
  apply.

## Scanner contracts

- Scanner inputs are three-channel `uint8` **BGR** NumPy arrays; Pillow and
  Streamlit images are **RGB**. Convert explicitly at boundaries.
- `scan_document(image)` returns `(scanned, perspective_corrected)`: a 2-D
  `uint8` black-and-white image and a boolean.
- `enhance_document` accepts only `black-and-white`, `grayscale`, and `color`;
  color output is BGR and the others are grayscale.
- Corners are clockwise: top-left, top-right, bottom-right, bottom-left. Reject
  crossed, duplicate, non-finite, or out-of-bounds corners.
- Preserve the 20 MB upload limit, 200-million-pixel source limit, 3-pixel
  minimum dimension, and 2,000-pixel processing long edge with no upscaling
  unless the requirements explicitly change.
- Automatic page detection is best effort. On failure, enhance the whole image
  and show the existing perspective-correction warning.
- Keep uploads and results in the current in-memory Streamlit session. Replacing,
  removing, or failing to process an upload must clear the previous preview and
  download.
- Keep workflow state under the `rescue_` prefix. Preserve keyboard, touch, and
  focus accessibility.

## Change rules

- Inspect behavior and call sites before editing. Make the smallest relevant
  change, preserve public contracts, and do not overwrite unrelated user work.
- Validate untrusted metadata and values before expensive OpenCV work. Convert
  low-level failures into concise errors without exposing document contents.
- Prefer existing modules and dependencies. Update `requirements.txt` and
  `README.md` when setup or user-visible behavior changes.
- Do not add network services, telemetry, external scripts, persistent storage,
  OCR, PDF output, or batch processing unless explicitly requested.
- Match existing Python style and use synthetic, non-sensitive test images.
- Use desktop `opencv-python`, not `opencv-python-headless`, because the CLI uses
  `cv2.imshow`.

## Run and verify

Run from the repository root:

```powershell
python -m streamlit run app.py
python docu_scanner.py "C:\path\to\document.jpg"
```

Minimum final checks:

```powershell
python -m compileall app.py docu_scanner.py scan_widgets.py
python -c "import app, docu_scanner, scan_widgets"
python -c "import numpy as np; from docu_scanner import scan_document; image = np.full((100, 80, 3), 255, dtype=np.uint8); scanned, corrected = scan_document(image); assert scanned.ndim == 2 and scanned.dtype == np.uint8; assert isinstance(corrected, bool)"
python -m unittest discover -s tests -p "test_*.py"
git diff --check
```

For UI changes, exercise upload, automatic result, replacement/removal, fallback,
error, and download paths on desktop and mobile. For image-processing changes,
check a bounded page, whole-image fallback, invalid corners, and every affected
style. Review the diff for privacy, accessibility, stale state, RGB/BGR mistakes,
size limits, and documentation drift. Report changed files, check results, and
anything not verified.
