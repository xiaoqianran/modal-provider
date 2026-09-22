import React from "react";
import {Download,Layers3,Paintbrush,Scissors,Upload,WandSparkles} from "lucide-react";
import {Badge,Btn,PanelLabel} from "./components.jsx";
import {
  fetchArtifactBlob3d,
  jobArtifactRef,
  listOperations3d,
  pollJob3d,
  submitOperation3d,
  uploadAsset3d,
} from "./api/modal.js";

const TERMINAL_OK = "succeeded";
const SEGMENT_ROLES = ["parts-manifest", "face-labels", "quality-report"];

function errorText(job, fallback) {
  return job?.error || job?.detail || job?.error_code || fallback;
}

function artifactRoles(job) {
  return job?.result?.artifacts?.map((artifact) => artifact.role).filter(Boolean) || [];
}

function parseIndices(value) {
  const rows = String(value)
    .split(/[\s,]+/)
    .filter(Boolean)
    .map((item) => Number(item));
  if (!rows.length || rows.some((item) => !Number.isInteger(item) || item < 0)) {
    throw new Error("Part indices must be comma-separated non-negative integers.");
  }
  return [...new Set(rows)];
}

function numberValue(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function AssetOperationsPanel({assetRef, assetLabel, onArtifactReady}) {
  const [available, setAvailable] = React.useState([]);
  const [segmentJob, setSegmentJob] = React.useState(null);
  const [activeOperation, setActiveOperation] = React.useState("");
  const [operationJob, setOperationJob] = React.useState(null);
  const [error, setError] = React.useState("");
  const [history, setHistory] = React.useState([]);
  const [partIndices, setPartIndices] = React.useState("0");
  const [filterMode, setFilterMode] = React.useState("keep");
  const [partIndex, setPartIndex] = React.useState("0");
  const [completionSteps, setCompletionSteps] = React.useState("50");
  const [octreeResolution, setOctreeResolution] = React.useState("512");
  const [referenceFile, setReferenceFile] = React.useState(null);
  const [referenceUrl, setReferenceUrl] = React.useState(null);
  const referenceUrlRef = React.useRef(null);

  React.useEffect(() => {
    let mounted = true;
    listOperations3d()
      .then((payload) => {
        if (mounted) setAvailable((payload.operations || []).map((row) => row.id));
      })
      .catch(() => {
        if (mounted) setAvailable([]);
      });
    return () => { mounted = false; };
  }, []);

  React.useEffect(() => () => {
    if (referenceUrlRef.current) URL.revokeObjectURL(referenceUrlRef.current);
  }, []);

  const supported = (operation) => !available.length || available.includes(operation);
  const running = Boolean(activeOperation);

  const setReference = (file) => {
    if (!file) return;
    if (file.type !== "image/png" && !file.name.toLowerCase().endsWith(".png")) {
      setError("Hunyuan Paint reference must be a PNG image.");
      return;
    }
    if (referenceUrlRef.current) URL.revokeObjectURL(referenceUrlRef.current);
    const next = URL.createObjectURL(file);
    referenceUrlRef.current = next;
    setReferenceUrl(next);
    setReferenceFile(file);
    setError("");
  };

  const runOperation = async (operation, inputs, options, afterSuccess) => {
    if (running || !assetRef) return;
    setActiveOperation(operation);
    setOperationJob(null);
    setError("");
    try {
      const submitted = await submitOperation3d({operation, inputs, options});
      setOperationJob(submitted);
      const finished = await pollJob3d(submitted.id, {
        intervalMs: 1200,
        timeoutMs: 30 * 60 * 1000,
        onUpdate: setOperationJob,
      });
      if (String(finished.status || "").toLowerCase() !== TERMINAL_OK) {
        throw new Error(errorText(finished, `${operation} failed`));
      }

      const blob = await fetchArtifactBlob3d(finished.id, "primary-glb");
      onArtifactReady?.({
        jobId: finished.id,
        role: "primary-glb",
        blob,
        name: `${operation}-${finished.id}.glb`,
        operation,
        job: finished,
      });
      setHistory((rows) => [
        {operation, id: finished.id, roles: artifactRoles(finished)},
        ...rows,
      ].slice(0, 8));
      afterSuccess?.(finished);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setActiveOperation("");
    }
  };

  const runSegment = () => runOperation(
    "segment_parts",
    {asset: assetRef},
    {},
    (finished) => setSegmentJob(finished),
  );

  const segmentationInputs = segmentJob ? {
    asset: jobArtifactRef(segmentJob.id, "primary-glb"),
    parts_manifest: jobArtifactRef(segmentJob.id, "parts-manifest"),
    face_labels: jobArtifactRef(segmentJob.id, "face-labels"),
  } : null;

  const runFilter = () => {
    try {
      const indices = parseIndices(partIndices);
      return runOperation(
        "filter_parts",
        segmentationInputs,
        {part_indices: indices, mode: filterMode},
      );
    } catch (err) {
      setError(err.message);
      return undefined;
    }
  };

  const runComplete = () => runOperation(
    "complete_parts",
    segmentationInputs,
    {
      part_index: Math.max(0, Math.trunc(numberValue(partIndex, 0))),
      seed: 42,
      num_inference_steps: Math.max(1, Math.trunc(numberValue(completionSteps, 50))),
      octree_resolution: Math.max(128, Math.min(512, Math.trunc(numberValue(octreeResolution, 512)))),
    },
  );

  const runTexture = async () => {
    if (running) return;
    if (!referenceFile) {
      setError("Upload a PNG reference image before texturing.");
      return;
    }
    setActiveOperation("texture_generate");
    setOperationJob(null);
    setError("");
    try {
      const reference = await uploadAsset3d(referenceFile);
      const submitted = await submitOperation3d({
        operation: "texture_generate",
        inputs: {
          asset: assetRef,
          reference_image: {artifact_id: reference.id},
        },
        options: {preserve_geometry: true},
      });
      setOperationJob(submitted);
      const finished = await pollJob3d(submitted.id, {
        intervalMs: 1200,
        timeoutMs: 30 * 60 * 1000,
        onUpdate: setOperationJob,
      });
      if (String(finished.status || "").toLowerCase() !== TERMINAL_OK) {
        throw new Error(errorText(finished, "texture_generate failed"));
      }
      const blob = await fetchArtifactBlob3d(finished.id, "primary-glb");
      onArtifactReady?.({
        jobId: finished.id,
        role: "primary-glb",
        blob,
        name: `texture_generate-${finished.id}.glb`,
        operation: "texture_generate",
        job: finished,
      });
      setHistory((rows) => [
        {operation: "texture_generate", id: finished.id, roles: artifactRoles(finished)},
        ...rows,
      ].slice(0, 8));
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setActiveOperation("");
    }
  };

  const downloadArtifact = async (jobId, role) => {
    try {
      const blob = await fetchArtifactBlob3d(jobId, role);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${role}-${jobId}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (err) {
      setError(err.message || String(err));
    }
  };

  if (!assetRef) return null;

  const segmentRoles = artifactRoles(segmentJob);
  const status = operationJob?.status || "";
  const activeLabel = activeOperation
    ? `${activeOperation} · ${status || "submitting"}`
    : "Ready";

  return (
    <section className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-950/35 p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-xs font-semibold text-zinc-100">Asset Operations</div>
          <div className="max-w-[260px] truncate text-[10px] text-zinc-500">{assetLabel || assetRef.job_id}</div>
        </div>
        <Badge>{activeLabel}</Badge>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/45 p-2.5">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-zinc-200">
          <Scissors size={14}/> Parts · P3-SAM / X-Part
        </div>
        <Btn
          className="w-full"
          disabled={running || !supported("segment_parts")}
          onClick={runSegment}
        >
          {activeOperation === "segment_parts" ? "Segmenting…" : "Segment Current Model"}
        </Btn>

        {segmentJob && (
          <>
            <div className="mt-2 rounded-md border border-emerald-500/20 bg-emerald-500/5 p-2 text-[10px] text-zinc-400">
              <div className="font-medium text-emerald-300">Segmentation ready</div>
              <div className="mt-1 truncate">{segmentJob.id}</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {segmentRoles.map((role) => <Badge key={role}>{role}</Badge>)}
              </div>
            </div>

            <PanelLabel>Part indices</PanelLabel>
            <input
              value={partIndices}
              onChange={(event) => setPartIndices(event.target.value)}
              placeholder="0, 1"
              className="h-8 w-full rounded-md border border-zinc-700 bg-zinc-950 px-2 text-xs text-zinc-200 outline-none"
            />

            <div className="mt-2 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setFilterMode("keep")}
                className={"rounded-md border px-2 py-1.5 text-xs " + (filterMode === "keep" ? "border-indigo-500/40 bg-indigo-500/15 text-indigo-200" : "border-zinc-700 text-zinc-400")}
              >
                Keep
              </button>
              <button
                type="button"
                onClick={() => setFilterMode("exclude")}
                className={"rounded-md border px-2 py-1.5 text-xs " + (filterMode === "exclude" ? "border-indigo-500/40 bg-indigo-500/15 text-indigo-200" : "border-zinc-700 text-zinc-400")}
              >
                Exclude
              </button>
            </div>

            <div className="mt-2 grid grid-cols-2 gap-2">
              <Btn disabled={running || !supported("filter_parts")} onClick={runFilter}>
                <Layers3 size={13}/> {activeOperation === "filter_parts" ? "Filtering…" : "Filter Parts"}
              </Btn>
              <Btn
                disabled={running}
                onClick={() => SEGMENT_ROLES.forEach((role) => downloadArtifact(segmentJob.id, role))}
              >
                <Download size={13}/> Sidecars
              </Btn>
            </div>

            <PanelLabel>Complete one part</PanelLabel>
            <div className="grid grid-cols-3 gap-2">
              <input
                value={partIndex}
                onChange={(event) => setPartIndex(event.target.value)}
                type="number"
                min="0"
                title="Part index"
                className="h-8 rounded-md border border-zinc-700 bg-zinc-950 px-2 text-xs text-zinc-200 outline-none"
              />
              <input
                value={completionSteps}
                onChange={(event) => setCompletionSteps(event.target.value)}
                type="number"
                min="1"
                max="100"
                title="Inference steps"
                className="h-8 rounded-md border border-zinc-700 bg-zinc-950 px-2 text-xs text-zinc-200 outline-none"
              />
              <select
                value={octreeResolution}
                onChange={(event) => setOctreeResolution(event.target.value)}
                title="Octree resolution"
                className="h-8 rounded-md border border-zinc-700 bg-zinc-950 px-2 text-xs text-zinc-200 outline-none"
              >
                <option value="256">256</option>
                <option value="512">512</option>
              </select>
            </div>
            <Btn
              className="mt-2 w-full"
              disabled={running || !supported("complete_parts")}
              onClick={runComplete}
            >
              <WandSparkles size={13}/> {activeOperation === "complete_parts" ? "Completing…" : "Complete Selected Part"}
            </Btn>
          </>
        )}
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/45 p-2.5">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-zinc-200">
          <Paintbrush size={14}/> Texture · Hunyuan3D-Paint
        </div>
        <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-zinc-700 bg-zinc-950/60 p-2">
          {referenceUrl ? (
            <img src={referenceUrl} alt="Texture reference" className="h-12 w-12 rounded object-cover"/>
          ) : (
            <span className="flex h-12 w-12 items-center justify-center rounded bg-zinc-900 text-zinc-500"><Upload size={16}/></span>
          )}
          <span className="min-w-0 flex-1">
            <b className="block truncate text-xs text-zinc-200">{referenceFile?.name || "PNG reference image"}</b>
            <small className="text-[10px] text-zinc-500">Geometry is preserved</small>
          </span>
          <input type="file" accept="image/png,.png" className="hidden" onChange={(event) => setReference(event.target.files?.[0])}/>
        </label>
        <Btn
          primary
          className="mt-2 w-full"
          disabled={running || !referenceFile || !supported("texture_generate")}
          onClick={runTexture}
        >
          <Paintbrush size={13}/> {activeOperation === "texture_generate" ? "Texturing…" : "Generate Texture"}
        </Btn>
      </div>

      {operationJob?.id && (
        <div className="rounded-md border border-zinc-800 bg-zinc-950/60 p-2 text-[10px] text-zinc-500">
          <div className="truncate">job: {operationJob.id}</div>
          <div>status: {operationJob.status}</div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs text-rose-200">
          {error}
        </div>
      )}

      {history.length > 0 && (
        <div className="space-y-1">
          <PanelLabel>Operation history</PanelLabel>
          {history.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-2 rounded-md border border-zinc-800/70 px-2 py-1.5 text-[10px]">
              <span className="truncate text-zinc-300">{row.operation}</span>
              <span className="truncate text-zinc-600">{row.id}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
