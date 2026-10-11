"""Right-angle orientation and bounded small-angle deskew with inverse maps."""

import fitz
from PIL import Image


def rotate(image, transform, angle):
    width, height = image.size
    if angle == 180:
        return image.transpose(Image.Transpose.ROTATE_180), fitz.Matrix(-1, 0, 0, -1, width, height) * transform
    if angle == 90:
        return image.transpose(Image.Transpose.ROTATE_90), fitz.Matrix(0, 1, -1, 0, width, 0) * transform
    if angle == 270:
        return image.transpose(Image.Transpose.ROTATE_270), fitz.Matrix(0, -1, 1, 0, 0, height) * transform
    inverse = fitz.Matrix(1, 0, 0, 1, -width / 2, -height / 2) * fitz.Matrix(angle) * fitz.Matrix(1, 0, 0, 1, width / 2, height / 2)
    return image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor="white"), inverse * transform


def locate(image, transform, detect):
    straight = detect(image)
    choices = []
    if straight:
        flipped, inverse = rotate(image, transform, 180)
        choices.extend([(image, transform, 0, straight), (flipped, inverse, 180, detect(flipped))])
    for angle in (90, 270):
        oriented, inverse = rotate(image, transform, angle)
        found = detect(oriented)
        if found:
            choices.append((oriented, inverse, angle, found))
    if choices:
        return choices
    # Search at low resolution first, retaining at most three full-resolution
    # attempts. This is correction of measured line geometry, not of text.
    preview = image.copy()
    preview.thumbnail((1000, 1000))
    proposals = []
    for angle in (-.5, .5, -1, 1, -1.5, 1.5, -2, 2, -2.5, 2.5, -3, 3):
        small = preview.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor="white")
        found = detect(small)
        if found:
            proposals.append((sum(len(grid["ys"]) for grid in found), angle))
    for _, angle in sorted(proposals, reverse=True)[:3]:
        oriented, inverse = rotate(image, transform, angle)
        found = detect(oriented)
        if found:
            flipped, flip_inverse = rotate(oriented, inverse, 180)
            return [(oriented, inverse, angle, found), (flipped, flip_inverse, angle + 180, detect(flipped))]
    return []
