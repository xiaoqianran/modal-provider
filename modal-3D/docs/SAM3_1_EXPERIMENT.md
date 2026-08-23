# SAM 3.1 preprocessing experiment

This is an isolated experiment for a future multi-object image-to-3D input layer. It does **not** change the gateway or any existing 3D worker.

## Decision

Use SAM 3.1 as a smart object-selection service, but use its native SAM 3.x prompt path:

```text
concept text
  -> candidate instance masks
  -> user clicks an existing candidate
  -> text + native box refinement when ambiguous
  -> confirmed mask
  -> canonical RGBA
  -> 3D worker
```

Do **not** build V1 around the legacy `predict_inst` point/box path with `sam3.1_multiplex.pt`. The checkpoint does not contain the full `inst_interactive_predictor` weights; enabling that head produces missing-key warnings and invalid masks.

## Pins

- App: `modal-3d-sam31-experiment`
- GPU: NVIDIA L40S
- Python 3.12
- CUDA 12.8
- Torch 2.10.0 + cu128
- SAM code: `facebookresearch/sam3@8f0b7f4d4e7eda2ed606ebde6702c93359ad01da`
- SAM 3.1: `facebook/sam3.1@daa63191845a41281374e725f4c9e51c7a824460`
- Checkpoint: `sam3.1_multiplex.pt`
- Synced SAM 3.1 checkpoint/config: 3,502,781,787 bytes

A SAM 3.0 control was also pinned to `facebook/sam3@3c879f39826c281e95690f02c7821c4de09afae7` (`sam3.pt`, 3,450,062,241 bytes).

## L40S measurements

SAM 3.1 clean image path (`enable_inst_interactivity=False`):

| Metric | First image | Warm second image |
| --- | ---: | ---: |
| Model load | 10.354 s | resident |
| Image encode | 462 ms | **46.6 ms** |
| Warm concept prompt | ~51-55 ms | ~53 ms |
| Native box prompt | 80.5 ms | **53.3 ms** |
| Exact native-box IoU to text mask | 0.9831 | **0.9846** |
| Peak allocated VRAM | 4.94 GiB | 4.95 GiB |

The first text prompt pays one-time prompt-path warm-up (~0.96 s on the first image). Later concepts are ~50 ms.

## Multi-object behavior

The fixed experiment vocabulary was:

```text
person chair table cup bottle bag shoe plant lamp car
```

On `pinterest-a1`, SAM 3.1 returned multiple instances for several concepts, including 2 bottles, 2 bags, 16 plants, and 9 lamps.

On `pinterest-01`, `cup` returned **2 instances** and `plant` returned 2. This validates the core product requirement: one concept can expose multiple candidate objects and the UI can let the user choose an already-computed mask without another GPU inference.

## Box refinement

Native geometric prompting is `Sam3Processor.add_geometric_prompt()`, using normalized `[cx, cy, w, h]` boxes.

Using the selected text object's bbox as the exact box produced ~0.98 IoU to the text mask on both inputs. Deliberately perturbed boxes showed that box-only prompting should be treated as instance/exemplar guidance rather than a generic detector. Combining the concept text with the box was more robust.

For the second image (`cup`):

| Text + box variant | IoU to selected text mask |
| --- | ---: |
| Exact | 0.9888 |
| Expand 20% | 0.8226 |
| Shrink 15% | 0.9707 |
| Shift Y by 10% of box height | 0.9109 |
| Shift X by 10% of box width | 0.0612 |

The low horizontal-shift result is consistent with an ambiguous multi-instance scene: the same concept has two cup instances, so a shifted exemplar can select a different instance. This is why V1 should first expose concept candidates, then use a box for disambiguation/refinement.

These IoUs are **self-consistency against the SAM text mask, not human-ground-truth segmentation accuracy**.

## SAM 3.0 control

The base `sam3.pt` checkpoint contains the legacy interactive head. On the warm second image:

- encode: 46.8 ms
- text concept: ~50.7 ms
- point prompt: 11.0 ms, IoU to selected text mask 0.8636
- legacy box: 9.6 ms, IoU 0.7631

On the first image, point/box IoU to the selected text mask was ~0.938/~0.944. The control proves that the broken SAM 3.1 legacy path was a checkpoint/head compatibility issue, not a general failure of the interactive API.

## Engineering observations

The public SAM package's image import closure needed three small dependencies not covered by the minimal base install used here: `einops`, `pycocotools`, and `psutil`. They are pinned in the experiment image.

The SAM 3.1 release/checkpoint is primarily multiplex-oriented. For static image selection, version number alone is not a reason to reuse every SAM 3.0 interactive API. Build against the prompt heads actually present in the selected checkpoint.

## Experiment artifacts

The worker persists mask, RGBA cutout, and overlay PNGs under `sam31-experiment/` in the shared artifacts Volume. Raw benchmark evidence is recorded in:

`benchmarks/sam3.1-preprocess-l40s-2026-08-23.json`

The experiment remains separate from production routing.
