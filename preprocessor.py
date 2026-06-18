from PIL import Image
from pdf2image import convert_from_path

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
        pages = convert_from_path(file_path, dpi=200, first_page=1, last_page=1)
        img = pages[0].convert("RGB")
        return _resize(img)

    ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    if ext not in SUPPORTED_IMAGE_EXTS:
        raise ValueError(f"Unsupported file format: '{ext}'. "
                         "Upload a PDF, JPG, PNG, or TIFF.")

    img = Image.open(file_path).convert("RGB")
    return _resize(img)
