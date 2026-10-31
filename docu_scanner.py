

import cv2


def resize_img(img):
    return cv2.resize(img, (800, 1100))


img = cv2.imread('image fix.jpg')
#cv2.imshow('Original Image', resize_img(img))



hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
saturation = hsv[:, :, 1]

# Threshold saturation
_, mask = cv2.threshold(
    saturation,
    60,
    255,
    cv2.THRESH_BINARY_INV
)

# Create kernel
kernel = cv2.getStructuringElement(
    cv2.MORPH_RECT,
    (5, 5)
)

# Fill small holes
closed = cv2.morphologyEx(
    mask,
    cv2.MORPH_CLOSE,
    kernel,
    iterations=2
)
# Remove small noise
cleaned = cv2.morphologyEx(
    closed,
    cv2.MORPH_OPEN,
    kernel,
    iterations=1
)



#contour filtering
con,hierarchy = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
sorted_contours = sorted(con, key=cv2.contourArea, reverse=True)

largest_contours = sorted_contours[:1]

img_copy = img.copy()

cv2.drawContours(img_copy, largest_contours, -1, (0,255,0), 2)



document_contour = sorted_contours[0]

# Calculate perimeter
perimeter = cv2.arcLength(document_contour, True)


approx = cv2.approxPolyDP(
    document_contour, 0.04 * perimeter, True
)
for point in approx:
    x, y = point[0]
    cv2.circle(img_copy, (x, y), 15, (0, 0, 255), -1)



#reordering points;
import numpy as np

def reorder_points(points):

    points = points.reshape(4, 2)

    ordered = np.zeros((4, 2), dtype=np.float32)

    # Calculate sums
    s = points.sum(axis=1)

    # Calculate differences (y - x)
    d = np.diff(points, axis=1).flatten()

    ordered[0] = points[np.argmin(s)]  # Top-left
    ordered[1] = points[np.argmin(d)]  # Top-right
    ordered[2] = points[np.argmax(d)]  # Bottom-left
    ordered[3] = points[np.argmax(s)]  # Bottom-right

    return ordered
ordered_points = reorder_points(approx)

import numpy as np

# Source points
pts = ordered_points

# Reorder for perspective transformation
src = np.array([
    pts[0],  # Top-left
    pts[1],  # Top-right
    pts[3],  # Bottom-right
    pts[2]   # Bottom-left
], dtype=np.float32)


# Calculate output width
width_top = np.linalg.norm(src[1] - src[0])
width_bottom = np.linalg.norm(src[2] - src[3])

max_width = int(max(width_top, width_bottom))


# Calculate output height
height_left = np.linalg.norm(src[3] - src[0])
height_right = np.linalg.norm(src[2] - src[1])

max_height = int(max(height_left, height_right))


# Destination points
dst = np.array([
    [0, 0],
    [max_width - 1, 0],
    [max_width - 1, max_height - 1],
    [0, max_height - 1]
], dtype=np.float32)


# Calculate transformation matrix
matrix = cv2.getPerspectiveTransform(src, dst)


# Apply perspective transformation
warped = cv2.warpPerspective(
    img,
    matrix,
    (max_width, max_height)
)
warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
clahe = cv2.createCLAHE(
    clipLimit=1.0,
    tileGridSize=(8, 8)
)
denoised = cv2.fastNlMeansDenoising(
    warped_gray,
    None,
    8,
    7,
    21
)
# Apply contrast enhancement
enhanced = clahe.apply(denoised)

adaptive = cv2.adaptiveThreshold(
    enhanced,
    255,
    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
    cv2.THRESH_BINARY,
    21,
    10
)
cv2.imshow("Before CLAHE", resize_img(warped_gray))
cv2.imshow("After CLAHE", resize_img(enhanced))
cv2.imshow("Scanned Document", resize_img(warped))
cv2.imshow('Adaptive Image', resize_img(adaptive))
cv2.waitKey(0)
cv2.destroyAllWindows()