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

这些目录是 **monorepo 内部 package / deployment unit**。其中 `modal-2D-client`、`modal-3D-client`、`modal-gen-client` 同时维护独立 Git 仓库，用于单独查看、CI、发布和分发；代码真值仍以本 monorepo 为准。

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

## Standalone package repositories

本 monorepo 是代码真值源，同时维护以下独立 package 仓库：

- `modal-2D-client` → https://github.com/xiaoqianran/modal-2D-client
- `modal-3D-client` → https://github.com/xiaoqianran/modal-3D-client
- `modal-gen-client` → https://github.com/xiaoqianran/modal-gen-client

同步规则：

1. 先在 `modal-provider` 完成修改、测试、commit 和 push。
2. 如果改动涉及上述 package，再把对应目录同步到对应独立仓库。
3. 独立仓库保留自己的 `.git`、`.github` 和历史。
4. 默认使用普通 commit + fast-forward push；禁止 force push，除非明确要求。
5. 推送后检查 monorepo 与对应独立仓库的 `main` HEAD，并确认 working tree clean。

代码真值优先级：

```text
modal-provider monorepo
    ↓ sync
standalone package repositories
```

旧的 standalone `modal-build` 不再作为当前产品边界；Kaggle Provider 与独立 `modal-lab` 也不属于本 monorepo 的目标运行时架构。

## Development

进入具体 package 后使用它自己的 README、lockfile、测试与部署命令。跨 package 变更应在本 monorepo 内一次审查，并保持 AgentScape-facing contract 向后兼容或显式版本化。
