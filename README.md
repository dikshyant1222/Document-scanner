# Document Scanner - Scan Rescue Studio

A Python/OpenCV document scanner with a simple local Streamlit web app. Upload one document photo, let the app scan it automatically, preview the black-and-white result, and download it as a PNG.

## Setup

Use Python 3.11 or newer. Run these commands from the repository folder in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell does not allow activation, use `.\.venv\Scripts\python.exe` instead of `python` in the commands below.

The requirements use desktop `opencv-python` so the original CLI image window still works. Do not install `opencv-python-headless` into the same environment.

## Web app

```powershell
python -m streamlit run app.py
```

Open the local URL printed in the terminal, usually `http://localhost:8501`.

1. Upload one JPG/JPEG, PNG, WebP, or BMP image from any folder. No image needs to be copied into the repository.
2. The app automatically detects the page and creates a black-and-white scan using the default scanner pipeline.
3. Review the single scanned-result preview, then use **Download scanned PNG** to save `<original-name>_scanned.png`.

For the best perspective correction, include one clearly visible, four-cornered page against a contrasting background. The scanner checks both saturation and edge contours before correcting perspective, reducing noise, enhancing contrast, and producing the black-and-white result.

If no usable page boundary is found, the app enhances the whole image instead and warns that perspective correction was skipped. Automatic detection is best effort and is not guaranteed for every photo.

Uploads are limited to **20 MB** and **200 million pixels (200 MP)**. Images must be at least 3 pixels wide and tall. Phone-photo EXIF orientation is applied, grayscale images are supported, and transparency is composited onto white. Higher-resolution images are automatically downsized for processing and previews, preserving aspect ratio with a maximum **2,000-pixel long edge** and no upscaling. Downloads use the processed resolution, not necessarily the original photo resolution.

Uploads and scanned results stay in private in-memory Streamlit session state on the computer running the app; there is no shared image cache, saved document file, scan history, or persistent storage. Replacing or removing a file with the native uploader clears its previous result and download, and an invalid upload cannot expose a stale result. Input photos are intentionally not tracked in Git. Keep personal documents and contact details out of public commits.

This version runs locally and handles one image at a time. The simplified web app does not expose manual corner editing or alternate enhancement settings. OCR, PDF export, batch scanning, camera capture, redaction, and public deployment are not included.

## Command-line scanner

```powershell
python docu_scanner.py "C:\path\to\your-document.jpg"
```

The result appears in the **Scanned Image** window; press any key in that window to close it. The CLI displays the result but does not save an output file. It uses the same scanner and whole-image fallback as the web app.

If no image path is supplied, the CLI uses a local `imig.jpg` in the current working directory. Provide your own image; the sample is not included in Git.

For Python callers, `scan_document(image)` in `docu_scanner.py` accepts a three-channel, 8-bit BGR NumPy array and returns `(scanned, perspective_corrected)`: a grayscale black-and-white array and a boolean. Importing the module does not parse arguments, read files, or open windows.

The scanner module also exposes `warp_document(image, corners)` for four distinct, finite, in-bounds clockwise pixel coordinates of shape `(4, 2)`, and `enhance_document(image, *, style='black-and-white', remove_shadows=False, denoise_strength=8, contrast=1.0, threshold_offset=10)`. Enhancement styles are `black-and-white`, `grayscale`, and `color`; color returns a BGR array and other styles return a grayscale array. These options remain available to Python callers but are not exposed in the simplified web app. The default `scan_document(image)` behavior and CLI interface remain unchanged.

## Other tracked code

`CV and YOLO/segmentation.py` remains in the repository as a separate YOLO segmentation experiment. It is not part of the document scanner and is not required to run it. The scanner's requirements do not include YOLO dependencies; local experiment videos and model weights are not included.

`.gitignore` keeps local images, videos, model weights, Python caches, and unrelated practice scripts out of new commits. It does not untrack the existing segmentation file.

## OpenCode workflow

OpenCode auto-loads `AGENTS.md`. **Full** stays the default for new sessions;
**Quick** is an explicit user choice, never automatic.

- **Full:** choose for security-sensitive work, upload validation/privacy
  changes, coordinated cross-module changes, or work needing separate review.
  Use `/full <task>` to select **both** `sol-orchestrator` and
  `AgentRouter-openai-gateway/gpt-6.1-sol#medium`. The Sol orchestrator delegates
  every implementation edit to `sol-implementer` using
  `AgentRouter-openai-gateway/gpt-5.6-sol#medium`, reviews the diff, and personally
  runs final verification. If that profile is missing or its model is mismatched,
  stop and report the blocker; never substitute another profile or an inherited
  model.
- **Quick:** choose only for tiny, bounded, low-risk tasks. Use `/quick <task>`
  to select **both** `sol-direct` and
  `AgentRouter-openai-gateway/gpt-6.1-sol#medium`. Sol Direct implements,
  reviews its diff, and runs required checks without delegation or extra
  planning/handoff. Quick removes the separate orchestrator review, **not tests**.
  `sol-direct` remains primary-only, not an orchestrator subagent or fallback. For
  unsuitable work, stop before editing and ask the user to select Full with
  `/full <task>`; do not self-switch agents/models.

For example, enter these commands in OpenCode:

```text
/quick Fix a typo in the README setup section.
/full Add a scan feature spanning the pipeline and UI.
```

Both commands select the primary agent and exact model/variant in the **current
session** (`subagent: false`), without a child session or handoff. The selections
persist for subsequent messages until changed. Use `/full <task>` to return
from Quick or recover a mismatched primary session. With no task, either
command asks what to work on without editing.

Existing sessions do not auto-switch when defaults change. To migrate, invoke
the updated `/full <task>` or start a fresh session. Sessions store the selected
model separately from the agent; choosing a primary agent by ID alone does not
change that stored model, whereas these commands explicitly select both. Manual
agent and model/variant selection remains valid; choose both exact values above.
Command files and project configuration hot-reload; no OpenCode restart is
required.

These are user-invoked selectors, not a way for the Sol orchestrator or its
children to bypass current-session editing/delegation restrictions. These
profiles do not override higher-priority current-session instructions or
permissions.
