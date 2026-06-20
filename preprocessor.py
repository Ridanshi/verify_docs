import numpy as np
import fitz  # PyMuPDF — no Poppler required
from PIL import Image, ImageEnhance

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
MAX_SIDE = 1120

# Scan enhancement constants — mild values that help any real-world scan
_SHARPEN_FACTOR  = 1.5   # 1.0 = original, 2.0 = fully sharpened
_CONTRAST_FACTOR = 1.2   # 1.0 = original, slight lift for washed-out scans
_DESKEW_MAX_DEG  = 5.0   # search range; real skew rarely exceeds this
_DESKEW_STEP     = 0.5   # coarse enough to be fast, fine enough to matter
_DESKEW_MIN_DEG  = 0.3   # skip rotation if detected angle is negligible


def _resize(img: Image.Image) -> Image.Image:
    w, h = img.size
    if max(w, h) <= MAX_SIDE:
        return img
    scale = MAX_SIDE / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _detect_skew(img: Image.Image) -> float:
    """Estimate rotation angle by maximising row-projection variance on a thumbnail."""
    thumb = img.copy()
    thumb.thumbnail((300, 300))
    gray = np.array(thumb.convert("L"), dtype=np.float32)

    best_angle = 0.0
    best_var   = -1.0
    angles = np.arange(-_DESKEW_MAX_DEG, _DESKEW_MAX_DEG + 0.01, _DESKEW_STEP)
    for angle in angles:
        rotated   = thumb.rotate(float(angle), fillcolor=255)
        row_sums  = (np.array(rotated.convert("L"), dtype=np.float32) < 128).sum(axis=1)
        var       = float(np.var(row_sums))
        if var > best_var:
            best_var   = var
            best_angle = float(angle)
    return best_angle


def _enhance_scan(img: Image.Image) -> Image.Image:
    """Deskew + sharpen + mild contrast boost for scanned images."""
    angle = _detect_skew(img)
    if abs(angle) >= _DESKEW_MIN_DEG:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))

    img = ImageEnhance.Sharpness(img).enhance(_SHARPEN_FACTOR)
    img = ImageEnhance.Contrast(img).enhance(_CONTRAST_FACTOR)
    return img


def load_image(file_path: str) -> Image.Image:
    path = file_path.lower()

    if path.endswith(".pdf"):
        doc = fitz.open(file_path)
        page = doc[0]
        mat = fitz.Matrix(200 / 72, 200 / 72)  # 200 DPI
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return _resize(img)  # PDFs are clean renders — no scan enhancement needed

    ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    if ext not in SUPPORTED_IMAGE_EXTS:
        raise ValueError(f"Unsupported file format: '{ext}'. "
                         "Upload a PDF, JPG, PNG, or TIFF.")

    img = Image.open(file_path).convert("RGB")
    img = _resize(img)
    return _enhance_scan(img)
