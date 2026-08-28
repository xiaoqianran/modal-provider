from __future__ import annotations

import base64

from modal_3d_client import background


def test_predict_mask_calls_t4_class_method_directly(monkeypatch):
    class Method:
        def remote(self, data):
            assert data == b"source"
            return {
                "mask_bytes_b64": base64.b64encode(b"mask-png").decode("ascii"),
                "engine": "birefnet-general-lite",
                "elapsed_ms": 12.5,
                "source_size": [64, 32],
            }

    class Obj:
        process = Method()

    class Cls:
        def __call__(self):
            return Obj()

    seen = {}

    def from_name(app, cls, *, client):
        seen.update(app=app, cls=cls, client=client)
        return Cls()

    token = object()
    monkeypatch.setattr(background, "client", lambda: token)
    monkeypatch.setattr(background.modal.Cls, "from_name", from_name)
    result = background.predict_mask(b"source")
    assert seen == {"app": "modal-3d-rembg", "cls": "RemBgWorker", "client": token}
    assert result["mask_bytes"] == b"mask-png"
    assert result["engine"] == "birefnet-general-lite"


def test_predict_mask_rejects_invalid_payload(monkeypatch):
    class Method:
        def remote(self, _data):
            return {"mask_bytes_b64": "***not-base64***"}

    class Obj:
        process = Method()

    class Cls:
        def __call__(self):
            return Obj()

    monkeypatch.setattr(background, "client", lambda: object())
    monkeypatch.setattr(background.modal.Cls, "from_name", lambda *a, **k: Cls())
    try:
        background.predict_mask(b"source")
    except ValueError as exc:
        assert "mask encoding" in str(exc)
    else:
        raise AssertionError("invalid mask encoding must fail")
