import base64
import io
import logging
from dataclasses import dataclass
from typing import Literal

MAX_IMAGE_BYTES = 10 * 1024 * 1024

MEDIA_JPEG = "image/jpeg"
MEDIA_PNG = "image/png"
MEDIA_WEBP = "image/webp"
MEDIA_HEIC = "image/heic"
MEDIA_HEIF = "image/heif"
MEDIA_GIF = "image/gif"

InputType = Literal["text", "image"]
SUPPORTED_MEDIA = frozenset({MEDIA_JPEG, MEDIA_PNG, MEDIA_WEBP, MEDIA_HEIC, MEDIA_HEIF, MEDIA_GIF})

logger = logging.getLogger(__name__)


class MediaValidationError(Exception):
    pass


@dataclass
class MediaDetails:
    media_type: str
    size: int


@dataclass
class TranscodedImage:
    media_type: str
    data_url: str
    size: int
    bytes: bytes


def _fourcc(raw: bytes, offset: int) -> str:
    end = min(offset + 4, len(raw))
    return raw[offset:end].decode("ascii", errors="replace")


def detect_media_type(raw: bytes) -> str:
    if not raw:
        raise MediaValidationError("the file is empty.")
    if raw[:8] == b"\xff\xd8\xff":
        return MEDIA_JPEG
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return MEDIA_PNG
    if raw[:4] == b"GIF8" and raw[4:6] in (b"7a", b"9a"):
        return MEDIA_GIF
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return MEDIA_WEBP
    if raw[4:8] == b"ftyp":
        brand = _fourcc(raw, 8).lower()
        if brand.startswith(("heic", "heix", "avici", "mlih", "mfi1")) or brand == "m1ai":
            return MEDIA_HEIC
        if brand.startswith(("heif",)):
            return MEDIA_HEIF
    raise MediaValidationError("unsupported image type.")


def validate_image(raw: bytes) -> MediaDetails:
    if not raw:
        raise MediaValidationError("the file is empty.")
    size = len(raw)
    if size > MAX_IMAGE_BYTES:
        raise MediaValidationError("the image exceeds the 10 MiB maximum upload size.")
    media_type = detect_media_type(raw)
    if media_type not in SUPPORTED_MEDIA:
        raise MediaValidationError(
            "unsupported image type. JPEG, PNG, WebP, HEIC/HEIF, and GIF are supported."
        )
    try:
        from PIL import Image

        Image.open(io.BytesIO(raw)).verify()
    except Exception:
        raise MediaValidationError("the file is not a readable image.") from None
    logger.debug("validated %s image (%d bytes)", media_type, size)
    return MediaDetails(media_type=media_type, size=size)


def transcode_to_jpeg(raw: bytes) -> TranscodedImage:
    from PIL import Image

    source = Image.open(io.BytesIO(raw))
    image = source.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90, optimize=True)
    jpeg = buffer.getvalue()
    encoded = base64.b64encode(jpeg).decode("ascii")
    logger.debug("transcoded image to JPEG (%d bytes)", len(jpeg))
    return TranscodedImage(
        media_type=MEDIA_JPEG,
        data_url=f"data:{MEDIA_JPEG};base64,{encoded}",
        size=len(jpeg),
        bytes=jpeg,
    )


def prepare_image(raw: bytes) -> TranscodedImage:
    """Validate the source bytes, then return a standardized JPEG image."""
    validate_image(raw)
    return transcode_to_jpeg(raw)
