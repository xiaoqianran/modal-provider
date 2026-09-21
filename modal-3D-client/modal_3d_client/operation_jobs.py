"""Durable asset operations, dependency continuation and multi-artifact transport."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import modal
from modal.exception import Error as ModalError
from modal.exception import NotFoundError, OutputExpiredError
from modal_3d.operation_runner import validate_file
from modal_3d.operations import (
    MAX_BYTES,
    MIMES,
    RESULT_CONTRACT,
    SPECS,
    capabilities,
    options_for,
    request_key,
    required_roles_for,
    revision_for,
    input_mimes_for,
    validate_descriptor,
    worker_for,
)

from . import artifacts
from .contracts import ContractError
from .modal_session import client

TERMINAL = {"succeeded", "failed", "cancelled", "expired"}


class OperationService:
    def __init__(self, jobs):
        self.jobs = jobs
        self.path = jobs.store.path.with_name("operations.sqlite3")
        self._lock = threading.RLock()
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS operation_jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS operation_assets (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA busy_timeout=30000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _get(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT payload FROM operation_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return json.loads(row[0])

    def _save(self, state):
        from .jobs import _now
        state["updated_at"] = _now()
        with self.db() as db:
            db.execute("UPDATE operation_jobs SET payload=? WHERE id=?", (json.dumps(state), state["id"]))
        return self.public(state)

    @staticmethod
    def public(state):
        value = {k: v for k, v in state.items() if k not in {"remote_call_id", "resolved_inputs", "identity"}}
        if value.get("result"):
            value["result"] = {**value["result"], "artifacts": [
                {k: v for k, v in a.items() if k != "path"} for a in value["result"]["artifacts"]]}
        return value

    def list(self, limit=50):
        with self.db() as db:
            rows = db.execute("SELECT payload FROM operation_jobs").fetchall()
        states = sorted((json.loads(r[0]) for r in rows), key=lambda r: r["created_at"], reverse=True)
        return [self.public(s) for s in states[:limit]]

    def register(self, descriptor):
        value = validate_descriptor(descriptor)
        value["id"] = f"art_{value['sha256']}"
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO operation_assets VALUES (?,?)", (value["id"], json.dumps(value)))
        return {k: v for k, v in value.items() if k != "path"}

    def asset(self, artifact_id):
        with self.db() as db:
            row = db.execute("SELECT payload FROM operation_assets WHERE id=?", (artifact_id,)).fetchone()
        if not row:
            raise KeyError(artifact_id)
        return validate_descriptor(json.loads(row[0]))

    def upload(self, data: bytes, *, expected_sha256=None, mime="model/gltf-binary",
               role="primary-glb", filename=None):
        if not data or len(data) > MAX_BYTES:
            raise ContractError("artifact must be between 1 byte and 512 MiB")
        suffix_by_mime = {v: k for k, v in MIMES.items()}
        if mime not in suffix_by_mime:
            raise ContractError(f"unsupported artifact MIME: {mime}")
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ContractError("artifact SHA256 mismatch")
        with tempfile.TemporaryDirectory() as tmp:
            suffix = suffix_by_mime[mime]
            file = Path(tmp) / f"input{suffix}"
            file.write_bytes(data)
            validate_file(file, mime)
        path = (f"mesh-inputs/{digest}.glb" if mime == "model/gltf-binary"
                else f"operation-inputs/{digest}{suffix}")
        with artifacts._volume().batch_upload(force=True) as upload:
            upload.put_file(io.BytesIO(data), path)
        return self.register({"sha256": digest, "bytes": len(data), "mime": mime,
                              "role": role, "path": path, "filename": filename or f"input{suffix}"})

    def submit(self, operation, inputs, options=None, job_id=None):
        from .jobs import _now
        options = options_for(operation, options)
        if not isinstance(inputs, dict) or set(inputs) != set(SPECS[operation]["inputs"]):
            raise ValueError("inputs do not match operation")
        local_id = job_id or f"op_{uuid.uuid4().hex}"
        if not re.fullmatch(r"op_[A-Za-z0-9_-]{1,150}", local_id):
            raise ValueError("operation job_id must start with op_ and be URL-safe")
        dependencies = []
        expected_mimes = input_mimes_for(operation)
        for name, ref in inputs.items():
            if not isinstance(ref, dict):
                raise TypeError("input must reference artifact_id or job_id + role")
            if set(ref) == {"artifact_id"}:
                desc = self.asset(ref["artifact_id"])
                if desc["mime"] != expected_mimes[name]:
                    raise ValueError(f"{name} must be {expected_mimes[name]}")
            elif set(ref) <= {"job_id", "role"} and ref.get("job_id") and ref.get("role"):
                parent = ref["job_id"]
                if parent == local_id:
                    raise ValueError("job cannot depend on itself")
                self._get(parent) if parent.startswith("op_") else self.jobs.store.get(parent)
                dependencies.append(parent)
            else:
                raise ValueError("invalid artifact reference")
        revision = revision_for(operation)
        worker_app = worker_for(operation)
        required_roles = required_roles_for(operation)
        identity = json.dumps({"operation": operation, "revision": revision, "worker_app": worker_app,
                               "required_roles": required_roles, "inputs": inputs,
                               "options": options}, sort_keys=True, allow_nan=False)
        timestamp = _now()
        state = {"id": local_id, "operation": operation, "model": operation, "revision": revision,
                 "worker_app": worker_app, "required_roles": required_roles,
                 "inputs": inputs, "options": options, "dependencies": sorted(set(dependencies)),
                 "identity": identity, "status": "queued", "remote_call_id": None,
                 "created_at": timestamp, "updated_at": timestamp, "result": None,
                 "error_code": None, "retryable": False}
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO operation_jobs VALUES (?,?)", (local_id, json.dumps(state)))
        current = self._get(local_id)
        if current["identity"] != identity:
            raise ValueError("job_id already used with different inputs/options/revision")
        return self.poll(local_id)

    def _resolve(self, state):
        resolved = {}
        for name, ref in state["inputs"].items():
            if "artifact_id" in ref:
                resolved[name] = self.asset(ref["artifact_id"])
                continue
            parent_id = ref["job_id"]
            parent = self.jobs.poll(parent_id)
            if parent["status"] in {"failed", "expired", "cancelled", "cancel_requested"}:
                state.update(status="failed", error_code="dependency.failed", retryable=False)
                return None
            if parent["status"] != "succeeded":
                return None
            if parent_id.startswith("op_"):
                rows = self._get(parent_id)["result"]["artifacts"]
            else:
                result = self.jobs.store.get(parent_id).result
                rows = list((result.get("artifact_sources") or {}).values())
                if not rows:
                    _, path = self.jobs.artifact(parent_id)
                    public = self.upload(path.read_bytes())
                    rows = [self.asset(public["id"])]
            matched = [a for a in rows if a.get("role", "primary-glb") == ref["role"]]
            if len(matched) != 1:
                raise ValueError(f"parent artifact role not found: {ref['role']}")
            resolved[name] = validate_descriptor(matched[0])
            if resolved[name]["mime"] != input_mimes_for(state["operation"])[name]:
                raise ValueError(f"parent artifact MIME mismatch: {name}")
        return resolved

    def poll(self, job_id):
        from modal.exception import TimeoutError as ModalTimeoutError

        from .jobs import _RECOVERABLE

        submission_errors = (*_RECOVERABLE, ModalError, OSError)
        with self._lock:
            state = self._get(job_id)
            if state["status"] in TERMINAL:
                return self.public(state)
            if state["status"] in {"submitting", "submission_unknown"} and not state["remote_call_id"]:
                # A crash between remote spawn and persistence must never trigger another spawn.
                state.update(status="submission_unknown", error_code="remote.submission_unknown", retryable=False)
                return self._save(state)
            if state["status"] in {"queued", "connection_required"} and not state["remote_call_id"]:
                try:
                    resolved = self._resolve(state)
                    if resolved is None:
                        return self._save(state)
                    remote_client = client()  # Fail before claiming/sending if disconnected.
                except _RECOVERABLE:
                    state.update(status="connection_required", error_code="modal.connection_required")
                    return self._save(state)
                except (ValueError, TypeError, KeyError) as exc:
                    state.update(status="failed", error_code="input.invalid", error=str(exc))
                    return self._save(state)
                state["resolved_inputs"] = resolved
                state["request_key"] = request_key(state["operation"], resolved, state["options"])
                # Compare-and-swap also prevents duplicate spawns across client processes.
                with self.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    current = json.loads(db.execute("SELECT payload FROM operation_jobs WHERE id=?", (job_id,)).fetchone()[0])
                    if current["status"] not in {"queued", "connection_required"} or current["remote_call_id"]:
                        return self.public(current)
                    state["status"] = "submitting"
                    db.execute("UPDATE operation_jobs SET payload=? WHERE id=?", (json.dumps(state), job_id))
                try:
                    worker = modal.Cls.from_name(state["worker_app"], "Model", client=remote_client)()
                    call = worker.run_job.spawn({"operation": state["operation"], "inputs": resolved}, state["options"])
                    state.update(remote_call_id=str(call.object_id), status="running", error_code=None)
                except submission_errors as exc:
                    state.update(status="submission_unknown", error_code="remote.submission_unknown", error=type(exc).__name__)
                return self._save(state)
            try:
                call = modal.FunctionCall.from_id(state["remote_call_id"], client=client())
                value = call.get(timeout=0)
            except (ModalTimeoutError, TimeoutError):
                return self.public(state)
            except (NotFoundError, OutputExpiredError):
                state.update(status="expired", error_code="remote.output_expired")
                return self._save(state)
            except _RECOVERABLE:
                state.update(error_code="modal.connection_required")
                return self._save(state)
            except ModalError as exc:
                state.update(status="failed", error_code="remote.execution_failed", error=str(exc)[-2000:], retryable=True)
                return self._save(state)
            try:
                if (value.get("contract") != RESULT_CONTRACT or value.get("revision") != state["revision"]
                    or value.get("operation") != state["operation"] or value.get("request_key") != state["request_key"]):
                    raise ValueError("operation response identity mismatch")
                rows = [validate_descriptor(a) for a in value["artifacts"]]
                roles = [a["role"] for a in rows]
                required = set(state.get("required_roles") or ["primary-glb", "quality-report"])
                if not required.issubset(roles) or len(set(roles)) != len(roles):
                    raise ValueError("missing or duplicate artifact roles")
                for desc in rows:
                    self.register(desc)
                state.update(status="succeeded", result={"artifacts": rows, "metrics": value.get("metrics", {}),
                             "timing": value.get("timing", {}), "request_key": value["request_key"]}, error_code=None)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                state.update(status="failed", error_code="remote.invalid_response", error=str(exc))
            return self._save(state)

    def cancel(self, job_id):
        with self._lock:
            state = self._get(job_id)
            if state["status"] in TERMINAL:
                return self.public(state)
            if state["status"] in {"submitting", "submission_unknown"} and not state["remote_call_id"]:
                state.update(error_code="remote.cancel_requires_rebind")
                return self._save(state)
            if state["remote_call_id"]:
                modal.FunctionCall.from_id(state["remote_call_id"], client=client()).cancel()
            state.update(status="cancelled", error_code=None)
            self._save(state)
            for child in self.list(100000):
                if job_id in child["dependencies"] and child["status"] not in TERMINAL:
                    self.cancel(child["id"])
            return self.public(state)

    def rebind(self, job_id, call_id):
        if not re.fullmatch(r"fc-[A-Za-z0-9]+", call_id):
            raise ValueError("invalid Modal FunctionCall id")
        with self._lock:
            state = self._get(job_id)
            if state["status"] not in {"submission_unknown", "submitting"}:
                raise ValueError("only unknown submissions can be rebound")
            state.update(remote_call_id=call_id, status="running", error_code=None)
            self._save(state)
        return self.poll(job_id)

    def retry(self, job_id):
        state = self._get(job_id)
        if state["status"] not in {"failed", "expired", "cancelled"}:
            raise ValueError("only terminal unsuccessful jobs can be retried")
        return self.submit(state["operation"], state["inputs"], state["options"])

    def artifact(self, job_id, role="primary-glb"):
        state = self._get(job_id)
        if state["status"] != "succeeded":
            raise RuntimeError("artifact not ready")
        desc = next((a for a in state["result"]["artifacts"] if a["role"] == role or a["id"] == role), None)
        if desc is None:
            raise KeyError(role)
        destination = artifacts._cache_path(desc["sha256"])
        if not destination.is_file():
            fd, name = tempfile.mkstemp(dir=destination.parent, suffix=".part")
            temporary = Path(name)
            try:
                total = 0
                with os.fdopen(fd, "wb") as stream:
                    for chunk in artifacts._artifact_chunks(desc["path"]):
                        total += len(chunk)
                        if total > desc["bytes"]:
                            raise ContractError("artifact exceeds declared size")
                        stream.write(chunk)
                if total != desc["bytes"] or artifacts._sha256_file(temporary) != desc["sha256"]:
                    raise ContractError("artifact integrity mismatch")
                validate_file(temporary, desc["mime"])
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        if destination.stat().st_size != desc["bytes"] or artifacts._sha256_file(destination) != desc["sha256"]:
            raise ContractError("cached artifact integrity mismatch")
        validate_file(destination, desc["mime"])
        return {k: v for k, v in desc.items() if k != "path"}, destination

    def reconcile(self):
        for state in self.list(100000):
            if state["status"] not in TERMINAL:
                try:
                    self.poll(state["id"])
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("operation recovery failed: %s", state["id"])


def connector_capabilities(status):
    result = []
    for cap in capabilities():
        op = cap["id"]
        input_mimes = input_mimes_for(op)
        refs = {name: {"type": "object", "required": ["id", "role", "mime", "hash"],
                "additionalProperties": False, "properties": {
                    "id": {"type": "string", "minLength": 1}, "role": {"type": "string"},
                    "mime": {"const": mime},
                    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}}}
                for name, mime in input_mimes.items()}
        required = required_roles_for(op)
        result.append({"operation": cap["operation"], "version": "1", "displayName": cap["name"],
            "category": "asset-processing", "status": status,
            "input": {"types": ["mesh"], "schema": {"type": "object", "additionalProperties": False,
                "required": SPECS[op]["inputs"], "properties": refs},
                "limits": {"maxSourceBytes": MAX_BYTES}},
            "output": {"roles": required, "required": required, "optional": []},
            "profiles": {"recommended": {}},
            "optionsSchema": {"type": "object", "additionalProperties": False, "properties": SPECS[op]["options"]},
            "execution": {"async": True, "durationClass": "long",
                          "costClass": cap["execution"]["resource"]},
            "prerequisites": {"authMode": "connector-session", "connection": True},
            "support": {"cancel": True, "resume": True, "idempotency": True},
            "artifactTransport": "connector-artifact"})
    return result
