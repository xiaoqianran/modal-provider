from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from hashlib import sha256
from typing import Any

from .errors import ConnectorError

_SECRET_KEY = re.compile(
    r"authorization|api[-_]?key|access[-_]?token|refresh[-_]?token|secret|credential|signed[-_]?url",
    re.IGNORECASE,
)
_JS_MAX_SAFE_INTEGER = 2**53 - 1

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def safe_json(value: Any, path: str = "value") -> JsonValue:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        if abs(value) > _JS_MAX_SAFE_INTEGER:
            raise ConnectorError("JOB_REQUEST_INVALID", f"整数超出 JS 安全范围: {path}", 422)
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConnectorError("JOB_REQUEST_INVALID", f"包含非有限数字: {path}", 422)
        return value
    if isinstance(value, list):
        return [safe_json(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConnectorError("JOB_REQUEST_INVALID", f"JSON key 必须是字符串: {path}", 422)
            if _SECRET_KEY.search(key):
                raise ConnectorError("JOB_SECRET_FIELD", f"Job 包含敏感字段: {path}.{key}", 422)
            result[key] = safe_json(item, f"{path}.{key}")
        return result
    raise ConnectorError("JOB_REQUEST_INVALID", f"不是 JSON 兼容类型: {path}", 422)


def canonical_job_request(payload: dict[str, Any]) -> dict[str, JsonValue]:
    provider = str(payload.get("provider") or "").strip()
    operation = str(payload.get("operation") or "").strip()
    if not provider or not operation:
        raise ConnectorError("JOB_REQUEST_INVALID", "Job 缺少 provider/operation", 422)
    roles = sorted(
        {str(role) for role in payload.get("outputRoles") or [] if str(role)}, key=_utf16_key
    )
    return {
        "provider": provider,
        "operation": operation,
        "inputs": safe_json(payload.get("inputs") or {}, "inputs"),
        "profile": None if payload.get("profile") is None else str(payload["profile"]),
        "options": safe_json(payload.get("options") or {}, "options"),
        "outputRoles": roles,
        "parent": None if payload.get("parent") is None else safe_json(payload["parent"], "parent"),
        "retention": (
            None
            if payload.get("retention") is None
            else safe_json(payload["retention"], "retention")
        ),
        "metadata": None
        if payload.get("metadata") is None
        else safe_json(payload["metadata"], "metadata"),
    }


def request_hash(payload: dict[str, Any]) -> str:
    return f"sha256:{sha256(_stable_json(canonical_job_request(payload))).hexdigest()}"


def idempotency_key(payload: dict[str, Any]) -> str:
    digest = request_hash(payload)
    return f"idem_{digest[7:47]}"


def verify_request_identity(payload: dict[str, Any]) -> None:
    expected_hash = request_hash(payload)
    expected_idempotency = f"idem_{expected_hash[7:47]}"
    if payload.get("requestHash") != expected_hash:
        raise ConnectorError("JOB_REQUEST_HASH_MISMATCH", "requestHash 与请求语义不一致", 409)
    if payload.get("idempotencyKey") != expected_idempotency:
        raise ConnectorError(
            "JOB_IDEMPOTENCY_MISMATCH", "idempotencyKey 与 requestHash 不一致", 409
        )


def _utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be", "surrogatepass")


def _array_index(value: str) -> int | None:
    if not value or not value.isascii() or not value.isdigit():
        return None
    if value != "0" and value.startswith("0"):
        return None
    index = int(value)
    return index if index < 2**32 - 1 else None


def _object_keys(value: dict[str, JsonValue]) -> list[str]:
    ordered = sorted(value, key=_utf16_key)
    indices = sorted(
        (key for key in ordered if _array_index(key) is not None), key=lambda key: int(key)
    )
    return indices + [key for key in ordered if _array_index(key) is None]


def _js_number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if value == 0:
        return "0"
    if value.is_integer() and abs(value) < 1e21:
        return str(int(value))
    text = repr(value).lower()
    absolute = abs(value)
    if 1e-6 <= absolute < 1e21:
        return format(Decimal(text), "f") if "e" in text else text
    if "e" not in text:
        text = format(value, ".17e")
    mantissa, exponent = text.split("e", 1)
    if mantissa.endswith(".0"):
        mantissa = mantissa[:-2]
    exponent_value = int(exponent)
    sign = "+" if exponent_value >= 0 else "-"
    return f"{mantissa}e{sign}{abs(exponent_value)}"


def _js_string(value: str) -> str:
    dumped = json.dumps(value, ensure_ascii=False)
    return "".join(
        f"\\u{ord(char):04x}" if 0xD800 <= ord(char) <= 0xDFFF else char for char in dumped
    )


def _js_json(value: JsonValue) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _js_number(value)
    if isinstance(value, str):
        return _js_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_js_json(item) for item in value) + "]"
    return (
        "{"
        + ",".join(f"{_js_string(key)}:{_js_json(value[key])}" for key in _object_keys(value))
        + "}"
    )


def _stable_json(value: JsonValue) -> bytes:
    return _js_json(value).encode("utf-8")
