# Modal Provider

> AgentScape 的生成与资产处理 Provider 集成主仓（Monorepo）。
>
> **状态基线：2026-10-15（PC1 本地检出）**。本 README 将“已有代码”“历史实测”和“当前通过验证”分开记录；不将历史 GPU smoke 或存在的 Worker 文件等同于当前生产稳定。

## 项目定位与结构

```text
AgentScape（意图、资产语义、场景和世界状态）
    │ Capability / Job / Artifact 契约
    ▼
modal-provider
├── modal-gen-client/   本地 Provider Hub：会话、能力、任务、产物、Studio 与独立部署管理
├── modal-2D/           2D 生成 Provider，含 modal_2d.client 适配层
├── modal-3D/           3D 生成及资产处理 Provider，含 modal_3d.client 适配层
├── modal-world/        HY-World 2.0 世界生成/重建 Provider
├── modal-fire3d/       独立 FIRE3D 重建运行时和适配层
├── modal-EmbodiedGen/  EmbodiedGen fork 及其专属 Modal 集成
├── modal-build/        通用 CUDA/PyTorch 构建与可复现产物
├── 3daistudio/         独立 Web 前端（功能页面不代表全部 API 已接通）
├── templates/provider/  Provider Standard v1 参考实现
└── scripts/            架构检查与独立仓库安全同步脚本
```

**架构原则：统一源码管理，保留各包运行时与部署边界。** 2D/3D Client 已迁入对应 Provider 包；原独立 Client 仓库仅用于历史回溯，不能与新插件同时加载。ComfyUI 的 HY-World 试验仓不是正式 World Provider。

项目设计规范：[Provider Standard v1](docs/standards/README.md)；各子包的具体运行方法、参数和模型清单以子包 README/Registry/Manifest 为准。

## 能力清单与实际状态

| 领域 | 当前已具备的代码与接口 | 验证程度 |
| --- | --- | --- |
| Provider Hub | 身份/配对、权限、能力快照、Job、Artifact、持久化、Studio；部署服务与生成执行职责分离 | 代码存在；2026-10-15 集成测试有失败 |
| 2D | 文生图及 Provider/Client 接口 | 历史 Modal 实测成功；本次未复验 |
| 3D 生成 | FastSAM3D++、Hunyuan2.1++、Pixal3D、Hermite-TRELLIS2++ | Worker/接口存在；历史 PNG→GLB 实测成功；本次未逐个复验 |
| 网格处理 | 检查、清理、修复、减面、QuadriFlow 重拓扑 | 已注册实现，未完成本轮全项 GPU/CPU 端到端复验 |
| 部件处理 | P3-SAM 分割、X-Part 补全、保留/排除部件 | 已有 Worker 与操作定义，未完成本轮全链验收 |
| 材质 | xatlas UV 展开、PBR 烘焙、Hunyuan3D-Paint 参考纹理生成 | 已注册实现，未完成本轮全链验收 |
| 多视角与角色 | Hunyuan3D-2mv、TokenRig 骨骼绑定、Blender 预设 Pose | 已注册实现，未完成本轮全链验收 |
| World | HY-World 2.0 重建/扩展、WorldNav、WorldStereo、3DGS；独立 FIRE3D | 历史单卡 RTX PRO 6000 HY-World 验证有记录；不等于长期生产稳定 |
| EmbodiedGen / 构建 | 独立 fork、构建配方及测试 | 工程集成存在；未完成本轮统一端到端验证 |
| 3DAI Studio | Dashboard、Image-to-3D、Operations、Studio 等前端模块 | 页面代码存在；未验证完整后台工作流或本轮构建 |

### 明确尚未实现的 3D 操作

`modal-3D/modal_3d/operations/registry.py` 的 `PLANNED_SPECS` 保留了以下操作 ID，**仅用于规划，不能当作可执行能力**：

- `mesh_optimize`：智能网格优化。
- `uv_optimize`：高级 UV 优化。
- `texture_edit`：局部纹理编辑（不同于已注册的 `texture_generate`）。
- `animation_generate`：骨骼动画生成（不同于已注册的 `pose_apply`）。

### 当前已知集成问题与验收边界（2026-10-15）

- PC1 本地 `modal-gen-client` 的 `pytest -q` **退出码为 1**；多项用例失败，不能认定 CI 全绿。
- 可复现的失败链：`CapabilityRegistry.snapshot() → Modal3DProvider.descriptor() → connector_capabilities() → input_mimes_for("mesh_optimize") → spec_for()` 抛出 `ValueError: operation not implemented: mesh_optimize`。回退的 unavailable descriptor 也触发同一路径。能力枚举必须排除尚未实现操作，或者保证规划项无法进入可执行 Capability。
- PC1 已通过 `scripts/check-provider-architecture.py`、`check-legacy-providers.py`、`check-runtime-architecture.py` 三项架构检查。
- **尚未进行本轮** 2D/3D/World 全部测试、前端构建、CI 远端确认、Modal GPU 实际运行、跨前端/AgentScape 的端到端验收。禁止据此声称已经生产就绪。

后续优先级：①修复能力枚举与集成测试；②执行各包 CI 等价检查；③云端真实 2D→3D→资产处理/World smoke；④完成前端和 AgentScape 的任务/产物闭环与恢复验证。

## 历史验证记录（不代表当前版本验收）

2026-08-31 的旧版本曾在 Modal 成功执行文生图（1024×1024 PNG）、图片转 GLB，以及 2D→3D；具体历史测试数量与耗时不能直接套用于当前版本。详见子包测试、历史提交及运行记录。

`modal-world/VERIFIED_RUN.md` 另记录单卡 RTX PRO 6000 96GB 的 HY-World 2.0 分阶段验证：WorldStereo 9/9、GS 数据准备 283 视角、Stage 5 100-step smoke、checkpoint/PLY/SPZ 产物。上述属于历史案例级验证，不能替代当前多任务长期稳定性测试。

## 部署与运行职责

- `modal-gen-client` 的**生成请求链**不应在每次任务提交时自动部署或自动补权重。
- 但 `modal-gen-client/modal_gen/deployment/` **确实存在独立的 DeploymentService**，由本地管理 UI、BAT/CLI 复用，负责 Secret、权重和部署前置校验。不能再描述为“整个 modal-gen-client 不管理部署”。
- 2D/3D/World Provider 分别承担自己的模型、GPU Worker、conditioning、运行时状态与产物生成；Modal App 不必共享同一进程。
- 3D 部署必须先在 Modal `main` 环境创建名为 `huggingface` 的 Secret，字段为 `HF_TOKEN`，并满足目标模型访问权限；缺失时应中止部署。敏感凭据不可写入源码。
- 不要将本地页面启动成功、单模型部署成功、测试断言通过混为一谈。

## 开发与验证入口

```powershell
# 在仓库根目录：架构检查
python scripts/check-provider-architecture.py
python scripts/check-legacy-providers.py
python scripts/check-runtime-architecture.py

# 在 modal-gen-client 子目录，使用已同步的本地虚拟环境
python -m pytest -q

# 3daistudio 子目录（安装依赖后）
npm run build
npm test
```

仓库的 `.github/workflows/ci.yml` 还配置了架构、前端、Hub、2D、3D、World、FIRE3D、EmbodiedGen 与构建流程。**配置存在不代表某次远端 CI 成功**；实际发布前以对应提交的 CI 结果和真实 smoke 为准。
## 职责边界

`modal-provider` owns：

- Modal credential/runtime integration；
- Provider-private Job / Artifact execution facts；
- GPU/model lifecycle；
- Reference Sidecar restore/cache；
- local pairing/session/security gateway 与独立 deployment management；
- 2D/3D input conditioning and model execution；
- World generation/reconstruction、HY-World 2.0 orchestration and resumable world artifacts；
- EmbodiedGen fork 与其 `modal/` 下的 EmbodiedGen-specific build/runtime/control plane；
- FastSAM3D、Hunyuan3D、TRELLIS、Pixal3D、BiRefNet、HY-World 等通用 CUDA/PyTorch build artifacts。

`modal-provider` does **not** own：

- Agent/Human intent or workflow truth；
- AgentScape Asset semantic truth；
- World desired/compiled/live state；
- Runtime verification authority outside Provider artifact validity。

## 子包独立性

合并仓库不意味着把运行时边界揉成一个进程。每个 package 仍可以保留：

- 独立 `pyproject.toml` / lockfile / Node package；
- 独立测试矩阵；
- 独立 Modal app identity；
- 独立 GPU image / autoscaling / deployment lifecycle；
- 独立 failure/retry owner。

原则是：**repository consolidation, runtime boundary preservation**。

### Python 锁文件来源策略

仓库中所有 `uv.lock` 必须使用官方 PyPI registry：

```text
https://pypi.org/simple
```

锁文件中的 wheel / sdist artifact URL 必须保持为官方 `files.pythonhosted.org` 地址。不要把本机 `uv`、pip 或系统级镜像配置（例如腾讯云、阿里云等）写回 lockfile；这类本地镜像会造成无意义的大规模 diff，并可能使 GitHub CI / release 校验失败。需要本机加速时，只通过本地环境配置使用镜像，不改变已提交的 lockfile source。

## EmbodiedGen 集成

`modal-EmbodiedGen` 保持完整的 EmbodiedGen fork 形态，当前目标为 EmbodiedGen v2.1.0。EmbodiedGen 自身源码、apps、tests 与 thirdparty submodule 声明留在该目录；所有 **只与 EmbodiedGen 有关** 的 Modal build/runtime/patch/tests 收敛在 `modal-EmbodiedGen/modal/`。

通用构建能力属于独立的 `modal-build/`：FastSAM3D、Hunyuan3D、Hermit/TRELLIS2、Pixal3D、trellis.cpp、BiRefNet、HY-World 等 build recipes 与环境 manifest 不再混入 `modal-EmbodiedGen`。`modal-build` 也不再保存 EmbodiedGen production code 的副本。

## 独立子仓库与同步

本 monorepo 是集成主仓，同时维护以下独立 package 仓库：

- `modal-2D` (`main`) → https://github.com/xiaoqianran/modal-2D
- `modal-2D-client` (`main`) → https://github.com/xiaoqianran/modal-2D-client （历史独立仓库；迁移期间冻结，不再作为活动 2D Client 发布来源）
- `modal-3D` (`master`) → https://github.com/xiaoqianran/modal-3D
- `modal-3D-client` (`main`) → https://github.com/xiaoqianran/modal-3D-client （历史独立仓库；迁移期间冻结）
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
./scripts/check-standalone-sync.sh modal-2D modal-3D modal-gen-client
```

安全同步必须使用仓库内置脚本，而不是整目录覆盖：

```bash
# 默认只做 dry-run，不写远端
./scripts/sync-standalone.sh modal-build
./scripts/sync-standalone.sh modal-world

# 审查输出后才允许普通 fast-forward push
./scripts/sync-standalone.sh modal-world --push
```

该脚本有以下硬约束：

- 源 package 必须是已提交的干净状态；
- 真正 push 前会刷新 `origin/main`，并要求待发布 package tree 与最新 canonical package tree 完全一致；feature/local-only 内容不能发布到 standalone；
- 同步固定到开始时的 committed `HEAD` / package tree；同步过程中若该 package 被并发修改或提交，push 前会直接中止并要求重跑；
- `.git` 与 `.github` 永远不参与复制，standalone 自己的 CI / Release workflow 保留；
- 发现 standalone-only 普通文件时默认拒绝删除，必须审查后显式传 `--allow-delete`；
- 只执行普通 branch push，不使用 `--force`、不推 tag；
- 不调用 `gh release`，因此不会创建、覆盖或删除 GitHub Release / Release assets；
- push 后必须重新读取远端 branch HEAD 并与本地 commit 对齐。

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

## 开发约定

进入具体 package 后使用它自己的 README、lockfile、测试与部署命令。跨 package 变更应在本 monorepo 内一次审查，并保持 AgentScape-facing contract 向后兼容或显式版本化。
