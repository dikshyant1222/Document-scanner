"""In-memory upload limits, lazy resizing, and color/orientation regressions."""

from io import BytesIO
import struct
import unittest
from unittest.mock import MagicMock, patch
import warnings
import zlib

import numpy as np
from PIL import Image, ImageOps, JpegImagePlugin, PngImagePlugin

import app


def encode_image(image, image_format='PNG', **options):
    with BytesIO() as buffer:
        image.save(buffer, format=image_format, **options)
        return buffer.getvalue()


def image_bytes(mode, size, color, image_format='PNG', **options):
    with Image.new(mode, size, color) as image:
        return encode_image(image, image_format, **options)


def png_header(size):
    """Readable metadata with insufficient raster data; no large allocation."""
    def chunk(name, payload):
        return (
            struct.pack('>I', len(payload)) + name + payload
            + struct.pack('>I', zlib.crc32(name + payload))
        )

    metadata = struct.pack('>IIBBBBB', *size, 8, 2, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', metadata)
        + chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00'))
        + chunk(b'IEND', b'')
    )


def oriented_pixels(pixels, orientation):
    return {
        1: pixels,
        2: np.fliplr(pixels),
        3: np.rot90(pixels, 2),
        4: np.flipud(pixels),
        5: pixels.swapaxes(0, 1),
        6: np.rot90(pixels, -1),
        7: np.flip(pixels.swapaxes(0, 1), axis=(0, 1)),
        8: np.rot90(pixels),
    }[orientation]


def high_resolution_jpeg(size, orientation):
    # One grayscale source at a time (not RGB/NumPy), closed before decoding.
    width, height = size
    exif = Image.Exif()
    exif[274] = orientation
    with Image.new('L', size) as image:
        for value, box in (
            (32, (0, 0, width // 2, height // 2)),
            (96, (width // 2, 0, width, height // 2)),
            (160, (0, height // 2, width // 2, height)),
            (224, (width // 2, height // 2, width, height)),
        ):
            image.paste(value, box)
        return encode_image(image, 'JPEG', quality=90, exif=exif)


class UploadResolutionTests(unittest.TestCase):
    def assert_rgb_image(self, image, shape):
        self.assertIsInstance(image, np.ndarray)
        self.assertEqual(image.dtype, np.uint8)
        self.assertEqual(image.shape, shape)
        self.assertLessEqual(max(image.shape[:2]), 2000)

    def decode_jpeg_with_lazy_checks(self, data, source_size):
        thumbnail = Image.Image.thumbnail
        draft = JpegImagePlugin.JpegImageFile.draft
        load = JpegImagePlugin.JpegImageFile.load
        transpose = ImageOps.exif_transpose
        convert = Image.Image.convert
        events = []
        raster_loads = []

        def tracked_thumbnail(image, *args, **kwargs):
            events.append('thumbnail')
            self.assertEqual(image.size, source_size)
            self.assertTrue(image.tile, 'JPEG must still be lazy at thumbnail entry')
            return thumbnail(image, *args, **kwargs)

        def tracked_draft(image, *args, **kwargs):
            events.append('draft')
            self.assertTrue(image.tile, 'Draft must precede raster loading')
            return draft(image, *args, **kwargs)

        def tracked_load(image, *args, **kwargs):
            if image.tile:
                events.append('load')
                self.assertIn('draft', events)
                raster_loads.append((image.size, image.decoderconfig[0]))
            return load(image, *args, **kwargs)

        def tracked_transpose(image, *args, **kwargs):
            events.append('orientation')
            # Fail before a regression can allocate a full-resolution EXIF copy.
            self.assertLessEqual(max(image.size), 2000)
            return transpose(image, *args, **kwargs)

        def tracked_convert(image, *args, **kwargs):
            self.assertLessEqual(max(image.size), 2000)
            return convert(image, *args, **kwargs)

        with (
            patch.object(Image.Image, 'thumbnail', tracked_thumbnail),
            patch.object(JpegImagePlugin.JpegImageFile, 'draft', tracked_draft),
            patch.object(JpegImagePlugin.JpegImageFile, 'load', tracked_load),
            patch.object(ImageOps, 'exif_transpose', tracked_transpose),
            patch.object(Image.Image, 'convert', tracked_convert),
        ):
            result = app.decode_image(data)

        self.assertEqual(events[0], 'thumbnail')
        self.assertLess(events.index('draft'), events.index('load'))
        self.assertLess(events.index('load'), events.index('orientation'))
        self.assertTrue(raster_loads)
        if min(source_size) >= 8000:
            loaded_size, decoder_scale = raster_loads[0]
            self.assertGreaterEqual(decoder_scale, 2)
            self.assertLess(
                loaded_size[0] * loaded_size[1], source_size[0] * source_size[1],
            )
        return result

    def test_real_48_108_and_200_mp_jpegs_are_accepted_and_bounded(self):
        for megapixels, size, orientation, shape in (
            (48, (8000, 6000), 1, (1500, 2000, 3)),
            (108, (12000, 9000), 6, (2000, 1500, 3)),
            (200, (20000, 10000), 7, (2000, 1000, 3)),
        ):
            with self.subTest(megapixels=megapixels, orientation=orientation):
                data = high_resolution_jpeg(size, orientation)
                self.assertLess(len(data), 20 * 1024 * 1024)
                with Image.open(BytesIO(data)) as source:
                    self.assertEqual(source.size, size)
                    self.assertEqual(source.width * source.height, megapixels * 1_000_000)
                result = self.decode_jpeg_with_lazy_checks(data, size)
                self.assert_rgb_image(result, shape)
                height, width = result.shape[:2]
                samples = result[[height // 4, 3 * height // 4]][:, [width // 4, 3 * width // 4]]
                expected = oriented_pixels(np.array([[32, 96], [160, 224]]), orientation)
                expected = np.repeat(expected[:, :, None], 3, axis=2)
                np.testing.assert_allclose(samples, expected, atol=2, rtol=0)

    def test_explicit_metadata_cap_rejects_before_thumbnail_or_load(self):
        image = MagicMock(spec=Image.Image)
        image.width, image.height = 20001, 10000
        image.size = (image.width, image.height)
        image.__enter__.return_value = image
        with (
            patch.object(Image, 'open', return_value=image),
            patch.object(ImageOps, 'exif_transpose') as transpose,
        ):
            with self.assertRaisesRegex(ValueError, '200 million pixels or fewer'):
                app.decode_image(b'metadata-only upload')
        image.thumbnail.assert_not_called()
        image.load.assert_not_called()
        transpose.assert_not_called()

    def test_pillow_warning_and_error_guards_reject_before_raster_loading(self):
        original_limit = Image.MAX_IMAGE_PIXELS
        original_filters = list(warnings.filters)
        with patch.object(PngImagePlugin.PngImageFile, 'load') as load:
            for size, cause in (
                ((20000, 10001), Image.DecompressionBombWarning),
                ((20000, 20001), Image.DecompressionBombError),
            ):
                with self.subTest(size=size, cause=cause):
                    with self.assertRaisesRegex(ValueError, '200 million') as raised:
                        app.decode_image(png_header(size))
                    self.assertIsInstance(raised.exception.__cause__, cause)
            load.assert_not_called()
        self.assertEqual(Image.MAX_IMAGE_PIXELS, original_limit)
        self.assertEqual(warnings.filters, original_filters)

    def test_empty_and_over_20_mb_uploads_reject_before_open(self):
        with patch.object(Image, 'open') as open_image:
            for data, message in (
                (b'', 'empty'),
                (b'\x00' * (20 * 1024 * 1024 + 1), '20 MB'),
            ):
                with self.subTest(message=message):
                    with self.assertRaisesRegex(ValueError, message):
                        app.decode_image(data)
            open_image.assert_not_called()

    def test_exactly_20_mb_valid_upload_is_accepted(self):
        data = image_bytes('RGB', (12, 9), (17, 63, 211))
        data += b'\x00' * (20 * 1024 * 1024 - len(data))
        self.assertEqual(len(data), 20 * 1024 * 1024)
        result = app.decode_image(data)
        self.assert_rgb_image(result, (9, 12, 3))
        np.testing.assert_array_equal(result[0, 0], [17, 63, 211])

    def test_supported_formats_keep_small_images_rgb_without_upscaling(self):
        for image_format, options in (
            ('JPEG', {'quality': 100, 'subsampling': 0}),
            ('PNG', {}),
            ('WEBP', {'lossless': True}),
            ('BMP', {}),
        ):
            with self.subTest(image_format=image_format):
                data = image_bytes('RGB', (12, 9), (17, 63, 211), image_format, **options)
                result = app.decode_image(data)
                self.assert_rgb_image(result, (9, 12, 3))
                expected = np.broadcast_to([17, 63, 211], result.shape)
                np.testing.assert_allclose(result, expected, atol=2, rtol=0)
        self.assert_rgb_image(app.decode_image(image_bytes('RGB', (3, 3), 'white')), (3, 3, 3))

    def test_grayscale_and_transparency_convert_to_rgb_on_white(self):
        for mode, color, options, expected in (
            ('L', 77, {}, [77, 77, 77]),
            ('LA', (50, 0), {}, [255, 255, 255]),
            ('RGBA', (10, 20, 30, 0), {}, [255, 255, 255]),
            ('RGBA', (0, 100, 200, 128), {}, [127, 177, 227]),
            ('RGB', (17, 63, 211), {'transparency': (17, 63, 211)}, [255, 255, 255]),
        ):
            with self.subTest(mode=mode, color=color):
                result = app.decode_image(image_bytes(mode, (12, 9), color, **options))
                self.assert_rgb_image(result, (9, 12, 3))
                np.testing.assert_array_equal(result, np.broadcast_to(expected, result.shape))
        result = app.decode_image(image_bytes('RGBA', (3000, 12), (10, 20, 30, 0)))
        self.assert_rgb_image(result, (8, 2000, 3))
        self.assertTrue((result == 255).all())

    def test_all_exif_flips_and_rotations_preserve_small_rgb_pixels(self):
        pixels = np.arange(8 * 12 * 3, dtype=np.uint8).reshape(8, 12, 3)
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                exif = Image.Exif()
                exif[274] = orientation
                with Image.fromarray(pixels) as image:
                    data = encode_image(image, exif=exif)
                expected = oriented_pixels(pixels, orientation)
                result = app.decode_image(data)
                self.assert_rgb_image(result, expected.shape)
                np.testing.assert_array_equal(result, expected)

    def test_thumbnail_rounding_is_preserved_near_minimum_dimension(self):
        for size in ((2001, 3), (3, 2001), (3000, 4), (4, 3000), (2700, 3), (3, 2700)):
            with self.subTest(size=size):
                data = image_bytes('L', size, 77)
                with Image.open(BytesIO(data)) as reference:
                    reference.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                    expected_size = reference.size
                if min(expected_size) < 3:
                    with self.assertRaisesRegex(ValueError, 'too narrow'):
                        app.decode_image(data)
                else:
                    result = app.decode_image(data)
                    self.assert_rgb_image(result, (*reversed(expected_size), 3))

    def test_too_small_metadata_rejects_before_raster_loading(self):
        with patch.object(PngImagePlugin.PngImageFile, 'load') as load:
            for size in ((2, 10000), (10000, 2), (1, 1)):
                with self.subTest(size=size):
                    with self.assertRaisesRegex(ValueError, 'at least 3 pixels'):
                        app.decode_image(png_header(size))
            load.assert_not_called()

    def test_extremely_narrow_metadata_rejects_before_raster_loading(self):
        with patch.object(PngImagePlugin.PngImageFile, 'load') as load:
            for size in ((50_000_000, 3), (3, 50_000_000), (4000, 3), (3, 4000)):
                with self.subTest(size=size):
                    with self.assertRaisesRegex(ValueError, 'too narrow'):
                        app.decode_image(png_header(size))
            load.assert_not_called()

    def test_invalid_truncated_and_unsupported_data_have_useful_errors(self):
        truncated_jpeg = image_bytes('L', (80, 60), 127, 'JPEG')[:-20]
        with Image.open(BytesIO(truncated_jpeg)) as image:
            self.assertEqual(image.size, (80, 60))
        for data in (
            b'not an image', b'\x89PNG\r\n\x1a\n', png_header((20, 20)),
            truncated_jpeg, image_bytes('RGB', (12, 9), 'white', 'GIF'),
        ):
            with self.subTest(length=len(data)):
                with self.assertRaisesRegex(ValueError, 'valid JPG, PNG, WebP, or BMP'):
                    app.decode_image(data)

    def test_decoder_memory_error_is_actionable_without_internal_details(self):
        data = image_bytes('RGB', (12, 9), 'white')
        with patch.object(
            PngImagePlugin.PngImageFile, 'load',
            side_effect=MemoryError('decoder-specific allocation details'),
        ):
            with self.assertRaisesRegex(ValueError, 'memory.*resize') as raised:
                app.decode_image(data)
        self.assertNotIn('decoder-specific', str(raised.exception))

    def test_uploader_help_describes_limits_and_downsized_downloads(self):
        with (
            patch.object(app.st, 'set_page_config'), patch.object(app.st, 'title'),
            patch.object(app.st, 'write'), patch.object(app.st, 'caption'),
            patch.object(app.st, 'info'), patch.object(app, 'clear_studio'),
            patch.object(app.st, 'file_uploader', return_value=None) as uploader,
        ):
            app.main()
        options = uploader.call_args.kwargs
        self.assertEqual(options['max_upload_size'], 20)
        self.assertEqual(options['type'], ['jpg', 'jpeg', 'png', 'webp', 'bmp'])
        self.assertFalse(options['accept_multiple_files'])
        for text in ('20 MB', '200 million source pixels', 'downsized', '2,000-pixel', 'downloads'):
            self.assertIn(text, options['help'])


if __name__ == '__main__':
    unittest.main()
