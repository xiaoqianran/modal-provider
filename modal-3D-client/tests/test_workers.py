from __future__ import annotations

from modal_3d_client import workers


class _Method:
    def __init__(self, events):
        self.events = events

    def spawn(self, *args):
        self.events.append(("spawn", args))
        return object()


class _RemoteObject:
    def __init__(self, events):
        self.warmup = _Method(events)
        self.generate_job = _Method(events)


class _RemoteClass:
    def __init__(self, events):
        self.events = events

    def __call__(self):
        return _RemoteObject(self.events)


def test_spawn_warmup_targets_selected_model_class(monkeypatch):
    events = []
    token = object()

    def from_name(app, class_name, *, client):
        events.append(("from_name", app, class_name, client))
        return _RemoteClass(events)

    monkeypatch.setattr(workers, "client", lambda: token)
    monkeypatch.setattr(workers.modal.Cls, "from_name", from_name)

    workers.spawn_warmup("hunyuan2.1-plus-plus")

    assert events == [
        ("from_name", "modal-3d-hunyuan", "Model", token),
        ("spawn", ()),
    ]
