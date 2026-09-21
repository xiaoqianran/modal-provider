# 3daistudio local — code graph & notes

## Dependency graph (runtime)

```
main.jsx
├── tailwind.css          # theme zinc/indigo/amber + #1a1a1a/#232526
├── layout.jsx
│   └── data.js (toolboxGroups)
│   └── AppLayout → Shell (persistent sidebar) → <Outlet/>
├── components.jsx        # Btn/Badge/ChipRow/PanelLabel/...
├── data.js               # all page catalog data
├── three-viewport.jsx    # three + @react-three/fiber + drei
│
├── pages-dashboard.jsx → components
├── pages-image.jsx     → components, data
├── pages-3d.jsx        → components, data, three-viewport
├── pages-tools.jsx     → components, data, three-viewport
├── pages-misc.jsx      → components, data
└── settings.jsx        → components, data
```

Marketing routes **outside** Shell: `/Platform`, `/ModelComparison`.

## Issues fixed in this pass

| Issue | Fix |
|-------|-----|
| `a\|\|b\|\|c&&JSX` operator precedence in ToolBody | Parentheses `(a\|\|b\|\|c)&&` |
| Unused lucide/react-router imports | Removed |
| Duplicate `PanelLabel` in pages-3d / pages-tools | Shared `components.jsx` |
| Missing React `key` on model quick-select | Added `key={x}` |
| Object URL leak in Viewport3DUpload | Revoke on replace + unmount |
| Dead `styles.css` (~60KB) / `index.css` | Removed (not imported) |
| Unused `SettingsOverlay` | Removed |
| Chip style duplication | `chipActiveClass` / `chipIdleClass` |

## Still worth watching (not blocking)

1. **`EmptyState`** exported but unused — keep for future empty UIs or delete later.
2. **`pages-image` ToolDetail** still has static form UI (no generation API) — intentional local mock.
3. **`/Tools/:tool` catch-all** can shadow unknown tools — fine; add real tools to `toolPages`.
4. **Platform / ModelComparison** leave app shell — intentional (official-like marketing chrome).
5. **three-viewport** uses `@react-three/drei` helpers; official CDN only proved **fiber 9.4.2 + three r175** (same family).
6. **HMR**: if colors “don’t change”, restart Vite + hard refresh; clear `node_modules/.vite`.
7. **React 19.2 pin** required for `@react-three/fiber@9` peer (`react < 19.3`).

## Local commands

```bash
npm run dev   # http://127.0.0.1:5173
```

Reference for engine proof: `reference/3daistudio/ENGINE-EVIDENCE.md`
