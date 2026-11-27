"""Floor plans (0.9) – optional pictures under the house tiles, one per floor.

PNG or JPEG only, at most 2 MB, checked by magic bytes, stored locally in Bifrost's own database.
"""

from __future__ import annotations

import base64

MAX_FLOORPLAN = 2 * 1024 * 1024
PNG_MAGIC, JPEG_MAGIC = b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"


def validate_floorplan(b64: str) -> tuple[bytes, str]:
    """Decode an uploaded floor plan. Only PNG/JPEG, at most 2 MB. Raises ValueError."""
    if not isinstance(b64, str) or len(b64) > MAX_FLOORPLAN * 4 // 3 + 16:
        raise ValueError("floor plan too large (max 2 MB)")
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception as err:  # noqa: BLE001
        raise ValueError("invalid encoding") from err
    if len(data) > MAX_FLOORPLAN:
        raise ValueError("floor plan too large (max 2 MB)")
    if data.startswith(PNG_MAGIC):
        return data, "image/png"
    if data.startswith(JPEG_MAGIC):
        return data, "image/jpeg"
    raise ValueError("only PNG or JPEG")
