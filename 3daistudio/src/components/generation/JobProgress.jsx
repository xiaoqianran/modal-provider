import React from "react";

export function JobProgress({job, elapsed, phase}) {
  return <div className="absolute inset-x-4 bottom-4 rounded-xl border border-zinc-700/60 bg-zinc-950/90 p-3">
    <div className="mb-2 flex items-center justify-between gap-3 text-xs text-zinc-300">
      <span>{phase === "artifact" ? "Downloading verified GLB…" : `Job ${job?.status || job?.state || "submitting"}…`}</span>
      <span>{elapsed}s</span>
    </div>
    <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800"><div className="h-full w-1/3 animate-pulse rounded-full bg-indigo-500"/></div>
    {job?.id && <div className="mt-2 truncate text-[10px] text-zinc-500">job: {job.id}</div>}
  </div>;
}
