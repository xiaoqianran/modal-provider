# FIRE3D 源码审查与拆分结论

审查日期：2026-09-12。FIRE3D 固定版本：
`2368dd2f3909120cf90bbf8a17807abe9c41e600`。
本次直接读取官方源码和论文；没有重新执行 H100 推理，也没有下载历史 GLB 核验。

## 2026-09-13 实现更新

下文保留 2026-09-12 审查时的历史判断。其后已补齐 raw-image adapter：当前
`modal-fire3d` 可接收 JPG/PNG，固定使用论文基线 Pi3（源码 revision
`9fa3ddb3f8d53041f8b2738df404f62223bbaa7b`，Hub 权重 revision
`b1a2678bfcdc34b4d3b4b199ea959629782106ff`），生成 FIRE3D `single_image`
目录契约后进入原 reconstruction path。

实现不是把 Pi3 官方稀疏 PLY 直接塞给 FIRE3D：它保留完整 dense local point map，
按原图 `floor(H/2) x floor(W/2)` 建立有序点阵；使用 nearest depth + recovered
pinhole backprojection，低置信度/geometry-edge 位置保留为 NaN。另写入
`camera.json` 与 `preprocess.json` provenance。Pi3 推理完成后主动释放模型/VRAM，
再启动 FIRE3D 子进程。当前本地 contract/unit tests 已覆盖该转换；完整任意图片的
H100 Pi3 -> FIRE3D 质量仍必须用真实远端 E2E 验收，不能由单元测试替代。

## 独立判断

FIRE3D 的核心是实例级场景重建：感知对象、生成形状与材质、把 canonical
对象组装回世界坐标。HYWorld2 当前集成包含 WorldNav、WorldStereo、GS 数据准备和
3DGS 训练，是另一条执行链。两者可以共享结果契约，不应共享模型部署清单、版本哈希
或默认后端注册。项目已据此拆分，具体入口见 README。

“官方样例跑通”与“任意 RGB 输入已完成”之间仍有实质距离。剩余工作不仅是把数组
写成 PLY，还包括输入几何、真实竖直方向、尺度、像素对应关系及质量验收。
当前不应直接认定 Pi3X 为已经验证的默认方案。

## 对提供现状的核实

| 说法 | 审查结论 |
| --- | --- |
| single_image 需要 RGB 与有序点云 | 已由感知和重建加载器确认 |
| 点数为 `(H/2)*(W/2)` | 精确写法是 `floor(H/2)*floor(W/2)`；随后按行 reshape |
| PLY 必须 binary little endian / float xyz | 这是可采用的输出约定；加载器使用 `trimesh.load(process=False)`，没有把该编码声明为唯一合法格式。未在本次读取官方样例 PLY 头，不能声称独立核实了它的编码 |
| camera.json 必须参与重建 | 不准确。重建加载器不读它；相机视图函数读取它，缺失时尝试旧 annotation/depth 文件 |
| 输入需要 ground-aligned world | 固定协议明确规定；默认不会事后估计地面对齐 |
| 无效点可以保留 NaN | 重建会按二维网格最近邻填充，并拒绝全无效点云；感知先稀疏采样再过滤，因此还需检查采样后有足够有效点 |
| 论文使用 Pi3 | 已确认，论文 §3.2 及单图实验明确说明 |
| Pi3X 是论文默认方案 | 没有这个证据；论文写 Pi3，不能自动等同于 Pi3X |
| 9 个对象、25.2 MiB、exit 0、4 秒 deploy | 用户提供的历史运行结果，本次未独立重验 |
| CUDA 扩展已完全脱离镜像编译 | 不成立：当前镜像仍含 PyTorch3D Git 源码安装，以及其他 native 扩展安装步骤 |

## 坐标系与相机

固定协议的 `scope.coordinate_contract` 为
`ground_aligned_world_without_posthoc_alignment`。
感知加载器默认只调用 `point_normalize`；这个函数减去 XYZ 最小值，并不旋转或
归一化尺度。可选 wall alignment 只在竖直轴周围选择 0/90/180/270 度 yaw，不能
修正相机俯仰或侧倾。

论文同时说单图使用相机坐标作为 reference，并把几何规范化到 FIRE3D 的坐标约定。
这不足以给出从任意照片到固定发布协议的完整对齐算法。我的判断是：必须显式处理
相机轴约定与场景竖直方向，不能把两者混为一个固定旋转矩阵，也不能声称论文已给出
这部分发布代码。可靠地平面、室内竖直线或外部姿态信息可作为候选约束；缺少可靠
估计时应记录失败或降级状态，而不是默认为地面对齐成功。

`scene_camera` 接受 `fire3d_single_image_camera_v1`，分别读取 `native` 和
`reconstruction`。相机的 eye/lookat/up 要与点云使用同一个世界变换；内参随图像
缩放与裁剪更新。不要将相机信息文件误当作对齐点云的执行入口。

## Pi3X 接口：已经查清的部分

审查了 Pi3 官方仓库当时的 `main`，尚未将它固定为本项目运行依赖：

- `load_images_as_tensor` 默认像素预算为 255000，按首帧长宽比选取 14 的倍数尺寸，
  用 Lanczos resize。不是始终输出固定的宽高，也不是保留原始 JPG 尺寸。
- `Pi3X.forward_head` 将点图和置信度 reshape 为输入张量的 `B,N,H,W,...`。
  所以输出空间大小对应 resize 后的模型输入。
- `local_points` 和 `points` 返回前已乘 `metric`，相机平移也已缩放；下游不能再乘一遍。
- 输出相机位姿与 local points 的关系可直接从 `points = camera_pose @ local_points`
  的计算核查，但输出 world frame 没有提供重力对齐保证。
- 官方导出示例会按 mask 丢掉顶点，得到无序稀疏云；不能直接拿这个 PLY 当 FIRE3D 的
  half-resolution organized grid。

因此 Pi3X 可作为工程候选；若优先追求论文路线可比性，应先固定 Pi3 基线，再对比
Pi3X。MoGe 也可做对照，但没有证据在本项目中已经通过同等质量验收。

## 自定义 RGB 接口的正确验收目标

前处理输出应是独立数据 artifact，包含 RGB、完整有序点阵、相机信息和 provenance
（输入 hash、前处理模型 revision、resize/crop 参数、尺度和坐标变换）。FIRE3D runtime
继续只消费该 artifact。

对原图 `H,W`，点云网格需要严格为 `floor(H/2),floor(W/2)`。重建还会把这个网格
中心裁成两个维度均可被 16 整除的区域，RGB 使用相同区域。必须同时定义像素中心
映射、有效性 mask、重采样方式和内参变换，不能仅按元素个数 reshape。
跨深度边缘直接插值 XYZ 可能产生伪表面，需有边缘/置信度策略。

最小闭环应检查：输入网格/相机重投影一致、竖直方向合理、尺度合理、有效点覆盖，
再运行 FIRE3D 并确认所有预期对象状态、非空 GLB、对象 world transform 和可视化。
单张图 exit 0 只能证明这一个样例执行成功，不能证明任意 RGB 的稳定性。

还需注意官方 CLI 的 `--data-root` 是包含 `single_image/` 的父目录。
实际文件路径是 `<data-root>/single_image/data/<scene_id>/...`，不是直接把
`<scene_id>` 目录传给 CLI。

## 本地集成的其他缺口

1. 原 capability 宣称 image/video/rgbd/point_cloud，而 adapter 仅消费准备好的数据集。
   本次改为 `prepared_dataset`，避免向调用方承诺不存在的前处理。
2. 原部署清单把 FIRE3D 与 HYWorld2 一起计算 revision，且 FIRE3D prerequisites 为空。
   本次拆成独立清单，声明两个 wheel manifest 及 build/smoke 入口。
   manifest 文件存在仅是部署前检查，wheel/hash/smoke 状态仍由运行时检查。
3. 原 smoke 在父进程读取 `torch.cuda.max_memory_allocated()`，模型实际在子进程中运行。
   这个数值不能当成完整推理峰值显存；后续应在模型进程记录或使用 NVML 采样。
4. 默认 smoke 带 `--skip-existing`。重复调用可能复用产物，耗时不能自动算成冷启动
   或完整模型推理耗时。
5. adapter 的结果校验比 smoke 宽松：未检查至少一个 canonical object，且仅检查
   路径/JSON 状态，不解析 GLB。后续产品级入口应补齐产物验收。

为了让拆分与原运行环境的差异可控，本次保留 native 安装链与推理函数行为。
缓存镜像 deploy 的速度与冷构建可复现性是两个不同的验证事项。

## 原始来源

- [FIRE3D 论文 §3.2](https://arxiv.org/html/2609.08848v1#S3.SS2)
- [冻结单图协议](https://github.com/xiahongchi/Fire3D/blob/2368dd2f3909120cf90bbf8a17807abe9c41e600/configs/inference/fire3d_single_image_v1.json)
- [感知加载器与相机读取](https://github.com/xiahongchi/Fire3D/blob/2368dd2f3909120cf90bbf8a17807abe9c41e600/utils/data_single_image.py)
- [重建加载器 load_single_image_scene_inputs](https://github.com/xiahongchi/Fire3D/blob/2368dd2f3909120cf90bbf8a17807abe9c41e600/benchmarks/scene_reconstruction/run_lc64_geometry.py)
- [point_normalize](https://github.com/xiahongchi/Fire3D/blob/2368dd2f3909120cf90bbf8a17807abe9c41e600/utils/transforms.py)
- [官方 CLI](https://github.com/xiahongchi/Fire3D/blob/2368dd2f3909120cf90bbf8a17807abe9c41e600/fire3d/cli.py)
- [Pi3 图像加载器](https://github.com/yyfz/Pi3/blob/main/pi3/utils/basic.py)
- [Pi3X 模型](https://github.com/yyfz/Pi3/blob/main/pi3/models/pi3x.py)
