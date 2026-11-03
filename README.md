# Document Scanner

A Python/OpenCV document scanner that detects a document's corners, corrects perspective, reduces noise, and displays a high-contrast black-and-white scan.

## Setup

Run these commands from the repository folder in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Use the desktop `opencv-python` package in `requirements.txt`, not the headless variant: the scanner opens an image window.

## Scan a document

```powershell
python docu_scanner.py "C:\path\to\your-document.jpg"
```

Use a photo with one clearly visible, four-cornered document against a contrasting background. The result appears in the **Scanned Image** window; press any key in that window to close it. The script displays the result but does not save an output file.

If no image path is supplied, the script uses a local `imig.jpg` in the current working directory. Input photos are intentionally not tracked, so provide your own image. Keep personal documents and contact details out of public commits.

## Other tracked code

`CV and YOLO/segmentation.py` remains in the repository as a separate YOLO segmentation experiment. It is not part of the document scanner and is not required to run it. The scanner's requirements do not include YOLO dependencies; local experiment videos and model weights are not included.

`.gitignore` keeps local images, videos, model weights, Python caches, and unrelated practice scripts out of new commits. It does not untrack the existing segmentation file.
