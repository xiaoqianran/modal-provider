# modal-provider ↔ 3daistudio 对接评估

## 结论

**好对接，但只覆盖「生成能力」子集，不是官网全量后端。**  
推荐路径：本地 React → **modal-*-client REST（Sidecar）** → Modal GPU Provider。  
难度：**中等偏易**（核心 2D/3D 生成链路清晰）；难点在 **UI 模型名映射** 与 **异步 Job 轮询/产物下载**。

## Monorepo 角色（`wk08/modal-provider`）

| 包 | 作用 | 与 UI 关系 |
|----|------|------------|
| `modal-gen-client` | Provider Hub（统一 Job/Artifact） | 可选总入口 |
| `modal-2D-client` | 文生图 Sidecar | Image Studio Generate |
| `modal-3D-client` | 图生 3D Sidecar | Image to 3D / 部分 Text 工作流 |
| `modal-2D` / `modal-3D` | Modal GPU Provider | 不直接被浏览器调用 |
| `modal-world` / `EmbodiedGen` / `fire3d` | 世界/具身/重建 | 超出当前 3daistudio UI 范围 |

根 README 验收记录：**PNG→GLB 约 42s**、**prompt→PNG 约 10s**（需 Modal + HF Secret）。

## 已有 HTTP 契约（对接面）

### modal-3D-client（默认 CORS `*`，端口 3213）

```text
GET  /health
GET  /v1/models
GET  /v1/capabilities
POST /v1/jobs                 multipart: file, model, profile?, seed?
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/artifact   → GLB
POST /modal/connect           {token_id, token_secret}
```

离线演示：`MODAL_3D_CLIENT_DEMO=1`（假 capability + 内存 Job）。

### modal-2D-client

```text
POST /v1/jobs
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/artifact   → image/png
```

CORS：`MODAL_2D_CORS_ORIGINS`，默认 `*`。

### 资产后处理（modal-3D operations）

`POST /v1/assets` → `POST /v1/operations/jobs`  
operation 包括 `uv_unwrap`、`inspect_mesh`、`filter_parts`、`texture_generate` 等（以 `/v1/operations` 返回为准）。

`texture_generate` 当前真实链路：GLB + reference PNG → Hunyuan3D-Paint 2.1 → textured GLB + material-report + quality-report；支持 `preserve_geometry=true` 严格几何保持校验。

## 与 3daistudio 前端的差距

| 官网 UI | modal-provider | 对接 |
|---------|----------------|------|
| Image Studio 文生图 | modal-2D `text_to_image` | 直接 |
| Image to 3D | modal-3D `image_to_3d` + 模型 id | 需 **模型名映射表** |
| Text to 3D | 无统一 text→GLB 一条命令 | 可先 2D 文生图 → 再 3D |
| Texture / Remesh / UV | operations 子集 | 可映射 Toolbox |
| Dashboard 账号/积分/项目 | 无 | 仍本地 mock |
| Flow / Video / Community | 无 | 仍本地 mock |
| 官网 Prism/Hunyuan 商品名 | Provider 模型 id 不同 | **必须 adapter** |

## 推荐对接架构

```text
3daistudio/src
  api/modal.js          base URL + session header + fetch helper
  api/mapModels.js      "Prism 3.1" ↔ modal model id
  hooks/useGenerateJob  submit → poll → artifact URL/blob
  three-viewport        GET artifact blob → useGLTF

modal-2D-client :3212   modal-3D-client :3213
        │                      │
        └──────── Modal GPU ───┘
```

### 最小前端改动

1. `.env`：`VITE_MODAL_3D_URL`、`VITE_MODAL_2D_URL`、可选 `VITE_MODAL_3D_SESSION`
2. `POST /v1/jobs` 替换 mock `runGenerate`
3. 轮询 `GET /v1/jobs/{id}` 到 `succeeded`
4. `GET .../artifact` blob URL 交给 `Viewport3D url=`
5. 失败态：409 未连接 Modal → UI 提示 connect token

### 服务端启动（演示）

```bash
# modal-3D-client
cd ../modal-3D-client
MODAL_3D_CLIENT_DEMO=1 MODAL_3D_CLIENT_PORT=3213 uv run python -m modal_3d_client
# 真实 Modal 时去掉 DEMO，并 /modal/connect 填 token
```

## 风险与成本

1. **模型目录不一致** — 前端 `data.js` 是官网商品名；以 `/v1/models` 为准做映射  
2. **异步时延** — GPU 生成数十秒～分钟，UI 需任务列表/后台轮询  
3. **鉴权** — Sidecar 默认无鉴权；公网需 `MODAL_*_CLIENT_TOKEN`  
4. **产物体积** — GLB 可能数 MB～更大，注意下载与 three 加载  
5. **Text→3D** — 不是一键，需两段式流水线  
6. **Modal/HF 成本与部署** — 真实推理要 Secret `huggingface` + GPU Worker  

## 好不好对接？一句话

- **UI 壳 + Image to 3D / 文生图**：好对接，Sidecar REST + CORS 已齐，还有 demo 模式可先不接 GPU。  
- **「model-provider 里的全部」= 官网所有功能**：不行；缺账号、项目库、Flow、Video、Community 等。  
- **现实做法**：3daistudio 继续当壳；**核心生成按钮** 接 `modal-2D/3D-client`；其余保持 mock。

下一步若实施：先在 `src/api/modal.js` + `ImageTo3D` 接 `/v1/jobs` + 本地 DEMO 联调。
