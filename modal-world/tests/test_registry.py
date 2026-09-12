from modal_world.backends.hyworld2 import HYWorld2Backend
from modal_world.providers import register_builtin_backends
from modal_world.registry import get_backend, list_backends


def test_builtin_registry_contains_world_backends():
    register_builtin_backends()
    assert list_backends() == ("hyworld2",)
    assert isinstance(get_backend("HYWORLD2"), HYWorld2Backend)
