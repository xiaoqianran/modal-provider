import React, {Suspense, lazy} from "react";

// Keep the Three.js renderer out of dashboards until a preview is actually opened.
const LoadedViewport = lazy(() => import("../three-viewport.jsx").then(module => ({
  default: module.Viewport3DUpload,
})));

export function LazyViewport3DUpload(props) {
  return (
    <Suspense fallback={<div role="status" className="flex h-full min-h-[240px] items-center justify-center rounded-xl bg-zinc-900 text-sm text-zinc-400">Loading 3D viewer…</div>}>
      <LoadedViewport {...props}/>
    </Suspense>
  );
}
