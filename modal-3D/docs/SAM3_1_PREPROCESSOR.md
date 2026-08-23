# SAM 3.1 production preprocessor

This feature branch turns the validated SAM 3.1 experiment into a small, production-shaped multi-object preprocessing service. It is intentionally **not wired into the gateway or any 3D worker yet**.

## Product contract

The service follows the interaction that survived the experiment:

```text
image + concept
  -> candidate instances (bbox + score)
  -> user chooses an existing candidate
  -> optional text + positive/negative box refinement
  -> CPU materialize selected mask
  -> canonical RGBA
  -> downstream image-to-3D worker
```

There is no point-prompt API in V1. `sam3.1_multiplex.pt` does not contain the legacy `inst_interactive_predictor` weights, so exposing that API would create an untrained/random head.

## Apps and pins

- Modal app: `modal-3d-sam31`
- GPU: `L40S`
- GPU `max_containers=1`
- idle scale-down: 300 s
- Python 3.12
- CUDA 12.8
- Torch 2.10.0 + cu128
- SAM source: `facebookresearch/sam3@8f0b7f4d4e7eda2ed606ebde6702c93359ad01da`
- SAM 3.1: `facebook/sam3.1@daa63191845a41281374e725f4c9e51c7a824460`
- checkpoint: `sam3.1_multiplex.pt`
- weight/config Volume: 3,502,781,787 bytes

The weight synchronizer is CPU-only. A cached sync measured 1.18 s.

## API shape

### `Model.segment(image_bytes, concept, max_candidates=16)`

- validates and EXIF-normalizes the input image;
- stores the **original bytes** under a SHA-256 `scene_id`;
- image-encodes on SAM 3.1;
- runs the text concept prompt;
- returns up to 24 ranked candidates (default 16);
- each candidate includes score, model bbox, normalized bbox, mask bbox and mask coverage;
- all masks are persisted together in one bit-packed `masks.bin` plus one `result.json`.

The UI can render candidate boxes immediately. Clicking a candidate does not require another GPU inference.

### `Model.refine(scene_id, concept, boxes, max_candidates=16)`

`boxes` contains 1–16 normalized center-format prompts:

```json
{
  "cx": 0.65,
  "cy": 0.72,
  "width": 0.40,
  "height": 0.27,
  "positive": true
}
```

The method resets prompts, applies the text concept, then adds boxes in order. Positive and negative boxes are both validated. If the scene is still in the single-entry GPU cache, encode time is zero. If it was evicted, the method reloads original bytes from the artifacts Volume and re-encodes; sticky routing is not required.

### `materialize(scene_id, selection_id, candidate_id, output_size=1024)`

This is CPU-only. It decodes just the selected bit-packed mask and writes:

- `mask.png`
- `canonical.png` (RGBA, square, 8% padding, centered, default 1024×1024)

Full-size RGBA is optional (`include_full_rgba=True`) and is off by default to avoid unnecessary encoding and storage.

## Why masks are bit-packed

The first production-shaped implementation eagerly wrote mask, overlay, full RGBA and 1024 RGBA for every candidate. A 16-instance `plant` result made artifact processing dominate the request.

The final design stores one bit-packed matrix for all candidates. On the 640×855 test image, 16 masks occupy 1,094,400 bytes total. Only the object the user actually chooses is PNG/materialized.

## L40S measurements

Representative final measurements:

| Path | Model work | Client wall |
| --- | ---: | ---: |
| Cold `cup` segment | load 10.22 s + encode 439 ms + prompt 922 ms | 26.85 s |
| Warm same-scene `cup` | encode 0 + prompt **52 ms** | **1.20 s** |
| Warm new-scene `plant` ×16 | encode 47 ms + prompt 82 ms | 3.80 s |
| Warm cached-scene `plant` ×16 | encode 0 + prompt **53 ms** | **1.30 s** |
| Warm text + one box refine | GPU prompts **118 ms** | **1.14 s** |
| CPU materialize | — | cold 4.26 s / warm **0.72 s** |

Peak allocated GPU memory stayed around 4.4 GiB on these paths.

A cache-eviction test also passed: after another image replaced the one-entry state cache, refining the old scene reloaded it from Volume, re-encoded in 46.8 ms and completed in 1.49 s wall time.

Positive + negative box refinement on the two-cup image produced one candidate with score 0.9883.

## SAM 3.1 image-backbone adapter

The official SAM 3.1 HF config describes three detector FPN feature sizes. The generic image builder in the pinned source constructs four neck levels and then discards the lowest-resolution one with `scalp=1`. Loading the 3.1 multiplex checkpoint through that generic builder therefore reports four missing weights for `convs.3`; that fourth level is computed and discarded.

The production worker makes the effective architecture explicit:

1. build the generic image model on CPU without loading weights;
2. require the expected four-level + `scalp=1` layout;
3. remove the unused fourth neck level;
4. set `scalp=0` so the same three effective features remain;
5. load the pinned 3.1 checkpoint;
6. move the model to CUDA.

After this adapter there are no missing-key warnings. Both `cup` candidates were compared before/after the adapter; score, bbox, mask pixel count and mask bbox were identical.

## Canonical RGBA

A downloaded production artifact was verified as:

```text
mode: RGBA
size: 1024 × 1024
alpha extrema: 0 .. 255
alpha bbox: (65, 118, 959, 906)
bytes: 777,298
```

This validates the downstream file contract, not human-ground-truth segmentation quality.

## Deliberate non-goals

V1 does not add:

- point prompting;
- BiRefNet/rembg fallback;
- GroundingDINO;
- automatic VLM concept discovery;
- gateway routing;
- changes inside FastSAM3D++, Hermite, Hunyuan, Pixal3D or trellis.cpp;
- more than one GPU container.

Those are separate decisions after this preprocessing contract is accepted.

## Operations

```bash
modal deploy modal_3d/sam3_1.py
```

CPU-only weight sync:

```bash
modal run modal_3d/sam3_1.py::sync_weights
```

Raw benchmark evidence is recorded in:

`benchmarks/sam3.1-preprocessor-production-l40s-2026-08-23.json`
