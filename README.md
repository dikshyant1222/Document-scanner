# Document Scanner - Scan Rescue Studio

A Python/OpenCV document scanner with a local Streamlit web app. Upload a document photo, rescue missed page corners and uneven lighting, compare the cleanup, and download a black-and-white, grayscale, or color PNG.

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
2. The app generates the first black-and-white scan automatically.
3. Adjust the four page-corner handles and cleanup settings, then click **Apply changes**.
4. Drag the before/after divider to compare the same cropped page before and after cleanup.
5. Click **Download scanned PNG** to save `<original-name>_scanned.png`.

### Rescue tools

- **Page-corner editor:** drag numbered handles with a mouse or touch. Tab to a handle and use arrow keys for one-pixel adjustments, or Shift + arrow for ten pixels. Keep them clockwise: top-left, top-right, bottom-right, bottom-left. Invalid or crossed selections show an error instead of silently falling back.
- **Scan styles:** black-and-white is the default; grayscale retains tonal detail, and color preserves color information while enhancing page lightness.
- **Shadow cleanup:** optional illumination normalization for uneven lighting, off by default. It may alter photos, colored paper, or faint markings; compare before downloading. It is not a guarantee of recovering obscured content.
- **Noise cleanup:** 0-15, default 8. Stronger cleanup can soften fine details.
- **Contrast:** 1.0-3.0, default 1.0.
- **Paper whitening:** 0-20, default 10; only available for black-and-white. Higher values whiten more of the page, while lower values retain lighter marks.
- **Apply and Reset:** edits do not rescan until Apply is clicked. Downloads are hidden while edits are unapplied. Reset restores automatic boundaries and default settings and regenerates the baseline scan.

The corner editor uses the uploaded photo. The comparison uses matching page geometry, not a stretched original photo. Comparison movement stays in the browser and never triggers a new scan. The untouched original remains available under **View original photo**.

For the best perspective correction, include one clearly visible, four-cornered page against a contrasting background. The scanner checks both saturation and edge contours before correcting perspective, reducing noise, enhancing contrast, and producing the black-and-white result.

If no usable page boundary is found, the app enhances the whole image instead and warns that perspective correction was skipped. Handles start at the image edges; move them onto the page and click Apply to rescue the crop manually. Leaving them unchanged preserves whole-image enhancement. Automatic detection is not guaranteed for every photo.

Uploads are limited to **20 MB** and **40 million pixels**. Images must be at least 3 pixels wide and tall. Phone-photo EXIF orientation is applied, grayscale images are supported, and transparency is composited onto white. Processing and previews preserve aspect ratio, with a maximum **2,000-pixel long edge** and no upscaling. Downloads use the processed resolution, not necessarily the original photo resolution.

Uploads, draft settings, and applied results stay in private in-memory Streamlit session state on the computer running the app; there is no shared image cache, saved document file, or scan history. Replacing or removing an upload clears its editor and previous result. Invalid uploads cannot expose a previous document's download. Input photos are intentionally not tracked in Git. Keep personal documents and contact details out of public commits.

This version runs locally and handles one image at a time. The custom editors use Streamlit components v2, with no external scripts or frontend build step. OCR, PDF export, batch scanning, camera capture, redaction, and public deployment are not included.

## Command-line scanner

```powershell
python docu_scanner.py "C:\path\to\your-document.jpg"
```

The result appears in the **Scanned Image** window; press any key in that window to close it. The CLI displays the result but does not save an output file. It uses the same scanner and whole-image fallback as the web app.

If no image path is supplied, the CLI uses a local `imig.jpg` in the current working directory. Provide your own image; the sample is not included in Git.

For Python callers, `scan_document(image)` in `docu_scanner.py` accepts a three-channel, 8-bit BGR NumPy array and returns `(scanned, perspective_corrected)`: a grayscale black-and-white array and a boolean. Importing the module does not parse arguments, read files, or open windows.

The scanner module also exposes `warp_document(image, corners)` for four distinct, finite, in-bounds clockwise pixel coordinates of shape `(4, 2)`, and `enhance_document(image, *, style='black-and-white', remove_shadows=False, denoise_strength=8, contrast=1.0, threshold_offset=10)`. Enhancement styles are `black-and-white`, `grayscale`, and `color`; color returns a BGR array and other styles return a grayscale array. The default `scan_document(image)` behavior and CLI interface remain unchanged.

## Other tracked code

`CV and YOLO/segmentation.py` remains in the repository as a separate YOLO segmentation experiment. It is not part of the document scanner and is not required to run it. The scanner's requirements do not include YOLO dependencies; local experiment videos and model weights are not included.

`.gitignore` keeps local images, videos, model weights, Python caches, and unrelated practice scripts out of new commits. It does not untrack the existing segmentation file.
