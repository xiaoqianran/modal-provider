# 3D 能力扩展实施计划

更新：2026-09-22。范围：3D Provider、3D Client 及必要的 3D 调用适配。

FastSAM3D++ 已修好，按用户确认作为稳定基线。P0 通用 operation 底座、P1 Mesh/UV/Rebake，
以及 P2 的 P3-SAM 拆分 + X-Part lite 条件补全主链已于 2026-09-22 完成首轮实现、测试、
`main` 环境部署和远端闭环；P2 的客户端部件交互完善与 P3 及以后仍按本计划继续。
2D、World、EmbodiedGen 不纳入本轮实施。

## 1. 当前基线与目标

目标：将现有生成结果变成可继续加工的资产，支持拆分、补全、网格优化、UV、独立贴图、绑定、姿态和动画，并增加正式多视图输入。

| 层 | 仓库现状 | 下一步 |
| --- | --- | --- |
| 图片转 3D | FastSAM3D++、Hunyuan2.1++、Hermite-TRELLIS2++、Pixal3D 四个 Worker | 保留生成入口和 profile，作为后处理输入来源 |
| 通用协议 | ✅ `modal-3d.operations.v1`、命名输入、规范化 options、内容幂等键、多产物结果已落地 | P2+ 复用，不再另建协议 |
| 实际路由 | ✅ generation `WORKERS` 与通用 `ROUTES` 分离；P1 注册 `modal-3d-mesh` | 新能力实测后逐个注册 |
| 执行与产物 | ✅ `run_operation_job()`、类型/摘要/路径校验、临时产物原子发布与缓存已落地 | P2+ 扩展产物角色 |
| 对外 Provider | ✅ 支持 Mesh Artifact、operation options、异步 Job、多产物与下载 | 后续扩展 PartSet/Rig 等类型 |
| 编排 | ✅ SQLite operation jobs、依赖、取消、rebind、恢复与 unknown-submission 防重复 | P2+ 补跨类型 DAG 规则 |
| 文档 | 旧 PLAN 缺 Pixal3D；ARCHITECTURE 的 shared-source 描述滞后于 README | 协议落地时按实际实现同步 |

内部 remesh、UV、纹理生成不计作独立服务。枚举、文档或 mock 测试存在，也不代表功能上线。

## 2. 选型修订

以下为官方资料核对与工程建议，不使用“五星”代替真实验收。每个候选进入实现前，锁定源码和权重版本，并记录代码、权重、依赖的许可信息。

| 能力 | 主线 | 边界及备选 |
| --- | --- | --- |
| 部件拆分 | P3-SAM | Hunyuan3D-Part 的分割组件；标签映射成可选部件，不默认提供可靠自然语言名称 |
| 部件补全 | X-Part | 官方公开为 light version；先验收条件式完整部件生成，不承诺任意缺件或提示词生成 |
| Cleanup / Repair / Decimation | 独立 Mesh Worker，确定性几何算法 | 与 Retopology 分别声明，操作可能改变形状或材质 |
| 四边形重拓扑 | QuadriFlow，Instant Meshes 作对照 | 不承诺任意模型都得到适合动画的关节布线 |
| 自动 UV | xatlas + 独立 rebake | xatlas 负责展开/打包，材质迁移和重烘焙另行实现 |
| 参考图独立贴图 | 优先抽取 Hunyuan3D-Paint 2.1 | 官方已有 Mesh + image 入口，四种生成器产物的兼容性仍需实测 |
| Prompt 贴图 | MVPaint 实验适配 | 官方称 preliminary testing release；多阶段环境，不设为唯一生产后端，不自动等同完整 PBR |
| Rig | SkinTokens / TokenRig | 同一套方案：表示与统一绑骨框架，不重复部署两个服务 |
| A/T Pose / 自定义姿态 | TokenRig + Blender | 先合格人形骨架；需要语义映射、关节限制和蒙皮验证，Blender 不自动解决全部问题 |
| 多视图生成 | Hunyuan3D-2mv | 独立权重/环境/契约，不视为现有 Hunyuan2.1++ 的一个开关 |
| 多图备选 | 原版 TRELLIS `run_multi_image()` | 官方为无需再训练的多图条件算法，不直接认定 Hermite-TRELLIS2++ 支持 |
| 局部编辑 | TEXTure 实验适配 | 有提示词/涂画编辑实现；产品笔刷、mask 投射、未选区保护仍需实现 |
| 动画 | 先动作导入/重定向，再 Puppeteer | Puppeteer 为视频引导路线，不据此承诺任意文本生成动画 |
| 图片直接生成部件 | PartCrafter 实验支线 | 不替代“已有 Mesh 拆分”的 P3-SAM 入口 |
| Part-aware UV | 先按 part_id 分组调用 xatlas | PartUV 后续对照，许可与依赖单独核对 |
| Native Text → 3D | 延后，候选包括原版 TRELLIS-text | 不只 Hunyuan3D-1.0；TRELLIS 已有文本模型，但官方仍建议先图后 3D |
| AI 低模拓扑 | MeshAnything V2 实验支线 | 官方输出上限 1600 faces，不替代高精度资产通用重拓扑 |

依据：[Hunyuan3D-Part](https://github.com/Tencent-Hunyuan/Hunyuan3D-Part)、[SkinTokens / TokenRig](https://github.com/VAST-AI-Research/SkinTokens)、[QuadriFlow](https://github.com/hjwdzh/QuadriFlow)、[Instant Meshes](https://github.com/wjakob/instant-meshes)、[xatlas](https://github.com/jpcy/xatlas)、[Hunyuan3D-Paint 2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)、[MVPaint](https://github.com/3DTopia/MVPaint)、[Hunyuan3D-2mv 官方仓库](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)、[TRELLIS](https://github.com/microsoft/TRELLIS)、[TEXTure](https://github.com/TEXTurePaper/TEXTurePaper)、[Puppeteer](https://github.com/Seed3D/Puppeteer)、[PartCrafter](https://github.com/wgsxm/PartCrafter)、[PartUV 许可文件](https://github.com/EricWang12/PartUV/blob/main/LICENSE)、[MeshAnything V2](https://github.com/buaacyw/MeshAnythingV2)。

## 3. 共同资产契约

现有 `Model.generate_job(input_path, options)` 保持兼容。新操作使用 `Model.run_job(inputs, options)`，接收命名 Artifact 引用，返回带角色的多产物清单；编排和状态仍由 Client/VPS 负责。

必需数据：

- Artifact identity、SHA256、类型、大小、schema version、父资产、operation、模型/权重版本、seed、参数。
- 坐标系、单位、归一化及逆变换；分割、补全、UV、绑骨必须回到同一资产空间。
- Geometry/topology revision，以及顶点/面索引映射的有效范围。
- Material/UV revision、PBR 通道、色彩空间、normal/tangent 约定。
- PartSet：稳定 part_id、源 mesh revision、面/点标签映射、部件路径、局部变换、bbox、可选名称及来源/置信信息。
- P3-SAM → X-Part 的专用条件：特征、点采样、bbox 等按实际接口保存，不能只保留拆出来的 GLB。
- Rig：骨架层级、bind pose、inverse bind matrices、蒙皮权重、顶点版本。
- Pose/Animation：骨架引用、关节变换、时间单位、帧率和 clip 范围。
- TextureMask：资产/UV revision、材质/图集编号、可见面限定、mask 和编辑范围。
- 多视图 manifest：图片引用、视角标签、顺序、裁剪/缩放变换、可选相机参数；按后端校验必需视角。

产物角色包括 primary、preview、editable-source、textures、parts-manifest、quality-report。阶段文件先写临时路径，校验并提交 Volume 后才发布结果清单。

四边面必须交付能保留 polygon 的 OBJ 或 `.blend` 等源文件，另附三角化 GLB 预览。glTF 标准没有 quad primitive，GLB 正常显示不能证明保留四边面。[glTF 标准拓扑示例](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/Models/MeshPrimitiveModes/README.md)

UV 展开可能复制接缝顶点，需保留映射，不能简单要求前后 GLB 顶点数组相同。Texture-only 严格模式必须保护输入几何和约定保留的 UV，会自动 remesh 的路径不能标为严格模式。

## 4. 阶段与验收

### P0：完成通用 operation 与多产物底座

状态：✅ 首轮完成。generation 与 operation 路由已分离；Client 已支持持久化 operation job、
Artifact identity、内容幂等、多产物、依赖/取消/rebind/恢复。Provider 与 Client 全量回归通过，
并新增 operation 专项测试覆盖幂等提交、submission unknown、防重复 spawn、多产物注册与下载完整性。

1. 审查现有 `common.py`、`capabilities.py`、`router.py`、`test_operation_contract.py` 改动，补通用执行器和结果封装。
2. 分离 generation model 与通用 capability 路由集合；当前 `WORKERS = ROUTES` 别名不能让新后处理操作混入生成模型列表。
3. 扩展 3D Client 的 Provider、capability 解析、Job 输入、options 校验、产物列表与下载。
4. 输入引用校验覆盖类型、所有权、摘要、路径边界；公开 API 用 Artifact identity，Worker 用解析后的 Volume 相对路径。
5. 幂等键纳入输入内容摘要、operation/schema/backend revision 和规范化参数，不仅依赖可变路径。
6. 增加步骤依赖、parent job、恢复与取消下游；处理提交结果未知和进程重启，避免重复计算。

验收：旧生成契约兼容测试通过；通用操作能接已有 Mesh 引用并返回多个可下载产物；失败和恢复测试通过。P1 的实际 Worker 再完成远端闭环。

### P1：独立 Mesh + UV + Rebake

状态：✅ 首轮实现并部署。实际采用单一 CPU App `modal-3d-mesh` 承载多个独立 operation，
因为 inspect/cleanup/repair/QuadriFlow/xatlas/rebake 共用 Blender/xatlas 运行时；API 能力仍逐项独立，
没有把这些操作合并成一个强制流水线。

- `inspect_mesh`：面数、组件、边界、非流形、退化面、材质、UV、包围盒。
- `mesh_cleanup` / `mesh_repair`：明确操作开关，保留原资产，不自动删除有意义的小部件。
- `decimate`：目标面数/比例、边界和材质接缝保护，目标不可达时报告。
- `retopology`：QuadriFlow 主后端，Instant Meshes 对照，三角和四边形输出分别声明。
- `uv_unwrap`：xatlas，图集分辨率、padding、分组、像素密度目标与质量报告。
- `texture_bake`：源高模/带纹理模型 → 目标 Mesh/UV，处理投射距离、遮挡、normal 和 PBR 通道。

验收：四种生成器代表产物走通“GLB → 减面或重拓扑 → UV → 重烘焙 → 下载”；源四边面文件回读；记录形状误差、四边面比例、UV 重叠/拉伸、纹理丢失和接缝。

2026-09-22 首轮远端 smoke：真实 GLB 在 Modal `main` 上完成
`inspect_mesh → retopology → uv_unwrap → texture_bake`。最终 revision
`mesh-operations.v1-bpy420-xatlas009-r2` 首次无缓存远端调用约
9.423s / 4.453s / 3.961s / 4.704s；inspect 将 GLB seam 顶点与几何拓扑分开统计，
样例为 1 component / 0 boundary / 0 non-manifold；100/100 retopology faces 为 quad，
UV utilization≈0.7061；rebake 产出 baseColor/roughness/metallic/normal 四张贴图，
质量报告从共享 Volume 回读成功。第二次相同输入/参数四阶段均命中内容缓存（约 0.58–0.87s/阶段）。
这证明 Worker 与共享 Artifact 闭环已上线；“四种生成器代表资产”的完整质量矩阵仍属于 P1 扩展验收，
不能用该 smoke 替代。

### P2：部件拆分与条件补全

状态：✅ 模型主链首轮闭环。已部署独立 `modal-3d-p3sam` 与 `modal-3d-xpart`；
`complete_parts` 直接消费 P3-SAM 的 PartSet/face labels/bbox，不在 X-Part 内重复加载 P3-SAM。
客户端部件合并/排除等交互仍属于后续产品层完善。

建议服务：`modal-3d-p3sam`、`modal-3d-xpart`，分别隔离环境和权重。

- `segment_parts`：Mesh → 标签/特征 → 源面映射 → 独立部件、PartSet、彩色预览。
- 客户端支持部件选择、合并/排除、单部件下载；连通组件与语义部件分开声明。
- `complete_parts`：选定部件 + X-Part 实际需要的源模型条件 → 完整部件与装配预览。
- 保留原坐标变换、切分结果、补全结果及改变区域；新增表面进入 P1/P3 补 UV 和纹理。

验收：“拆分 → 选部件 → 补全 → 原位置装配”无整体坐标漂移；记录分割覆盖率、碎片、补全边界与重叠。light 版不满足要求的类别标为实验或不支持，不宣称完整版效果。

2026-09-22 远端实测：P3-SAM 在 A100-80GB、官方默认 `100k points / 400 prompts`
下将 499,588-face 样例拆为 26 parts，face coverage=1.0；Worker 约 173.89s。
L40S 48GB 在该默认档 OOM，因此生产 profile 使用 A100-80GB。X-Part 使用公开 lite safetensors，
源码固定到 `e96be065`、权重固定到 HF revision `67717446`；CPU prepare 下载约 9GB 必需权重，
GPU 离线加载。选 `part-0000` 的首次 smoke（10 steps / 256）成功：
移除源残片 3,944 faces，生成完整部件 3,184 faces，Worker 约 11.25s，并返回
`completed-part.glb`、`assembly-preview.glb`、`quality-report.json`。
官方默认质量档（50 steps / 512）亦成功，生成 12,900 faces，Worker 约 14.22s、warm wall 约 18.96s。
相同低档请求命中内容缓存；由于当前 cache 位于 GPU class method 内，冷容器仍需先加载 X-Part，
后续如需优化缓存命中 TTFT，应在 GPU Worker 前增加轻量 resolver。

### P3：独立贴图与重生成

状态：✅ Hunyuan3D-Paint texture-only 主后端已远端闭环。2026-09-22 在 L40S 上以
Hunyuan3D-2mv 的 280,368-face GLB + front PNG 实测 `preserve_geometry=true`：
输出仍为 280,368 faces，topology_preserved=true，paint 100.31s / worker total 109.82s，
输出 15.5 MB textured GLB。公开权重改为匿名 CPU provisioning，不再无必要依赖 Modal
`huggingface` Secret。MVPaint 仍作为实验适配线，不阻塞生产贴图主线。

建议服务：`modal-3d-hunyuan-paint`；`modal-3d-mvpaint` 待实验通过。

- 抽取 Paint-only 加载/推理，复用现有安装补丁与权重准备逻辑。
- `texture_generate` / `texture_regenerate` 接收已有 Mesh + 参考图，覆盖完整资产和指定部件。
- 核对 remesh、展开、序列化行为，声明 `preserve_geometry` / `preserve_uv` 能力。
- 无法直接保护拓扑时，验证生成外观后投射回原模型的方案，再提供严格模式。
- 输出材质通道清单；RGB 与 PBR 分开，旧通道保留或默认值明确标识。
- 再评估 MVPaint 的 Mesh + prompt 路线、阶段成本和质量；不扩展本轮 2D 服务范围。

验收：四种生成器产物可只换纹理，几何保护可验证，版本可追溯；新增部件表面完成贴图；PBR 正确绑定/回读。整资产重新生成不计作 Texture-only。

### P4：Rig 与姿态

状态：✅ TokenRig → Blender Pose 远端 E2E 已闭环。2026-09-22 使用 Hunyuan3D-2mv
真实 5.0 MB GLB 验证：TokenRig 在 A100-80GB 输出 28-bone rigged GLB，839,366 个
weighted vertices、0 invalid weights，推理约 35.75s / worker total 52.82s；Pose worker
自动识别 TokenRig 匿名骨架并输出 T-pose，CPU worker total 14.03s。两套 Blender runtime
均在镜像构建期执行 `import bpy` smoke，避免缺失 X11 runtime library 导致容器重启循环。

建议服务：`modal-3d-tokenrig`、`modal-3d-pose`（Blender headless）。

- `rig`：最终网格 → 骨架 + 蒙皮，保留材质/单位/变换，输出 rigged GLB。
- 高面数先测内存与质量，必要时用代理网格绑骨并验证权重迁移。
- 建立骨骼语义映射与标准骨架 profile；先人形，再按类别扩展动物等对象。
- `pose`：A/T 预设、指定关节旋转，再加 IK、关节限制和可选约束。
- 区分 pose snapshot 与修改 rest/bind pose；后者要更新绑定数据。

验收：骨架无环、权重有效且归一、关键关节变形可用、材质保留；姿态在目标查看器重现；不支持的骨架类别有明确错误。

### P5：正式多视图转 3D

建议服务：`modal-3d-hunyuan2mv`。P0 后可独立实施，默认排在资产加工主线之后。

- `multiview_to_3d`：按官方后端接同一物体视图集合，输出一个资产。
- 校验必需视角、重复图、主体、比例、姿态一致性；不承诺任意相册自动摄影测量。
- 规范化保留多视图关系，不逐图任意拉伸；相机数据按后端要求传递。
- 独立锁环境和权重，几何产物交 P3；原版 TRELLIS 多图作对照，不直接认定 TRELLIS.2 兼容。

验收：多图生成单个可追溯资产；与同物体单图基线比较侧面/背面一致性；记录实际使用视角，不一致输入明确失败或提示降级。

### P6：局部纹理编辑

建议服务：`modal-3d-texture-edit`，TEXTure 为初始实验后端。

- 表面笔刷拾取 → face/UV 映射 → 材质 mask，处理接缝、多材质和遮挡，避免涂到背面。
- `texture_edit` 接收 textured asset、mask、prompt、参数，锁定资产/UV revision。
- 实现范围内编辑、边缘羽化、未选区保护、多视角一致性、烘焙和版本撤销。
- 先 baseColor；roughness/metallic/normal 保留或编辑分别声明。
- 3D Paintbrush 留为效果对照，其具体可运行路径核验后再排实现任务。

验收：笔刷范围与变化一致，边缘缓冲区外纹理保持约定不变；几何不变，多视角无明显接缝，撤销可恢复原资产。

### P7：动画与研究支线

主线：`animate` 先支持动作 clip 导入、重定向和 GLB 导出，再验证 Puppeteer 视频引导。需要视频输入规范、目标骨架映射、时间轴，以及漂移、脚滑、穿模评测。

验收：产物有可播放 animation tracks，帧率/时长正确，蒙皮和材质兼容目标查看器。仅输出渲染视频不计作可编辑动画资产。

研究支线：PartCrafter、PartUV、MeshAnything V2、TRELLIS-text。先固定样本实验，再决定正式接入，不阻塞主线。

## 5. 顺序与依赖

默认工程顺序：P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7。首个交付目标为 P0 + P1，验证平台能可靠加工已有 3D 资产。

资产流水线按需组合，不强制所有模型走全部步骤：

```text
单图生成 / 多视图生成 / 上传已有模型
                 ↓
            原始资产版本
                 ↓
       [部件拆分 → 条件补全]
                 ↓
  Cleanup → [Decimation 或 Retopology]
                 ↓
                 UV
                 ↓
      Rebake 或 Texture Generation
                 ↓
         [局部 Texture Edit]
                 ↓
       [Rig → Pose / Animation]
                 ↓
     源文件 + 预览 GLB + 元数据
```

拓扑变更使 face/vertex 映射、UV 或蒙皮失效时，标记并重建相关下游。已绑骨资产再 remesh 不能静默沿用旧权重。刚体道具跳过 Rig；已有合格 UV/材质可跳过相应步骤。

## 6. 运行约束

- 每个模型家族独立 Modal App/Image/权重 Volume；新模型按实测选择 GPU，不预设全部适合 L40S。
- GPU 保持 `max_containers=1`、`min_containers=0`，不开输入并发，一次一个 Job，溢出排队。
- 权重由 CPU 函数下载、锁版、校验、持久化；GPU 挂载本地权重，`@modal.enter()` 加载一次。
- Mesh/UV/Blender 按实际需求选择 CPU/GPU。真实 CPU 几何计算允许，纯转发 CPU gateway 不引入。
- Client/VPS 负责路由、编排、重试/恢复；Worker 直接消费共享 Artifact，避免产物反复下载上传。
- Volume 写入、commit/reload、不可变路径和完成标记纳入跨 Worker 测试。
- 批量仍为多个 Job + 有界队列、逐项结果和失败重试；tensor batch 不纳入优先工作，也不承诺同模型并行推理。
- UI 按实际可用 capability 开放，规划按钮和演示数据不能当上线证据。

## 7. 验收与成本记录

固定小型资产集覆盖四个生成器、人形/动物、硬表面、薄片、遮挡部件、多材质、高面数和异常网格；记录源摘要、授权来源、版本及参数。

每个服务依次达到：官方样例复现 → 契约/失败测试 → Modal 单 Job → 跨服务闭环 → 质量/恢复/成本验收 → capability 可用。

沿用原 benchmark 要求，分别记录：Image build；CPU 下载时间/字节；冷调用总时间；模型加载；首次推理；多次 warm 推理；峰值 allocated/reserved VRAM；产物大小；每成功产物估算计算成本。CPU Worker 另记 CPU 时间和内存。流水线另计排队、传输、计算及总成本。

不得用采样阶段微基准代替端到端耗时。先实测再设时间/成本门槛；几何、UV、分割、变形和纹理保护阈值按资产集和 profile 固化，不能只验证文件非空。

完成定义：稳定 I/O、真实可下载产物、质量报告、版本可追溯、失败/重试/取消恢复、部署/权重说明、调用示例。未满足保持 planned / experimental。

## 8. 第一批具体工作

1. 补完 P0 协议草稿、通用 runner、多产物 manifest 与兼容性审查。
2. 3D Client 接 Mesh Artifact、operation options、多结果和共享产物引用。
3. 首个真实 `inspect_mesh` / `decimate` Worker 跑通“生成 GLB → 新 Job → 加工产物”。
4. 增加 QuadriFlow、xatlas、rebake，交付独立网格与 UV 闭环。
5. 再接 P3-SAM / X-Part，复用输入、任务、版本和产物机制。

本次规划核对没有重新运行模型推理、部署新服务或认证候选的生产成熟度。
