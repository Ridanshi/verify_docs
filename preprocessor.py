import fitz  # PyMuPDF — no Poppler required
from PIL import Image

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
MAX_SIDE = 1120


def _resize(img: Image.Image) -> Image.Image:
    w, h = img.size
    if max(w, h) <= MAX_SIDE:
        return img
    scale = MAX_SIDE / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def load_image(file_path: str) -> Image.Image:
    path = file_path.lower()

    if path.endswith(".pdf"):
        doc = fitz.open(file_path)
        page = doc[0]
        mat = fitz.Matrix(200 / 72, 200 / 72)  # 200 DPI
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return _resize(img)

    ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    if ext not in SUPPORTED_IMAGE_EXTS:
        raise ValueError(f"Unsupported file format: '{ext}'. "
                         "Upload a PDF, JPG, PNG, or TIFF.")

    img = Image.open(file_path).convert("RGB")
    return _resize(img)
