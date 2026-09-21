import React,{useMemo,useState} from "react";
import {NavLink,useParams} from "react-router-dom";
import {Search,Upload,WandSparkles,ChevronDown,Sparkles,CheckCircle2} from "lucide-react";
import {Badge,Btn,ChipRow,PanelLabel,SettingRow,Toggle} from "./components.jsx";
import {imageGroups,categories} from "./data.js";

const slugMap={
  "Nano Banana 2 Lite - Generate":"nano-banana-2-lite-inf",
  "ImageGen 3":"imagegen-3","Nano Banana 2 - Generate":"nano-banana-2-inf",
  "Nano Banana Pro - Generate":"nano-banana-pro-inf","Nano Banana - Generate":"nano-banana-inf",
  "GPT Image 2":"gpt-image-2","GPT Image 2.5 Flare":"gpt-image-2-5-flare",
  "GPT Image 2.5 Sunburst":"gpt-image-2-5-sunburst",
  "SeedDream v5 Lite - Generate":"seedream-v5-lite-generate","Seedream 5 Pro":"seedream-5-pro-generate",
  "Flux 2":"flux2","Flux 2 Flex":"flux2-flex","Flux 2 Pro":"flux2-pro","ImageGen 3 Fast":"imagegen-3-fast",
  "Flux":"flux","Flux Pro":"flux-pro","Flux Dev":"flux-pro-1-1","GPT-Image-1":"gpt-image-1",
  "GPT Image 2 Edit":"gpt-image-2-edit","Gemini Edit":"gemini-edit-inf",
  "Pose Generator":"pose-generator","Custom Style Reference":"style-reference-custom",
  "Remove Background":"remove-background","Sketch → Image":"sketch-to-image"
};
const slugOf=name=>slugMap[name]||name.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/(^-|-$)/g,"");

function StudioSide({active,query,onQuery}){
  return <aside className="border-r border-zinc-700/30 bg-zinc-950/40 p-4">
    <div className="rounded-xl border border-zinc-700/40 bg-zinc-800/30 p-3">
      <div className="flex items-center justify-between"><Badge>Quick Start</Badge><ChevronDown size={14} className="text-zinc-400"/></div>
      <p className="mb-2 mt-1.5 text-xs text-zinc-400">We choose the best model for you</p>
      <NavLink to="/ImageGeneration/generate" className="flex items-center gap-2 py-2 text-xs text-sky-300 hover:text-sky-200"><WandSparkles size={14}/>Create an image now</NavLink>
      <NavLink to="/ImageGeneration/edit" className="flex items-center gap-2 py-2 text-xs text-sky-300 hover:text-sky-200"><Upload size={14}/>Edit an image now</NavLink>
    </div>
    <div className="mb-2.5 mt-6">
      <span className="text-[11px] text-zinc-400">Or choose the model yourself</span>
      <h1 className="mt-1 text-lg font-semibold text-zinc-50">Choose a Category</h1>
    </div>
    <div className="flex flex-col gap-0.5">
      {categories.map(([id,l])=>(
        <NavLink key={id} to={"/ImageGeneration/"+id} className={
          "flex items-center gap-2 rounded-lg border-l-2 px-2 py-2.5 text-[13px] transition "+
          (id===active?"border-l-indigo-500 bg-zinc-800/60 font-semibold text-zinc-50":"border-l-transparent text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-200")
        }>
          <span>{l}</span>{id==="utilities"&&<em className="ml-auto rounded-full border border-amber-500/30 bg-amber-400/10 px-1.5 py-0.5 text-[9px] not-italic text-amber-300">NEW</em>}
        </NavLink>
      ))}
    </div>
    <div className="my-4 flex items-center gap-2 rounded-lg border border-zinc-700/50 bg-zinc-900/70 px-3">
      <Search size={14} className="text-zinc-500"/>
      <input value={query} onChange={e=>onQuery(e.target.value)} className="h-9 w-full bg-transparent text-xs outline-none placeholder:text-zinc-600" placeholder="Search tools..."/>
    </div>
    <div className="flex gap-1.5 text-[11px] text-zinc-500"><span>Generate guide</span><i>·</i><span>Edit guide</span></div>
  </aside>;
}

function ToolCard({item,group,featured}){
  const [name,desc,badge]=item;
  return <NavLink className={"relative rounded-lg border border-zinc-700/40 bg-zinc-800/25 transition hover:border-zinc-600 hover:bg-zinc-800/45"+(featured?" mt-3":"")} to={"/ImageGeneration/"+group+"/"+slugOf(name)}>
    {featured&&<div className="absolute -top-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 whitespace-nowrap rounded-full border border-amber-500/30 bg-[#2a220f] px-2.5 py-1 text-[10px] font-bold tracking-wide text-amber-300"><Sparkles size={11}/>BEST FOR GETTING STARTED</div>}
    <div className="aspect-[8/5] rounded-lg bg-zinc-900/80 grid place-items-center text-indigo-300"><WandSparkles size={34}/></div>
    <div className="p-3">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[11px] text-zinc-500">Click to open tool</span>
        {badge&&<Badge>{badge}</Badge>}
      </div>
      <h3 className="text-sm font-semibold text-zinc-50">{name}</h3>
      <p className="mt-1 line-clamp-2 text-xs text-zinc-400">{desc}</p>
    </div>
  </NavLink>;
}

export function ImageStudio(){
  const {category="generate"}=useParams();
  const group=imageGroups[category]?category:"generate";
  const [query,setQuery]=useState("");
  const tools=useMemo(()=>{
    const list=imageGroups[group]||[];
    const q=query.trim().toLowerCase();
    if(!q) return list;
    return list.filter(([name,desc,badge])=>
      (name+" "+(desc||"")+" "+(badge||"")).toLowerCase().includes(q)
    );
  },[group,query]);

  return <>
    <div className="grid min-h-full grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)]">
      <StudioSide active={group} query={query} onQuery={setQuery}/>
      <section className="p-4">
        <div className="mb-3 flex items-center justify-between text-xs text-zinc-500">
          <span>{tools.length} tools in {group}</span>
          {query&&<button type="button" className="text-indigo-300" onClick={()=>setQuery("")}>Clear search</button>}
        </div>
        {tools.length===0?(
          <div className="rounded-xl border border-dashed border-zinc-700 px-6 py-16 text-center text-sm text-zinc-400">
            No tools match “{query}”
          </div>
        ):(
          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
            {tools.map((x,i)=><ToolCard key={x[0]} item={x} group={group} featured={!query&&group==="generate"&&i===0}/>)}
          </div>
        )}
      </section>
    </div>
  </>;
}

export function ToolDetail(){
  const {category,tool}=useParams();
  const pretty=(tool||"AI Tool").split("-").map(x=>x?x[0].toUpperCase()+x.slice(1):x).join(" ");
  const convertPose=category==="convert"&&tool==="pose-generator";
  const styleRef=category==="style-reference"&&tool==="style-reference-custom";
  const removeBg=category==="utilities"&&tool==="remove-background";
  const edit=category==="edit";
  const generate=category==="generate";
  const examples=["⚔️ Battle Axe","🧙 Stylized Warrior","🐉 Baby Dragon","👹 Orc Chieftain","🧪 Potion Bottle"];
  const [prompt,setPrompt]=useState("");
  const [example,setExample]=useState("");
  const [status,setStatus]=useState("idle"); // idle|running|done
  const [progress,setProgress]=useState(0);
  const [view,setView]=useState("View 1");

  const runMock=()=>{
    if(status==="running") return;
    setStatus("running");
    setProgress(0);
    const t0=Date.now();
    const dur=1800;
    const id=setInterval(()=>{
      const p=Math.min(100,Math.round((Date.now()-t0)/dur*100));
      setProgress(p);
      if(p>=100){ clearInterval(id); setStatus("done"); }
    },80);
  };

  return <>
    <div className="flex items-center justify-between gap-2 border-b border-zinc-800/60 px-4 py-3">
      <NavLink to={"/ImageGeneration/"+category} className="text-xs text-zinc-400 hover:text-zinc-200">← Back to all Tools</NavLink>
      <b className="text-sm text-zinc-100">{pretty}</b>
      <div className="flex gap-1.5"><Btn>Prompt Helper</Btn><Btn>Prompt Library</Btn></div>
    </div>
    <div className="grid min-h-full grid-cols-1 lg:grid-cols-[1fr_340px]">
      <section className="relative flex flex-col border-r border-zinc-800/40 p-4">
        <div className="mb-3 flex items-center gap-2">
          <Badge>Image Studio</Badge>
          <span className="text-xs text-zinc-500">{category}</span>
          <div className="ml-auto flex gap-1">{["View 1","View 2","View 3","Tools"].map(x=>
            <button type="button" key={x} onClick={()=>setView(x)} className={"rounded-md border px-2 py-1 text-[11px] "+(view===x?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{x}</button>)}</div>
        </div>
        <div className="flex flex-1 flex-col items-center justify-center gap-3 rounded-xl border border-zinc-800/50 bg-zinc-950/30 p-6 text-center">
          {status==="idle"&&<>
            <WandSparkles size={48} className="text-zinc-600"/>
            <h2 className="text-lg font-semibold text-zinc-100">{removeBg?"Canvas Ready":convertPose?"Transform any image into a new style.":styleRef?"Style Reference Generator":edit?"What would you like to change?":"What would you like to create?"}</h2>
            <p className="text-sm text-zinc-400">Describe anything in the prompt. Choose examples below or type freely.</p>
          </>}
          {status==="running"&&<>
            <div className="h-2 w-64 max-w-full overflow-hidden rounded-full bg-zinc-800"><div className="h-full bg-indigo-500 transition-all" style={{width:progress+"%"}}/></div>
            <b className="text-sm text-zinc-200">Generating mock result… {progress}%</b>
            <span className="text-xs text-zinc-500">Local demo · no cloud API</span>
          </>}
          {status==="done"&&<>
            <div className="flex h-40 w-full max-w-md items-center justify-center rounded-xl border border-indigo-500/30 bg-indigo-500/10">
              <CheckCircle2 size={48} className="text-indigo-300"/>
            </div>
            <b className="text-sm text-zinc-100">Mock generation complete</b>
            <p className="max-w-md text-xs text-zinc-400">{prompt||example||"Untitled prompt"} · view {view}</p>
            <Btn onClick={()=>setStatus("idle")}>Generate another</Btn>
          </>}
        </div>
      </section>
      <aside className="space-y-3 p-4">
        <div className="flex items-center justify-between"><h2 className="text-sm font-semibold text-zinc-100">{pretty}</h2><Btn>Collapse Settings</Btn></div>
        {(edit||convertPose||styleRef||removeBg)&&<><PanelLabel>{styleRef?"STYLE REFERENCE IMAGES (0/10)":"Upload Image"}</PanelLabel>
          <div className="flex min-h-[120px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-4">
            <Upload size={20} className="text-zinc-400"/><b className="text-sm text-zinc-200">Drop, paste, or click to select</b><span className="text-xs text-zinc-500">{styleRef?"Up to 10 reference images":"PNG, JPG, WebP"}</span>
          </div></>}
        {!removeBg&&<><PanelLabel required>Prompt</PanelLabel>
          <textarea value={prompt} onChange={e=>setPrompt(e.target.value)}
            className="min-h-[100px] w-full rounded-xl border border-zinc-700/50 bg-zinc-900/60 p-3 text-sm text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-indigo-500/50"
            placeholder={edit?"Describe your edit...":"Describe what you want to generate, e.g., 'stylized 3D sword, low-poly'..."}/>
        </>}
        <PanelLabel>Try an example</PanelLabel>
        <div className="flex flex-wrap gap-1.5">{examples.map(x=>
          <button type="button" key={x} onClick={()=>{setExample(x);setPrompt(x.replace(/^[^\s]+\s/,""));}}
            className={"rounded-lg border px-2.5 py-1.5 text-xs "+(example===x?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 bg-zinc-800/40 text-zinc-300")}>{x}</button>)}</div>
        <PanelLabel>Number of Images</PanelLabel>
        <ChipRow items={["1","2","3","4"]}/>
        {generate&&<><PanelLabel>Acceleration</PanelLabel><ChipRow items={["None","Regular","High"]}/></>}
        <details className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
          <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-zinc-400">ADVANCED +</summary>
          <div className="mt-2 divide-y divide-zinc-800">
            <SettingRow title="Seed" sub="Random by default"><input className="w-20 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs" placeholder="Random"/></SettingRow>
            <SettingRow title="Email When Complete" sub="Notify on completion"><Toggle/></SettingRow>
          </div>
        </details>
        <Btn primary className="w-full !py-2.5" disabled={status==="running"} onClick={runMock}>
          {status==="running"?"Generating…":removeBg?"Run":"Generate"}
          <span className="ml-1 text-[10px] opacity-80">{convertPose?"6 credits":removeBg?"1 credit":"4 credits"}</span>
        </Btn>
      </aside>
    </div>
  </>;
}
