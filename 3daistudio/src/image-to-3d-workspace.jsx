import React from "react";
import {ChevronDown,Download,RefreshCw,Upload,X} from "lucide-react";
import {Badge,Btn,PanelLabel} from "./components.jsx";
import {Viewport3DUpload} from "./three-viewport.jsx";
import {AssetOperationsPanel} from "./asset-operations.jsx";
import {
  fetchArtifactBlob3d,
  jobArtifactRef,
  health3d,
  listModels3d,
  pollJob3d,
  submitImageTo3d,
  errorMessage,
} from "./api/modal.js";

const FALLBACK_MODEL = {
  id: "fastsam3d-plus-plus",
  name: "FastSAM3D++",
  description: "Full textured image-to-3D pipeline",
  status: "enabled",
  profiles: [
    {id: "recommended", name: "Recommended · Full textured asset"},
    {id: "fast", name: "Fast · Vertex Color"},
  ],
  reference: {e2e_seconds: 37.27, profile_id: "recommended"},
};

function modelProfiles(model) {
  return Array.isArray(model?.profiles) && model.profiles.length
    ? model.profiles
    : FALLBACK_MODEL.profiles;
}

function terminalError(job) {
  if (!job) return "3D generation failed";
  return errorMessage(job.error || job.detail || job.error_code || `Job ended with status: ${job.status || job.state || "unknown"}`);
}

function ProviderModelPicker({models, selectedId, onSelect, onClose}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-2xl border border-zinc-700/50 bg-zinc-900 p-4 shadow-2xl">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div>
            <div className="text-sm font-semibold text-zinc-100">modal-provider models</div>
            <div className="text-xs text-zinc-500">Available generation models</div>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-zinc-400 hover:text-zinc-100">
            <X size={16}/>
          </button>
        </div>
        <div className="space-y-2">
          {models.map((model) => (
            <article key={model.id} className="flex items-start gap-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold text-zinc-100">
                  {model.name || model.id} {model.id === selectedId && <Badge>SELECTED</Badge>}
                </h3>
                <p className="mt-1 text-xs text-zinc-400">{model.description || model.id}</p>
                <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-zinc-500">
                  <span>{model.output || "GLB"}</span>
                  <span>{model.profiles?.length || 1} profile(s)</span>
                  {model.reference?.e2e_seconds && <span>ref ~{Math.round(model.reference.e2e_seconds)}s E2E</span>}
                </div>
              </div>
              <Btn onClick={() => { onSelect(model); onClose(); }}>Select</Btn>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ImageTo3DWorkspace() {
  const [models, setModels] = React.useState([FALLBACK_MODEL]);
  const [selectedId, setSelectedId] = React.useState(FALLBACK_MODEL.id);
  const [profile, setProfile] = React.useState("recommended");
  const [seed, setSeed] = React.useState(42);
  const [picker, setPicker] = React.useState(false);
  const [sourceFile, setSourceFile] = React.useState(null);
  const [sourceUrl, setSourceUrl] = React.useState(null);
  const [artifactUrl, setArtifactUrl] = React.useState(null);
  const [artifactName, setArtifactName] = React.useState("");
  const [currentAssetRef, setCurrentAssetRef] = React.useState(null);
  const [generationJobId, setGenerationJobId] = React.useState(null);
  const [providerState, setProviderState] = React.useState("checking");
  const [job, setJob] = React.useState(null);
  const [phase, setPhase] = React.useState("idle");
  const [error, setError] = React.useState("");
  const [elapsed, setElapsed] = React.useState(0);
  const sourceUrlRef = React.useRef(null);
  const artifactUrlRef = React.useRef(null);
  const startedAtRef = React.useRef(null);

  const selectedModel = models.find((model) => model.id === selectedId) || FALLBACK_MODEL;
  const profiles = modelProfiles(selectedModel);
  const running = phase === "submitting" || phase === "running" || phase === "artifact";

  const replaceObjectUrl = React.useCallback((ref, setter, blobOrFile) => {
    if (ref.current) URL.revokeObjectURL(ref.current);
    const next = blobOrFile ? URL.createObjectURL(blobOrFile) : null;
    ref.current = next;
    setter(next);
    return next;
  }, []);

  const refreshProvider = React.useCallback(async () => {
    setProviderState("checking");
    try {
      const [health, payload] = await Promise.all([health3d(), listModels3d()]);
      const enabled = (payload.models || []).filter((model) => model.status !== "disabled");
      setModels(enabled);
      if (enabled.length) {
        setSelectedId((current) => enabled.some((m) => m.id === current) ? current : enabled[0].id);
      }
      setProviderState(health.modal_connected === false ? "disconnected" : "ready");
      setError("");
    } catch (err) {
      setProviderState("offline");
      setError(`Studio unavailable: ${err.message}`);
    }
  }, []);

  React.useEffect(() => {
    refreshProvider();
  }, [refreshProvider]);

  React.useEffect(() => {
    const validProfiles = modelProfiles(selectedModel);
    if (!validProfiles.some((item) => item.id === profile)) {
      setProfile(validProfiles[0]?.id || "recommended");
    }
  }, [selectedModel, profile]);

  React.useEffect(() => {
    if (!running || !startedAtRef.current) return undefined;
    const tick = () => setElapsed(Math.max(0, Math.round((Date.now() - startedAtRef.current) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [running]);

  React.useEffect(() => () => {
    if (sourceUrlRef.current) URL.revokeObjectURL(sourceUrlRef.current);
    if (artifactUrlRef.current) URL.revokeObjectURL(artifactUrlRef.current);
  }, []);

  const chooseSource = (file) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("Please choose an image file.");
      return;
    }
    setSourceFile(file);
    replaceObjectUrl(sourceUrlRef, setSourceUrl, file);
    replaceObjectUrl(artifactUrlRef, setArtifactUrl, null);
    setArtifactName("");
    setCurrentAssetRef(null);
    setGenerationJobId(null);
    setJob(null);
    setPhase("idle");
    setError("");
  };

  const runGenerate = async () => {
    if (running) return;
    if (!sourceFile) {
      setError("Upload an image before generating.");
      return;
    }
    setError("");
    setJob(null);
    replaceObjectUrl(artifactUrlRef, setArtifactUrl, null);
    setArtifactName("");
    startedAtRef.current = Date.now();
    setElapsed(0);
    try {
      setPhase("submitting");
      const submitted = await submitImageTo3d({
        file: sourceFile,
        model: selectedModel.id,
        profile,
        seed: Number.isFinite(Number(seed)) ? Number(seed) : 42,
      });
      setJob(submitted);
      setPhase("running");

      const finished = await pollJob3d(submitted.id, {
        intervalMs: 1500,
        timeoutMs: 20 * 60 * 1000,
        onUpdate: setJob,
      });
      const status = (finished.status || finished.state || "").toLowerCase();
      if (status !== "succeeded") throw new Error(terminalError(finished));

      setPhase("artifact");
      const blob = await fetchArtifactBlob3d(submitted.id, "primary-glb");
      replaceObjectUrl(artifactUrlRef, setArtifactUrl, blob);
      setArtifactName(`${selectedModel.name || selectedModel.id}-${submitted.id}.glb`);
      setCurrentAssetRef(jobArtifactRef(submitted.id, "primary-glb"));
      setGenerationJobId(submitted.id);
      setPhase("done");
      setProviderState("ready");
    } catch (err) {
      setPhase("failed");
      setError(err.message || String(err));
    }
  };

  const handleOperationArtifact = React.useCallback(({jobId, role, blob, name}) => {
    replaceObjectUrl(artifactUrlRef, setArtifactUrl, blob);
    setArtifactName(name);
    setCurrentAssetRef(jobArtifactRef(jobId, role));
    setPhase("done");
    setError("");
  }, [replaceObjectUrl]);

  const jobStatus = job?.status || job?.state;
  const referenceSeconds = selectedModel.reference?.e2e_seconds;
  const providerLabel = providerState === "ready"
    ? "Provider ready"
    : providerState === "disconnected"
      ? "Modal credentials required"
      : providerState === "offline"
        ? "Studio offline"
        : "Checking provider…";

  return (
    <>
      <div className="grid min-h-full grid-cols-1 lg:grid-cols-[1fr_380px]">
        <section className="relative flex flex-col border-r border-zinc-800/40 p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded-lg border border-zinc-700/40 bg-zinc-800/40 px-2.5 py-1.5 text-xs text-zinc-200">Default Project</span>
            <span className={"rounded-full border px-2 py-1 text-[10px] " + (providerState === "ready" ? "border-emerald-500/30 text-emerald-300" : "border-amber-500/30 text-amber-300")}>
              {providerLabel}
            </span>
            <button type="button" onClick={refreshProvider} className="rounded-md p-1 text-zinc-500 hover:text-zinc-200" title="Refresh provider">
              <RefreshCw size={13}/>
            </button>
          </div>

          <Badge>IMAGE TO 3D · LIVE PROVIDER</Badge>
          <h1 className="mt-2 text-2xl font-semibold text-zinc-50">Turn Images Into 3D Assets</h1>
          <p className="text-sm text-zinc-400">modal-3D-client → Modal GPU → verified GLB → Three.js viewport</p>

          <div className="relative mt-4 min-h-[380px] flex-1">
            <Viewport3DUpload
              withToggles
              externalUrl={artifactUrl}
              externalName={artifactName || "Generated GLB"}
              emptyHint={sourceFile ? `${sourceFile.name} ready for generation` : "Upload an image to start"}
              emptySub={artifactUrl ? "Generated artifact · drag to orbit" : "The GLB returned by modal-provider will appear here"}
            />

            {running && (
              <div className="absolute inset-x-4 bottom-4 rounded-xl border border-zinc-700/60 bg-zinc-950/90 p-3">
                <div className="mb-2 flex items-center justify-between gap-3 text-xs text-zinc-300">
                  <span>{phase === "artifact" ? "Downloading verified GLB…" : `Job ${jobStatus || "submitting"}…`}</span>
                  <span>{elapsed}s</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
                  <div className="h-full w-1/3 animate-pulse rounded-full bg-indigo-500"/>
                </div>
                {job?.id && <div className="mt-2 truncate text-[10px] text-zinc-500">job: {job.id}</div>}
              </div>
            )}

            {phase === "done" && artifactUrl && (
              <div className="absolute right-4 top-4 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-950/80 px-3 py-2 text-xs text-emerald-300">
                <span>Verified GLB ready</span>
                <a href={artifactUrl} download={artifactName || "asset.glb"} className="rounded p-1 hover:bg-emerald-500/10" title="Download GLB">
                  <Download size={14}/>
                </a>
              </div>
            )}
          </div>
        </section>

        <aside className="space-y-3 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-100">IMAGE TO 3D</h2>
            <Badge>{selectedModel.id}</Badge>
          </div>

          <button type="button" onClick={() => setPicker(true)} className="flex w-full items-center justify-between rounded-xl border border-zinc-700/50 bg-zinc-800/40 p-3 text-left">
            <div>
              <b className="block text-sm text-zinc-100">{selectedModel.name || selectedModel.id}</b>
              <small className="text-xs text-zinc-400">{selectedModel.description || "Provider model"}</small>
            </div>
            <ChevronDown size={16} className="shrink-0 text-zinc-400"/>
          </button>

          <div className="flex flex-wrap gap-1.5">
            {models.slice(0, 4).map((model) => (
              <button
                type="button"
                key={model.id}
                onClick={() => setSelectedId(model.id)}
                className={"rounded-lg border px-2.5 py-1.5 text-xs " + (model.id === selectedId ? "border-indigo-500/40 bg-indigo-500/15 text-indigo-200" : "border-zinc-700/40 bg-zinc-800/40 text-zinc-400")}
              >
                {model.name || model.id}
              </button>
            ))}
          </div>

          <PanelLabel required>Upload Image</PanelLabel>
          <label
            className="flex min-h-[150px] cursor-pointer flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-4 hover:border-zinc-600"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              chooseSource(event.dataTransfer.files?.[0]);
            }}
          >
            {sourceUrl ? (
              <>
                <img src={sourceUrl} alt="3D source" className="max-h-24 max-w-full rounded-lg object-contain"/>
                <b className="max-w-full truncate text-sm text-zinc-200">{sourceFile?.name}</b>
                <span className="text-xs text-zinc-500">Click or drop to replace</span>
              </>
            ) : (
              <>
                <Upload size={22} className="text-zinc-400"/>
                <b className="text-sm text-zinc-200">Upload an image</b>
                <span className="text-xs text-zinc-500">Click or drag & drop</span>
              </>
            )}
            <input type="file" accept="image/*" className="hidden" onChange={(event) => chooseSource(event.target.files?.[0])}/>
          </label>

          <PanelLabel>Generation Profile</PanelLabel>
          <div className="flex flex-wrap gap-1.5">
            {profiles.map((item) => (
              <button
                type="button"
                key={item.id}
                onClick={() => setProfile(item.id)}
                className={"rounded-lg border px-2.5 py-1.5 text-xs " + (profile === item.id ? "border-indigo-500/40 bg-indigo-500/15 text-indigo-200" : "border-zinc-700/40 text-zinc-400")}
              >
                {item.name || item.id}
              </button>
            ))}
          </div>

          <PanelLabel>Seed</PanelLabel>
          <input
            type="number"
            min="0"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
            className="h-9 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 text-sm text-zinc-200 outline-none"
          />

          <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 text-[11px] text-zinc-400">
            <div><b className="text-zinc-200">Output:</b> {selectedModel.artifact?.mime || "model/gltf-binary"}</div>
            <div><b className="text-zinc-200">Profile:</b> {profile}</div>
            {referenceSeconds && <div><b className="text-zinc-200">Reference E2E:</b> ~{Math.round(referenceSeconds)}s ({selectedModel.reference?.status || "benchmark"})</div>}
          </div>

          {error && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
              {error}
            </div>
          )}

          <Btn primary className="w-full !py-2.5" disabled={running || !sourceFile || providerState !== "ready" || !models.length} onClick={runGenerate}>
            {running ? "Generating…" : artifactUrl ? "Generate Again" : "Generate 3D Model"}
            <span className="text-[10px] opacity-80">
              {providerState === "disconnected" ? "Connect Modal credentials in modal-3D-client" : "Real modal-provider job"}
            </span>
          </Btn>

          {currentAssetRef && (
            <AssetOperationsPanel
              key={generationJobId || "asset-operations"}
              assetRef={currentAssetRef}
              assetLabel={artifactName}
              onArtifactReady={handleOperationArtifact}
            />
          )}
        </aside>
      </div>

      {picker && (
        <ProviderModelPicker
          models={models}
          selectedId={selectedId}
          onSelect={(model) => setSelectedId(model.id)}
          onClose={() => setPicker(false)}
        />
      )}
    </>
  );
}
