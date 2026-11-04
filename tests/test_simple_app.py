"""Focused regressions for the automatic upload-to-scan Streamlit flow."""

from contextlib import contextmanager, nullcontext
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

import app


class UploadedImage:
    def __init__(self, name, data, before_getvalue=None):
        self.name = name
        self._data = data
        self._before_getvalue = before_getvalue

    def getvalue(self):
        if self._before_getvalue is not None:
            self._before_getvalue()
        return self._data


class MemoryFailingUpload:
    name = 'too-large-in-memory.png'

    def getvalue(self):
        raise MemoryError('private allocation details')


def png_upload(name, color):
    with BytesIO() as buffer:
        with Image.new('RGB', (5, 4), color) as image:
            image.save(buffer, format='PNG')
        return UploadedImage(name, buffer.getvalue())


class ContainerStub:
    def __init__(self, streamlit, source, options):
        self.streamlit = streamlit
        self.source = source
        self.options = options

    def __enter__(self):
        key = self.options.get('key')
        self.streamlit.context_stack.append(key)
        self.streamlit.events.append(('container.enter', key))
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        key = self.streamlit.context_stack.pop()
        self.streamlit.events.append(('container.exit', key))
        return False


class PlaceholderStub:
    def __init__(self, streamlit):
        self.streamlit = streamlit

    def container(self, **kwargs):
        self.streamlit.container_calls.append(('placeholder', kwargs))
        return ContainerStub(self.streamlit, 'placeholder', kwargs)


class StreamlitStub:
    """Small UI recorder that rejects calls to removed interactive controls."""

    REMOVED_CONTROLS = {
        'button', 'columns', 'expander', 'selectbox', 'slider', 'toggle',
    }

    def __init__(self):
        self.session_state = {}
        self.uploaded_file = None
        self.visible_result_elements = []
        self.reset_output()

    def reset_output(self):
        self.context_stack = []
        self.events = []
        self.page_configs = []
        self.html_calls = []
        self.container_calls = []
        self.empty_calls = 0
        self.titles = []
        self.writes = []
        self.captions = []
        self.uploader_calls = []
        self.infos = []
        self.spinners = []
        self.errors = []
        self.subheaders = []
        self.successes = []
        self.warnings = []
        self.images = []
        self.downloads = []

    def _record(self, name):
        context = self.context_stack[-1] if self.context_stack else None
        self.events.append((name, context))

    def __getattr__(self, name):
        if name in self.REMOVED_CONTROLS:
            raise AssertionError(f'Removed control was rendered: {name}')
        raise AttributeError(name)

    def set_page_config(self, **kwargs):
        self.page_configs.append(kwargs)
        self._record('page_config')

    def html(self, body, **kwargs):
        self.html_calls.append((body, kwargs))
        self._record('html')

    def container(self, **kwargs):
        self.container_calls.append(('root', kwargs))
        return ContainerStub(self, 'root', kwargs)

    def empty(self):
        self.empty_calls += 1
        self.visible_result_elements.clear()
        self._record('empty')
        return PlaceholderStub(self)

    def title(self, text):
        self.titles.append(text)
        self._record('title')

    def write(self, text):
        self.writes.append(text)
        self._record('write')

    def caption(self, text):
        self.captions.append(text)
        self._record('caption')

    def file_uploader(self, label, **kwargs):
        self.uploader_calls.append((label, kwargs))
        self.session_state[kwargs['key']] = self.uploaded_file
        self._record('uploader')
        return self.uploaded_file

    def info(self, text):
        self.infos.append(text)
        self._record('info')

    @contextmanager
    def spinner(self, text):
        self.spinners.append(text)
        self._record('spinner')
        yield

    def error(self, text):
        self.errors.append(text)
        self._record('error')

    def subheader(self, text):
        self.subheaders.append(text)
        self._record('subheader')

    def success(self, text):
        self.successes.append(text)
        self._record('success')

    def warning(self, text):
        self.warnings.append(text)
        self._record('warning')

    def image(self, image, **kwargs):
        self.images.append((image, kwargs))
        self.visible_result_elements.append('image')
        self._record('image')

    def download_button(self, label, **kwargs):
        self.downloads.append((label, kwargs))
        self.visible_result_elements.append('download')
        self._record('download')
        return False


class SimpleAppTests(unittest.TestCase):
    def setUp(self):
        self.streamlit = StreamlitStub()
        self.streamlit_patch = patch.object(app, 'st', self.streamlit)
        self.streamlit_patch.start()

    def tearDown(self):
        self.streamlit_patch.stop()

    def seed_valid_result(self):
        self.streamlit.uploaded_file = png_upload('original.png', (20, 40, 60))
        with patch.object(
            app, 'scan_document',
            return_value=(np.zeros((4, 5), dtype=np.uint8), True),
        ):
            app.main()
        self.assertIn('rescue_studio', self.streamlit.session_state)
        self.assertEqual(self.streamlit.visible_result_elements, ['download', 'image'])

    def assert_failed_run_has_no_result(self):
        self.assertNotIn('rescue_studio', self.streamlit.session_state)
        self.assertEqual(self.streamlit.images, [])
        self.assertEqual(self.streamlit.downloads, [])
        self.assertEqual(self.streamlit.visible_result_elements, [])
        self.assertEqual(self.streamlit.empty_calls, 1)
        self.assertEqual(len(self.streamlit.errors), 1)
        error_events = [context for name, context in self.streamlit.events if name == 'error']
        self.assertEqual(error_events, ['rescue_result'])

    def test_default_scan_converts_rgb_to_bgr_and_png_matches_preview(self):
        pixels = np.array([
            [[10, 20, 30], [40, 50, 60], [70, 80, 90], [100, 110, 120], [130, 140, 150]],
            [[15, 25, 35], [45, 55, 65], [75, 85, 95], [105, 115, 125], [135, 145, 155]],
            [[20, 30, 40], [50, 60, 70], [80, 90, 100], [110, 120, 130], [140, 150, 160]],
            [[25, 35, 45], [55, 65, 75], [85, 95, 105], [115, 125, 135], [145, 155, 165]],
        ], dtype=np.uint8)
        with BytesIO() as buffer:
            Image.fromarray(pixels, mode='RGB').save(buffer, format='PNG')
            self.streamlit.uploaded_file = UploadedImage('receipt.photo.png', buffer.getvalue())
        scanned = np.array([
            [0, 255, 0, 255],
            [255, 0, 255, 0],
            [0, 0, 255, 255],
        ], dtype=np.uint8)

        with patch.object(app, 'scan_document', return_value=(scanned, True)) as scanner:
            app.main()

        scanner.assert_called_once()
        scanner_input = scanner.call_args.args[0]
        self.assertEqual(scanner.call_args.kwargs, {})
        np.testing.assert_array_equal(scanner_input, pixels[:, :, ::-1])
        self.assertEqual(scanner_input.dtype, np.uint8)

        studio = self.streamlit.session_state['rescue_studio']
        self.assertEqual((studio['width'], studio['height']), (4, 3))
        self.assertNotIn('original', studio)
        np.testing.assert_array_equal(studio['scanned'], scanned)
        self.assertEqual(len(self.streamlit.images), 1)
        np.testing.assert_array_equal(self.streamlit.images[0][0], scanned)
        self.assertEqual(self.streamlit.images[0][1], {'width': 'stretch'})

        self.assertEqual(len(self.streamlit.downloads), 1)
        label, options = self.streamlit.downloads[0]
        self.assertEqual(label, 'Download scanned PNG')
        self.assertEqual(options['file_name'], 'receipt.photo_scanned.png')
        self.assertEqual(options['mime'], 'image/png')
        self.assertEqual(options['on_click'], 'ignore')
        self.assertEqual(options['type'], 'primary')
        self.assertEqual(options['width'], 'stretch')
        event_names = [name for name, _ in self.streamlit.events]
        self.assertLess(event_names.index('download'), event_names.index('image'))
        self.assertEqual(self.streamlit.visible_result_elements, ['download', 'image'])
        downloaded = cv2.imdecode(
            np.frombuffer(options['data'], dtype=np.uint8), cv2.IMREAD_UNCHANGED,
        )
        self.assertEqual(downloaded.dtype, np.uint8)
        self.assertEqual(downloaded.shape, scanned.shape)
        np.testing.assert_array_equal(downloaded, scanned)
        self.assertEqual(self.streamlit.spinners, ['Creating your scan…'])
        self.assertEqual(len(self.streamlit.successes), 1)
        self.assertEqual(self.streamlit.warnings, [])

    def test_unchanged_upload_does_not_reprocess_on_rerun(self):
        self.streamlit.uploaded_file = png_upload('page.png', (20, 40, 60))
        scanned = np.zeros((4, 5), dtype=np.uint8)
        with patch.object(app, 'scan_document', return_value=(scanned, True)) as scanner:
            app.main()
            first_studio = self.streamlit.session_state['rescue_studio']
            self.streamlit.reset_output()
            app.main()

        scanner.assert_called_once()
        self.assertIs(self.streamlit.session_state['rescue_studio'], first_studio)
        self.assertEqual(self.streamlit.spinners, [])
        self.assertEqual(len(self.streamlit.images), 1)
        self.assertEqual(len(self.streamlit.downloads), 1)

    def test_changed_bytes_and_changed_filename_each_replace_the_result(self):
        first = png_upload('page.png', (20, 40, 60))
        second = png_upload('page.png', (70, 90, 110))
        renamed = UploadedImage('renamed.png', second.getvalue())
        scans = (
            np.zeros((4, 5), dtype=np.uint8),
            np.full((4, 5), 255, dtype=np.uint8),
            np.array([[0, 255], [255, 0]], dtype=np.uint8),
        )

        with patch.object(
            app, 'scan_document',
            side_effect=[(scans[0], True), (scans[1], False), (scans[2], True)],
        ) as scanner:
            upload_ids = []
            png_results = []
            for upload in (first, second, renamed):
                self.streamlit.uploaded_file = upload
                self.streamlit.reset_output()
                app.main()
                studio = self.streamlit.session_state['rescue_studio']
                upload_ids.append(studio['upload_id'])
                png_results.append(studio['png'])

        self.assertEqual(scanner.call_count, 3)
        self.assertEqual(len(set(upload_ids)), 3)
        self.assertEqual(len(set(png_results)), 3)
        self.assertEqual(
            self.streamlit.session_state['rescue_studio']['download_name'],
            'renamed_scanned.png',
        )
        np.testing.assert_array_equal(
            self.streamlit.session_state['rescue_studio']['scanned'], scans[2],
        )

    def test_replacement_clears_slot_then_state_before_scan_and_encoding(self):
        self.seed_valid_result()
        replacement_data = png_upload('replacement.png', (70, 90, 110)).getvalue()
        checkpoints = []

        def before_getvalue():
            self.assertEqual(self.streamlit.empty_calls, 1)
            self.assertEqual(self.streamlit.visible_result_elements, [])
            checkpoints.append('slot cleared')

        def scan_replacement(image):
            self.assertNotIn('rescue_studio', self.streamlit.session_state)
            self.assertEqual(self.streamlit.visible_result_elements, [])
            checkpoints.append('scan')
            return np.full((4, 5), 255, dtype=np.uint8), True

        real_imencode = cv2.imencode

        def encode_replacement(extension, image):
            self.assertNotIn('rescue_studio', self.streamlit.session_state)
            self.assertEqual(self.streamlit.visible_result_elements, [])
            checkpoints.append('encode')
            return real_imencode(extension, image)

        self.streamlit.uploaded_file = UploadedImage(
            'replacement.png', replacement_data, before_getvalue=before_getvalue,
        )
        self.streamlit.reset_output()
        with (
            patch.object(app, 'scan_document', side_effect=scan_replacement),
            patch.object(app.cv2, 'imencode', side_effect=encode_replacement),
        ):
            app.main()

        self.assertEqual(checkpoints, ['slot cleared', 'scan', 'encode'])
        self.assertIn('rescue_studio', self.streamlit.session_state)
        self.assertEqual(self.streamlit.visible_result_elements, ['download', 'image'])

    def test_removing_upload_clears_result_but_preserves_live_widget(self):
        self.streamlit.uploaded_file = png_upload('page.png', (20, 40, 60))
        with patch.object(
            app, 'scan_document',
            return_value=(np.zeros((4, 5), dtype=np.uint8), True),
        ):
            app.main()
        self.assertIn('rescue_studio', self.streamlit.session_state)

        self.streamlit.uploaded_file = None
        self.streamlit.reset_output()
        app.main()

        self.assertNotIn('rescue_studio', self.streamlit.session_state)
        self.assertIn('rescue_upload', self.streamlit.session_state)
        self.assertIsNone(self.streamlit.session_state['rescue_upload'])
        self.assertEqual(self.streamlit.images, [])
        self.assertEqual(self.streamlit.downloads, [])
        self.assertEqual(len(self.streamlit.infos), 1)

    def test_invalid_replacement_cannot_reveal_previous_scan(self):
        self.streamlit.uploaded_file = png_upload('page.png', (20, 40, 60))
        with patch.object(
            app, 'scan_document',
            return_value=(np.zeros((4, 5), dtype=np.uint8), True),
        ) as scanner:
            app.main()
            self.streamlit.uploaded_file = UploadedImage('page.png', b'not an image')
            self.streamlit.reset_output()
            app.main()

        scanner.assert_called_once()
        self.assert_failed_run_has_no_result()
        self.assertIn('valid JPG, PNG, WebP, or BMP', self.streamlit.errors[0])

    def test_processing_failure_cannot_reveal_previous_scan_or_details(self):
        first = png_upload('page.png', (20, 40, 60))
        second = png_upload('page.png', (70, 90, 110))
        self.streamlit.uploaded_file = first
        with patch.object(
            app, 'scan_document',
            side_effect=[
                (np.zeros((4, 5), dtype=np.uint8), True),
                ValueError('low-level document details'),
            ],
        ):
            app.main()
            self.streamlit.uploaded_file = second
            self.streamlit.reset_output()
            app.main()

        self.assert_failed_run_has_no_result()
        self.assertIn('clearer or smaller', self.streamlit.errors[0])
        self.assertNotIn('low-level', self.streamlit.errors[0])

    def test_encoding_failure_cannot_reveal_previous_scan(self):
        first = png_upload('page.png', (20, 40, 60))
        second = png_upload('page.png', (70, 90, 110))
        scanned = np.zeros((4, 5), dtype=np.uint8)
        real_imencode = cv2.imencode
        encoding_calls = 0

        def fail_second_encoding(extension, image):
            nonlocal encoding_calls
            encoding_calls += 1
            if encoding_calls == 2:
                return False, None
            return real_imencode(extension, image)

        self.streamlit.uploaded_file = first
        with (
            patch.object(app, 'scan_document', return_value=(scanned, True)),
            patch.object(app.cv2, 'imencode', side_effect=fail_second_encoding),
        ):
            app.main()
            self.streamlit.uploaded_file = second
            self.streamlit.reset_output()
            app.main()

        self.assertEqual(encoding_calls, 2)
        self.assert_failed_run_has_no_result()
        self.assertIn('PNG download', self.streamlit.errors[0])

    def test_getvalue_memory_failure_clears_previous_result_without_details(self):
        self.seed_valid_result()
        self.streamlit.uploaded_file = MemoryFailingUpload()
        self.streamlit.reset_output()

        app.main()

        self.assert_failed_run_has_no_result()
        self.assertIn('memory to read', self.streamlit.errors[0])
        self.assertIn('resize', self.streamlit.errors[0])
        self.assertNotIn('private allocation', self.streamlit.errors[0])

    def test_scan_memory_failure_clears_previous_result_without_details(self):
        self.seed_valid_result()
        self.streamlit.uploaded_file = png_upload('replacement.png', (70, 90, 110))
        self.streamlit.reset_output()

        with patch.object(
            app, 'scan_document', side_effect=MemoryError('private scan allocation details'),
        ):
            app.main()

        self.assert_failed_run_has_no_result()
        self.assertIn('memory to scan', self.streamlit.errors[0])
        self.assertIn('resize', self.streamlit.errors[0])
        self.assertNotIn('private scan', self.streamlit.errors[0])

    def test_encoding_memory_failure_clears_previous_result_without_details(self):
        self.seed_valid_result()
        self.streamlit.uploaded_file = png_upload('replacement.png', (70, 90, 110))
        self.streamlit.reset_output()

        with (
            patch.object(
                app, 'scan_document',
                return_value=(np.zeros((4, 5), dtype=np.uint8), True),
            ),
            patch.object(
                app.cv2, 'imencode',
                side_effect=MemoryError('private encoder allocation details'),
            ),
        ):
            app.main()

        self.assert_failed_run_has_no_result()
        self.assertIn('memory to prepare the PNG download', self.streamlit.errors[0])
        self.assertIn('resize', self.streamlit.errors[0])
        self.assertNotIn('private encoder', self.streamlit.errors[0])

    def test_cv2_processing_and_encoding_errors_are_safe_and_clear_old_result(self):
        for stage in ('processing', 'encoding'):
            with self.subTest(stage=stage):
                self.streamlit.session_state.clear()
                self.streamlit.visible_result_elements.clear()
                self.streamlit.reset_output()
                self.seed_valid_result()
                self.streamlit.uploaded_file = png_upload(
                    f'{stage}.png', (70, 90, 110),
                )
                self.streamlit.reset_output()

                if stage == 'processing':
                    scanner = patch.object(
                        app, 'scan_document',
                        side_effect=cv2.error('private processing details'),
                    )
                    encoder = nullcontext()
                else:
                    scanner = patch.object(
                        app, 'scan_document',
                        return_value=(np.zeros((4, 5), dtype=np.uint8), True),
                    )
                    encoder = patch.object(
                        app.cv2, 'imencode',
                        side_effect=cv2.error('private encoding details'),
                    )

                with scanner, encoder:
                    app.main()

                self.assert_failed_run_has_no_result()
                self.assertNotIn('private', self.streamlit.errors[0])
                expected = 'clearer or smaller' if stage == 'processing' else 'PNG download'
                self.assertIn(expected, self.streamlit.errors[0])

    def test_invalid_scan_dimensions_and_dtype_are_rejected_before_encoding(self):
        invalid_scans = {
            'color dimensions': np.zeros((4, 5, 3), dtype=np.uint8),
            'floating dtype': np.zeros((4, 5), dtype=np.float32),
            'not an array': [[0, 255], [255, 0]],
        }
        for description, invalid_scan in invalid_scans.items():
            with self.subTest(description=description):
                self.streamlit.session_state.clear()
                self.streamlit.visible_result_elements.clear()
                self.streamlit.reset_output()
                self.seed_valid_result()
                self.streamlit.uploaded_file = png_upload(
                    f'{description}.png', (70, 90, 110),
                )
                self.streamlit.reset_output()

                with (
                    patch.object(
                        app, 'scan_document', return_value=(invalid_scan, True),
                    ),
                    patch.object(app.cv2, 'imencode') as encoder,
                ):
                    app.main()

                encoder.assert_not_called()
                self.assert_failed_run_has_no_result()
                self.assertIn('clearer or smaller', self.streamlit.errors[0])

    def test_clear_studio_keeps_uploader_and_unrelated_state_only(self):
        live_upload = object()
        self.streamlit.session_state.update({
            'rescue_upload': live_upload,
            'rescue_studio': {'old': 'result'},
            'rescue_setting_style': 'Color',
            'rescue_editor_old': {'corners': []},
            'rescue_comparison_old': {'position': 50},
            'unrelated_preference': 'keep me',
        })

        app.clear_studio()

        self.assertEqual(self.streamlit.session_state, {
            'rescue_upload': live_upload,
            'unrelated_preference': 'keep me',
        })

    def test_result_slot_uses_native_scoped_card_and_responsive_image_styles(self):
        app.main()

        self.assertEqual(self.streamlit.empty_calls, 1)
        self.assertIn(
            ('placeholder', {'key': 'rescue_result', 'border': True}),
            self.streamlit.container_calls,
        )
        self.assertEqual(len(self.streamlit.html_calls), 1)
        styles, options = self.streamlit.html_calls[0]
        self.assertEqual(options, {})
        for text in (
            '.st-key-rescue_result', 'max-height: min(65vh, 36rem)',
            'object-fit: contain', 'min-height: 44px',
        ):
            self.assertIn(text, styles)
        info_contexts = [context for name, context in self.streamlit.events if name == 'info']
        self.assertEqual(info_contexts, ['rescue_result'])

    def test_real_streamlit_empty_state_preserves_widget_and_clears_old_rescue_state(self):
        from streamlit.testing.v1 import AppTest

        test_app = AppTest.from_file(str(Path(app.__file__)))
        test_app.session_state['rescue_studio'] = {'old': 'result'}
        test_app.session_state['rescue_editor_old'] = {'corners': []}
        test_app.session_state['unrelated_preference'] = 'keep me'

        test_app.run(timeout=30)

        self.assertEqual(list(test_app.exception), [])
        self.assertEqual(len(test_app.file_uploader), 1)
        self.assertEqual(test_app.file_uploader[0].key, 'rescue_upload')
        self.assertNotIn('rescue_studio', test_app.session_state)
        self.assertNotIn('rescue_editor_old', test_app.session_state)
        self.assertIn('rescue_upload', test_app.session_state)
        self.assertIsNone(test_app.session_state['rescue_upload'])
        self.assertEqual(test_app.session_state['unrelated_preference'], 'keep me')
        self.assertEqual(
            [message.value for message in test_app.info],
            ['Add a JPG, PNG, WebP, or BMP image to create your scan.'],
        )

    def test_empty_and_fallback_states_stay_single_action_and_downloadable(self):
        app.main()
        self.assertEqual(self.streamlit.page_configs[0]['layout'], 'centered')
        self.assertEqual(len(self.streamlit.uploader_calls), 1)
        self.assertEqual(self.streamlit.subheaders, [])
        self.assertEqual(self.streamlit.images, [])
        self.assertEqual(self.streamlit.downloads, [])
        self.assertEqual(len(self.streamlit.infos), 1)

        self.streamlit.uploaded_file = png_upload('page.png', (20, 40, 60))
        self.streamlit.reset_output()
        with patch.object(
            app, 'scan_document',
            return_value=(np.zeros((4, 5), dtype=np.uint8), False),
        ):
            app.main()

        self.assertEqual(self.streamlit.subheaders, ['Scanned result'])
        self.assertEqual(self.streamlit.successes, [])
        self.assertEqual(len(self.streamlit.warnings), 1)
        self.assertIn('Whole-image enhancement', self.streamlit.warnings[0])
        self.assertIn('perspective correction was skipped', self.streamlit.warnings[0])
        self.assertEqual(len(self.streamlit.images), 1)
        self.assertEqual(len(self.streamlit.downloads), 1)


if __name__ == '__main__':
    unittest.main()
