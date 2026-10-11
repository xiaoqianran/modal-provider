"""The 3D local adapter is distributed with modal-3d, not a second package."""

from importlib.metadata import PackageNotFoundError, distribution, entry_points
from importlib.resources import files

import pytest


def test_3d_provider_entry_point_is_unique():
    matches = [e for e in entry_points(group="modal_gen.providers") if e.name == "modal-3d"]
    assert len(matches) == 1
    assert matches[0].value == "modal_3d.client.provider:create_provider"
    assert matches[0].load()().id == "modal-3d"


def test_old_3d_client_distribution_is_not_installed():
    with pytest.raises(PackageNotFoundError):
        distribution("modal-3d-client")


def test_3d_client_ui_and_capability_data_are_available():
    base = files("modal_3d.client")
    for resource in (
        "capabilities.json",
        "static/index.html",
        "static/app.js",
        "static/styles.css",
    ):
        assert base.joinpath(resource).is_file()
