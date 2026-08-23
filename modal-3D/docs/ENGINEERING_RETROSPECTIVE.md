# Engineering Retrospective

This document records the mistakes, failed assumptions, debugging lessons, and engineering rules learned
while turning several research image-to-3D repositories into small, reproducible Modal workers.

The purpose is not to celebrate what worked. It is to make future mistakes cheaper and less likely.

## 1. Stable architecture rules

These rules should not drift unless a benchmark gives a concrete reason to change them.

- One model family = one Modal App/Image/weight Volume boundary.
- Every GPU worker uses `max_containers=1`.
- Do not enable Modal container input concurrency for model inference.
- Queue overflow instead of adding another GPU container.
- `min_containers=0` until a measured business requirement justifies paid warm capacity.
- Model and auxiliary checkpoints are synchronized on CPU and persisted in a Volume.
- GPU workers run offline and should fail when a required model is missing rather than silently download.
- Expensive native compilation belongs in `modal-build`, never in the production inference worker.
- Production images consume pinned release artifacts with `uv` and do not rebuild CUDA extensions.
- Benchmark cold and warm paths separately and never call a reused-container request "cold".
- Keep generated GLB files in artifact storage, not in Git history.

## 2. `modal-build` artifact rules

Artifact naming is fixed:

`<model>-py<python>-cu<cuda>-torch<torch>-sm<arch>-v<n>`

For native C++ projects without Python/PyTorch, use explicit `pynone` / `torchnone`; do not silently omit
ABI dimensions.

Git repositories contain build scripts, environment manifests, hashes, and documentation. Large binary
artifacts live in GitHub Release assets.

Examples:

- `hermit-trellis2-plus-plus-py311-cu124-torch260-sm89-v1`
- `pixal3d-py310-cu124-torch260-sm89-v1`
- `trellis.cpp-pynone-cu129-torchnone-sm89-v2`

Every build must pin source commits, compiler/runtime ABI, CUDA architecture, and package versions. A
successful compile is not sufficient; the artifact must also be installable/importable in a clean runtime
image.

## 3. Mistake: I initially used the wrong project name

The first TRELLIS worker was internally and externally shortened to `trellis2`, even though the model being
integrated was `Archerkattri/hermit-trellis2-plus-plus`.

Why this was bad:

- benchmark names became ambiguous;
- Release tags no longer identified the actual implementation;
- later adding `pwilkin/trellis.cpp` made the ambiguity much worse;
- external APIs and internal storage names started to diverge without an explicit reason.

Fix:

All public worker, benchmark, module, and Release names were changed to
`hermit-trellis2-plus-plus`. An old 24.35 GiB physical Volume name was intentionally retained only to avoid
redownloading data; that legacy storage name is treated as an implementation detail.

Rule learned:

**Name artifacts after the exact upstream/fork being benchmarked.** Performance data without implementation
identity is not reproducible data.

## 4. Mistake: Git remote was not verified before pushing

While editing `modal-build`, the local repository unexpectedly had an `openi-build` remote. A commit was
pushed to the wrong repository before the mismatch was noticed.

Fix:

- inspected remotes and branch heads;
- corrected `origin` to `xiaoqianran/modal-build`;
- pushed the intended history to the correct repository;
- removed the accidental branch only after verifying its exact commit/message.

Rule learned:

Before modifying or pushing a repository that may have been touched by another worker, always inspect:

```bash
git status --short
git remote -v
git branch -vv
git log -3 --oneline
```

Never assume the directory name proves repository identity.

## 5. Mistake: native wheel builds initially pulled dependency trees

The first `pip wheel` commands did not use `--no-deps`. Building a CUDA extension unexpectedly pulled a
newer Torch/CUDA dependency tree (including incompatible CUDA 13-era dependencies) into the wheelhouse.

That artifact would have looked complete while actually destroying ABI reproducibility.

Fix:

Native extension build commands now use `--no-deps`, while Torch/CUDA are installed and pinned separately in
the build environment.

Rule learned:

A native wheel cache is **not a generic Python package mirror**. Cache only the expensive compiled artifact;
let the runtime environment declare normal dependency versions explicitly.

## 6. Mistake: CUDA architecture auto-detection was trusted in builders

CuMesh initially failed while building without a visible GPU because PyTorch attempted to auto-detect CUDA
architectures and produced an empty architecture list.

Fix:

For L40S artifacts, compilation explicitly pins:

```text
TORCH_CUDA_ARCH_LIST=8.9
CUDA architecture = SM89
```

Rule learned:

Build architecture is part of the ABI. Never depend on auto-probing in a remote image builder.

## 7. Mistake: a long CPU image build was treated like a compiler failure

A long CuMesh build was terminated by an external image-builder shutdown. The source did not actually fail
to compile.

Fix:

The expensive native compilation stage was moved to a one-time GPU build environment and eventually into
`modal-build`, so production deploys no longer depend on long compiler jobs.

Rule learned:

Distinguish:

- compiler errors;
- process OOM;
- platform cancellation;
- outer RPC timeout;
- user/dashboard stop.

They require different fixes.

## 8. Mistake: missing vendored Eigen was discovered late

`o-voxel` expected Eigen headers under `third_party/eigen`, but the checked-out source did not provide the
required content in that location.

Fix:

The builder explicitly vendors a pinned Eigen commit before creating the `o-voxel` wheel.

Rule learned:

`git submodule update --recursive` is not proof that a project contains all build-time third-party sources.
Inspect the include paths used by the build system.

## 9. Mistake: model dependency discovery was initially incomplete

The TRELLIS pipeline had indirect model dependencies beyond the obvious main checkpoint, including DINOv3
and background-removal models. GPU-offline mode exposed the omission.

Fix:

Before GPU startup, search the source for all forms of remote resolution:

- `from_pretrained()`
- `snapshot_download()`
- `hf_hub_download()`
- `torch.hub.load()`
- hard-coded URLs
- config files containing external model IDs

Rule learned:

A model is "fully cached" only when a clean offline GPU container can start and infer. A successful main
checkpoint download proves almost nothing.

## 10. Gated Hugging Face repositories must fail in the CPU stage

DINOv3 returned HTTP 401 during an anonymous CPU sync. A suitable Hugging Face Modal Secret already existed,
so the downloader was authenticated without adding a token to the GPU worker.

Rule learned:

- Secrets required for model acquisition belong on CPU download functions.
- GPU inference should not receive credentials it does not need.
- If an external gated model cannot be acquired, fail before paying for GPU startup.

## 11. Background removal should not consume the inference GPU

For both TRELLIS and Pixal3D, loading BiRefNet on the L40S was unnecessary when the product contract already
allowed pre-matted RGBA input.

In Pixal3D this became especially obvious when an `einops` error appeared while loading a background model
that the benchmark would never call.

Fix:

The production Pixal3D worker requires a meaningful alpha channel and installs a no-op rembg implementation.
BiRefNet is removed from the active GPU path.

Rule learned:

Do not "fix a dependency error" before asking whether that dependency should exist in the production path at
all. Deleting unnecessary work is better than making unnecessary work reliable.

## 12. Mistake: `huggingface_hub` was pinned too early in an install sequence

Pixal3D initially installed a compatible Hugging Face Hub version, but a later MoGe install upgraded it to a
1.x version incompatible with the pinned Transformers release. The L40S then failed during model startup.

Fix:

- apply the compatibility pin **after** all packages that may mutate it;
- run an import/version assertion during image build.

Rule learned:

Dependency order matters. A lock/pin is not effective if later installers can overwrite it. Critical ABI
constraints should be asserted at build time, not discovered on a GPU.

## 13. Mistake: precompiled CUDA wheels do not eliminate all runtime compilation

Pixal3D's native extensions were prebuilt correctly, but Triton/FlexGEMM still compiled a small runtime
`driver.c` during first initialization. The minimal CUDA runtime image had no C compiler.

Fix:

Add only the minimal runtime compiler (`gcc`) and set `CC=/usr/bin/gcc`. Do not reintroduce the full CUDA
build toolchain into production.

Rule learned:

"No CUDA extension compilation at runtime" and "absolutely no compilation at runtime" are different goals.
Triton/JIT systems need separate treatment and benchmarking.

## 14. FlexGEMM/Triton autotuning is a real cold-start cost

The first clean Pixal3D request performs substantial kernel autotuning. Warm requests reuse the selected
configurations and are much faster than the first inference, but still not fast enough compared with public
RTX 5090 results.

Current measured Pixal3D/L40S numbers:

```text
clean cold wall          288.31 s
@modal.enter load         76.89 s
cold inference/autotune  189.23 s
warm wall median         108.92 s
warm inference median     99.39 s
cold peak board VRAM      31.37 GiB
warm peak board VRAM      30.49 GiB
```

Rule learned:

Separate these phases in every benchmark:

1. container/scheduler wall overhead;
2. model load;
3. first inference/JIT/autotune;
4. steady-state inference;
5. postprocess/export.

Without this split, optimizing "cold start" becomes guesswork.

## 15. Mistake: benchmark clients were left alive during iterative debugging

Several local Pixal3D benchmark clients from previous debugging attempts remained alive. Because the Modal
worker correctly had `max_containers=1`, those requests queued and were consumed serially. The artifact
Volume kept receiving GLBs, while the newest benchmark log appeared empty.

This could easily have been misinterpreted as Modal spawning multiple containers or the service behaving
non-deterministically.

Fix:

- identify exact stale client PIDs;
- terminate only those clients;
- stop and redeploy the Modal App once;
- run one clean benchmark client.

Rule learned:

Before any performance run, verify both sides:

```text
local benchmark processes == exactly one
Modal max_containers      == 1
old queued calls          == none
```

A clean benchmark is an experiment, not merely another request.

## 16. Mistake: I initially mislabeled a reused-container request as cold

A successful TRELLIS request followed an earlier failed request whose container remained alive. The first
successful request therefore included first-inference work but not a clean container startup.

Fix:

The app was explicitly stopped/redeployed and the measurement repeated.

Rule learned:

**"First successful request" is not synonymous with "cold request."** A cold benchmark requires a verified
fresh container.

## 17. `trellis.cpp`: external stop was initially easy to misread as a crash

The first long `trellis.cpp` run showed cancellation and termination, but Modal logs later proved that:

- CUDA initialized successfully;
- L40S/SM89 was detected;
- model stages ran;
- a large mesh was decoded;
- the app was stopped externally from the dashboard.

It was not an OOM, CUDA failure, or segfault.

Rule learned:

When a remote job "crashes", inspect the platform event that ended the container before changing model code.
Do not debug an external stop as if it were a kernel failure.

## 18. `trellis.cpp`: cancellation must terminate child inference

A cancelled Python/Modal call could leave the resident C++ server continuing to consume GPU time.

Fix:

The worker now ties the server process lifecycle to Modal lifecycle hooks and kills the server on a failed or
cancelled generation call.

Rule learned:

When a worker launches subprocesses, Modal cancellation does not automatically define the desired child
process semantics. Explicit ownership is required.

## 19. Mistake: `trellis.cpp` runtime bundle duplicated NVIDIA libraries

The first native bundle copied CUDA runtime libraries, including a very large `libcublasLt`, even though the
production base image was already a pinned NVIDIA CUDA runtime image.

Result:

```text
v1 bundle  ~716 MiB
v2 bundle  ~162 MiB
```

Fix:

The v2 Release contains only project-compiled binaries/shared objects. CUDA runtime libraries come from the
pinned NVIDIA base image.

Rule learned:

A self-contained bundle is not automatically a better bundle. Do not package platform runtime libraries when
the runtime image is already part of the compatibility contract.

## 20. Mistake: `ldd` validation initially rejected `libcuda.so.1`

`ldd` validation in a non-GPU build container reported `libcuda.so.1 => not found`. That library is expected
to be provided by the NVIDIA driver at GPU runtime and should never be packaged with the application.

Fix:

Runtime dependency validation allows driver-injected `libcuda.so.1` while still rejecting other unresolved
libraries.

Rule learned:

Dependency validation needs a model of which layer owns each library:

- app bundle;
- base image;
- GPU driver injection.

"Not found in builder" does not always mean "missing in production".

## 21. `trellis.cpp` performance lesson: simpler runtime does not imply faster inference

The native C++/GGML implementation has major operational advantages: no PyTorch runtime, smaller geometry
weight storage, native Q8/Q4 support, and a compact deployable runtime. It was nevertheless much slower than
`hermit-trellis2-plus-plus` for the tested 1024 F16 geometry path.

Measured warm medians:

```text
hermit-trellis2-plus-plus  ~11.98 s wall
trerellis.cpp              ~120.67 s wall
```

The `trellis.cpp` server starts quickly, but it still stage-loads models and spends substantial time in high
resolution shape flow and mesh decoding.

Rule learned:

Deployment simplicity, storage size, cold startup, VRAM, and inference throughput are independent axes. Do
not infer one from another.

## 22. Pixal3D lesson: lab code is evidence, not production architecture

`modal-lab/005-v2-pixal3d-l40s` was valuable because it proved a compatible environment and exposed known
L40S/SM89 requirements. It was not suitable to copy wholesale into production.

The lab mixed:

- building;
- wheel storage;
- dependency verification;
- model downloads;
- runtime installation;
- inference;
- benchmarking;
- viewer/UI;
- smoke tests;
- operational commands.

It also rebuilt/reinitialized the Pixal3D pipeline per inference path.

The production worker instead has three responsibilities:

```text
sync_weights()  # CPU-only acquisition
@modal.enter()  # load resident model state once
generate()      # one inference + artifact write
```

Rule learned:

A research/lab script should be mined for verified constraints and failure knowledge, not copied as an
application architecture.

## 23. Pixal3D lesson: L40S should use its memory when latency matters

The lab defaulted to low-VRAM staged placement. On L40S we tested `low_vram=False` rather than preserving
that setting by habit.

Observed full-pipeline peak board memory was about 31.4 GiB, comfortably within L40S capacity.

Rule learned:

Use measurements to choose between staging and residency. Paying for 48 GB and then avoiding available VRAM
can be an unnecessary latency tax.

## 24. Public Pixal3D performance indicates our current worker is not the speed ceiling

Our current production benchmark is deliberately conservative and quality-oriented:

- L40S;
- Linux/Modal;
- `1024_cascade`;
- upstream checkpoint defaults: 12 sparse / 12 shape / 12 texture steps;
- `low_vram=False`;
- textured GLB;
- 1,000,000 triangle decimation target;
- 4096 texture;
- warm wall median ~108.92 s.

Public community work reports materially faster runs on RTX 5090-class hardware. `dreamrec/ComfyUI-Pixal3D`
reports approximately 50-65 s warm for 1024 cascade, 16/16/16 steps, 300k decimation, 4096 texture and
`low_vram=false`; it also reports 64-71 s warm for a 1536 low-VRAM configuration on RTX 5090. A release note
records a 56.5 s warm run with 8/8/8 steps and a smaller texture/output setting.

These results are not directly interchangeable with our L40S numbers. Differences include GPU generation,
Torch/CUDA stack, decimation target, token limits, step count, postprocessing, texture settings, ComfyUI
integration, and possibly cached autotune state.

References:

- https://github.com/TencentARC/Pixal3D
- https://github.com/dreamrec/ComfyUI-Pixal3D
- https://github.com/dreamrec/ComfyUI-Pixal3D/releases

Rule learned:

Never advertise a "fastest seconds" number without attaching its complete quality/runtime configuration.
Latency without configuration is not a benchmark.

## 25. Cost accounting must be labeled correctly

We currently use client wall time multiplied by the published L40S per-second rate as a conservative cost
proxy. That is useful for comparing configurations but is not authoritative billing because scheduler/client
wall time and actual billable GPU lifetime are not identical.

Rule learned:

Every cost number must say whether it is:

- GPU-active measured runtime;
- client wall-time proxy;
- provider invoice/billing data.

Do not collapse them into one number.

## 26. Outer VPS gateway errors are not Modal failures

The remote VPS control path produced Cloudflare 520/524 errors during long commands. In several cases the
`nohup` process on the VPS continued normally.

Fix:

Use local background processes plus explicit log/exit-file polling for long Modal build/deploy/download
commands.

Rule learned:

There are multiple control planes:

```text
Chat/control RPC -> VPS shell -> Modal CLI -> Modal builder/container
```

A timeout at one layer does not prove failure below it. Inspect the nearest durable state before restarting
work.

## 27. Do not solve performance problems before establishing a clean baseline

During this project it was tempting to immediately add snapshots, prewarm kernels, quantization, or different
GPU types. That would have made failures difficult to attribute.

The correct order proved to be:

1. pin source and ABI;
2. remove runtime downloads/compilation;
3. get one real artifact;
4. verify the artifact file;
5. create a clean cold run;
6. run multiple warm requests in the same container;
7. collect VRAM and artifact size;
8. only then optimize the dominant phase.

Rule learned:

**Optimization before observability creates folklore.** Optimization after measurement creates engineering.

## 28. Required checklist for every future model integration

### Repository identity

- exact upstream/fork URL
- pinned commit
- pinned model-data revision when weights/config live outside Git
- local Git remote verified
- concurrent unrelated work left untouched

### Build

- Python/CUDA/Torch/SM explicitly pinned
- package/build tool versions explicitly pinned
- native source commits pinned
- `--no-deps` for native wheel packaging
- compiled artifacts published to `modal-build`
- manifest and SHA256 generated
- clean-runtime import/`ldd` verification

### Weights

- enumerate all implicit external models
- CPU-only sync
- gated access handled before GPU
- GPU starts offline
- no model token supplied to GPU unless unavoidable

### Worker

- `max_containers=1`
- no container input concurrency
- `min_containers=0` by default
- expensive model state loaded in `@modal.enter()`
- cancellation cleans up child processes/resources
- artifact persisted outside Git

### Benchmark hygiene

- kill stale local benchmark clients
- verify no old queued calls
- explicitly create a fresh container for cold tests
- record load separately from first inference/JIT
- run at least three warm samples
- record board-level VRAM when possible
- record exact input hash, seed, resolution, step counts, token limits, texture size and decimation
- validate the output artifact locally
- label cost numbers as proxy vs billing

### Before optimization

Ask these questions in order:

1. Is the work necessary at all?
2. Is it happening on the right CPU/GPU side?
3. Is it repeated per request unnecessarily?
4. Is it compiling/autotuning unnecessarily?
5. Is the model resident when memory allows?
6. Is postprocessing dominating model inference?
7. Are we comparing equivalent quality settings?

## 29. Current self-assessment

The strongest decisions were the architectural ones: single-container workers, CPU weight sync, offline GPU
inference, `modal-build`, explicit ABI tags, and persistent benchmarks.

The weakest part of the process was early assumption discipline. Several errors came from assuming:

- a repo directory had the expected Git remote;
- a dependency pin would survive later installs;
- a downloaded main checkpoint represented the full dependency graph;
- a prebuilt CUDA wheel eliminated all runtime compilation;
- the first successful request was a clean cold request;
- a remote termination represented a model crash;
- old benchmark clients had exited when a newer test began.

These are all avoidable with cheap checks. The main improvement I want to carry forward is to move those
checks **earlier**, before GPU allocation, and turn them into build-time assertions whenever possible.

The standard for future integrations should be: fewer assumptions, more explicit contracts, fewer moving
parts, and benchmark evidence before optimization claims.

## 30. A direct worker smoke does not validate the public integration contract

Hunyuan2.1-plus-plus passed direct calls to `Model.generate`, but the shared gateway still resolved
`("modal-3d-hunyuan", "generate")`. The deployed app had no top-level `generate`, so the model worker was healthy
while the repository's declared public route was broken.

The right fix was not to redesign the gateway or force every existing worker into a new abstraction. The gateway
already had a simple contract: `input_path + options`. Hunyuan now exposes a thin CPU adapter with exactly that
contract, reads the input from the shared artifacts Volume, and delegates to the resident GPU class.

Rule learned:

**Validate through the same boundary users actually call. A successful class-method smoke proves the engine, not the integration.**

## 31. Pin data and build tools, not only source code

The Hunyuan fork was pinned to a Git commit, but the base Hugging Face model initially used the repository's moving
HEAD. That meant an identical Git commit could later sync different weights or config files. The exact base-model
revision is now pinned alongside the fork commit.

The runtime image also used `pip install --upgrade uv`, making the image builder itself a moving dependency. It now
uses Modal's native `uv_pip_install` with an explicit uv version.

Rule learned:

**Reproducibility requires four identities: source commit, model-data revision, ABI/runtime versions, and build-tool version.**

## 32. Never compare first inference with later warm runs and call the difference an acceleration

FastSAM3D++ initially appeared to show a dramatic result:

```text
DMD-off first inference ~5.73s
DMD later inference     ~2.6s
```

That comparison was wrong. The first inference paid one-time kernel/cache warm-up costs; the DMD calls ran afterward in an already warm resident container.

The fair same-container sweep was:

```text
interval=1  2.579s
interval=3  2.600s
interval=4  2.636s
interval=6  2.652s
```

The apparent ~2x DMD win disappeared completely. DMD was slightly slower.

**Permanent rule:** acceleration claims must compare equivalent lifecycle states. A first inference, cold model, warm model, and steady-state request are different benchmark classes.

## 33. An acceleration layer can be correct and still be a net loss

HiCache++ DMD works and produces valid geometry in FastSAM3D++, but Fast-SAM3D has already reduced the slat workload aggressively through its own shortcut/token-carving path. On this L40S workload, the remaining DMD fit/forecast bookkeeping costs at least as much as the transformer work it skips.

The right production decision is therefore not "turn DMD on because this is the plus-plus fork". It is:

```text
keep Fast-SAM3D acceleration
keep DMD available as an experiment
production default = DMD off
```

**Permanent rule:** compose accelerators empirically. Speedups are not additive, and a valid optimization can become negative when applied after another optimization has already removed most of its target cost.

## 34. Missing runtime assets should be reconstructed from provenance, not copied blindly

The FastSAM3D++ fork references `ss_generator_faster.yaml` and `slat_generator_faster.yaml` but does not contain them. The official Fast-SAM3D repository does, and each differs from Meta's pinned baseline config by exactly one `_target_` line.

Rather than vendor two nearly identical YAML files, `sync_weights()` now derives them deterministically from the pinned Meta configs and verifies the expected source strings exist before replacing them.

**Permanent rule:** when a fork omits generated/config assets, trace their provenance and reproduce the minimal transformation. Do not create another large copied configuration that can silently drift.

## 35. Source-hygiene patches need syntax validation before expensive native or GPU work

Removing research-only visualization imports exposed a subtle failure mode: broad string replacement removed a function-local import and left an indented block syntactically invalid. The mistake only surfaced when a GPU container imported the patched module.

The build now runs `py_compile` on patched files before deployment, and expensive PyTorch3D compilation is placed in an earlier cacheable image layer so later pure-Python patch iterations do not rebuild native code.

**Permanent rule:** source patches are code generation. Validate their syntax immediately, and arrange image layers so cheap/high-churn transformations sit after expensive/stable native builds.

## 36. A package name is not a dependency identity

SAM3D imports `utils3d`. Installing the PyPI package with that name would be wrong: it is a different project and even pulls an obsolete Open3D stack. The actual dependency is EasternJournalist/utils3d, and MoGe itself pins a compatible Git commit.

**Permanent rule:** for research repositories, resolve ambiguous imports to their actual source repository and commit. Never assume a matching PyPI name is the intended package.

## 37. A newer checkpoint can remove a head that older APIs still construct

The first SAM 3.1 experiment enabled `enable_inst_interactivity=True` because the public builder supports the legacy SAM1-style `predict_inst` interface. The `sam3.1_multiplex.pt` load logs then showed that the checkpoint does not contain the full `inst_interactive_predictor` weights. Those modules were therefore not valid pretrained inference heads, and point/box masks expanded across most of the image.

The SAM 3.0 `sam3.pt` control contains that head and produced coherent point/box masks on the same inputs.

**Permanent rule:** an API existing in source code does not prove that a selected checkpoint contains the weights needed by that API. Inspect missing/unexpected keys and validate each head before exposing it as a product feature.

## 38. Product interaction should follow the model's native prompt semantics

SAM 3.1 worked very well with concept prompts and its native `add_geometric_prompt()` box path. It also returned multiple masks for one concept (`cup` returned two instances on a test scene). This makes a simpler interaction possible:

```text
concept -> candidate masks -> click an existing mask -> optional text + box refinement
```

That is better than forcing a point-first UX simply because older SAM generations made point prompting familiar.

**Permanent rule:** do not preserve an old interaction contract when the new model has a stronger native abstraction. Design the UI around the validated model semantics, not around historical API familiarity.

## 39. Self-consistency is not ground-truth mask quality

The SAM 3.1 box-robustness experiment measures IoU between a box-prompt result and the text-prompt mask selected from the same model. This is useful for prompt stability and instance-switching behavior, but it is not human-ground-truth segmentation accuracy.

Likewise, the experiment's `selected_text_prompt` is the highest score among a fixed ten-concept vocabulary, not proof of open-ended scene understanding.

**Permanent rule:** name the reference behind every quality metric. Model-vs-model-self IoU, GT IoU, perceptual quality, and user selection correctness answer different questions and must never be collapsed into one "quality" score.

## 40. Isolate architecture experiments from production worktrees

The SAM 3.1 work was created in a separate Git worktree and branch from the already-stable Plus workers and the in-progress Pages work. That allowed CUDA/Python changes, experimental dependencies, and model-specific debugging without contaminating the production working tree.

**Permanent rule:** when an experiment changes runtime generations or explores an uncertain architecture, use a separate worktree/branch and merge only after the experiment has a reproducible result and an explicit product decision.

## 41. Research-package metadata may not describe the real inference import closure

The minimal SAM 3 image import path failed successively on `einops`, `pycocotools`, and `psutil`. The latter two arrived through top-level imports that cross interactive/training/video modules even in an image-only service.

The fix was to identify and pin the actual small runtime dependencies, not install the repository's full research environment.

**Permanent rule:** build the smallest proven inference closure. Treat upstream dependency metadata as a starting point, then use import probes to discover real runtime requirements without dragging notebooks, training, or unrelated subsystems into production images.

## 42. Do not materialize every candidate before the user chooses one

The first production-shaped SAM 3.1 path eagerly generated mask, overlay, full RGBA and canonical RGBA for every detected instance. On a concept returning 16 objects, artifact encoding and file fan-out dominated the model itself.

The final design stores one bit-packed mask matrix plus metadata, then materializes only the chosen candidate on CPU.

**Permanent rule:** in an interactive selection workflow, make candidate discovery cheap and defer expensive representation work until selection. The user will discard most candidates.

## 43. A checkpoint's effective architecture should match before weights are loaded

The generic SAM 3 image builder creates four FPN neck levels and later discards one with `scalp=1`. The SAM 3.1 multiplex checkpoint/config contains three detector FPN levels, so generic loading produced four missing `convs.3` keys. The missing module did not affect outputs because its feature was discarded, but leaving randomly initialized unused weights in a production model is still poor hygiene and wastes compute.

The production adapter removes the unused fourth level before loading the checkpoint and changes `scalp` from 1 to 0. Candidate score, bbox and mask statistics were identical before/after, and checkpoint loading became clean.

**Permanent rule:** do not normalize away "harmless" missing-key warnings. Reconcile the effective architecture with the pinned checkpoint and prove output equivalence when making a structural cleanup.

## 44. GPU inference and artifact materialization belong on different resources

SAM 3.1 warm prompting is tens of milliseconds. PNG creation, resizing, compression and Volume commits are CPU/storage work and can easily take longer than inference. Keeping those operations on the L40S would waste the expensive resource while doing no GPU work.

The final service leaves detection/refinement on the GPU class and moves selected-object materialization to a CPU Modal function.

**Permanent rule:** split pipeline stages by the resource they actually consume, especially when a fast GPU model feeds comparatively slow serialization or storage work.

## 45. A scene cache must be an optimization, never a correctness dependency

A one-entry GPU scene cache is enough because a warm SAM 3.1 image encode is about 47 ms. The cache-eviction test deliberately replaced scene A with scene B and then refined A. The service reloaded A's original bytes from the shared artifact Volume and completed correctly.

**Permanent rule:** interactive caches may remove latency, but durable identifiers and durable source data must be sufficient to recover after eviction, scale-down or routing to a fresh container.

## 46. Breaking deployed method signatures require a clean-container smoke

During the optimization pass, a newly deployed class was followed by a call whose traceback still matched the previous method signature/body. Stopping the app and redeploying forced a clean container and removed the ambiguity.

**Permanent rule:** after a breaking remote method-signature change, validate on a clean deployment/container before diagnosing argument errors as application logic bugs.
