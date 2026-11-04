from hashlib import sha256
from io import BytesIO
from pathlib import Path
import warnings

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
import streamlit as st

from docu_scanner import MAX_PROCESSING_DIMENSION, scan_document


MAX_UPLOAD_MB = 20
MAX_SOURCE_PIXELS = 200_000_000
# Align Pillow's finite bomb guard with our explicit source-metadata limit.
Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
SUPPORTED_FORMATS = ('JPEG', 'PNG', 'WEBP', 'BMP')


class ScanProcessingError(Exception):
    """A scanner failure safe to summarize without exposing low-level details."""


class ScanEncodingError(Exception):
    """A failure while preparing the in-memory PNG download."""


class ScanProcessingMemoryError(ScanProcessingError):
    """A memory failure while creating the scan."""


class ScanEncodingMemoryError(ScanEncodingError):
    """A memory failure while preparing the in-memory PNG download."""


RESULT_STYLES = '''
<style>
.st-key-rescue_upload_panel {
    margin-bottom: 0.5rem;
}
.st-key-rescue_upload_panel [data-testid="stFileUploader"] button,
.st-key-rescue_result [data-testid="stDownloadButton"] button {
    min-height: 44px;
}
.st-key-rescue_result,
.st-key-rescue_result [data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 0.9rem;
}
.st-key-rescue_result [data-testid="stImage"] img {
    display: block;
    width: auto !important;
    max-width: 100%;
    height: auto !important;
    max-height: min(65vh, 36rem);
    margin-inline: auto;
    object-fit: contain;
}
</style>
'''


def decode_image(image_bytes):
    """Decode an upload into an oriented, size-limited RGB image in memory."""
    if not image_bytes:
        raise ValueError('The uploaded file is empty. Please choose an image.')
    if len(image_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f'Please upload an image smaller than {MAX_UPLOAD_MB} MB.')

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(image_bytes), formats=SUPPORTED_FORMATS) as image:
                if image.width * image.height > MAX_SOURCE_PIXELS:
                    raise ValueError(
                        'This image is too large to process safely. '
                        'Please resize it to 200 million pixels or fewer.'
                    )
                if min(image.size) < 3:
                    raise ValueError('The image must be at least 3 pixels wide and tall.')
                # Reject ratios that stay below 3 pixels even when rounded up.
                if min(image.size) * MAX_PROCESSING_DIMENSION <= 2 * max(image.size):
                    raise ValueError(
                        'This image is too narrow after resizing. '
                        'Please crop it or choose a less elongated photo.'
                    )
                # Resize lazily so JPEG draft decoding precedes EXIF/color copies.
                image.thumbnail(
                    (MAX_PROCESSING_DIMENSION, MAX_PROCESSING_DIMENSION),
                    Image.Resampling.LANCZOS,
                )
                if min(image.size) < 3:
                    raise ValueError(
                        'This image is too narrow after resizing. '
                        'Please crop it or choose a less elongated photo.'
                    )
                oriented = ImageOps.exif_transpose(image)
                if 'A' in oriented.getbands() or 'transparency' in oriented.info:
                    transparent = oriented.convert('RGBA')
                    background = Image.new('RGBA', transparent.size, 'white')
                    rgb = Image.alpha_composite(background, transparent).convert('RGB')
                else:
                    rgb = oriented.convert('RGB')
                return np.array(rgb, dtype=np.uint8)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError(
            'This image is too large to process safely. '
            'Please resize it to 200 million pixels or fewer.'
        ) from error
    except MemoryError as error:
        raise ValueError(
            'Not enough memory to read this image. Please resize it or choose a smaller photo.'
        ) from error
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise ValueError(
            'Could not read this image. Please upload a valid JPG, PNG, WebP, or BMP file.'
        ) from error


def clear_studio():
    for key in list(st.session_state):
        if key.startswith('rescue_') and key != 'rescue_upload':
            del st.session_state[key]


def initialize_studio(original, upload_id, upload_name):
    """Create a complete default scan before exposing any new session result."""
    try:
        image = cv2.cvtColor(original, cv2.COLOR_RGB2BGR)
        scanned, corrected = scan_document(image)
    except MemoryError as error:
        raise ScanProcessingMemoryError from error
    except (ValueError, cv2.error) as error:
        raise ScanProcessingError from error

    if not isinstance(scanned, np.ndarray) or scanned.dtype != np.uint8 or scanned.ndim != 2:
        raise ScanProcessingError

    try:
        encoded, png = cv2.imencode('.png', scanned)
        if not encoded:
            raise ScanEncodingError
        png_bytes = png.tobytes()
    except ScanEncodingError:
        raise
    except MemoryError as error:
        raise ScanEncodingMemoryError from error
    except (ValueError, cv2.error) as error:
        raise ScanEncodingError from error

    height, width = scanned.shape
    filename = Path(upload_name).stem or 'document'
    return {
        'upload_id': upload_id,
        'scanned': scanned,
        'png': png_bytes,
        'corrected': bool(corrected),
        'width': width,
        'height': height,
        'download_name': f'{filename}_scanned.png',
        'mime': 'image/png',
    }


def main():
    st.set_page_config(page_title='Scan Rescue Studio', page_icon='📄', layout='centered')
    st.html(RESULT_STYLES)
    with st.container(key='rescue_intro'):
        st.title('Scan Rescue Studio')
        st.write('Add a document photo and get a clean black-and-white scan automatically.')
    with st.container(key='rescue_upload_panel'):
        uploaded_file = st.file_uploader(
            'Add a document image', type=['jpg', 'jpeg', 'png', 'webp', 'bmp'],
            accept_multiple_files=False, max_upload_size=MAX_UPLOAD_MB,
            help=(
                'Up to 20 MB and 200 million source pixels. Photos are automatically '
                'downsized to at most a 2,000-pixel long edge for processing and downloads. '
                'Include the full page when possible.'
            ),
            key='rescue_upload',
        )
        st.caption(
            'One image at a time · Kept in memory for this session · Nothing is saved '
            'until you download it'
        )

    result_slot = st.empty()
    with result_slot.container(key='rescue_result', border=True):
        if uploaded_file is None:
            clear_studio()
            st.info('Add a JPG, PNG, WebP, or BMP image to create your scan.')
            return

        try:
            image_bytes = uploaded_file.getvalue()
            upload_name = str(uploaded_file.name)
            upload_id = sha256(image_bytes).hexdigest() + ':' + upload_name
        except MemoryError:
            clear_studio()
            st.error(
                'Not enough memory to read this image. '
                'Please resize it or choose a smaller photo.'
            )
            return

        studio = st.session_state.get('rescue_studio')
        if not isinstance(studio, dict) or studio.get('upload_id') != upload_id:
            clear_studio()
            try:
                with st.spinner('Creating your scan…'):
                    studio = initialize_studio(
                        decode_image(image_bytes), upload_id, upload_name,
                    )
            except ScanEncodingMemoryError:
                st.error(
                    'Not enough memory to prepare the PNG download. '
                    'Please resize the image or choose a smaller photo.'
                )
                return
            except ScanProcessingMemoryError:
                st.error(
                    'Not enough memory to scan this image. '
                    'Please resize it or choose a smaller photo.'
                )
                return
            except ScanEncodingError:
                st.error('Could not prepare the PNG download. Please try another image.')
                return
            except ScanProcessingError:
                st.error('Could not scan this image. Please try a clearer or smaller photo.')
                return
            except ValueError as error:
                st.error(str(error))
                return
            except MemoryError:
                st.error(
                    'Not enough memory to scan this image. '
                    'Please resize it or choose a smaller photo.'
                )
                return

            st.session_state['rescue_studio'] = studio

        st.subheader('Scanned result')
        if studio['corrected']:
            st.success('Scan ready. The page was detected and straightened automatically.')
        else:
            st.warning(
                'No page boundary was found. Whole-image enhancement was used, and '
                'perspective correction was skipped.'
            )
        st.caption(f"{studio['width']} × {studio['height']} pixels · Black-and-white PNG")
        st.download_button(
            'Download scanned PNG', data=studio['png'], file_name=studio['download_name'],
            mime=studio['mime'], on_click='ignore', type='primary', width='stretch',
        )
        st.image(studio['scanned'], width='stretch')


if __name__ == '__main__':
    main()
