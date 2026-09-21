---
name: 3DAI Studio
colors:
  background: "#1a1a1a"
  surface: "#232526"
  surface-deep: "#121212"
  surface-elevated: "#2d2f30"
  surface-overlay: "#3f4244"
  border: "#2d2f30"
  border-strong: "#3f4244"
  text-primary: "#e8e6e1"
  text-secondary: "#d6d4d1"
  text-muted: "#999288"
  text-faint: "#7f776c"
  accent: "#4a7fc1"
  accent-soft: "#6b9ad4"
  accent-text: "#b7d0f2"
  success: "#52b788"
  warning: "#e8ba3f"
  warning-bg: "#d4a017"
---

# Design System: 3DAI Studio

**Project ID:** 3daistudio-recreation

Warm zinc-dark professional AI creation studio. Dense, technical, calm — a tool for 3D artists and prompt engineers, not a marketing site.

## 1. Visual Theme & Atmosphere

The interface lives in a warm near-black world: charcoal shells, soft stone borders, and muted steel-blue accents. It feels like a high-end creative workstation — Blender sidebar density crossed with Linear/Figma polish. Surfaces step upward in lightness instead of casting shadows; elevation is communicated with slightly lighter fills and hairline borders, never with heavy drop shadows or glassmorphism.

Whitespace is intentional but tight. Side panels pack many controls (model pickers, advanced settings, credit estimates) while the main viewport stays open for 3D/image work. Typography stays small and utilitarian — uppercase micro-labels, compact buttons, no display serifs. One restrained accent (muted indigo-blue) marks selection and primary action; gold-amber marks premium/badge moments; emerald confirms success. The overall mood is confident, industrial, and quiet.

## 2. Color Palette & Roles

### Primary Foundation
| Name | Hex | Role |
|:---|:---|:---|
| **Charcoal Shell** | `#1a1a1a` | App chrome, sidebar, outer frame |
| **Graphite Canvas** | `#232526` | Main content surface (`#app-main`) |
| **Ink Depth** | `#121212` | 3D viewport void, empty wells, code/preview guts |
| **Elevated Stone** | `#2d2f30` | Raised cards, input tracks, subtle fills |
| **Hairline Stone** | `#3f4244` | Borders, dividers, slider tracks, form edges |

### Accent & Interactive
| Name | Hex | Role |
|:---|:---|:---|
| **Studio Blue** | `#4a7fc1` | Primary action, active chip fill, progress bar, toggle-on |
| **Soft Studio Blue** | `#6b9ad4` | Hover / secondary accent |
| **Pale Blue Ink** | `#b7d0f2` | Primary button text, active chip text |

Active selection pattern: translucent blue wash (`bg-indigo-500/15`–`/20`) + blue border (`/30`–`/40`) + light blue text. Idle controls: zinc border + zinc text, lift to brighter zinc on hover.

### Typography & Text Hierarchy
| Name | Hex | Role |
|:---|:---|:---|
| **Near-White** | `#f4f2ef` / `#e8e6e1` | Headings, titles |
| **Warm Silver** | `#d6d4d1` | Body copy, default UI text |
| **Muted Taupe** | `#999288` | Secondary labels, idle nav |
| **Faint Taupe** | `#7f776c` | Captions, placeholders, micro-meta |

### Functional States
| Name | Hex | Role |
|:---|:---|:---|
| **Jade Success** | `#52b788` | Ready badges, online dot, feature checkmarks |
| **Gold Amber** | `#e8ba3f` / `#d4a017` | NEW badge, Unlock All Tools, REQUIRED, warnings |
| **Soft Cream** | `#f0d48a` | Amber text on dark fills |

Neutrals are **warm** (brown-tinted zinc), not cool slate. Accent blue is **desaturated steel-indigo**, never pure `#6366f1`.

## 3. Typography Rules

### Hierarchy & Weights
- **Family:** `ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- **Micro-labels / panel labels:** 10–11px, `uppercase`, `tracking-wide` / `tracking-wider`, medium–semibold, faint taupe
- **Captions / meta:** 11px, muted taupe
- **Body / control text:** 12–13px (`text-xs` / `text-sm`), regular–medium
- **Card & section titles:** 13–14px, `font-semibold`, near-white
- **Page headings:** 20–24px (`text-xl` / `text-2xl`), `font-semibold`, near-white
- **Empty-state titles:** 18px, semibold
- **Numeric meta (credits, %):** 10–12px, often `font-mono`, `tabular-nums`

Letter-spacing: wider on uppercase labels and tiny badges; default on body. Line-height is compact (controls) to comfortable (paragraphs).

### Spacing Principles
- Base rhythm: 4px; common gaps `gap-1.5` (6px), `gap-2` (8px), `gap-3` (12px)
- Card padding: 12–16px (`p-3` / `p-4`); modal padding 20px (`p-5`)
- Section stack: 12–20px vertical (`space-y-3` / `mb-5`)
- Tight tool density preferred over airy marketing whitespace

## 4. Component Stylings

### Buttons
- **Shape:** `rounded-lg`, border always present, `px-3 py-2`, `text-xs`, `font-medium`, icon+label with `gap-1.5`
- **Primary:** translucent blue — `border` blue/40, `bg` blue/20, text pale blue; hover deepens to `/30`
- **Secondary / ghost:** zinc border (`zinc-700/60`), zinc-800/50 fill, zinc-300 text; hover brightens border + text
- **Premium CTA (Unlock All Tools):** gold amber border/30, amber-400/10 fill, amber-300 text
- **Disabled:** 50% opacity, `cursor-not-allowed`
- **Transition:** `transition-all`, ~150–200ms

### Cards & Tool Panels
- **Radius:** `rounded-xl` (cards/panels), `rounded-2xl` (modals), `rounded-lg` (controls), `rounded-md` (badges/icon wells)
- **Border:** 1px zinc-800 to zinc-700 at 40–60% opacity — hairline, never thick
- **Fill:** zinc-900 at 40–60% opacity over charcoal; elevated blocks use zinc-800/50
- **Shadow:** rare; only `shadow-lg` / `shadow-2xl` on sidebar shell and dialogs
- **Internal padding:** 12–16px
- **Image/viewport wells:** full-bleed dark `#121212` or `#1a1a1a`, optional rounded-xl frame

### Navigation
- **Layout:** fixed left sidebar **300px** + fluid main canvas
- **Sidebar chrome:** `#1a1a1a`, right hairline border, top account/credits card, scrollable nav, bottom onboarding strip + user row
- **Nav items:** full-width `rounded-xl`, `px-3 py-2.5`, icon 18px + 13px label; idle muted taupe; active zinc-800 fill + white text
- **Dividers:** 1px zinc-800 with side margins
- **Expandable groups:** chevron rotate, nested list with left border rail (`ml-6 border-l`)
- **Badges:** tiny uppercase gold “NEW” on nav rows

### Inputs & Forms
- **Text fields / textarea:** `rounded-xl` (block) or `rounded-lg` (inline), zinc-700 border, zinc-900/60 fill, `text-sm`, placeholder zinc-600
- **Focus:** subtle outline; no neon glow
- **Dashed dropzones:** `rounded-xl`, dashed zinc-700 / zinc-600-80, zinc-900/50 fill, centered icon + bold label + muted hint; min-height 100–140px
- **Toggle:** 28×16px pill (`h-4 w-7`), off zinc-700, on Studio Blue; 12px white knob
- **Range slider:** transparent track, 6px zinc-700 pill rail, 14px zinc-200 circular thumb
- **Setting rows:** label (12px medium zinc-200) + sub (11px zinc-500) left; compact control right
- **Chip / segmented choice:** `rounded-lg`, `px-2.5 py-1.5`, `text-xs`; active = blue wash; idle = zinc outline

### Domain-Specific Components
- **Right tool rail:** fixed ~320–380px panel, stacked settings, model selector card, generate CTA full-width with credit subline
- **Progress overlay:** bottom bar card (`bg-zinc-950/90`), 8px track zinc-800, Studio Blue fill
- **Status pill (ready/complete):** emerald border/30 + emerald-950/70 fill + emerald-300 text, `rounded-lg`
- **Empty states:** dashed frame, large 48px icon zinc-500, 18px title, 13px muted body, optional CTA
- **3D viewport controls:** floating chips with `backdrop-blur`, zinc-900/70 fill; active chips use blue wash

## 5. Layout Principles

### Grid & Structure
- **Shell:** `h-dvh` flex row — sidebar 300px fixed + main `flex-1` scroll
- **Workspace pages:** `grid` with `1fr` stage + right rail `320px` / `360px` / `380px` (collapses to single column below `lg`)
- **Community / gallery:** `grid-cols-1` → `md:2` → `xl:3`, gap 12px
- **Tool + side help:** `1fr` + `280px`
- Breakpoints: Tailwind defaults; desktop-first dense workstation, stacks on smaller widths

### Whitespace Strategy
- Page padding: 16px (`p-4`); header strips 8–12px
- Panel gaps: 12px; form groups: 8–12px
- Prefer stacking controls tightly inside rounded panels over large empty gutters

### Alignment & Visual Balance
- Left-aligned labels and body; right-aligned values/credits
- Primary CTA anchors bottom of the right rail, full width
- Micro-labels above fields, uppercase and faint — industrial console feel
- Icons: Lucide-style 12–22px, muted zinc; never colorful emoji chrome

### Responsive Behavior & Touch
- Desktop tool first; sidebars become stacked sections on narrow viewports
- Touch targets: nav ~40px tall; chips/buttons ≥32px
- Scroll: thin custom scrollbar (6px), zinc thumb at 35% opacity

## 6. Design System Notes for Stitch Generation

### Language to Use
Describe screens as **dense dark creative tooling**: “warm charcoal zinc workstation”, “muted steel-blue selection”, “hairline stone borders”, “gold premium badges”, “emerald ready status”. Avoid pure black + neon, avoid cool slate/dark-navy SaaS defaults, avoid playful rounded consumer UI.

### Color References
- Shell `#1a1a1a`, content `#232526`, viewport `#121212`
- Borders `#2d2f30` / `#3f4244`
- Text `#e8e6e1` / `#d6d4d1` / `#999288`
- Accent `#4a7fc1` with soft `#b7d0f2` text
- Success `#52b788`, warning/gold `#e8ba3f`

### Component Prompts
1. “Dark left sidebar 300px with account card, dense nav icons+labels, gold Unlock CTA, bottom onboarding progress.”
2. “Two-column AI tool workspace: large dark 3D/image stage left, 360px settings rail right with model chips, dashed upload zone, advanced accordion, full-width blue generate button showing credit cost.”
3. “Gallery grid of dark rounded-xl cards with 16:10 preview, prompt excerpt, user meta — information-dense, no marketing fluff.”

### Incremental Iteration
Keep the **shell (sidebar + graphite main)** stable across screens. Vary only the workspace stage content (canvas vs form vs gallery). Prefer Variations that tighten control hierarchy and clarify primary action over decorative restyles. When refining, lock this DESIGN.md palette and ask for “same tokens, better layout density.”
