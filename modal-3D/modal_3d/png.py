"""Small PNG helpers used by canonical-input validation and benchmarks.

Only the canonical format is supported: 8-bit, non-interlaced RGBA PNG.
Keeping this decoder dependency-free lets CPU gateway/benchmark checks run
without Pillow while still validating the exact bytes sent to GPU workers.
"""

from __future__ import annotations

import binascii
import zlib


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_up and distance_left <= distance_upper_left:
        return left
    if distance_up <= distance_upper_left:
        return up
    return upper_left


def _idat_payload(data: bytes) -> bytes:
    offset = 8
    idat = bytearray()
    saw_iend = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        body_start = offset + 8
        body_end = body_start + length
        crc_end = body_end + 4
        if crc_end > len(data):
            raise ValueError("PNG chunk is truncated")
        body = data[body_start:body_end]
        expected_crc = int.from_bytes(data[body_end:crc_end], "big")
        actual_crc = binascii.crc32(chunk_type)
        actual_crc = binascii.crc32(body, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("PNG chunk CRC is invalid")
        if chunk_type == b"IDAT":
            idat.extend(body)
        elif chunk_type == b"IEND":
            saw_iend = True
            break
        offset = crc_end
    if not idat or not saw_iend:
        raise ValueError("PNG must contain IDAT and IEND chunks")
    try:
        return zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise ValueError("PNG image data could not be decompressed") from exc


def decode_rgba8(data: bytes, width: int, height: int) -> list[bytes]:
    """Return reconstructed RGBA rows for a canonical non-interlaced PNG."""
    raw = _idat_payload(data)
    stride = width * 4
    if len(raw) != height * (stride + 1):
        raise ValueError("PNG decoded data length does not match dimensions")

    rows: list[bytes] = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor : cursor + stride]
        cursor += stride
        if filter_type > 4:
            raise ValueError(f"unsupported PNG filter type: {filter_type}")

        current = bytearray(stride)
        for index, value in enumerate(encoded):
            left = current[index - 4] if index >= 4 else 0
            up = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            else:
                predictor = _paeth(left, up, upper_left)
            current[index] = (value + predictor) & 0xFF
        rows.append(bytes(current))
        previous = current
    return rows


def alpha_range(data: bytes, width: int, height: int) -> tuple[int, int]:
    """Fast alpha-only decode for the production canonical contract."""
    raw = _idat_payload(data)
    stride = width * 4
    if len(raw) != height * (stride + 1):
        raise ValueError("PNG decoded data length does not match dimensions")

    previous = bytearray(width)
    alpha_min, alpha_max = 255, 0
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor : cursor + stride][3::4]
        cursor += stride
        if filter_type > 4:
            raise ValueError(f"unsupported PNG filter type: {filter_type}")
        current = bytearray(width)
        for index, value in enumerate(encoded):
            left = current[index - 1] if index else 0
            up = previous[index]
            upper_left = previous[index - 1] if index else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            else:
                predictor = _paeth(left, up, upper_left)
            current[index] = (value + predictor) & 0xFF
        alpha_min = min(alpha_min, min(current))
        alpha_max = max(alpha_max, max(current))
        previous = current
    return alpha_min, alpha_max


def foreground_stats(data: bytes, width: int, height: int, *, alpha_threshold: int = 8) -> dict:
    """Describe RGB information inside visible foreground pixels.

    These statistics are diagnostic, not part of the production image contract:
    a genuinely black object is valid. Benchmark tooling may apply stricter
    thresholds because benchmark source images are known to contain color data.
    """
    foreground = 0
    rgb_nonzero = 0
    rgb_min, rgb_max = 255, 0
    x_min, y_min = width, height
    x_max = y_max = -1

    for y, row in enumerate(decode_rgba8(data, width, height)):
        for x in range(width):
            base = x * 4
            r, g, b, a = row[base : base + 4]
            if a <= alpha_threshold:
                continue
            foreground += 1
            if r or g or b:
                rgb_nonzero += 1
            rgb_min = min(rgb_min, r, g, b)
            rgb_max = max(rgb_max, r, g, b)
            x_min, y_min = min(x_min, x), min(y_min, y)
            x_max, y_max = max(x_max, x), max(y_max, y)

    total = width * height
    bbox = None if foreground == 0 else [x_min, y_min, x_max + 1, y_max + 1]
    return {
        "foreground_pixels": foreground,
        "foreground_fraction": foreground / total,
        "foreground_rgb_nonzero_fraction": 0.0 if foreground == 0 else rgb_nonzero / foreground,
        "foreground_rgb_min": None if foreground == 0 else rgb_min,
        "foreground_rgb_max": None if foreground == 0 else rgb_max,
        "foreground_bbox": bbox,
    }
