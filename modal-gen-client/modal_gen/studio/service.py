from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime

import jsonschema

from ..errors import ConnectorError
from ..identity import idempotency_key, request_hash, safe_json
from .storage import R2Archive, StudioStore

LOG = logging.getLogger(__name__)
ORIGIN = "https://studio.internal"
TERMINAL = {"succeeded", "failed", "cancelled", "expired", "submission_unknown"}
TEXT_IMAGE = "modal-2d.image.text_to_image.v1"
IMAGE_3D = "modal-3d.asset.image_to_3d.v1"


def now():
    return datetime.now(UTC).isoformat()


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def fail(code, message, status=422):
    raise ConnectorError(code, message, status)


class StudioService:
    """Durable intent queue. Run exactly one process against its persistent data directory."""

    def __init__(self, runtime, path, archive=None):
        self.hub = runtime
        self.store = StudioStore(path)
        self.archive = archive
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.worker = None

    @classmethod
    def configured(cls, runtime):
        from ..paths import data_dir

        archive = R2Archive() if os.getenv("STUDIO_R2_BUCKET") else None
        return cls(runtime, data_dir() / "studio.sqlite3", archive)

    def session(self, owner, snapshot=None):
        result = {"client_identity": owner, "origin": ORIGIN}
        if snapshot:
            result.update(
                capability_hash=snapshot["hash"], capability_revision=snapshot["revision"]
            )
        return result

    def owned(self, kind, owner, item_id):
        row = self.store.get(kind, owner, item_id)
        if row is None:
            fail("STUDIO_NOT_FOUND", f"{kind} not found", 404)
        return row

    def project(self, owner, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            fail("STUDIO_PROJECT", "Project name must be 1–120 characters")
        return self.store.save(
            "project",
            owner,
            {
                "id": new_id("project"),
                "name": name.strip(),
                "createdAt": now(),
            },
        )

    def _project(self, owner, project_id):
        if project_id:
            return self.owned("project", owner, project_id)["id"]
        default_id = "project_" + hashlib.sha256(owner.encode()).hexdigest()[:32]
        if not self.store.get("project", owner, default_id):
            self.store.save(
                "project",
                owner,
                {
                    "id": default_id,
                    "name": "Default Project",
                    "createdAt": now(),
                },
            )
        return default_id

    def record_asset(self, owner, artifact, *, name, project_id, job_id=None, parents=None):
        # Artifact IDs are immutable versions; assetId groups a primary model's lineage.
        existing = self.store.get("asset", owner, artifact["id"])
        if existing:
            return existing
        artifact, path = self.hub.artifacts.open(
            artifact["id"], owner_client=owner, owner_origin=ORIGIN
        )
        if self.archive:
            self.archive.put(owner, artifact, path)
        parents = parents or []
        root = artifact["id"]
        for parent_id in parents:
            parent = self.owned("asset", owner, parent_id)
            if parent["role"] == artifact["role"] == "primary-glb":
                root = parent["assetId"]
                break
        return self.store.save(
            "asset",
            owner,
            {
                **self.hub.artifacts.summary(artifact),
                "assetId": root,
                "name": name[:180],
                "projectId": project_id,
                "jobId": job_id,
                "parents": parents,
                "createdAt": now(),
                "archived": bool(self.archive),
            },
        )

    def upload(self, owner, data, mime, name, project_id=None):
        project_id = self._project(owner, project_id)
        if mime not in {"image/png", "model/gltf-binary"}:
            fail("STUDIO_UPLOAD", "Upload a PNG image or GLB model", 415)
        artifact = self.hub.artifacts.register_upload(
            data,
            owner_client=owner,
            owner_origin=ORIGIN,
            mime=mime,
            role="primary-image" if mime == "image/png" else "primary-glb",
            allow_mesh=True,
        )
        return self.record_asset(owner, artifact, name=name, project_id=project_id)

    def open_asset(self, owner, asset_id):
        asset = self.owned("asset", owner, asset_id)
        path = self.hub.artifacts._cache_path(asset)
        if not path.is_file() and asset["archived"] and self.archive:
            self.archive.restore(owner, asset, path)
        return self.hub.artifacts.open(asset_id, owner_client=owner, owner_origin=ORIGIN)

    def reference(self, owner, value):
        if "job_id" in value:
            job = self.owned("job", owner, value["job_id"])
            if job["status"] != "succeeded":
                fail("STUDIO_INPUT", "Input task has not succeeded", 409)
            matches = [
                a
                for a in job["result"]["artifacts"]
                if a["role"] == value.get("role", "primary-glb")
            ]
            if len(matches) != 1:
                fail("STUDIO_INPUT", "Select a specific artifact ID")
            asset_id = matches[0]["id"]
        else:
            asset_id = value.get("artifact_id") or value.get("id")
        asset = self.owned("asset", owner, asset_id)
        self.open_asset(owner, asset_id)
        return {k: asset[k] for k in ("id", "role", "mime", "hash")}

    def normalize(self, owner, spec):
        if not isinstance(spec, dict):
            fail("STUDIO_REQUEST", "Task must be an object")
        spec = dict(safe_json(spec))
        operation = spec.get("operation")
        if not isinstance(operation, str):
            fail("STUDIO_OPERATION", "operation is required")
        if operation not in {TEXT_IMAGE, IMAGE_3D, "studio.text_to_3d.v1"}:
            if not operation.startswith("modal-3d.asset.") or not operation.endswith(".v1"):
                fail("STUDIO_OPERATION", "Unsupported operation")
        inputs = spec.get("inputs", {})
        if not isinstance(inputs, dict) or not isinstance(spec.get("options", {}), dict):
            fail("STUDIO_REQUEST", "inputs and options must be objects")
        # Only resolve reference-shaped objects, never accept remote URLs or paths.
        inputs = {
            k: self.reference(owner, v) if isinstance(v, dict) else v for k, v in inputs.items()
        }
        if operation == "studio.text_to_3d.v1":
            if not isinstance(inputs.get("prompt"), str) or not inputs["prompt"].strip():
                fail("STUDIO_PROMPT", "A text prompt is required")
            if not inputs.get("model") or not inputs.get("imageModel"):
                fail("STUDIO_MODEL", "Select both image and 3D models")
        return {
            "operation": operation,
            "inputs": inputs,
            "options": spec.get("options", {}),
            "profile": spec.get("profile", "recommended"),
            "projectId": self._project(owner, spec.get("projectId")),
        }

    def submit(self, owner, payload, key):
        if not isinstance(key, str) or not 8 <= len(key) <= 160:
            fail("STUDIO_IDEMPOTENCY", "Idempotency-Key must be 8–160 characters")
        with self.lock:
            spec = self.normalize(owner, payload)
            digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
            job = {
                "id": new_id("studiojob"),
                "createdAt": now(),
                "updatedAt": now(),
                "status": "queued",
                "stage": "queued",
                "spec": spec,
                "operation": spec["operation"],
                "projectId": spec["projectId"],
                "steps": [],
                "result": None,
                "error": None,
                "cancelRequested": False,
            }
            prior_digest, job_id = self.store.reserve(owner, key, digest, job)
            if digest != prior_digest:
                fail("STUDIO_IDEMPOTENCY", "This key already belongs to a different request", 409)
            return self.owned("job", owner, job_id)

    def cancel(self, owner, job_id):
        with self.lock:
            job = self.owned("job", owner, job_id)
            if job["status"] not in TERMINAL:
                job["cancelRequested"] = True
                if not job["steps"]:
                    job["status"] = "cancelled"
                else:
                    job["status"] = "cancel_requested"
                self.save_job(owner, job)
            return job

    def save_job(self, owner, job):
        job["updatedAt"] = now()
        self.store.save("job", owner, job)

    def _step_spec(self, job):
        spec = job["spec"]
        if spec["operation"] != "studio.text_to_3d.v1":
            return spec
        values = spec["inputs"]
        if not job["steps"]:
            return {
                "operation": TEXT_IMAGE,
                "inputs": {
                    "prompt": values["prompt"],
                    "model": values["imageModel"],
                    "seed": values.get("seed", 42),
                },
                "profile": "recommended",
                "options": {},
            }
        source = next(
            a for a in job["steps"][0]["result"]["artifacts"] if a["role"] == "primary-image"
        )
        return {
            "operation": IMAGE_3D,
            "inputs": {
                "sourceArtifact": {k: source[k] for k in ("id", "role", "mime", "hash")},
                "model": values["model"],
                "seed": values.get("seed", 42),
            },
            "options": {},
            "profile": spec["profile"],
        }

    def _dispatch(self, owner, job):
        spec = self._step_spec(job)
        snapshot = self.hub.capabilities.snapshot()
        provider = "modal-2d" if spec["operation"] == TEXT_IMAGE else "modal-3d"
        resolved = self.hub.capabilities.capability(snapshot, provider, spec["operation"])
        cap = resolved["capability"]
        for value, schema in [
            (spec["inputs"], cap.get("input", {}).get("schema")),
            (spec["options"], cap.get("optionsSchema")),
        ]:
            if schema:
                try:
                    jsonschema.validate(value, schema)
                except jsonschema.ValidationError as exc:
                    fail("STUDIO_PARAMETERS", exc.message)
        payload = {
            "provider": provider,
            "operation": spec["operation"],
            "inputs": spec["inputs"],
            "options": spec["options"],
            "profile": spec["profile"],
            "outputRoles": cap["output"]["roles"],
            "metadata": {"studioJob": job["id"], "step": len(job["steps"])},
            "contractVersion": resolved["provider"].get("contractVersion", "1"),
            "operationVersion": cap["version"],
            "capabilityHash": snapshot["hash"],
            "capabilityRevision": snapshot["revision"],
        }
        payload.update(requestHash=request_hash(payload), idempotencyKey=idempotency_key(payload))
        # A crash inside dispatch must not trigger a second, potentially billable submission.
        job["status"] = "submitting"
        job["pendingKey"] = payload["idempotencyKey"]
        self.save_job(owner, job)
        step = self.hub.jobs.submit(payload, self.session(owner, snapshot))
        job["steps"].append(step)
        job["status"] = "running"
        job["stage"] = "image" if spec["operation"] == TEXT_IMAGE else "model"
        self.save_job(owner, job)

    def advance(self, owner, job):
        if job["status"] in TERMINAL:
            return
        if job["status"] == "submitting":
            prior = self.hub.store.find_job_by_idempotency(owner, ORIGIN, job["pendingKey"])
            if prior:
                job["steps"].append(self.hub.jobs.projection(prior))
                job["status"] = "running"
            else:
                job["status"] = "submission_unknown"
                job["error"] = {"message": "Submission interrupted; reconcile before resubmitting"}
            self.save_job(owner, job)
            return
        if not job["steps"]:
            if job["cancelRequested"]:
                job["status"] = "cancelled"
                self.save_job(owner, job)
            else:
                self._dispatch(owner, job)
            return
        last = job["steps"][-1]
        session = self.session(owner)
        if job["cancelRequested"] and last["status"] not in TERMINAL:
            last = self.hub.jobs.cancel(last["id"], session)
        else:
            last = self.hub.jobs.get(last["id"], session)
        job["steps"][-1] = last
        if last["status"] == "succeeded":
            parents = [
                v["id"] for v in job["spec"]["inputs"].values() if isinstance(v, dict) and "id" in v
            ]
            if len(job["steps"]) > 1:
                parents.extend(a["id"] for a in job["steps"][-2]["result"]["artifacts"])
            for artifact in last["result"]["artifacts"]:
                self.record_asset(
                    owner,
                    artifact,
                    name=f"{job['operation']} · {artifact['role']}",
                    project_id=job["projectId"],
                    job_id=job["id"],
                    parents=parents,
                )
            if (
                job["operation"] == "studio.text_to_3d.v1"
                and len(job["steps"]) == 1
                and not job["cancelRequested"]
            ):
                self._dispatch(owner, job)
                return
            job["status"] = "cancelled" if job["cancelRequested"] else "succeeded"
            job["result"] = last["result"]
        elif last["status"] in TERMINAL:
            job["status"], job["error"] = last["status"], last.get("error")
        else:
            job["status"] = last["status"]
        self.save_job(owner, job)

    def tick(self):
        with self.lock:
            jobs = self.store.list("job")
            active = sum(j["status"] not in TERMINAL | {"queued"} for _, j in jobs)
            maximum = int(os.getenv("STUDIO_MAX_ACTIVE_JOBS", "2"))
            for owner, job in reversed(jobs):
                if job["status"] in TERMINAL:
                    continue
                if job["status"] == "queued":
                    if active >= maximum:
                        continue
                    active += 1
                try:
                    self.advance(owner, job)
                except ConnectorError as exc:
                    if job["status"] == "submitting":
                        job["status"] = "submission_unknown"
                    elif 400 <= exc.status < 500 and exc.status not in {409, 429}:
                        job["status"] = "failed"
                    job["error"] = {"code": exc.code, "message": str(exc)}
                    self.save_job(owner, job)
                except Exception:
                    LOG.exception("Studio task processing failed: %s", job["id"])
                    job["error"] = {"message": "Execution temporarily unavailable; retrying safely"}
                    self.save_job(owner, job)

    def start(self):
        def loop():
            while not self.stop.is_set():
                try:
                    self.tick()
                except Exception:
                    LOG.exception("Studio scheduler error")
                self.stop.wait(2)

        self.worker = threading.Thread(target=loop, daemon=True, name="studio-jobs")
        self.worker.start()

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=15)
