import React from "react";
import {cancelJob, getJob3d, pollJob3d, terminal} from "../api/jobs.js";

/**
 * Observe a server-owned Job without resubmitting it.
 * Closing the page only stops polling; the remote task continues.
 */
export function useJob({intervalMs = 2000, enabled = true} = {}) {
  const [job, setJob] = React.useState(null);
  const [error, setError] = React.useState("");
  const [jobId, setJobId] = React.useState(null);

  const track = React.useCallback(value => {
    setError("");
    setJob(value && typeof value === "object" ? value : null);
    setJobId(typeof value === "string" ? value : value?.id || null);
  }, []);

  React.useEffect(() => {
    if (!enabled || !jobId || (job?.id === jobId && terminal(job))) return;
    let active = true;
    let timeout;
    const refresh = async () => {
      try {
        const next = await getJob3d(jobId);
        if (!active) return;
        setJob(next);
        setError("");
        if (!terminal(next)) timeout = setTimeout(refresh, intervalMs);
      } catch (err) {
        if (!active) return;
        setError(err.message || String(err));
        timeout = setTimeout(refresh, intervalMs);
      }
    };
    timeout = setTimeout(refresh, intervalMs);
    return () => {
      active = false;
      clearTimeout(timeout);
    };
  }, [enabled, jobId, job?.status, intervalMs]);

  const cancel = React.useCallback(async () => {
    if (!jobId) return null;
    const cancelled = await cancelJob(jobId);
    setJob(cancelled);
    return cancelled;
  }, [jobId]);

  const waitFor = React.useCallback(async (id, {signal, intervalMs: waitInterval = intervalMs, timeoutMs} = {}) => {
    setError("");
    try {
      return await pollJob3d(id, {intervalMs: waitInterval, timeoutMs, signal, onUpdate: track});
    } catch (err) {
      if (err?.name !== "AbortError") setError(err.message || String(err));
      throw err;
    }
  }, [intervalMs, track]);

  return {job, jobId, error, track, cancel, waitFor};
}
