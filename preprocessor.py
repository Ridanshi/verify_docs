# Preprocessor — turns whatever file the user uploads into a clean PIL image
# that the vision model can read accurately.
#
# PDFs are rendered at 200 DPI using PyMuPDF (no Poppler installation needed).
# JPGs and PNGs go through a light scan-enhancement pass — deskew, sharpen, contrast —
# because real-world scans are often slightly tilted or washed out.

import numpy as np
import fitz  # PyMuPDF
from PIL import Image, ImageEnhance

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}

# The model was trained on images up to 1120×1120. Anything larger gets scaled down.
MAX_SIDE = 1120

# Enhancement strengths — kept mild on purpose. Aggressive sharpening or contrast
# can actually hurt OCR by creating artefacts.
_SHARPEN_FACTOR  = 1.5   # 1.0 = original sharpness
_CONTRAST_FACTOR = 1.2   # 1.0 = original contrast
_DESKEW_MAX_DEG  = 5.0   # search ±5° — real scan tilt rarely exceeds this
_DESKEW_STEP     = 0.5   # step size for the angle search
_DESKEW_MIN_DEG  = 0.3   # don't bother rotating if the tilt is less than this


def _resize(img: Image.Image) -> Image.Image:
    """Scale the image down so its longest side is at most 1120px.
    Images smaller than 1120px are left untouched."""
    w, h = img.size
    if max(w, h) <= MAX_SIDE:
        return img
    scale = MAX_SIDE / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _detect_skew(img: Image.Image) -> float:
    """Find the rotation angle that straightens the text.

    Works by rotating a small thumbnail through angles from -5° to +5° and
    picking the angle where the row pixel-sums have the highest variance.
    Straight text creates sharp bright/dark row bands — maximising variance
    finds the angle where text is most horizontal.
    """
    thumb = img.copy()
    thumb.thumbnail((300, 300))  # work on a small copy — much faster

    best_angle = 0.0
    best_var   = -1.0
    angles = np.arange(-_DESKEW_MAX_DEG, _DESKEW_MAX_DEG + 0.01, _DESKEW_STEP)

    for angle in angles:
        rotated  = thumb.rotate(float(angle), fillcolor=255)
        row_sums = (np.array(rotated.convert("L"), dtype=np.float32) < 128).sum(axis=1)
        var      = float(np.var(row_sums))
        if var > best_var:
            best_var   = var
            best_angle = float(angle)

    return best_angle


def _enhance_scan(img: Image.Image) -> Image.Image:
    """Fix tilt, sharpen, and boost contrast on a scanned image.

    Called only on JPG/PNG inputs — PDFs are already clean vector renders
    and don't need this treatment.
    """
    angle = _detect_skew(img)
    if abs(angle) >= _DESKEW_MIN_DEG:
        # Rotate to straighten; fill the empty corners with white
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))

    img = ImageEnhance.Sharpness(img).enhance(_SHARPEN_FACTOR)
    img = ImageEnhance.Contrast(img).enhance(_CONTRAST_FACTOR)
    return img


def load_image(file_path: str) -> Image.Image:
    """Load a PDF or image file and return a clean, model-ready PIL image.

    PDF  → rendered at 200 DPI via PyMuPDF → resized (no scan enhancement).
    Image → opened with PIL → resized → deskew + sharpen + contrast boost.

    Raises ValueError for unsupported file formats.
    """
    path = file_path.lower()

    if path.endswith(".pdf"):
        doc  = fitz.open(file_path)
        page = doc[0]  # always use the first page
        mat  = fitz.Matrix(200 / 72, 200 / 72)  # render at 200 DPI
        pix  = page.get_pixmap(matrix=mat)
        img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return _resize(img)  # PDFs are already clean — skip scan enhancement

    ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    if ext not in SUPPORTED_IMAGE_EXTS:
        raise ValueError(
            f"Unsupported file format: '{ext}'. Upload a PDF, JPG, PNG, or TIFF."
        )

    img = Image.open(file_path).convert("RGB")
    img = _resize(img)
    return _enhance_scan(img)  # scanned images benefit from cleanup
