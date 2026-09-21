# Texture Generator / Texture Painter — remote implementation notes

Sources: Playwright live pages, network HAR/chunks, docs.3daistudio.com, modal-provider code.

## Official product split

| Surface | What it does (official) |
|---------|-------------------------|
| **Texture Generator** `/TextureGenerator/app` | Whole-model retexture: upload GLB/FBX/OBJ, pick engine, prompt or reference, output new textured model |
| **Texture Painter** `/TexturePainter` | Manual + AI projection painter (legacy UI; Texture AI 2.0 beta via Settings) |

Docs (search summary): Generator = one-shot retexture from prompt/image; Painter = brushes, layers, angle-by-angle AI projection.

## Texture Generator (remote)

### UI contract
- Engines: **Forge, Prism, Meshy, Hunyuan, Hitem3D** (third-party model brands, not modal-provider)
- 3D Model: GLB/FBX/OBJ, UI text “≤10–120MB”
- Prompt type: **Text | Image | Multi-View**
- Optional Style Image; “Generate reference image with AI”
- Quality select: Fast / Standard / Detailed (HD) / Extreme (Max)
- Advanced Settings + **Generate Texture**
- Viewport: Three.js canvas (draco wasm, three chunks on page)
- APIs observed on this page load: mainly `s.3daistudio.com/account/*`, maintenance; generation POST not captured until submit (auth/API may differ by session)

### Backend shape (inferred + FAQ/chunks)
- Cloud generation via their `s.3daistudio.com` + model vendor APIs (Forge/Prism/Meshy/Hunyuan/Hitem)
- Payload fields seen in bundles: `texture_prompt`, `texture_image_url(s)`, `texture_resolution`, `texture_guide`
- Output: full textured GLB; dashboard post-actions include **Texture AI**, retopology, remesh, etc.
- Viewer post-gen: Texture AI button opens `/TexturePainter?modelPath=<url>`

## Texture Painter (remote)

### UI contract (live)
- Banner: **legacy** vs **Texture AI 2.0 BETA** (Settings → Join Beta)
- Toolbar: Upload / Save / Help / Documentation
- Tabs: **Model | Tex 4K | Res 4K | Export**
- Settings: Brush Size / Hardness / Strength (range)
- AI: **Prompt**, **Negative Prompt**, **Creativity (0-1)**, **Resemblance (0.1-3)**
- CTA: **Generate Texture**
- Viewport: dual canvas + Three.js; loads demo `public/assets/models/Example1.glb`
- Also loads **threejs.org HDRI** `spruit_sunrise_4k.hdr.jpg` (client lighting)
- Preview webm: `/Tool_Preview_Videos/TexturePainterPreview.webm`
- Cursor asset: `/public/assets/cursor.png` (brush cursor)
- Network: browser **blob:** URLs after paint/process (client-side canvas/texture work)
- Docstring strings: `texture_painter`, `texture_ai` in chunks

### Implementation picture
1. **Client 3D**: Three.js + Draco GLB + HDRI environment (same stack as rest of site)
2. **Paint/brush**: browser-side brush onto UV/texture (blob textures)
3. **AI texture ops**: “Generate Texture” likely **server-side diffusion/inpaint** (prompt + brush mask + model); 2.0 beta = newer pipeline
4. **Entry**: from Dashboard / 3D viewer via `?modelPath=`

## modal-provider alignment

| Official capability | modal-provider today |
|---------------------|----------------------|
| Whole-model AI retexture (Texture Generator) | **Shipped** as `texture_generate` via dedicated `modal-3d-hunyuan-paint` worker (Hunyuan3D-Paint 2.1) |
| Rebake PBR to new UV | **`texture_bake`** operation exists (Blender/xatlas path) |
| UV unwrap | **`uv_unwrap`** (xatlas) |
| image_to_3d textured GLB | FastSAM3D++ / Hunyuan / TRELLIS paths (texture baking inside generation) |
| Texture Painter brush + prompt | **No equivalent** in modal-provider |
| Forge/Prism/Meshy engines | **Not** in modal-provider naming |

Current contract: `texture_generate` receives GLB + reference PNG and returns textured GLB + material/quality reports. Strict `preserve_geometry=true` verifies face count and bounding-box drift. `texture_regenerate` and masked `texture_edit` remain future work.

## Local recreation impact

- Texture Generator UI already lists engines/quality — fine as **shell**
- For **real** retexture: wire the UI to modal-provider `texture_generate`; vendor engines can remain UI aliases/mocks until separately integrated
- Painter: align controls (brush size/hardness/strength, negative prompt, creativity/resemblance) + Model/Tex 4K/Res 4K/Export tabs; viewport can load Example GLB + HDRI like official
- Do **not** assume modal-provider already has painter parity

## Key official asset URLs
- Example model: `https://www.3daistudio.com/public/assets/models/Example1.glb`
- Painter preview: `.../Tool_Preview_Videos/TexturePainterPreview.webm`
- HDRI (external): `https://threejs.org/examples/textures/equirectangular/spruit_sunrise_4k.hdr.jpg`
