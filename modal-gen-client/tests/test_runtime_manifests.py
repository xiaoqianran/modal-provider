from __future__ import annotations

import re

from modal_2d.deployment import deployment_manifest as deployment_2d
from modal_3d.deployment import deployment_manifest as deployment_3d

_TAG = re.compile(r"^[A-Za-z0-9._-]{1,50}$")


def test_runtime_revisions_are_valid_modal_deployment_tags():
    for manifest in (deployment_2d(), deployment_3d()):
        for target in manifest["targets"]:
            assert _TAG.fullmatch(target["revision"])
