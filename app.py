from hashlib import sha256
from io import BytesIO
from pathlib import Path
import warnings

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
import streamlit as st

from docu_scanner import (
    MAX_PROCESSING_DIMENSION, enhance_document, find_document_corners, warp_document,
)
from scan_widgets import compare_scans, corner_editor, image_data_uri


MAX_UPLOAD_MB = 20
MAX_SOURCE_PIXELS = 40_000_000
SUPPORTED_FORMATS = ('JPEG', 'PNG', 'WEBP', 'BMP')
STYLE_LABELS = {'Black-and-white': 'black-and-white', 'Grayscale': 'grayscale', 'Color': 'color'}
DEFAULT_SETTINGS = {
    'style': 'Black-and-white',
    'remove_shadows': False,
    'denoise_strength': 8,
    'contrast': 1.0,
    'threshold_offset': 10,
}


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
                        'Please resize it to 40 million pixels or fewer.'
                    )
                if min(image.size) < 3:
                    raise ValueError('The image must be at least 3 pixels wide and tall.')
                oriented = ImageOps.exif_transpose(image)
                oriented.thumbnail(
                    (MAX_PROCESSING_DIMENSION, MAX_PROCESSING_DIMENSION),
                    Image.Resampling.LANCZOS,
                )
                if min(oriented.size) < 3:
                    raise ValueError(
                        'This image is too narrow after resizing. '
                        'Please crop it or choose a less elongated photo.'
                    )
                if 'A' in oriented.getbands() or 'transparency' in oriented.info:
                    transparent = oriented.convert('RGBA')
                    background = Image.new('RGBA', transparent.size, 'white')
                    rgb = Image.alpha_composite(background, transparent).convert('RGB')
                else:
                    rgb = oriented.convert('RGB')
                return np.array(rgb, dtype=np.uint8)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError(
            'This image is too large to process safely. Please upload a smaller image.'
        ) from error
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise ValueError(
            'Could not read this image. Please upload a valid JPG, PNG, WebP, or BMP file.'
        ) from error


def clear_studio():
    for key in list(st.session_state):
        if key.startswith('rescue_'):
            del st.session_state[key]


def normalized_corners(corners, image_shape):
    height, width = image_shape[:2]
    return (np.asarray(corners, dtype=np.float64) / [width - 1, height - 1]).tolist()


def pixel_corners(corners, image_shape):
    try:
        points = np.asarray(corners, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError('Place four distinct handles on the page corners.') from error
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError('Place four valid handles on the page corners.')
    if (points < 0).any() or (points > 1).any():
        raise ValueError('Keep every corner handle inside the image.')
    height, width = image_shape[:2]
    return (points * [width - 1, height - 1]).astype(np.float32)


def same_corners(first, second):
    try:
        first_points = np.asarray(first, dtype=np.float64)
        second_points = np.asarray(second, dtype=np.float64)
        return first_points.shape == second_points.shape and np.allclose(
            first_points, second_points, rtol=0, atol=1e-8,
        )
    except (TypeError, ValueError):
        return False


def apply_scan(studio, settings):
    image = cv2.cvtColor(studio['original'], cv2.COLOR_RGB2BGR)
    corners = studio['draft_corners'] if studio['manual_corners'] else studio['auto_corners']
    page = warp_document(image, pixel_corners(corners, image.shape)) if corners is not None else image
    scanned = enhance_document(
        page, **{**settings, 'style': STYLE_LABELS[settings['style']]},
    )
    encoded, png = cv2.imencode('.png', scanned)
    if not encoded:
        raise ValueError('Could not prepare the PNG download. Please try another image.')
    before_uri = image_data_uri(page, bgr=True)
    after_uri = image_data_uri(scanned, bgr=settings['style'] == 'Color')
    studio.update({
        'scanned': scanned,
        'png': png.tobytes(),
        'before_uri': before_uri,
        'after_uri': after_uri,
        'corrected': corners is not None,
        'applied_corners': [list(point) for point in studio['draft_corners']],
        'applied_manual': studio['manual_corners'],
        'applied_settings': dict(settings),
        'error': None,
    })


def seed_settings():
    for name, value in DEFAULT_SETTINGS.items():
        st.session_state['rescue_setting_' + name] = value


def initialize_studio(original, upload_id):
    image = cv2.cvtColor(original, cv2.COLOR_RGB2BGR)
    detected = find_document_corners(image)
    if detected is not None:
        try:
            warp_document(image, detected)
        except ValueError:
            detected = None
    automatic = normalized_corners(detected, image.shape) if detected is not None else None
    studio = {
        'upload_id': upload_id,
        'original': original,
        'image_uri': image_data_uri(original),
        'auto_corners': automatic,
        'draft_corners': automatic or [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        'manual_corners': False,
        'editor_revision': 0,
    }
    apply_scan(studio, DEFAULT_SETTINGS)
    seed_settings()
    return studio


def reset_studio():
    studio = st.session_state['rescue_studio']
    studio['draft_corners'] = studio['auto_corners'] or [
        [0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0],
    ]
    studio['manual_corners'] = False
    studio['editor_revision'] += 1
    seed_settings()
    try:
        apply_scan(studio, DEFAULT_SETTINGS)
    except (ValueError, cv2.error) as error:
        studio['error'] = f'Could not reset the scan: {error}'


def main():
    st.set_page_config(page_title='Scan Rescue Studio', page_icon='📄', layout='wide')
    st.title('Scan Rescue Studio')
    st.write('Fix page corners, rescue uneven lighting, and choose your scan style.')
    st.caption('Upload → Adjust → Apply → Download · One image at a time · Processed on this computer')
    uploaded_file = st.file_uploader(
        'Upload a document photo', type=['jpg', 'jpeg', 'png', 'webp', 'bmp'],
        accept_multiple_files=False, max_upload_size=MAX_UPLOAD_MB,
        help='Up to 20 MB and 40 million pixels. Include the full page when possible.',
        key='document_upload',
    )
    st.caption(
        'Images stay in memory on this computer. Processing is capped at a '
        '2,000-pixel long edge; nothing is saved until you download it.'
    )
    if uploaded_file is None:
        clear_studio()
        st.info('Upload a photo to start. Your first scan is generated automatically.')
        return

    image_bytes = uploaded_file.getvalue()
    upload_id = sha256(image_bytes).hexdigest() + ':' + uploaded_file.name
    studio = st.session_state.get('rescue_studio')
    if studio is None or studio['upload_id'] != upload_id:
        clear_studio()
        try:
            with st.spinner('Finding the page and generating your first scan…'):
                studio = initialize_studio(decode_image(image_bytes), upload_id)
            st.session_state['rescue_studio'] = studio
        except ValueError as error:
            st.error(str(error))
            return
        except cv2.error:
            st.error('Could not process this image. Please try a clearer or smaller photo.')
            return

    editor_column, settings_column = st.columns([2, 1], gap='large')
    with editor_column:
        st.subheader('1. Adjust page corners')
        if studio['auto_corners'] is None:
            st.caption('No page boundary detected. Move the handles to rescue it, or keep the whole image.')
        editor_key = f"rescue_editor_{studio['upload_id']}_{studio['editor_revision']}"
        stored_draft = st.session_state.get(editor_key, {}).get('corners')
        if stored_draft is not None and not same_corners(stored_draft, studio['draft_corners']):
            studio['draft_corners'] = stored_draft
            studio['manual_corners'] = True
            studio['error'] = None
        draft = corner_editor(
            studio['image_uri'], studio['draft_corners'], studio['original'].shape,
            key=editor_key,
        )
        if draft is not None and not same_corners(draft, studio['draft_corners']):
            studio['draft_corners'] = draft
            studio['manual_corners'] = True
            studio['error'] = None
        with st.expander('View original photo'):
            st.image(studio['original'], width='stretch')

    with settings_column:
        st.subheader('2. Tune your scan')
        settings = {
            'style': st.selectbox('Scan style', list(STYLE_LABELS), key='rescue_setting_style'),
            'remove_shadows': st.toggle(
                'Shadow cleanup', key='rescue_setting_remove_shadows',
                help='Normalize uneven lighting. This may alter photos or colored paper.',
            ),
            'denoise_strength': st.slider(
                'Noise cleanup', 0, 15, step=1, key='rescue_setting_denoise_strength',
                help='Higher values smooth more noise but can soften fine details.',
            ),
            'contrast': st.slider(
                'Contrast', 1.0, 3.0, step=0.1, key='rescue_setting_contrast',
            ),
        }
        settings['threshold_offset'] = st.slider(
            'Paper whitening', 0, 20, step=1, key='rescue_setting_threshold_offset',
            disabled=settings['style'] != 'Black-and-white',
            help='Higher values whiten more of the page; lower values retain lighter marks.',
        )
        studio['draft_settings'] = dict(settings)
        dirty = (
            settings != studio['applied_settings']
            or studio['manual_corners'] != studio['applied_manual']
            or not same_corners(studio['draft_corners'], studio['applied_corners'])
        )
        apply_column, reset_column = st.columns(2)
        with apply_column:
            if st.button('Apply changes', type='primary', width='stretch', disabled=not dirty):
                try:
                    with st.spinner('Applying your page corners and cleanup settings…'):
                        apply_scan(studio, settings)
                    dirty = False
                except ValueError as error:
                    studio['error'] = str(error)
                except cv2.error:
                    studio['error'] = 'Could not process this selection. Try wider corners or less cleanup.'
        with reset_column:
            st.button('Reset', on_click=reset_studio, width='stretch')
        if studio['error']:
            st.error(studio['error'])
        if dirty:
            st.warning('Unapplied edits: the preview is your last applied scan. Apply or reset to download.')

    st.subheader('3. Compare and download')
    if studio['corrected']:
        boundary = 'Your page corners' if studio['applied_manual'] else 'Automatic page detection'
        st.success(f"{boundary} applied · {studio['applied_settings']['style']} scan ready.")
    else:
        st.warning('The whole image is enhanced; perspective correction was skipped.')
    compare_scans(
        studio['before_uri'], studio['after_uri'], studio['scanned'].shape,
        key=f"rescue_comparison_{studio['upload_id']}",
    )
    st.caption(
        'Drag the divider or use the slider to compare the same page before and after cleanup. '
        'Comparison movement does not rescan the image.'
    )
    height, width = studio['scanned'].shape[:2]
    st.caption(f'{width} × {height} pixels · PNG download uses the applied scan resolution')
    if not dirty and not studio['error']:
        filename = Path(uploaded_file.name).stem or 'document'
        st.download_button(
            'Download scanned PNG', data=studio['png'], file_name=f'{filename}_scanned.png',
            mime='image/png', on_click='ignore', type='primary',
        )


if __name__ == '__main__':
    main()
