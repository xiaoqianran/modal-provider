from ..capabilities import list_capabilities
from ..contracts import normalize_request


class ExampleProvider:
    """Synchronous demo adapter; production Hub transport is deliberately separate."""

    def list_capabilities(self):
        return list_capabilities()

    def run_example(self, request):
        normalized = normalize_request(request)
        return normalized.text.encode("utf-8")
