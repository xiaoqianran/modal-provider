# FIRE3D 实跑验收 — 2026-09-12

结论：**官方 single_image / 003025 的部署、真实推理、GLB 导出与读取链路通过；
视觉质量存在明显缺陷，不能无条件验收为生产级场景资产。**

## 本次实际执行

| 项目 | 实测结果 |
| --- | --- |
| FIRE3D commit | `2368dd2f3909120cf90bbf8a17807abe9c41e600`，云端 `git rev-parse HEAD` 核验 |
| 部署入口 | `modal_fire3d.app` |
| Modal app | `modal-world-fire3d` |
| 修复后缓存部署 | 3.680 秒 |
| 模型/数据 preload | 104.865 秒 |
| Run ID（UTC） | `20260911T204708Z` |
| Function call | `fc-01M293P84H3ZT9VHNK73Y9E5PQ` |
| 请求 GPU | H100 |
| 实际 GPU | **NVIDIA H200 / compute capability 9.0**，nvidia-smi 和 PyTorch 一致 |
| FlashAttention | 2.7.3，预编译 wheel SHA256 核验及 CUDA 运算通过 |
| PyTorch3D | 0.7.8，预编译 wheel SHA256 核验及 FPS CUDA 运算通过 |
| 完整 infer 子进程耗时 | **428.702 秒** |
| 重建内部报告耗时 | 329.569 秒 |
| infer exit code | **0** |
| expected / decoded | **9 / 9**（含 1 个 background，8 个其他实例） |
| 场景 GLB | **26,595,408 bytes / 25.36 MiB** |
| 独立 canonical GLB | **9 个**，全部下载并解析 |
| 场景 mesh / 三角面 | **9 / 825,067** |
| 带纹理 mesh | **9 / 9** |

本次使用全新的 `/outputs/acceptance/20260911T204708Z`，不存在历史产物。
实际 infer 命令没有 `--skip-existing`；上游固定重建协议的内部 resume 开关仍保留，
但新目录中没有任何可供恢复的结果。

```text
/usr/local/bin/python -m fire3d infer
  --dataset single_image --scene-id 003025
  --output-root /outputs/acceptance/20260911T204708Z
  --gpu 0 --skip-render
```

`--skip-render` 表示未执行官方 Blender 渲染。本次另用浏览器 Three.js 实际渲染
下载的 GLB，并采用官方输入相机、双面材质，保存 PBR 和无光照纹理对照图。

## 产物核验

- 10 个 GLB 的 magic/version/声明长度与文件长度一致。
- 10 个 GLB 均成功通过 trimesh 解析，网格非空、顶点有限、三角索引合法。
- 场景内 9 个节点的 world transform 与官方 appearance manifest 一致，矩阵非奇异。
- 每个节点的面数、顶点数与 manifest 一致，UV 坐标均有限。
- 浏览器 GLTFLoader 成功加载场景，9 个 mesh 均有颜色纹理。
- `summary.json` 和 `inference_summary.json` 均报告场景 complete，预期与完成数量均为 9。

场景 GLB SHA256：
`92fb3478f9160240b8e07f3ea5af8c1f40f5bd571bf1b6e69be7e58910403c03`

## 输入实测

官方 RGB 为 1296×968；PLY 为 `binary_little_endian`、float xyz，313632 个顶点，
全部有效，符合 484×648 的 organized grid。
使用官方 native camera 重投影，所有点均位于相机前方。
按原图 `(2*x, 2*y)` 像素坐标比较，误差中位数 0.00002113 px，P95 0.00004597 px。
这个样例对应偶数像素采样位置，而非默认半像素中心偏移。

PLY SHA256：
`f11ab1dc554b1a23d91aac27933d6a71be3d1edd4c2a1748481bf1b00b07f573`

## 视觉判断与限制

主要桌子、沙发、蓝色椅子及柜子的相对布局可辨认；场景可以正常渲染、切换视角，
也可以独立隐藏背景。但与输入图相比，墙面/地面明显缺损，桌面有大量斑点，
桌椅细杆及吊灯几何粗糙。切换为无光照纹理材质后仍存在这些问题，不能全部归因于
预览灯光。上游 manifest 另标记 background PBR 超出训练分布。

因此只通过“官方样例执行与可用文件交付”这一层验收。未验证碰撞、物理仿真、
水密性、官方 Blender 视觉指标或任意自定义 RGB 前处理。也不能把 H200 实测耗时
写成严格 H100 基准，或把这次 7 分多钟完整调用宣传成一分钟内完成。

当前返回值的 `peak_allocated_gb` 来自父进程，**不能作为模型子进程峰值显存**。
人工 nvidia-smi 单次采样为 9465 MiB、31% 利用率，也不是峰值。
日志中 AnyUp 权重发生一次运行时下载，整次调用包含初始化与加载开销。

## 本次发现并修复

第一次云端启动失败：`modal_fire3d.__init__` 提前导入 adapter，间接要求云端未挂载的
`modal_world`。改为延迟导入后重新部署，真实流程成功。新增云端无 modal_world 环境
的导入回归测试，当前 8 项测试通过。

另增加独立 run_id、新目录重复使用拒绝、运行中 checkout revision 核验、完整
stdout/stderr/exit code 保存，以及下载验收脚本。原样例输出没有删除或覆盖。

## 本地证据

- [执行回执及输出目录](acceptance/20260911T204708Z/)
- [远端返回结果](acceptance/20260911T204708Z/result.json)
- [GLB 检查报告](acceptance/20260911T204708Z/glb_validation.json)
- [对象装配检查](acceptance/20260911T204708Z/assembly_validation.json)
- [输入检查](acceptance/20260911T204509Z/input_validation.json)
- [输入相机 PBR 对照截图](acceptance/20260911T204708Z/native-preview.png)
- [无光照纹理对照截图](acceptance/20260911T204708Z/unlit-preview.png)
- [隐藏背景后的对象概览](acceptance/20260911T204708Z/objects-preview.png)
- [场景 GLB](acceptance/20260911T204708Z/output/reconstruction/003025/appearance/predicted_textured_world_scene.glb)

大型本地证据位于 gitignored `acceptance/`；远端完整日志及结果保存在
`fire3d-output` Volume 的 `acceptance/20260911T204708Z/`。
复跑入口为 `scripts/acceptance.py`，每次默认生成新的 UTC run ID。
