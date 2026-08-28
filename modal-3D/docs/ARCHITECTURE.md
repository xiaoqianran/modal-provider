# Architecture

The production path has no dispatch gateway and no CPU forwarding container.
The VPS/client owns orchestration. Modal is used only for useful model compute.

```text
local client / VPS (modal-3D-client)
  ├─ validate source/model/profile/options
  ├─ immediately spawn selected Model.warmup (L40S cold-start begins)
  ├─ if source already has useful alpha or caller mask:
  │    └─ condition locally
  ├─ else, opaque source only:
  │    └─ direct Modal class call -> modal-3d-rembg / RemBgWorker.process (T4)
  │                              <- foreground mask
  ├─ refine mask + crop/letterbox locally
  ├─ build/validate canonical 1024×1024 RGBA PNG locally
  ├─ upload client-inputs/<sha256>.png
  ├─ persist job id + FunctionCall id in local SQLite
  └─ direct Modal class spawn -> selected L40S Model.generate_job
                                  │
                                  ├─ read /artifacts/client-inputs/…
                                  ├─ validate canonical PNG
                                  ├─ run 3D inference
                                  ├─ validate GLB
                                  └─ return generation_result()
```

For every new valid request, the selected L40S `Model.warmup()` is spawned before
conditioning starts. On an opaque input, that cold-start runs in parallel with
the T4 `RemBgWorker.process` call. When the mask/canonical input is ready,
`generate_job` is submitted to the same `max_containers=1` model service and can
reuse the container that has already loaded (or queue behind the still-finishing
warmup). This hides most of the independent L40S startup behind preprocessing.

For an already-matted input the paid path is one Modal compute service: VPS ->
L40S. For an opaque input without a caller mask it is two useful compute services
running with overlapped startup: VPS -> T4 mask prediction and VPS -> selected
L40S warmup/generation. There is never a Modal CPU container whose only purpose
is dispatching another Modal call.

## Why there is no gateway

The old `modal-3d-gateway` had to cold-start before it could choose a worker.
Routing, option validation, job persistence and polling do not require cloud
compute, so they now live in the local sidecar. The client stores
`FunctionCall.object_id` and later restores the call with
`FunctionCall.from_id()`.

The old per-worker CPU adapter (`generate` / `health` / `register`) is gone for
the same reason. Each 3D worker exposes its GPU class method directly.

The T4 `RemBgWorker` is intentionally different: it performs the actual
BiRefNet inference, so it remains a Modal GPU worker. Its old CPU `condition()`
function and ASGI forwarding endpoint are not part of the production path.
Canonicalization after mask prediction is local.

## 3D worker contract

Every 3D worker capability declares:

```python
generation_entrypoint={
    "kind": "class_method",
    "class_name": "Model",
    "method_name": "generate_job",
}
```

and implements:

```python
@modal.method()
def generate_job(self, input_path: str, options: dict | None = None) -> dict:
    return run_generation_job(
        CAPABILITY["id"], artifacts, self._generate, input_path, options
    )
```

`_generate()` is a normal in-container method, not another Modal RPC. This is
important: `generate_job -> _generate` is one GPU invocation, not a second
remote dispatch.

All four L40S classes use `max_containers=1` and deliberately do **not** use
`@modal.concurrent`. These model objects mutate request-scoped/shared pipeline
state and are not safe for Modal's synchronous multi-threaded container input
concurrency. Overflow queues in Modal; one warm model handles one generation at
a time.

## T4 background-mask contract

`modal_3d/rembg_worker.py` exposes only:

```text
modal-3d-rembg / RemBgWorker.process(source_bytes) -> mask
```

It has `max_containers=1`, no `@app.function`, no ASGI app, no `condition()`
forwarder and no `source-inputs/` artifact path. Existing alpha/caller masks
bypass this worker entirely.

## Local responsibilities

`modal-3D-client` owns:

- model/profile/option validation;
- static model -> Modal App/class/method routing;
- request-id idempotency and local SQLite job state;
- source decoding, mask refinement and canonicalization;
- direct T4 mask lookup only when an opaque input needs it;
- upload to `client-inputs/<sha256>.png`;
- persistence/polling/cancellation of `FunctionCall.object_id`;
- artifact download/cache/integrity validation.

Content-level in-flight deduplication from the old Gateway is **not** silently
claimed here. The current local contract guarantees idempotency for the same
`job_id`; a submission whose remote outcome is unknown must remain recoverable
rather than inventing a task id.

## Extension rules

- Do not add a Modal CPU function that only forwards to another Modal function.
- Add a 3D model by adding its GPU worker capability and matching static routing
  row in the client/provider tooling.
- Keep `generate_job` as the only public generation RPC; keep `_generate`
  private/in-container.
- Do not enable `@modal.concurrent` on the L40S model classes without a separate
  thread-safety and VRAM concurrency validation.
- Keep canonical PNG and GLB validation at the worker boundary even though the
  client also validates locally.

## Removed production components

- `modal-3d-gateway` App;
- `gateway_tasks.py`, `gateway_registry.py`, `gateway_routing.py`;
- worker CPU forwarding adapters (`register_worker_entrypoint`);
- cloud `source-inputs/` conditioning path;
- rembg CPU `condition()` function and rembg ASGI forwarding endpoint.

The useful T4 `RemBgWorker` itself remains, but is called directly by the local
client only when mask inference is actually required.
