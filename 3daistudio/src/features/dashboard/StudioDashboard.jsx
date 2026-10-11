import React from "react";
import {NavLink, useSearchParams} from "react-router-dom";
import {Btn} from "../../components.jsx";
import {LazyViewport3DUpload as Viewport3DUpload} from "../../components/LazyViewport3DUpload.jsx";
import {errorMessage} from "../../api/client.js";
import {capabilities, listCapabilities3d, TEXT_IMAGE, IMAGE_3D} from "../../api/capabilities.js";
import {submitJob, cancelJob, terminal, listJobs} from "../../api/jobs.js";
import {uploadAsset3d, assetContentUrl, listAssets} from "../../api/assets.js";
import {listProjects, createProject as createStudioProject} from "../../api/projects.js";
import {useJob} from "../../hooks/useJob.js";
import {fieldClass, panelClass} from "../../components/studio-ui.js";


export function StudioDashboard() {
  const [data, setData] = React.useState({jobs: [], assets: [], projects: []});
  const [error, setError] = React.useState("");
  const [project, setProject] = React.useState("");
  const [name, setName] = React.useState("");
  const [preview, setPreview] = React.useState(null);
  const refresh = React.useCallback(async () => {
    try {
      const [jobs, assets, projects] = await Promise.all([listJobs(), listAssets(), listProjects()]);
      setData({...jobs, ...assets, ...projects}); setError("");
    } catch (err) { setError(err.message); }
  }, []);
  React.useEffect(() => {refresh(); const id = setInterval(refresh, 4000); return () => clearInterval(id);}, [refresh]);
  const createProject = async e => {
    e.preventDefault();
    try {await createStudioProject(name); setName(""); await refresh();}
    catch (err) {setError(err.message);}
  };
  return <main className="space-y-5 p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-xl font-semibold">Your Studio</h1>
      <nav className="flex gap-4 text-sm text-indigo-300"><NavLink to="/ImageTo3D">Image to 3D</NavLink><NavLink to="/TextTo3D">Text to 3D</NavLink><NavLink to="/Studio/operations">All operations</NavLink></nav>
    </div>
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
    <form className="flex flex-wrap gap-2" onSubmit={createProject}>
      <select aria-label="Project filter" className={fieldClass + " !w-auto"} value={project} onChange={e => setProject(e.target.value)}><option value="">All projects</option>{data.projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <input aria-label="New project name" className={fieldClass + " !w-auto"} value={name} onChange={e => setName(e.target.value)} placeholder="New project name" maxLength={120}/><button className="rounded-lg bg-indigo-600 px-4 text-sm" disabled={!name.trim()}>Create project</button>
    </form>
    <section className={panelClass}><h2 className="mb-3 font-semibold">Tasks</h2>
      {!data.jobs.length && <p className="text-sm text-zinc-400">No tasks yet. Start by generating a model.</p>}
      {data.jobs.filter(j => !project || j.projectId === project).map(job => <article key={job.id} className="flex flex-wrap items-center gap-3 border-t border-zinc-800 py-3 text-sm">
        <div className="min-w-0 flex-1"><p>{job.operation}</p><p className="text-xs text-zinc-500">{job.id}</p>{job.error && <p className="text-xs text-amber-300">{errorMessage(job.error)}</p>}</div>
        <span>{job.status} · {job.stage}</span>
        <NavLink className="text-indigo-300" to={job.operation === IMAGE_3D ? `/ImageTo3D?job=${encodeURIComponent(job.id)}` : `${job.operation === TEXT_IMAGE ? "/ImageGeneration/generate" : job.operation === "studio.text_to_3d.v1" ? "/TextTo3D" : "/Studio/operations"}?job=${encodeURIComponent(job.id)}`}>Open task</NavLink>
        {!terminal(job) && <Btn onClick={async () => {try {await cancelJob(job.id); await refresh();} catch(err) {setError(err.message);}}}>Cancel</Btn>}
        {job.result?.artifacts?.map(a => <a key={a.id} className="text-indigo-300" href={assetContentUrl(a.id)} download>{a.role}</a>)}
      </article>)}
    </section>
    <section className={panelClass}><h2 className="mb-3 font-semibold">Assets and versions</h2>
      {!data.assets.length && <p className="text-sm text-zinc-400">Uploaded and generated assets will appear here.</p>}
      <div className="grid gap-3 md:grid-cols-3">{data.assets.filter(a => !project || a.projectId === project).map(asset => <article key={asset.id} className="rounded-lg border border-zinc-800 p-3">
        {asset.mime === "image/png" && <img src={assetContentUrl(asset.id)} alt={asset.name} className="mb-2 h-32 w-full object-contain"/>}
        <p className="truncate text-sm">{asset.name}</p><p className="text-xs text-zinc-500">{asset.role} · {(asset.bytes / 1048576).toFixed(1)} MiB</p>
        {asset.parents.length > 0 && <p className="text-xs text-zinc-400">Derived from {asset.parents.length} input version(s)</p>}
        <div className="mt-2 flex gap-3 text-xs text-indigo-300"><a href={assetContentUrl(asset.id)} download>Download</a>{asset.mime === "model/gltf-binary" && <button onClick={() => setPreview(asset)}>Preview</button>}<NavLink to={`/Studio/operations?asset=${asset.id}`}>Process</NavLink></div>
      </article>)}</div>
    </section>
    {preview && <section className={panelClass}><Btn onClick={() => setPreview(null)}>Close preview</Btn><div className="h-[480px]"><Viewport3DUpload externalUrl={assetContentUrl(preview.id)} externalName={preview.name}/></div></section>}
  </main>;
}
