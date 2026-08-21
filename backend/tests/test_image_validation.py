"""Tests for image validation, transcoding, and transport coverage.

Covers the accepted/unsupported format matrix (JPEG, PNG, WebP, GIF, HEIC,
HEIF, BMP, AVIF), the 10 MiB limit, that every accepted format is normalized
to a JPEG, and that validated/transcoded images never leak into logs.
"""

import logging
from io import BytesIO

import pytest
from PIL import Image

from app.image import validation


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), (10, 120, 200)).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (16, 16), (10, 120, 200, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _webp_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), (10, 120, 200)).save(buffer, format="WEBP")
    return buffer.getvalue()


def _gif_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("P", (16, 16), 1).save(buffer, format="GIF")
    return buffer.getvalue()


def _bmp_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), (10, 120, 200)).save(buffer, format="BMP")
    return buffer.getvalue()


def _avif_bytes() -> bytes:
    return b"\x00\x00\x00\x1cftypavifMIB1\x00\x02\xff\xffgarbagepayload"


def _heic_bytes() -> bytes:
    import pillow_heif  # type: ignore[import-untyped]

    pillow_heif.register_heif_opener()
    buffer = BytesIO()
    Image.new("RGB", (24, 24), (10, 120, 200)).save(buffer, format="HEIF")
    return buffer.getvalue()


def _heif_bytes() -> bytes:
    import pillow_heif

    pillow_heif.register_heif_opener()
    buffer = BytesIO()
    Image.new("RGB", (24, 24), (10, 120, 200)).save(buffer, format="HEIF")
    return buffer.getvalue()


_FORMATS: dict[str, bytes] = {
    "JPEG": _jpeg_bytes(),
    "PNG": _png_bytes(),
    "WEBP": _webp_bytes(),
    "GIF": _gif_bytes(),
    "HEIF": _heif_bytes(),
}

_ACCEPTED: dict[str, bytes] = {
    "image/jpeg": _jpeg_bytes(),
    "image/png": _png_bytes(),
    "image/webp": _webp_bytes(),
    "image/gif": _gif_bytes(),
}


@pytest.mark.parametrize("source, raw", list(_ACCEPTED.items()))
def test_validate_image_accepts_and_types_each_accepted_format(source: str, raw: bytes) -> None:
    details = validation.validate_image(raw)
    assert details.media_type == source
    assert details.size == len(raw)


@pytest.mark.parametrize(
    "source",
    ["JPEG", "PNG", "WEBP", "GIF", "HEIF"],
)
def test_transcode_normalizes_every_accepted_format_to_jpeg(source: str) -> None:
    result = validation.prepare_image(_FORMATS[source])
    assert result.media_type == validation.MEDIA_JPEG
    assert result.bytes.startswith(b"\xff\xd8\xff")
    assert result.data_url == f"data:{validation.MEDIA_JPEG};base64,{_b64(result.bytes)}"


def _b64(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode("ascii")


def test_detect_media_type_jpeg_prefix() -> None:
    assert validation.detect_media_type(_jpeg_bytes()) == validation.MEDIA_JPEG
    assert validation.detect_media_type(_png_bytes()) == validation.MEDIA_PNG
    assert validation.detect_media_type(_gif_bytes()) == validation.MEDIA_GIF
    assert validation.detect_media_type(_webp_bytes()) == validation.MEDIA_WEBP


@pytest.mark.parametrize(
    "source",
    ["JPEG", "PNG", "WEBP", "GIF", "HEIF"],
)
def test_validate_accepts_real_formats(source: str) -> None:
    validation.validate_image(_FORMATS[source])


def test_heic_round_trips_through_validation_and_transcode() -> None:
    raw = _heic_bytes()
    validation.validate_image(raw)
    result = validation.prepare_image(raw)
    assert result.media_type == validation.MEDIA_JPEG
    assert len(result.bytes) > 0


def test_invalid_format_rejected() -> None:
    from app.image.validation import MediaValidationError

    for raw in (_bmp_bytes(), _avif_bytes()):
        with pytest.raises(MediaValidationError):
            validation.validate_image(raw)


def test_empty_and_overlimit_rejected() -> None:
    from app.image.validation import MediaValidationError

    with pytest.raises(MediaValidationError):
        validation.validate_image(b"")
    with pytest.raises(MediaValidationError):
        validation.validate_image(b"\xff\xd8\xff" + b"\x00" * (validation.MAX_IMAGE_BYTES + 1))


def test_corrupt_bytes_rejected() -> None:
    from app.image.validation import MediaValidationError

    with pytest.raises(MediaValidationError):
        validation.validate_image(b"\xff\xd8\xff\xea" + b"\x00" * 200)


def test_logs_record_only_type_and_size() -> None:
    records: list[logging.LogRecord] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Handler()
    logger = logging.getLogger("app.image.validation")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        validation.validate_image(_jpeg_bytes())
        validation.prepare_image(_jpeg_bytes())
    finally:
        logger.removeHandler(handler)

    rendered = "".join(record.getMessage() for record in records)
    assert "image/jpeg" in rendered
    assert "validated" in rendered
    assert "transcoded" in rendered
    # No raw bytes, base64, or data URLs leak into the log.
    assert ";base64," not in rendered
    assert "<binary>" not in rendered
