import argparse
import sys

import cv2
import numpy as np


MAX_PROCESSING_DIMENSION = 2000
SCAN_STYLES = ('black-and-white', 'grayscale', 'color')


def resize_image(image, max_dimension=MAX_PROCESSING_DIMENSION):
    height, width = image.shape[:2]
    scale = min(1.0, max_dimension / max(height, width))
    if scale == 1.0:
        return image
    return cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def validate_image(image, minimum_dimension=3):
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
    ):
        raise ValueError('The scanner needs an 8-bit BGR image with three channels.')
    if min(image.shape[:2]) < minimum_dimension:
        raise ValueError(f'The image must be at least {minimum_dimension} pixels wide and tall.')


def reorder_points(points):
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    start = np.lexsort((ordered[:, 1], ordered.sum(axis=1)))[0]
    return np.roll(ordered, -start, axis=0)


def find_document_corners(image):
    height, width = image.shape[:2]
    image_area = height * width
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    saturation = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 1]
    _, mask = cv2.threshold(saturation, 60, 255, cv2.THRESH_BINARY_INV)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    cleaned = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel, iterations=1)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    closed_edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    for candidate_mask in (cleaned, closed_edges):
        contours, _ = cv2.findContours(
            candidate_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
            if cv2.contourArea(contour) < image_area * 0.1:
                break
            perimeter = cv2.arcLength(contour, True)
            for tolerance in (0.02, 0.03, 0.04):
                corners = cv2.approxPolyDP(contour, tolerance * perimeter, True)
                if len(corners) != 4 or not cv2.isContourConvex(corners):
                    continue
                if cv2.contourArea(corners) < image_area * 0.1:
                    continue
                left, top, box_width, box_height = cv2.boundingRect(corners)
                if (
                    cv2.contourArea(corners) >= image_area * 0.95
                    and left <= 1
                    and top <= 1
                    and left + box_width >= width - 1
                    and top + box_height >= height - 1
                ):
                    continue
                points = corners.reshape(4, 2)
                if len(np.unique(points, axis=0)) == 4:
                    return reorder_points(points)
    return None


def warp_document(image, corners):
    """Crop a BGR image using four clockwise page corners in image pixels."""
    validate_image(image)
    try:
        points = np.asarray(corners, dtype=np.float32)
    except (TypeError, ValueError) as error:
        raise ValueError('Place four distinct handles on the page corners.') from error
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError('Place four finite, distinct handles on the page corners.')
    height, width = image.shape[:2]
    if (points < 0).any() or (points > [width - 1, height - 1]).any():
        raise ValueError('Keep every corner handle inside the image.')
    if len(np.unique(points, axis=0)) != 4:
        raise ValueError('Separate the handles so each marks a different page corner.')
    contour = points.reshape(4, 1, 2)
    if not cv2.isContourConvex(contour) or cv2.contourArea(contour, oriented=True) <= 0:
        raise ValueError(
            'Keep the handles in clockwise order without crossing: '
            'top-left, top-right, bottom-right, bottom-left.'
        )

    top_left, top_right, bottom_right, bottom_left = points
    output_width = round(max(
        np.linalg.norm(top_right - top_left),
        np.linalg.norm(bottom_right - bottom_left),
    ))
    output_height = round(max(
        np.linalg.norm(bottom_left - top_left),
        np.linalg.norm(bottom_right - top_right),
    ))
    if min(output_width, output_height) < 3:
        raise ValueError('Spread the handles apart; the selected page is too small.')
    destination = np.array([
        [0, 0],
        [output_width - 1, 0],
        [output_width - 1, output_height - 1],
        [0, output_height - 1],
    ], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(points, destination)
    if not np.isfinite(matrix).all() or np.linalg.matrix_rank(matrix) < 3:
        raise ValueError('The selected page is degenerate. Adjust its corners.')
    return resize_image(cv2.warpPerspective(image, matrix, (output_width, output_height)))


def normalize_illumination(lightness):
    """Flatten slow lighting changes while protecting dark text strokes."""
    kernel_size = max(3, round(min(lightness.shape) / 30) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    background = cv2.dilate(lightness, kernel)
    background = cv2.GaussianBlur(background, (0, 0), max(1.0, kernel_size / 2))
    denominator = np.maximum(background, 1).astype(np.float32)
    normalized = cv2.divide(lightness.astype(np.float32), denominator, scale=255.0)
    return np.clip(normalized, 0, 255).astype(np.uint8)


def enhance_document(
    image, *, style='black-and-white', remove_shadows=False,
    denoise_strength=8, contrast=1.0, threshold_offset=10,
):
    """Enhance a cropped BGR page; color returns BGR, other styles grayscale."""
    validate_image(image, minimum_dimension=1)
    if style not in SCAN_STYLES:
        raise ValueError('Choose black-and-white, grayscale, or color scan style.')
    for value, lower, upper, label in (
        (denoise_strength, 0, 15, 'Noise cleanup'),
        (contrast, 1.0, 3.0, 'Contrast'),
        (threshold_offset, 0, 20, 'Paper whitening'),
    ):
        if not isinstance(value, (int, float)) or not np.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f'{label} must be between {lower} and {upper}.')

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB) if style == 'color' else None
    lightness = lab[:, :, 0] if lab is not None else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if remove_shadows:
        lightness = normalize_illumination(lightness)
    if denoise_strength > 0:
        lightness = cv2.fastNlMeansDenoising(lightness, None, denoise_strength, 7, 21)
    enhanced = cv2.createCLAHE(clipLimit=contrast, tileGridSize=(8, 8)).apply(lightness)
    if lab is not None:
        lab[:, :, 0] = enhanced
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    if style == 'grayscale':
        return enhanced
    return cv2.adaptiveThreshold(
        enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        21, threshold_offset,
    )


def scan_document(image):
    """Return a black-and-white scan and whether perspective was corrected."""
    validate_image(image)
    working_image = resize_image(image)
    corners = find_document_corners(working_image)
    perspective_corrected = False
    if corners is not None:
        try:
            working_image = warp_document(working_image, corners)
            perspective_corrected = True
        except ValueError:
            pass
    return enhance_document(working_image), perspective_corrected


def main():
    parser = argparse.ArgumentParser(description='Scan a document from an image.')
    parser.add_argument(
        'image', nargs='?', default='imig.jpg',
        help='Path to the document image to scan.',
    )
    arguments = parser.parse_args()
    image = cv2.imread(arguments.image)
    if image is None:
        parser.error(f'Could not read image: {arguments.image}')
    try:
        scanned, perspective_corrected = scan_document(image)
    except (ValueError, cv2.error) as error:
        parser.error(f'Could not scan image: {error}')
    if not perspective_corrected:
        print(
            'No document corners found; enhancing the whole image without '
            'perspective correction.',
            file=sys.stderr,
        )
    cv2.imshow('Scanned Image', resize_image(scanned, 1100))
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
