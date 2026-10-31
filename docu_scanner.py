

import cv2


def resize_img(img):
    return cv2.resize(img, (800, 1100))


img = cv2.imread('imig.jpg')
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

cv2.imshow("Original Mask", resize_img(mask))
cv2.imshow("Cleaned Mask", resize_img(cleaned))


#contour filtering
con,hierarchy = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
sorted_contours = sorted(con, key=cv2.contourArea, reverse=True)

largest_contours = sorted_contours[:1]

img_copy = img.copy()

cv2.drawContours(img_copy, largest_contours, -1, (0,255,0), 2)
cv2.imshow('Contours_original', resize_img(img_copy))


document_contour = sorted_contours[0]

# Calculate perimeter
perimeter = cv2.arcLength(document_contour, True)

# Try different approximation tolerances
approx1 = cv2.approxPolyDP(
    document_contour, 0.01 * perimeter, True
)

approx2 = cv2.approxPolyDP(
    document_contour, 0.02 * perimeter, True
)

approx3 = cv2.approxPolyDP(
    document_contour, 0.04 * perimeter, True
)

print("Epsilon 0.01:", len(approx1))
print("Epsilon 0.02:", len(approx2))
print("Epsilon 0.04:", len(approx3))

cv2.waitKey(0)
cv2.destroyAllWindows()