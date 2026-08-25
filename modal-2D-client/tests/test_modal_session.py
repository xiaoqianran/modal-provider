import pytest

from modal_2d_client import modal_session


class Candidate:
    def __init__(self):
        self.hello_calls = 0

    def hello(self):
        self.hello_calls += 1


def test_credentials_live_only_in_memory(monkeypatch):
    candidate = Candidate()
    monkeypatch.setattr(
        modal_session.modal.Client, "from_credentials", lambda token_id, token_secret: candidate
    )
    modal_session.disconnect()
    modal_session.connect("id", "secret")
    assert modal_session.connected() is True
    assert modal_session.client() is candidate
    assert candidate.hello_calls == 1
    modal_session.disconnect()
    assert modal_session.connected() is False
    with pytest.raises(modal_session.NotConnectedError):
        modal_session.client()


def test_empty_credentials_are_rejected():
    with pytest.raises(ValueError):
        modal_session.connect("", "secret")
