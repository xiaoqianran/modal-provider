import React,{useState} from "react";
import {useParams,NavLink} from "react-router-dom";
import {Cuboid,Image,Search,SlidersHorizontal,Upload,Package,Type} from "lucide-react";
import {Badge,Btn,ChipRow,DropImage,DropModel,PanelLabel as L} from "./components.jsx";
import {communitySamples2D,communitySamples3D,toolPages} from "./data.js";
import {Viewport3D,Viewport3DUpload} from "./three-viewport.jsx";

export function CommunityPage({mode}){
  const all=mode==="3d"?communitySamples3D:communitySamples2D;
  const [q,setQ]=useState("");
  const [showFilters,setShowFilters]=useState(false);
  const [modelFilter,setModelFilter]=useState("All");
  const models=["All",...[...new Set(all.map(r=>r[0]))]];
  const data=all.filter(([model,prompt])=>{
    const needle=q.trim().toLowerCase();
    const okQ=!needle||(model+" "+prompt).toLowerCase().includes(needle);
    const okM=modelFilter==="All"||model===modelFilter;
    return okQ&&okM;
  });
  return <>
    <div className="flex flex-wrap items-center gap-2 p-4">
      <div className="mr-auto">
        <Badge>COMMUNITY</Badge>
        <h1 className="mt-1 text-2xl font-semibold text-zinc-50">{mode==="3d"?"3D Creations":"2D Creations"}</h1>
      </div>
      <div className="flex items-center gap-2 rounded-lg border border-zinc-700/50 bg-zinc-900/70 px-3">
        <Search size={14} className="text-zinc-500"/>
        <input value={q} onChange={e=>setQ(e.target.value)} className="h-9 w-48 bg-transparent text-sm outline-none" placeholder={mode==="3d"?"Search models...":"Search images..."}/>
      </div>
      <Btn className={showFilters?"!border-indigo-500/40 !bg-indigo-500/15 !text-indigo-200":""} onClick={()=>setShowFilters(v=>!v)}><SlidersHorizontal size={14}/>Filters</Btn>
      <span className="text-[11px] text-zinc-500">{data.length} results</span>
    </div>
    {showFilters&&<div className="flex flex-wrap gap-1.5 px-4 pb-2">
      {models.map(m=><Btn key={m} className={modelFilter===m?"!border-indigo-500/40 !bg-indigo-500/15 !text-indigo-200":""} onClick={()=>setModelFilter(m)}>{m}</Btn>)}
    </div>}
    {data.length===0?(
      <div className="mx-4 rounded-xl border border-dashed border-zinc-700 px-6 py-16 text-center text-sm text-zinc-400">No community items match</div>
    ):(
    <div className="grid grid-cols-1 gap-3 p-4 pt-0 md:grid-cols-2 xl:grid-cols-3">
      {data.map(([model,prompt,user],i)=><article key={model+user+i} className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/40">
        <div className={"flex h-40 items-center justify-center "+(mode==="3d"?"bg-indigo-500/10 text-indigo-300":"bg-emerald-500/10 text-emerald-300")}>
          {mode==="3d"?<Cuboid size={48}/>:<Image size={48}/>}
        </div>
        <div className="p-3">
          <Badge>Model: {model}</Badge>
          <small className="mt-2 block text-[11px] text-zinc-500">Prompt</small>
          <p className="mt-0.5 text-xs text-zinc-300">{prompt}</p>
          <div className="mt-3 flex items-center gap-2">
            <span className="mr-auto text-[11px] text-zinc-500">{user}</span>
            <Btn>{mode==="3d"?"View 3D Model":"View Full Image"}</Btn>
            <Btn primary>Remix</Btn>
          </div>
        </div>
      </article>)}
    </div>)}
  </>;
}

function PreviewPanel({d}){
  const tabs=d.previewTabs||["Preview"];
  const [tab,setTab]=useState(tabs[0]);
  return <section className="flex min-h-[320px] flex-col rounded-xl border border-zinc-800 bg-zinc-950/40 p-3">
    <div className="mb-3 flex flex-wrap gap-1">
      {tabs.map(t=><button type="button" key={t} onClick={()=>setTab(t)} className={"rounded-md px-2.5 py-1.5 text-xs "+(tab===t?"border border-indigo-500/30 bg-indigo-500/15 text-indigo-200":"text-zinc-400 hover:text-zinc-200")}>{t}</button>)}
    </div>
    <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center text-zinc-500">
      <Package size={44}/>
      <b className="text-sm text-zinc-200">{tab}</b>
      <span className="max-w-xs text-xs">Results appear here after you run the tool</span>
    </div>
  </section>;
}

function MarketingUpload({d}){
  return <>
    {(d.sections||["How it works","FAQ","Get started"]).map(s=><Btn key={s} className="mr-1.5">{s}</Btn>)}
    <div className="mt-3 flex min-h-[200px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-6 text-center">
      <Upload size={24} className="text-zinc-400"/>
      <b className="text-sm text-zinc-200">{d.uploadHint||"Drop your file here or click to browse"}</b>
      {d.ctaUpload&&<Btn>{d.ctaUpload}</Btn>}
      {d.steps&&<div className="mt-3 flex w-full max-w-md flex-col gap-1.5 text-left">{d.steps.map((s,i)=><div key={s} className="rounded-lg bg-zinc-800/50 px-3 py-2 text-xs text-zinc-300">{s}</div>)}</div>}
      <Btn primary className="mt-2">{d.action||"Get started"}</Btn>
    </div>
  </>;
}

function ViewerPanel({d}){
  const [material,setMaterial]=useState("Original");
  const [env,setEnv]=useState("STUDIO");
  return <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_280px]">
    <section className="flex min-h-[420px] flex-col rounded-xl border border-zinc-800 bg-zinc-950/40">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2 text-[11px] text-zinc-400">
        <span>3D VIEWER · No model loaded</span>
        <span className="rounded border border-zinc-700 px-1.5 py-0.5">FREE · 100% CLIENT-SIDE</span>
      </div>
      <div className="min-h-[360px] flex-1 p-2">
        <Viewport3DUpload
          withToggles
          emptyHint={d.subtitle||"Drop any 3D model to view"}
          emptySub={d.uploadHint||"GLB · GLTF · FBX · OBJ · STL"}
        />
      </div>
      <div className="flex flex-wrap justify-center gap-1 border-t border-zinc-800 p-2">
        {(d.cameras||[]).map(c=><button type="button" key={c} className="h-8 w-8 rounded-md border border-zinc-700 text-xs text-zinc-300">{c}</button>)}
      </div>
    </section>
    <aside className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
      {(d.tabs||[]).map(t=><div key={t} className="rounded-lg border border-zinc-800/80 bg-zinc-950/40 px-2.5 py-2 text-xs text-zinc-300">{t}</div>)}
      <L>MATERIAL MODE</L>
      <ChipRow items={d.options||["Original","Wireframe"]}/>
      <div className="flex flex-wrap gap-1.5">{(d.options||[]).map(o=>
        <button type="button" key={o} onClick={()=>setMaterial(o)} className={"rounded-lg border px-2 py-1 text-[11px] "+(material===o?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{o}</button>)}</div>
      <L>HDRI PRESET</L>
      <div className="flex flex-wrap gap-1.5">{(d.env||["STUDIO"]).map(o=>
        <button type="button" key={o} onClick={()=>setEnv(o)} className={"rounded-lg border px-2 py-1 text-[11px] "+(env===o?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{o}</button>)}</div>
      <div className="text-[10px] text-zinc-500">Formats: {(d.formats||[]).join(" · ")} · {material} / {env}</div>
    </aside>
  </div>;
}

function PromptHelperPanel({d}){
  return <div className="mx-auto max-w-2xl">
    <div className="mb-3 flex flex-wrap gap-1.5">
      {(d.buttons||[]).map((b,i)=><Btn key={b} primary={i===1}>{b}</Btn>)}
    </div>
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-base font-semibold text-zinc-50">{d.subtitle}</h2>
      <p className="mt-1 text-sm text-zinc-400">{d.hint}</p>
      <textarea className="mt-3 min-h-[120px] w-full rounded-xl border border-zinc-700/50 bg-zinc-950 p-3 text-sm outline-none" placeholder="A stylized fantasy warrior with emerald armor..."/>
      <div className="mt-3 flex flex-wrap gap-1.5">{(d.chips||[]).map(c=><button type="button" key={c} className="rounded-lg border border-zinc-700/40 bg-zinc-800/40 px-2.5 py-1.5 text-xs text-zinc-300">{c}</button>)}</div>
    </div>
  </div>;
}

function AudioPanel({d}){
  return <div className="mx-auto max-w-xl space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
    <div className="flex items-center justify-between"><h2 className="text-base font-semibold text-zinc-50">{d.title}</h2><Btn>Examples</Btn></div>
    <L>TEXT TO SPEAK</L>
    <textarea className="min-h-[100px] w-full rounded-xl border border-zinc-700/50 bg-zinc-950 p-3 text-sm" placeholder="Enter text to convert to speech..."/>
    <L>MODEL</L>
    <div className="grid grid-cols-2 gap-1.5">{(d.options||[]).slice(0,4).map((x,i)=><button type="button" key={x} className={"rounded-lg border px-2.5 py-2 text-left text-xs "+(i===0?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-300")}>{x}</button>)}</div>
    <L>VOICE</L><ChipRow items={(d.options||[]).slice(4)}/>
    <L>LANGUAGE</L><ChipRow items={["Auto-detect","English","中文","日本語"]}/>
    <Btn primary className="w-full !py-2.5">{d.action||"Generate Speech"}</Btn>
  </div>;
}

function StagerPanel({d}){
  return <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_340px]">
    <PreviewPanel d={{previewTabs:["Scene Preview"]}}/>
    <aside className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
      <L>{d.labels?.[0]||"3D Models 0/5"}</L><DropModel/>
      <Btn>{d.ctaUpload||"Choose from Dashboard"}</Btn>
      <L>Render Settings</L>
      <L>Creativity Level</L><ChipRow items={d.creativity||[]}/>
      <L>Render Style</L>
      <div className="flex flex-wrap gap-1">{(d.styles||[]).map((s,i)=><button type="button" key={s} className={"rounded-lg border px-2 py-1 text-[11px] "+(i===0?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{s}</button>)}</div>
      <L>Effects</L>
      <div className="flex flex-wrap gap-1">{(d.effects||[]).map(e=><span key={e} className="rounded-md border border-zinc-700/40 px-2 py-1 text-[10px] text-zinc-400">{e}</span>)}</div>
      <L>AI Model</L>
      <div className="space-y-1">{(d.models||[]).map((m,i)=><button type="button" key={m} className={"block w-full rounded-lg border px-2 py-1.5 text-left text-[11px] "+(i===0?"border-indigo-500/40 bg-indigo-500/10 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{m}</button>)}</div>
      <Btn primary className="w-full !py-2.5">{d.action}{d.cost&&<span className="text-[10px] opacity-80"> · {d.cost}</span>}</Btn>
    </aside>
  </div>;
}

function ToolBody({d}){
  if(d.kind==="viewer") return <ViewerPanel d={d}/>;
  if(d.kind==="prompt_helper") return <PromptHelperPanel d={d}/>;
  if(d.kind==="audio") return <AudioPanel d={d}/>;
  if(d.kind==="stager") return <StagerPanel d={d}/>;
  if(d.kind==="marketing"||d.kind==="marketing_upload") return <MarketingUpload d={d}/>;
  if(d.kind==="model_upload"||d.kind==="model_settings"||d.kind==="steps_upload"||d.kind==="upload_maps"||d.kind==="pose"||d.kind==="material"){
    return <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_340px]">
      <PreviewPanel d={d}/>
      <aside className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        {d.tabs&&<><L>Creation Method / Generation Mode</L>
          <div className="space-y-1.5">{d.tabs.map((t,i)=><button type="button" key={t} className={"block w-full rounded-lg border px-2.5 py-2 text-left text-xs "+(i===0?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-300")}>
            <b>{t}</b>{d.tabHints?.[i]&&<span className="mt-0.5 block text-[11px] text-zinc-400">{d.tabHints[i]}</span>}
          </button>)}</div></>}
        {d.presets&&<><L>Try this prompt</L><div className="flex flex-wrap gap-1.5">{d.presets.map(p=><button type="button" key={p} className="rounded-lg border border-zinc-700/40 bg-zinc-800/40 px-2.5 py-1.5 text-xs text-zinc-300">{p}</button>)}</div></>}
        {(d.kind==="pose"||d.kind==="upload_maps")&&<><L required={d.kind==="upload_maps"}>Source Image</L>
          <div className="flex min-h-[120px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-4 text-center">
            <Upload size={20} className="text-zinc-400"/>
            <b className="text-sm text-zinc-200">{d.uploadHint||"Drag & drop or click to upload"}</b>
            <Btn>{d.ctaUpload||"Choose from Dashboard"}</Btn>
          </div></>}
        {(d.kind==="model_upload"||d.kind==="model_settings"||d.kind==="steps_upload")&&<><L>3D Model / File</L>
          <div className="flex min-h-[120px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-4 text-center">
            <Upload size={20} className="text-zinc-400"/>
            <b className="text-sm text-zinc-200">{d.uploadHint||"Drop your file here or click to browse"}</b>
            {d.ctaUpload&&<Btn>{d.ctaUpload}</Btn>}
          </div></>}
        {d.kind==="material"&&<><L required>Material Description / Prompt</L>
          <textarea className="min-h-[90px] w-full rounded-xl border border-zinc-700/50 bg-zinc-950 p-3 text-sm" placeholder={d.placeholder||"Describe the material..."}/></>}
        {d.kind==="pose"&&<><L>Reference Pose</L>
          <div className="flex flex-wrap gap-1.5">{(d.options||[]).filter(o=>/Pose|Upload Your/.test(o)).map(o=><button type="button" key={o} className="rounded-lg border border-zinc-700/40 px-2.5 py-1.5 text-[11px] text-zinc-300">{o}</button>)}</div></>}
        {d.optionGroups&&Object.entries(d.optionGroups).map(([k,vals])=><div key={k}><L>{k}</L><ChipRow items={vals}/></div>)}
        {d.options&&!d.optionGroups&&<><L>Options</L><ChipRow items={d.options}/></>}
        {d.presets&&<><L>Try this prompt</L><div className="flex flex-wrap gap-1.5">{d.presets.map(p=><button type="button" key={p} className="rounded-lg border border-zinc-700/40 bg-zinc-800/40 px-2.5 py-1.5 text-xs text-zinc-300">{p}</button>)}</div></>}
        {d.models&&<><L>AI Model</L>
          <div className="space-y-1">{d.models.map((m,i)=><button type="button" key={m} className={"block w-full rounded-lg border px-2 py-1.5 text-left text-[11px] "+(i===0?"border-indigo-500/40 bg-indigo-500/10 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{m}</button>)}</div></>}
        {d.steps&&<div className="space-y-1.5">{d.steps.map(s=><div key={s} className="rounded-lg bg-zinc-800/50 px-2.5 py-2 text-xs text-zinc-300">{s}</div>)}</div>}
        {d.extras&&<div className="flex flex-wrap gap-1.5">{d.extras.map(e=><Btn key={e}>{e}</Btn>)}</div>}
        {d.cost&&<div className="text-xs text-zinc-500">{d.cost}</div>}
        <Btn primary className="w-full !py-2.5">{d.action}</Btn>
      </aside>
    </div>;
  }
  // fallback
  return <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_340px]">
    <PreviewPanel d={d}/>
    <aside className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <L>Source</L><DropImage/>
      <Btn primary className="w-full">{d.action||"Run Tool"}</Btn>
    </aside>
  </div>;
}

export function ToolboxPage(){
  const {tool}=useParams();
  const d=toolPages[tool]||{title:"3D AI Studio Tool",subtitle:"Utility workspace",kind:"upload_maps",action:"Run Tool"};
  return <>
    <div className="p-4">
      <header className="mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>TOOLBOX</Badge>
          {d.kind==="viewer"&&<Badge>FREE</Badge>}
          {/Beta|BETA/.test(d.subtitle||"")&&<Badge>BETA</Badge>}
        </div>
        <h1 className="mt-1 text-2xl font-semibold text-zinc-50">{d.title}</h1>
        <p className="max-w-3xl text-sm text-zinc-400">{d.subtitle}</p>
      </header>
      <ToolBody d={d}/>
      <div className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/30 p-4">
        <h2 className="text-sm font-semibold text-zinc-200">Related tools</h2>
        <div className="mt-2 flex flex-wrap gap-2">
          <NavLink to="/ImageTo3D/app"><Btn>Image to 3D</Btn></NavLink>
          <NavLink to="/Tools/Remesh"><Btn>Remesh</Btn></NavLink>
          <NavLink to="/Tools/Viewer3D"><Btn>3D Viewer</Btn></NavLink>
          <NavLink to="/Tools/GLBCompression"><Btn>GLB Compressor</Btn></NavLink>
          <NavLink to="/Tools/PromptHelper"><Btn>Prompt Helper</Btn></NavLink>
        </div>
      </div>
    </div>
  </>;
}

export function SVGTool({text=false}){
  return <>
    <div className="p-4">
      <div className="flex flex-wrap items-center gap-2"><Badge>FREE</Badge><Badge>{text?"3D TEXT":"SVG"}</Badge></div>
      <h1 className="mt-1 text-2xl font-semibold text-zinc-50">{text?"3D Text Generator":"SVG to 3D"}</h1>
      <p className="text-sm text-zinc-400">{text?"Turn any font into a 3D model":"Transform SVG files into 3D models"}</p>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        <aside className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          {text?<><L>Text</L>
            <textarea defaultValue={"3D AI\nStudio"} className="min-h-[80px] w-full rounded-xl border border-zinc-700/50 bg-zinc-950 p-3 text-sm"/>
            <ChipRow items={["Typography","Logo","Geometry","Material","Environment","Background","View"]}/>
            <L>Alignment</L><ChipRow items={["Left","Center","Right"]}/>
            <Btn primary className="w-full">Download GLB (3D)</Btn><Btn className="w-full">Download PNG</Btn>
          </>:<><L>Upload SVG</L>
            <div className="flex min-h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 p-4 text-center">
              <Upload size={20} className="text-zinc-400"/><b className="text-sm text-zinc-200">Click or drop your SVG here</b><span className="text-xs text-zinc-500">Max 5 MB</span>
            </div>
            <Btn primary className="w-full">Convert to 3D</Btn></>}
        </aside>
        <section className="min-h-[380px]">
          <Viewport3D
            textMode={!!text}
            hint={text?"3D Text Generator":"SVG to 3D"}
            subhint="WebGL preview · Click and drag to rotate"
          />
        </section>
      </div>
    </div>
  </>;
}

export function SplatPage({viewer=false}){
  return <>
    <div className="grid min-h-full grid-cols-1 lg:grid-cols-[1fr_340px]">
      <section className="min-h-[420px] border-r border-zinc-800/40 p-4">
        <Viewport3D
          hint={viewer?"Drop a .splat file to view it":"Your Gaussian splat will appear here"}
          subhint={viewer?"Orbit, zoom and pan in real time":"Upload an image and click Generate"}
        />
      </section>
      <aside className="space-y-3 p-4">
        <Badge>FREE GAUSSIAN SPLAT {viewer?"VIEWER":"GENERATOR"}</Badge>
        <h2 className="text-lg font-semibold text-zinc-50">{viewer?"Load a splat":"Turn Images Into Gaussian Splats"}</h2>
        <p className="text-xs text-zinc-400">{viewer?"Explore photorealistic Gaussian splats in the browser.":"Upload an image and generate a photorealistic 3D splat you can explore in real time."}</p>
        {viewer?<><DropModel/><L>Or load from a URL</L>
          <input className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm" placeholder="https://…/model.splat"/>
          <L>Try a sample</L><ChipRow items={["Garden","Bonsai","Kitchen","Bicycle"]}/>
        </>:<><DropImage/><L>Model Settings</L><L>Model Seed · optional</L>
          <input className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm" placeholder="Random"/>
          <Btn primary className="w-full !py-2.5">Generate Gaussian Splat</Btn></>}
        <div className="text-[11px] text-zinc-500">Free to try online · Real-time and photorealistic</div>
      </aside>
    </div>
  </>;
}
