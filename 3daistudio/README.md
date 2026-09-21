# 3DAI Studio local recreation

Recreated from the authenticated 3DAI Studio interface through the user's local Chrome DevTools / Playwright MCP session.

Implemented:
- Dashboard (Files / Projects / Branches / Shared)
- Image Studio: vertical category list + tool grid (Generate, Edit, Convert, Image Reference, Style Reference, Sketch, Image Tools, Video)
- Generic Image Studio tool detail pages
- Image to 3D
- Text to 3D
- Texture Generator
- Texture Painter (legacy banners + Model/Tex/Res/Export panel)
- Flow
- Learning Studio
- Video Studio
- Model Comparison
- Toolbox / Community / Settings shells

Private account data and backend generation calls are not copied.

Live capture notes (chrome-devtools MCP):
- Sidebar top card: logo + Unlock All Tools, Ready to Create / 3D AI Studio, credits
- Nav groups separated by dividers; Flow has NEW badge
- Image Studio uses left vertical categories, not horizontal tabs
- Image to 3D right panel includes Learn more / API / Batch Mode, pro tip, credit estimate

Reference JSON lives under `reference/3daistudio/pages/*/live-structure.json`.

Run:
```
npm install
npm run dev
```
Default Vite port may be 5173 (this machine served on http://127.0.0.1:5173).
