# 3D AI Studio — 3D engine identification evidence

Method: download official `_next/static/immutable/chunks/*.js` and search runtime strings + live page inspection.

## Smoking-gun strings (offline chunk analysis)

| Evidence | File | Meaning |
|----------|------|---------|
| `rendererPackageName:"@react-three/fiber",rendererVersion:"9.4.2"` | `0rx3bwerakp77.js` | **React Three Fiber 9.4.2** (React DevTools renderer metadata) |
| `e.__r3f` / `root.getState()` | `0rx3bwerakp77.js` | R3F canvas store API |
| `new g.WebGLRenderer` | `0rx3bwerakp77.js` | **three.js WebGLRenderer** |
| `"REVISION",0,"175"` | `3-0lvxofrehx9.js` | **Three.js r175** |
| `new b.GLTFLoader` + `setDRACOLoader` + `setMeshoptDecoder` | `0hsizpmnp6yvk.js` | three GLTF + Draco + meshopt |
| `THREE.DRACOLoader: ...` error strings | `2ya-i-bu9zorp.js` | three.js Draco loader source |
| `useFrame(...)` | several chunks | R3F hook |
| docs text: `using WebGL and three.js` | Viewer FAQ SEO in `3xx4uu6w2_563.js` | Their own copy confirms three.js for Viewer |

## Not the engine (false positives)

- `Babylon` / `model-viewer` in `3xx4uu6w2_563.js` → **FAQ/marketing prose** (“same Khronos loader as Sketchfab, model-viewer, and Babylon.js”)
- `GaussianSplat` in nav/route maps → route labels; splat implementation not proven as PlayCanvas/SuperSplat
- No `@react-three/drei` package string found in chunks
- No `babylonjs` / `PlayCanvas` engine code signatures

## Runtime (chrome on ImageTo3D)

- canvas present; WebGL 2.0 ANGLE (NVIDIA D3D11)
- `window.__THREE__` present
- empty workspace: mostly Tailwind zinc UI + small canvas — looks “not like three.js demos” because **app chrome is not the 3D engine**; viewport visual appears when a model loads

## Conclusion

**Image/Text to 3D + Viewer 3D viewport = Three.js r175 + @react-three/fiber 9.4.2 + GLTF/Draco/meshopt loaders (self-hosted Draco WASM).**  
Local recreation using three + R3F is the **same core stack**. drei is optional ecosystem helper, not proven on their CDN.

SuperSplat (superspl.at) is **PlayCanvas** — different product; do not treat it as 3daistudio’s engine unless splat-specific code is found.
