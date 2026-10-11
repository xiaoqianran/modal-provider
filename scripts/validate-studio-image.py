"""Build the Studio CPU image on Modal without deploying or running GPU models.

Run from modal-gen-client/: uv run python ../scripts/validate-studio-image.py
This creates a short-lived CPU Sandbox (and incurs the usual Modal build/CPU costs).
"""

from __future__ import annotations

import modal

from modal_gen.studio.modal_app import image


VERIFY = """
import importlib.metadata as metadata
from modal_gen.providers.loader import load_providers
from modal_2d.client.provider import create_provider as create_2d
from modal_2d.client.app import create_app as create_2d_api
from modal_3d.client.provider import create_provider as create_3d

providers = {provider.id for provider in load_providers()}
assert providers == {'modal-2d', 'modal-3d', 'modal-world'}, providers
assert create_2d().id == 'modal-2d'
assert create_3d().id == 'modal-3d'
assert callable(create_2d_api)
try:
    metadata.distribution('modal-2d-client-agent')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('legacy modal-2d-client-agent still installed')
try:
    metadata.distribution('modal-3d-client')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('legacy modal-3d-client still installed')
print('STUDIO_IMAGE_IMPORTS_OK', sorted(providers), flush=True)
"""


def main() -> None:
    with modal.enable_output():
        app = modal.App()
        with app.run():
            sandbox = modal.Sandbox.create(
                "python", "-c", VERIFY, image=image, app=app, timeout=120, idle_timeout=120,
            )
            try:
                sandbox.wait()
                result = sandbox.returncode
                print(sandbox.stdout.read())
                stderr = sandbox.stderr.read()
                if stderr:
                    print(stderr)
                if result != 0:
                    raise RuntimeError(f"Studio image smoke exited with code {result!r}")
            finally:
                sandbox.terminate()


if __name__ == "__main__":
    main()
