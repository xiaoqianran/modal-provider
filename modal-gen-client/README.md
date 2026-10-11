# modal-gen-client

AgentScape 的本地 Provider Hub：统一身份、能力、任务和产物，通过 Python 插件调用 2D / 3D / World Provider。

## 从哪里开始读

```text
modal_gen/
├── app.py                    # FastAPI 入口、服务组装
├── generation/
│   ├── service.py            # 统一组装 Capability / Job / Artifact 服务
│   ├── capabilities.py       # 能力发现和快照
│   ├── jobs.py               # 提交、幂等、状态追踪、取消
│   └── artifacts.py          # 产物登记、输入解析、校验和下载
├── providers/
│   ├── protocol.py           # Provider 契约和数据类型
│   └── loader.py             # Python entry point 加载和协议适配
├── gateway/
│   ├── api.py                # HTTP 路由、请求解析、CORS
│   └── sessions.py           # 配对、身份、权限和访问范围
├── deployment/
│   ├── service.py            # 云端部署、状态、Secret/权重前置检查、任务
│   ├── weights.py            # 缺失权重准备及校验
│   ├── manifests.py          # 从外部 Provider 读取部署清单
│   └── cli.py                # BAT/命令行共用的部署入口
├── storage.py                # SQLite 持久化
├── identity.py               # 请求哈希和幂等标识
├── errors.py
├── credentials.py            # 本机凭据保存和恢复
├── constants.py
├── paths.py
├── launcher.py               # Connector + UI 单进程启动
├── server.py                 # Uvicorn 命令入口
├── studio/                   # 项目、资产和持久化创作流程
└── ui/                       # 本地控制台和演示模式
```

阅读顺序：`app.py → gateway/api.py → generation/jobs.py → providers/protocol.py`。
查结果时看 `generation/artifacts.py`，查可用操作时看 `generation/capabilities.py`。

Gateway 验证身份和权限，再调用生成服务。生成模块通过 Provider 接口提交和追踪任务，使用 Store 保存统一身份与执行状态。
`generation/service.py` 集中连接这些服务，JobService 保持提交规则与幂等逻辑的唯一归属。
Studio 共用这些生成服务，并拥有自己的持久化创作流程队列。

具体模型、参数、conditioning、Modal SDK 调用、重试与恢复属于外部 Provider 包：
`modal_2d.client`、`modal_3d.client`、`modal_world`。
通过 `modal_gen.providers` entry-point group 加载；新增 Provider 无需在 Hub 添加具体模型实现。

## 六个概念

| 问题 | 概念 | 代码位置 |
| --- | --- | --- |
| 谁可以发起请求？ | Session / Gateway | gateway/ |
| 能执行什么任务？ | Capability | generation/capabilities.py |
| 使用哪个生成服务？ | Provider | providers/ 与外部 Provider 包 |
| 如何提交和追踪任务？ | Job | generation/jobs.py |
| 如何获取生成结果？ | Artifact | generation/artifacts.py |
| 如何管理云端模型？ | Deployment | deployment/ + UI + BAT |

Deployment 是独立于 Generation 的本地管理能力。Provider Hub 前端和 BAT 都复用
`modal_gen.deployment.service.DeploymentService`；部署会检查必需 Secrets，
验证模型权重和前置资源并在需要时准备权重，失败时停止部署。
Capability 负责声明生成能力；Deployment 负责云端 App 的版本、权重和就绪状态。

### Session / Gateway：允许谁调用

```text
AgentScape 请求生图
        │
        ▼
     Gateway
        │
        ├── 没有权限 → 拒绝
        │
        └── 有权限 → 调用生成服务
```

Session 绑定 client identity、Origin、scope、expiry 和 Capability snapshot。
本地管理接口使用控制 token；Connector 接口使用配对后的会话权限。

### Capability：能做什么

```text
       Capability
           │
           ├── 模型 A ── Text → Image
           ├── 模型 B ── Image → 3D
           └── 模型 C ── Image → World
```

这是能力示例。一个 Provider 可以暴露多个模型和操作；具体输入、输出和参数以快照中的 schema 为准。

### Provider：由谁生成

```text
          modal_gen
              │
        选择 Provider
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
 modal-2D  modal-3D  modal-world
    │         │         │
    ▼         ▼         ▼
   图片     3D 模型    世界场景
```

这里的三个 Provider 是本地安装的 Python 包，其客户端通过 Modal SDK 调用云端 GPU Runtime。
2D / 3D 正常生成链直接调用 Worker，不经过额外远端 CPU gateway。

标准生成接口：`descriptor()`、`submit()`、`get()`、`cancel()`、`iter_artifact()`。

### Job：如何追踪

```text
AgentScape：生成 3D 模型
             │
             ▼
       Job #1001
             │
          accepted
             │
          running
             │
       ┌─────┴─────┐
       ▼           ▼
   succeeded     failed
```

示意图省略了 queued、cancel_requested、cancelled、connection_required、
submission_unknown、expired 等状态。JobService 处理统一状态协调、归属和幂等；
Provider 拥有私有执行任务与恢复逻辑。

### Artifact：如何获取结果

```text
Job #1001 生成完成
        │
        ▼
     Artifact
        ├── 文件类型：GLB
        ├── 文件标识：Artifact ID
        ├── 所属任务：Job #1001
        ├── 完整性：大小 / SHA-256
        └── 获取方式：Connector 下载接口
```

Modal Volume 路径和 Provider 私有 ID 留在 Provider 内部。
同一任务支持多个同 role 产物。Artifact 可以被后续任务引用：

```text
Job #1001：生成猫的图片
    └── Artifact #A：cat.png
                │
                ▼
Job #1002：把图片转换为 3D
    ├── 输入：Artifact #A
    └── 输出：Artifact #B：cat.glb
```

ArtifactService 处理归属校验、文件完整性和跨 Provider 输入解析。

### Deployment：本地前端和命令行共同管理云端模型

```text
    本地 Provider Hub UI            deploy-modal.bat / delete-modal.bat
              │                                   │
              ▼                                   ▼
     /v1/deployments/*              modal_gen.deployment.cli
              │                                   │
              └────────────────┬──────────────────┘
                               ▼
                         DeploymentService
                         ├── Secret 预检
                         ├── 权重 / 前置资源检查
                         ├── 目标部署与状态
                         └── 指定 App 停止
                               │
                               ▼
                         Modal 云端 App
```

部署目标仍从各 Provider 的 deployment manifest 读取，限制为明确声明的 App。
正式部署复用 Modal SDK 与既有 WeightProvisioner；停止指定 App 通过受控 Modal CLI。
前端提交后得到 Deployment Job ID，可查询进度；这些管理任务状态当前保存在本地进程内，
服务重启后不会保留，云端已执行的操作也不会被自动回滚。

## 启动与部署命令

Windows PowerShell，在本目录运行：

```powershell
# 启动本地 Connector + UI，后台运行
.\start.bat
# 打开 http://127.0.0.1:48124/

# 停止 start.bat 启动的本地进程
.\stop.bat

# 查看部署计划，不访问云端
.\deploy-modal.bat --provider modal-2d --dry-run

# 部署全部 Runtime，或选择 Provider / 单个 App
.\deploy-modal.bat
.\deploy-modal.bat --provider modal-3d
.\deploy-modal.bat --provider modal-2d --app modal-2d-sana-sprint

# 查看停止计划，再显式停止指定云端 App
.\delete-modal.bat --app modal-2d-sana-sprint --dry-run
.\delete-modal.bat --app modal-2d-sana-sprint --yes

# 停止某个 Provider 的全部 manifest-listed Apps
.\delete-modal.bat --provider modal-3d --yes
```

`delete-modal.bat` 停止部署和运行容器，保留 Volume、模型权重、生成文件和 Secrets。
它要求显式选择 `--provider` 或 `--app`；实际停止还需要 `--yes`。
默认不包含 manifest 的可选 utilities，也不包含 Studio App。
`stop.bat` 使用 PID、启动时间、执行路径和启动命令验证进程归属，不按端口或进程名批量结束进程。
本地日志和 PID 记录位于 `.run/`。

云端命令优先复用 UI 保存的本机 `.secrets/modal.json` 凭据，否则使用本机 Modal CLI profile。
支持 `--env <环境>`，也读取 `MODAL_ENVIRONMENT`。

首次部署前，在仓库根目录配置 `.env` 中的 HF_TOKEN，再执行：

```powershell
.\modal_provider-create_secrets.bat
.\modal_provider-pull_models-ALL.bat
.\modal-gen-client\deploy-modal.bat
```

也可以使用各 Provider 自己的模型拉取脚本。模型下载和 World 构建前置资源以各 Provider README 为准。
部署命令只部署 manifest 中的 App；可以按 Provider 的 manifest 自动准备和校验权重、
前置资源，但不会自动创建 Hugging Face Secrets，首次部署前仍需要配置。

跨平台前台启动仍支持 `uv run modal-gen`。
独立入口保留 `modal-gen-agent`、`modal-gen-ui` 和 `modal-studio`。

## Connector API

```text
POST   /connector/v1/session
DELETE /connector/v1/session
GET    /connector/v1/capabilities
GET    /connector/v1/jobs
POST   /connector/v1/jobs
GET    /connector/v1/jobs/{id}
POST   /connector/v1/jobs/{id}/cancel
POST   /connector/v1/artifacts
GET    /connector/v1/artifacts
GET    /connector/v1/artifacts/{id}
```

生成、配对、连接和产物接口保持原协议。本地管理 API：

```text
GET    /v1/deployments
GET    /v1/deployments/jobs
GET    /v1/deployments/jobs/{id}
POST   /v1/deployments/deploy
POST   /v1/deployments/stop
```

这些接口仅允许本机访问，并需要 `X-Modal-Gen-Session` 管理令牌。
停止请求额外要求 `confirm: true`。Hugging Face Secrets 使用仓库根目录
`modal_provider-create_secrets.bat` 配置。

内部 Python 导入路径迁移为 `modal_gen.generation.*` 和 `modal_gen.gateway.sessions`。
`modal_gen.app:app`、`build_runtime()` 和 `create_app()` 入口保留。

## 本地控制台

控制台提供 Provider 连接、Capability 展示、配对批准、生成、任务追踪、取消、PNG 预览及 GLB 下载。
Provider Hub 中可以针对每个 App 部署、停止、刷新状态并跟踪 Deployment Job。
因为本地控制台默认可以监听全部网络接口，部署管理 API 默认仅允许从本机的
`localhost` / `127.0.0.1` 打开 UI 调用；通过远端端口转发访问时，
云端部署按钮将被拒绝，以免远程匿名请求引发费用或停机。

Modal credentials 验证后保存在本机 `.secrets/modal.json`，下次启动自动恢复；
不会写入 Connector SQLite。断开连接保留已保存凭据。

默认配置：

```text
MODAL_GEN_HOST=0.0.0.0
MODAL_GEN_PORT=48123
MODAL_GEN_UI_HOST=0.0.0.0
MODAL_GEN_UI_PORT=48124
MODAL_GEN_ALLOW_ANY_ORIGIN=1
```

本地控制 token 默认 `wangran`，通过 `MODAL_GEN_AGENT_TOKEN` 覆盖。
需要收紧访问时配置监听地址、Origin 和控制 token。

演示模式：设置 `MODAL_GEN_UI_DEMO=1` 后运行 `uv run modal-gen-ui`。

## 开发验证

```powershell
uv sync --dev
uv run ruff check modal_gen tests scripts
uv run pytest -q
npm ci
npm run lint
```
