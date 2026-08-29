from __future__ import annotations

import pytest

from modal_3d_client import models
from modal_3d_client.capabilities import CapabilityError


def test_public_models_are_exposed_from_validated_capabilities():
    public = models.public_models()
    assert public
    assert all(isinstance(model.get("id"), str) and model["id"] for model in public)


def test_options_for_resolves_profile_and_injects_seed():
    options = models.options_for("fastsam3d-plus-plus", "recommended", 7)
    assert options["seed"] == 7


def test_options_for_rejects_unknown_profile():
    with pytest.raises(CapabilityError, match="profile is unavailable"):
        models.options_for("fastsam3d-plus-plus", "missing", 7)
