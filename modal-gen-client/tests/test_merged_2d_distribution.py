"""The local 2D adapter is shipped by modal-2d, without a second pip distribution."""

from importlib.metadata import PackageNotFoundError, distribution, entry_points
from importlib.resources import files

import pytest


def test_2d_provider_entry_point_resolves_to_merged_package():
    matches = [
        entry for entry in entry_points(group="modal_gen.providers") if entry.name == "modal-2d"
    ]
    assert len(matches) == 1
    assert matches[0].value == "modal_2d.client.provider:create_provider"
    assert matches[0].load()().id == "modal-2d"


def test_legacy_2d_client_distribution_not_required():
    with pytest.raises(PackageNotFoundError):
        distribution("modal-2d-client-agent")


def test_client_ui_files_are_packaged_with_modal_2d():
    static = files("modal_2d.client").joinpath("static")
    for filename in ("index.html", "app.js", "styles.css", "views.css"):
        assert static.joinpath(filename).is_file()
