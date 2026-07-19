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

# Qwen2.5-VL uses native dynamic resolution (no fixed input size) — 1120 was
# a speed/memory-driven cap, not a model limit. Raised to match
# MAX_SIDE_HIGH_RES below, since that value is validated working (amount-stress
# test: 10/10 correct across a spread of magnitudes at this resolution) —
# reusing a proven number here for the main pass too, rather than guessing a
# new one. Helps small print on ANY field (not just amounts), including the
# single-digit misreads seen on loan_account_number/application_id.
MAX_SIDE = 2000
PDF_DPI  = 300

# Used for the focused amount-only re-extraction pass (see extractor.py's
# refine_amount_fields()) — kept as a separate constant even though it's
# currently the same value as MAX_SIDE/PDF_DPI above, since the two serve
# conceptually different purposes and may need to diverge again later.
MAX_SIDE_HIGH_RES = 2000
HIGH_RES_PDF_DPI  = 300

# Enhancement strengths — kept mild on purpose. Aggressive sharpening or contrast
# can actually hurt OCR by creating artefacts.
_SHARPEN_FACTOR  = 1.5   # 1.0 = original sharpness
_CONTRAST_FACTOR = 1.2   # 1.0 = original contrast
_DESKEW_MAX_DEG  = 5.0   # search ±5° — real scan tilt rarely exceeds this
_DESKEW_STEP     = 0.5   # step size for the angle search
_DESKEW_MIN_DEG  = 0.3   # don't bother rotating if the tilt is less than this


def _resize(img: Image.Image, max_side: int = MAX_SIDE) -> Image.Image:
    """Scale the image down so its longest side is at most max_side px.
    Images already smaller than that are left untouched."""
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    scale = max_side / max(w, h)
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


def _load(file_path: str, max_side: int, pdf_dpi: int) -> Image.Image:
    """Shared implementation behind load_image() and load_image_high_res() —
    only the resolution differs between the two."""
    path = file_path.lower()

    if path.endswith(".pdf"):
        doc  = fitz.open(file_path)
        page = doc[0]  # always use the first page
        mat  = fitz.Matrix(pdf_dpi / 72, pdf_dpi / 72)
        pix  = page.get_pixmap(matrix=mat)
        img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return _resize(img, max_side)  # PDFs are already clean — skip scan enhancement

    ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    if ext not in SUPPORTED_IMAGE_EXTS:
        raise ValueError(
            f"Unsupported file format: '{ext}'. Upload a PDF, JPG, PNG, or TIFF."
        )

    img = Image.open(file_path).convert("RGB")
    img = _resize(img, max_side)
    return _enhance_scan(img)  # scanned images benefit from cleanup


def load_image(file_path: str) -> Image.Image:
    """Load a PDF or image file and return a clean, model-ready PIL image.

    PDF  → rendered at PDF_DPI via PyMuPDF → resized to MAX_SIDE (no scan enhancement).
    Image → opened with PIL → resized to MAX_SIDE → deskew + sharpen + contrast boost.

    Raises ValueError for unsupported file formats.
    """
    return _load(file_path, max_side=MAX_SIDE, pdf_dpi=PDF_DPI)


def load_image_high_res(file_path: str) -> Image.Image:
    """Same as load_image(), but at a higher resolution cap (MAX_SIDE_HIGH_RES)
    and higher PDF render DPI. Used only for the focused amount-only
    re-extraction pass — small print needs more detail than the main
    9-field pass requires, at the cost of more GPU compute per call.

    Raises ValueError for unsupported file formats.
    """
    return _load(file_path, max_side=MAX_SIDE_HIGH_RES, pdf_dpi=HIGH_RES_PDF_DPI)
