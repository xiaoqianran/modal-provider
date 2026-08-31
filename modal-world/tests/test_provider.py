from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from modal_world.provider import MODEL, OPERATION, ModalWorldProvider


@dataclass
class InputArtifact:
    id: str
    role: str
    mime: str
    hash: str
    path: Path


class Resolver:
    def __init__(self, artifact: InputArtifact) -> None:
        self.artifact = artifact

    def resolve_input(self, artifact_id: str, **_kwargs):
        assert artifact_id == self.artifact.id
        return self.artifact


class Context:
    owner_client = "agentscape"
    owner_origin = "http://localhost:5173"
    request_id = "req_world_01"

    def __init__(self, artifact: InputArtifact) -> None:
        self.artifacts = Resolver(artifact)


class Batch:
    def __init__(self, uploads: list[tuple[Path, str]]) -> None:
        self.uploads = uploads

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def put_file(self, path: Path, remote: str) -> None:
        self.uploads.append((Path(path), remote))


class Volume:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str]] = []
        self.reads: dict[str, bytes] = {}

    def batch_upload(self, force: bool = False):
        assert force is True
        return Batch(self.uploads)

    def read_file(self, path: str):
        yield self.reads[path]


class Call:
    object_id = "fc_world_01"

    def __init__(self, result=None) -> None:
        self.result = result
        self.spawn_kwargs = None
        self.cancelled = False

    def spawn(self, **kwargs):
        self.spawn_kwargs = kwargs
        return self

    def get(self, timeout=0):
        assert timeout == 0
        return self.result

    def cancel(self):
        self.cancelled = True


def result():
    return {
        "model": MODEL,
        "artifacts": [
            {
                "id": "mesh",
                "role": "world-mesh",
                "mime": "model/ply",
                "bytes": 3,
                "sha256": "a" * 64,
                "path": "jobs/world/render_results/global_mesh.ply",
            },
            {
                "id": "sem",
                "role": "world-semantics",
                "mime": "application/json",
                "bytes": 2,
                "sha256": "b" * 64,
                "path": "jobs/world/camera_trajectory/target_camera.json",
            },
            {
                "id": "spz",
                "role": "world-visual",
                "mime": "model/spz",
                "bytes": 4,
                "sha256": "c" * 64,
                "path": "jobs/world/gs_result/ply/point_cloud_7999.spz",
            },
        ],
    }


def provider(tmp_path: Path, call_result=None):
    volume = Volume()
    call = Call(call_result)
    p = ModalWorldProvider(
        connected=lambda: True,
        client=lambda: object(),
        function_lookup=lambda *_args, **_kwargs: call,
        call_lookup=lambda *_args, **_kwargs: call,
        volume_lookup=lambda *_args, **_kwargs: volume,
    )
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    artifact = InputArtifact(
        "artifact_image", "primary-image", "image/png", "sha256:" + "d" * 64, image
    )
    return p, volume, call, artifact


def test_descriptor_exposes_one_image_to_world_capability(tmp_path: Path):
    p, _volume, _call, _artifact = provider(tmp_path)
    descriptor = p.descriptor()
    capability = descriptor["capabilities"][0]
    assert descriptor["id"] == "modal-world"
    assert capability["operation"] == OPERATION
    assert capability["output"]["required"] == ["world-mesh", "world-semantics", "world-visual"]


def test_submit_uploads_source_then_spawns_durable_pipeline(tmp_path: Path):
    p, volume, call, artifact = provider(tmp_path)
    state = p.submit(
        operation=OPERATION,
        inputs={
            "sourceArtifact": {
                "id": artifact.id,
                "role": artifact.role,
                "mime": artifact.mime,
                "hash": artifact.hash,
            },
            "prompt": "a walkable garden",
            "model": MODEL,
            "seed": 7,
        },
        profile="recommended",
        options={"force": False},
        context=Context(artifact),
    )
    assert state == {"id": "fc_world_01", "status": "running", "model": MODEL, "artifacts": []}
    assert volume.uploads[0][0] == artifact.path
    assert volume.uploads[0][1].endswith("/reference.png")
    assert call.spawn_kwargs["prompt"] == "a walkable garden"
    assert call.spawn_kwargs["seed"] == 7


def test_get_and_artifact_stream_use_pipeline_result(tmp_path: Path):
    p, volume, _call, _artifact = provider(tmp_path, result())
    state = p.get("fc_world_01")
    assert state["status"] == "succeeded"
    assert [item["role"] for item in state["artifacts"]] == [
        "world-mesh",
        "world-semantics",
        "world-visual",
    ]
    volume.reads[result()["artifacts"][0]["path"]] = b"ply"
    assert b"".join(p.iter_artifact("fc_world_01", "mesh")) == b"ply"
