# modal-provider

`modal-provider` 是 AgentScape 的 **Modal Provider monorepo**。过去分散在多个独立仓库中的 Gateway、2D/3D Provider、Reference Sidecar 与 EmbodiedGen build/runtime integration 已统一收敛到这里。

## Repository role

```text
AgentScape
   │ Capability / Job / Artifact contract
   ▼
modal-provider
├─ modal-gen-client/      optional local security gateway
├─ modal-2D-client/       image Reference Sidecar
├─ modal-2D/              image generation Provider
├─ modal-3D-client/       3D Reference Sidecar
├─ modal-3D/              3D generation Provider
└─ modal-EmbodiedGen/     EmbodiedGen build/runtime integration
```

这些目录是 **monorepo 内部 package / deployment unit**，不是 AgentScape 系统里的独立 Git repository boundary。

## Ownership

`modal-provider` owns：

- Modal credential/runtime integration；
- Provider-private Job / Artifact execution facts；
- GPU/model lifecycle；
- Reference Sidecar restore/cache；
- local pairing/session/security gateway；
- 2D/3D input conditioning and model execution；
- EmbodiedGen upstream pin、build artifacts、compatibility patches、production runtime。

`modal-provider` does **not** own：

- Agent/Human intent or workflow truth；
- AgentScape Asset semantic truth；
- World desired/compiled/live state；
- Runtime verification authority outside Provider artifact validity。

## Package independence

合并仓库不意味着把运行时边界揉成一个进程。每个 package 仍可以保留：

- 独立 `pyproject.toml` / lockfile / Node package；
- 独立测试矩阵；
- 独立 Modal app identity；
- 独立 GPU image / autoscaling / deployment lifecycle；
- 独立 failure/retry owner。

原则是：**repository consolidation, runtime boundary preservation**。

## EmbodiedGen

`modal-EmbodiedGen` 取代旧的 standalone `modal-build`/AgentScape-owned EmbodiedGen workspace 边界。它按需要 pin/clone 上游 `HorizonRobotics/EmbodiedGen`，构建可复现 CUDA/PyTorch artifacts、应用兼容 patch 并部署 Modal runtime。上游源代码是 dependency，不是本系统的独立产品仓库。

## Removed standalone topology

旧的 standalone `modal-gen-client`、`modal-2D*`、`modal-3D*`、`modal-build` 不再是当前仓库拓扑。Kaggle Provider 与独立 `modal-lab` 也不属于本 monorepo 的目标运行时架构。

## Development

进入具体 package 后使用它自己的 README、lockfile、测试与部署命令。跨 package 变更应在本 monorepo 内一次审查，并保持 AgentScape-facing contract 向后兼容或显式版本化。
