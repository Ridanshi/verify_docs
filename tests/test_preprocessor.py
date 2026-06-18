import pytest
from PIL import Image
from preprocessor import load_image
import tempfile, os


def _make_test_image(path: str, size=(800, 600)):
    img = Image.new("RGB", size, color=(255, 255, 255))
    img.save(path)


def test_load_jpg():
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        path = f.name
    _make_test_image(path)
    img = load_image(path)
    assert isinstance(img, Image.Image)
    assert img.mode == "RGB"
    os.unlink(path)


def test_load_png():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    _make_test_image(path)
    img = load_image(path)
    assert isinstance(img, Image.Image)
    os.unlink(path)


def test_resize_large_image():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    _make_test_image(path, size=(3000, 4000))
    img = load_image(path)
    assert max(img.size) <= 1120
    os.unlink(path)


def test_unsupported_format_raises():
    with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
        path = f.name
        f.write(b"GIF89a")
    with pytest.raises(ValueError, match="Unsupported"):
        load_image(path)
    os.unlink(path)
