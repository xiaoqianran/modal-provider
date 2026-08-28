# modal-provider

Modal provider monorepo for AgentScape.

## Phase 1 layout

```text
modal-provider/
├─ modal-gen-client/
├─ modal-2D-client/
├─ modal-2D/
├─ modal-3D-client/
├─ modal-3D/
└─ modal-EmbodiedGen/
```

Phase 1 intentionally preserves each component as an independent package and deployment unit. Package names, API endpoints, Modal app identities, Python requirements, lockfiles, GPU images, and autoscaling policies remain component-owned.

The repository-level workflows under `.github/workflows/` are the active monorepo CI. Historical component workflows remain inside their imported directories for provenance, but GitHub does not execute nested workflow directories.

A later phase may reorganize the same components into `connector/`, `2d/client`, `2d/runtime`, `3d/client`, and `3d/runtime` after this migration is stable.
