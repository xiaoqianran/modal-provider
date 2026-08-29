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
├─ modal-world/           world generation/reconstruction Provider
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
- World generation/reconstruction、HY-World 2.0 orchestration and resumable world artifacts；
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

本 monorepo 是集成主仓，同时维护以下独立 package 仓库：

- `modal-2D` (`main`) → https://github.com/xiaoqianran/modal-2D
- `modal-2D-client` (`main`) → https://github.com/xiaoqianran/modal-2D-client
- `modal-3D` (`master`) → https://github.com/xiaoqianran/modal-3D
- `modal-3D-client` (`main`) → https://github.com/xiaoqianran/modal-3D-client
- `modal-gen-client` (`main`) → https://github.com/xiaoqianran/modal-gen-client
- `modal-EmbodiedGen` (`master`) → https://github.com/xiaoqianran/modal-EmbodiedGen
- `modal-build` (`master`) → https://github.com/xiaoqianran/modal-build
- `modal-world` (`master`) → https://github.com/xiaoqianran/modal-world

### 同步前必须检查

不要依赖 README 中的固定 commit SHA 判断同步状态。每次修改、提交或推送前，先执行只读检查：

```bash
./scripts/check-standalone-sync.sh
```

只检查本次涉及的 package：

```bash
./scripts/check-standalone-sync.sh modal-2D modal-2D-client modal-gen-client
```

输出含义：

- `SYNC`：忽略独立 `.github` 与本地缓存后，两边源码树一致。
- `DRIFT`：两边源码树不同，**必须停止自动同步并审查差异**。
- `ERROR`：检查本身失败，不得继续声称仓库已同步。

### 强制同步规则

1. `modal-provider` 是最终集成主仓，但**不能假设它永远比 standalone 新**。独立仓库可能存在尚未合回 monorepo 的有效开发。
2. 发现 `DRIFT` 时，先检查 standalone 最新历史和逐文件差异，判断哪一侧包含更新实现；不得直接覆盖任何一侧。
3. 如果 standalone 含有 monorepo 不存在的新代码，必须先把这些变化审查、测试并合回 monorepo，再决定后续同步。
4. 只有确认 monorepo 当前 package 快照是本次期望真值后，才允许同步到 standalone。
5. 禁止在未完成第 2～4 步时执行机械 `rsync --delete`、目录覆盖、force push 或 history rewrite。
6. standalone 必须保留自己的 `.git`、`.github`、目标分支和历史；正常同步使用普通 commit + fast-forward push。
7. 推送前必须在**最新远端基线的干净 worktree**运行该 package 的 Ruff/tests/build/live smoke（按项目实际提供的检查项）。不要用旧分支、脏工作区或缓存结果代表远端健康状态。
8. 推送后再次运行 `check-standalone-sync.sh <package...>`，并核对 monorepo `origin` HEAD、standalone HEAD 和 working tree 状态。
9. 任一 push 返回非 0，即使日志看起来可能已推上去，也必须重新 fetch/ls-remote 验证后才能报告成功。

推荐流程：

```text
fetch 最新远端
    ↓
检查 working tree
    ↓
check-standalone-sync.sh
    ↓
DRIFT ? ── yes → 审查 standalone-only / monorepo-only changes → 合并正确实现
    │
    no
    ↓
在最新干净基线测试
    ↓
commit + push monorepo
    ↓
同步对应 standalone（如需要）
    ↓
再次检查源码树 + remote HEAD
```

`modal-build` 是构建工具边界，不是运行时 Provider；EmbodiedGen production code 只属于 `modal-EmbodiedGen`。Kaggle Provider 与独立 `modal-lab` 不属于本 monorepo 的目标运行时架构。

## Development

进入具体 package 后使用它自己的 README、lockfile、测试与部署命令。跨 package 变更应在本 monorepo 内一次审查，并保持 AgentScape-facing contract 向后兼容或显式版本化。
