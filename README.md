# modal-provider

`modal-provider` 是 AgentScape 的 **Modal Provider monorepo**。过去分散在多个独立仓库中的 Gateway、2D/3D Provider、Reference Sidecar、EmbodiedGen fork 与可复现 CUDA build tooling 已统一收敛到这里。

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
├─ modal-EmbodiedGen/     EmbodiedGen fork；其 modal/ 仅负责 EmbodiedGen 的 Modal 集成
└─ modal-build/           通用 CUDA/PyTorch 可复现构建与 release artifacts
```

这些目录是 **monorepo 内部 package / integration / build boundary**。其中 `modal-2D-client`、`modal-3D-client`、`modal-gen-client` 同时维护独立 Git 仓库，用于单独查看、CI、发布和分发；代码真值仍以本 monorepo 为准。

## Ownership

`modal-provider` owns：

- Modal credential/runtime integration；
- Provider-private Job / Artifact execution facts；
- GPU/model lifecycle；
- Reference Sidecar restore/cache；
- local pairing/session/security gateway；
- 2D/3D input conditioning and model execution；
- EmbodiedGen fork 与其 `modal/` 下的 EmbodiedGen-specific build/runtime/control plane；
- FastSAM3D、Hunyuan3D、TRELLIS、Pixal3D、BiRefNet、HY-World 等通用 CUDA/PyTorch build artifacts。

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

`modal-EmbodiedGen` 保持完整的 EmbodiedGen fork 形态，当前目标为 EmbodiedGen v2.1.0。EmbodiedGen 自身源码、apps、tests 与 thirdparty submodule 声明留在该目录；所有 **只与 EmbodiedGen 有关** 的 Modal build/runtime/patch/tests 收敛在 `modal-EmbodiedGen/modal/`。

通用构建能力属于独立的 `modal-build/`：FastSAM3D、Hunyuan3D、Hermit/TRELLIS2、Pixal3D、trellis.cpp、BiRefNet、HY-World 等 build recipes 与环境 manifest 不再混入 `modal-EmbodiedGen`。`modal-build` 也不再保存 EmbodiedGen production code 的副本。

## Standalone package repositories

本 monorepo 是代码真值源，同时维护以下独立 package 仓库：

- `modal-2D` → https://github.com/xiaoqianran/modal-2D
- `modal-2D-client` → https://github.com/xiaoqianran/modal-2D-client
- `modal-3D` → https://github.com/xiaoqianran/modal-3D
- `modal-3D-client` → https://github.com/xiaoqianran/modal-3D-client
- `modal-gen-client` → https://github.com/xiaoqianran/modal-gen-client
- `modal-EmbodiedGen` → https://github.com/xiaoqianran/modal-EmbodiedGen
- `modal-build` → https://github.com/xiaoqianran/modal-build

当前同步基线：

- `modal-2D` (`main`): `f1ebf6222c5299ad497ca53a3e415ddbfade1d0f`；
- `modal-2D-client` (`main`): `afc52f27e0064e99a37fa34304ba447c20378e7b`；
- `modal-3D` (`master`): `7cb8097410a5357f38ddfcfc1c5639ec69e36f2a`；
- `modal-3D-client` (`main`): `986dc6cb5769787895437dcdbf919fe9adceac78`；
- `modal-gen-client` (`main`): `6c777c4e68c65879936db654663c65e3c3543f89`；
- `modal-EmbodiedGen` (`master`): `b75e7309bba6e290ae1157e8ee3a59d4ad139e61`（EmbodiedGen v2.1.0）；
- `modal-build` (`master`): `1dd19dd55c62b1a8d7eb01dcefb69fc37e135da8`。该版本已移除 `integrations/embodiedgen` 历史备份；EmbodiedGen production code 的唯一真值是 `modal-EmbodiedGen/modal/`。

以上 standalone 源码树（忽略各仓库独立 `.github` 与本地缓存）均与本 monorepo 对应目录逐文件一致。

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

`modal-build` 作为构建工具边界存在，不是运行时 Provider；EmbodiedGen production code 则只属于 `modal-EmbodiedGen`。Kaggle Provider 与独立 `modal-lab` 不属于本 monorepo 的目标运行时架构。

## Development

进入具体 package 后使用它自己的 README、lockfile、测试与部署命令。跨 package 变更应在本 monorepo 内一次审查，并保持 AgentScape-facing contract 向后兼容或显式版本化。
