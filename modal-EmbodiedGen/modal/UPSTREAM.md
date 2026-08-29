# Upstream and production baseline

This repository is a fork of `HorizonRobotics/EmbodiedGen`.

The repository root and Modal production source now target upstream `v2.1.0`
(`f0124197888c2b733e4eaa65acd81ad9cfda3b79`). The previous validated production source was v2.0.0
(`cc3015ca5ccdacf94df3428d9e65f79375982216`).

The v2.1.0 upgrade keeps Python 3.10, CUDA 12.6, PyTorch 2.8.0, torchvision 0.23.0,
and xformers 0.0.32.post2. The SAM3D and TRELLIS submodule gitlinks are identical between v2.0.0
and v2.1.0. Existing precompiled PyTorch3D, nvdiffrast, and gsplat SM89 binaries are therefore
reused as an ABI bundle; they are not relabeled as a v2.1.0 release.

All production source patches apply cleanly to the v2.1.0 tree. v2.1.0 also pins OpenCV to
4.9.0.80, so the Modal runtime constraints were changed from 4.11.0.86 to 4.9.0.80.

A real Modal L40S end-to-end validation must pass before this document should describe the upgrade
as production-validated.
