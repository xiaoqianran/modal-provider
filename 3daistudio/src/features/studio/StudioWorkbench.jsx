import React from "react";
import {NavLink, useSearchParams} from "react-router-dom";
import {Btn} from "../../components.jsx";
import {Viewport3DUpload} from "../../three-viewport.jsx";
import {errorMessage} from "../../api/client.js";
import {capabilities, listCapabilities3d, TEXT_IMAGE, IMAGE_3D} from "../../api/capabilities.js";
import {submitJob, cancelJob, terminal, listJobs} from "../../api/jobs.js";
import {uploadAsset3d, assetContentUrl, listAssets} from "../../api/assets.js";
import {listProjects, createProject as createStudioProject} from "../../api/projects.js";
import {useJob} from "../../hooks/useJob.js";

const fieldClass = "w-full rounded-lg border border-zinc-700 bg-zinc-900 p-2 text-sm";
const panelClass = "rounded-xl border border-zinc-800 bg-zinc-950/40 p-4";

export function StudioWorkbench({mode = "operations"}) {
  const [search, setSearch] = useSearchParams();
  const [caps, setCaps] = React.useState([]);
  const [assets, setAssets] = React.useState([]);
  const [projects, setProjects] = React.useState([]);
  const [project, setProject] = React.useState("");
  const [operation, setOperation] = React.useState("");
  const [values, setValues] = React.useState({});
  const [options, setOptions] = React.useState({});
  const [prompt, setPrompt] = React.useState("");
  const [model, setModel] = React.useState("");
  const [imageModel, setImageModel] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const {job, error: jobError, track: trackJob, cancel: cancelTrackedJob} = useJob();
  const resumeId = search.get("job");
  React.useEffect(() => {
    if (resumeId) trackJob(resumeId);
  }, [resumeId, trackJob]);
  React.useEffect(() => {
    let live = true;
    Promise.all([listCapabilities3d(), listAssets(), listProjects()]).then(([snapshot, a, p]) => {
      if (!live) return;
      const list = capabilities(snapshot); setCaps(list); setAssets(a.assets); setProjects(p.projects);
      const choices = list.filter(c => mode === "image" ? c.operation === TEXT_IMAGE : c.category === "asset-processing");
      setOperation((choices.find(c => c.available) || choices[0])?.operation || "");
      setModel(list.find(c => c.operation === IMAGE_3D)?.input?.schema?.properties?.model?.enum?.[0] || "");
      setImageModel(list.find(c => c.operation === TEXT_IMAGE)?.input?.schema?.properties?.model?.enum?.[0] || "");
    }).catch(err => live && setError(err.message));
    return () => {live = false;};
  }, [mode]);
  const cap = caps.find(c => c.operation === operation);
  const imageCap = caps.find(c => c.operation === TEXT_IMAGE);
  const modelCap = caps.find(c => c.operation === IMAGE_3D);
  React.useEffect(() => {
    const defaults = {};
    for (const [key, schema] of Object.entries(cap?.input?.schema?.properties || {})) {
      if (schema.type === "object") defaults[key] = search.get("asset") || "";
      else if (schema.default !== undefined) defaults[key] = schema.default;
      else if (schema.enum?.length) defaults[key] = schema.enum[0];
    }
    setValues(defaults);
    setOptions(Object.fromEntries(Object.entries(cap?.optionsSchema?.properties || {}).filter(([, s]) => s.default !== undefined).map(([k, s]) => [k, s.default])));
  }, [cap, search]);
  const inputControl = (key, schema, current, setter, required = false) => {
    const value = current[key];
    const set = v => setter(old => ({...old, [key]: v}));
    return <label key={key} className="block space-y-1 text-xs text-zinc-300"><span>{key}{required ? " *" : ""}</span>
      {schema.type === "object" ? <>
        <select aria-label={key} className={fieldClass} value={value || ""} onChange={e => set(e.target.value)}><option value="">Select an asset</option>{assets.filter(a => !schema.properties?.mime?.const || a.mime === schema.properties.mime.const).map(a => <option key={a.id} value={a.id}>{a.name} · {a.role}</option>)}</select>
        {schema.properties?.mime?.const !== "application/json" && <input aria-label={`Upload ${key}`} type="file" accept={schema.properties?.mime?.const === "image/png" ? "image/*" : ".glb"} disabled={busy} onChange={async e => {
          if (!e.target.files[0]) return; setBusy(true); setError("");
          try {const asset = await uploadAsset3d(e.target.files[0], project); setAssets(a => [asset, ...a.filter(x => x.id !== asset.id)]); set(asset.id);} catch(err) {setError(err.message);} finally {setBusy(false);}
        }}/>}</>
        : schema.enum ? <select aria-label={key} className={fieldClass} value={value ?? ""} onChange={e => set(e.target.value)}>{schema.enum.map(v => <option key={v}>{v}</option>)}</select>
        : schema.type === "boolean" ? <input aria-label={key} type="checkbox" checked={!!value} onChange={e => set(e.target.checked)}/>
        : <input aria-label={key} className={fieldClass} type={["number", "integer"].includes(schema.type) ? "number" : "text"} min={schema.minimum} max={schema.maximum} step={schema.type === "integer" ? 1 : "any"} value={Array.isArray(value) ? value.join(",") : value ?? ""} onChange={e => set(schema.type === "array" ? e.target.value.split(",").map(Number) : ["number", "integer"].includes(schema.type) ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)}/>}
    </label>;
  };
  const generate = async () => {
    setBusy(true); setError("");
    try {
      const spec = mode === "text" ? {operation: "studio.text_to_3d.v1", inputs: {prompt, model, imageModel}}
        : {operation, inputs: Object.fromEntries(Object.entries(values).filter(([,v]) => v !== "").map(([k,v]) => [k, cap.input.schema.properties[k].type === "object" ? {artifact_id: v} : v])), options};
      const submitted = await submitJob({...spec, ...(project ? {projectId: project} : {})});
      trackJob(submitted);
      setSearch(previous => {
        const next = new URLSearchParams(previous);
        next.set("job", submitted.id);
        return next;
      }, {replace: true});
    } catch (err) {setError(err.message);} finally {setBusy(false);}
  };
  const ready = mode === "text" ? imageCap?.available && modelCap?.available && !!prompt.trim() && model && imageModel : cap?.available;
  const output = job?.result?.artifacts?.find(a => a.role === "primary-glb" || a.role === "primary-image");
  return <main className="grid gap-5 p-5 lg:grid-cols-[360px_1fr]">
    <section className={panelClass + " space-y-4"}><h1 className="text-xl font-semibold">{mode === "text" ? "Text to 3D" : mode === "image" ? "Generate image" : "Asset operations"}</h1>
      <label className="block text-xs">Project<select aria-label="Project" className={fieldClass} value={project} onChange={e => setProject(e.target.value)}><option value="">Default Project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      {mode === "text" ? <>
        <textarea aria-label="Prompt" className={fieldClass} placeholder="Describe the model" value={prompt} onChange={e => setPrompt(e.target.value)}/>
        {[["Image model", imageCap, imageModel, setImageModel], ["3D model", modelCap, model, setModel]].map(([label,c,v,set]) => <label key={label} className="block text-xs">{label}<select aria-label={label} className={fieldClass} value={v} onChange={e => set(e.target.value)}>{(c?.input?.schema?.properties?.model?.enum || []).map(id => <option key={id}>{id}</option>)}</select></label>)}
        <p className="text-xs text-zinc-400">Generate a reference image, then create a 3D model. Both steps continue in the background.</p>
      </> : <>
        <select aria-label="Operation" className={fieldClass} value={operation} onChange={e => setOperation(e.target.value)}>{caps.filter(c => mode === "image" ? c.operation === TEXT_IMAGE : c.category === "asset-processing").map(c => <option key={c.operation} value={c.operation}>{c.displayName}{c.available ? "" : " · unavailable"}</option>)}</select>
        {Object.entries(cap?.input?.schema?.properties || {}).map(([k,s]) => inputControl(k,s,values,setValues,cap.input.schema.required?.includes(k)))}
        {Object.entries(cap?.optionsSchema?.properties || {}).map(([k,s]) => inputControl(k,s,options,setOptions))}
      </>}
      {!ready && <p className="text-xs text-amber-300">Select the required inputs. Generation also requires an available provider.</p>}
      <Btn primary disabled={busy || !ready || (job && !terminal(job))} onClick={generate}>{busy ? "Submitting…" : "Run"}</Btn>
      {(error || jobError) && <p role="alert" className="text-sm text-red-300">{error || jobError}</p>}
      <NavLink className="block text-sm text-indigo-300" to="/Dashboard">View all tasks and assets →</NavLink>
    </section>
    <section className={panelClass}>
      {job ? <><p className="mb-2 text-sm">{job.status} · {job.stage}</p>{job.error && <p role="alert" className="text-amber-300">{errorMessage(job.error)}</p>}{!terminal(job) && <Btn onClick={async () => {try {await cancelTrackedJob();} catch(err) {setError(err.message);}}}>Cancel</Btn>}</> : <p className="text-zinc-400">Results appear here. Tasks are also saved in Dashboard.</p>}
      {output?.mime === "model/gltf-binary" && <div className="h-[550px]"><Viewport3DUpload externalUrl={assetContentUrl(output.id)} externalName={output.role}/></div>}
      {output?.mime === "image/png" && <img className="max-h-[550px] w-full object-contain" src={assetContentUrl(output.id)} alt="Generated image"/>}
      {job?.result?.artifacts?.map(a => <a key={a.id} className="mr-4 inline-block text-sm text-indigo-300" href={assetContentUrl(a.id)} download>Download {a.role}</a>)}
    </section>
  </main>;
}
