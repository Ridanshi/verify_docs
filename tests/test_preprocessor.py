import pytest
from PIL import Image
from preprocessor import load_image, load_image_high_res
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
    assert max(img.size) <= 2000
    os.unlink(path)


def test_unsupported_format_raises():
    with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
        path = f.name
        f.write(b"GIF89a")
    with pytest.raises(ValueError, match="Unsupported"):
        load_image(path)
    os.unlink(path)


def test_high_res_matches_load_image_resolution():
    # MAX_SIDE was raised to match MAX_SIDE_HIGH_RES (both 2000/300 DPI) after
    # the base extraction pass proved to benefit from the same resolution the
    # amount-refinement pass already used successfully — the two are now
    # intentionally the same, kept as separate constants since they serve
    # conceptually different purposes and may diverge again later.
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    _make_test_image(path, size=(3000, 4000))
    img_normal   = load_image(path)
    img_high_res = load_image_high_res(path)
    assert img_normal.size == img_high_res.size
    os.unlink(path)


def test_high_res_still_caps_extremely_large_images():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    _make_test_image(path, size=(6000, 8000))
    img = load_image_high_res(path)
    assert max(img.size) <= 2000
    os.unlink(path)


def test_high_res_unsupported_format_raises():
    with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
        path = f.name
        f.write(b"GIF89a")
    with pytest.raises(ValueError, match="Unsupported"):
        load_image_high_res(path)
    os.unlink(path)
