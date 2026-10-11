from dataclasses import asdict

import modal

from ..artifacts import describe_artifact
from ..contracts import normalize_request
from ..models import get_model

spec = get_model("echo-text")
app = modal.App(spec.worker_app)


@app.cls()
class EchoWorker:
    def echo(self, request: dict[str, object]) -> dict[str, object]:
        normalized = normalize_request(request)
        content = normalized.text.encode("utf-8")
        return {"content": content, "artifact": asdict(describe_artifact(content))}

    @modal.method()
    def run_job(self, request: dict[str, object]) -> dict[str, object]:
        return self.echo(request)
