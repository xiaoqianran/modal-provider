import React,{useState} from "react";
import {ChevronDown,Palette,Upload,X} from "lucide-react";
import {Badge,Btn,ChipRow,PanelLabel,SettingRow,Toggle} from "./components.jsx";
import {modelCatalog} from "./data.js";
import {Viewport3DUpload} from "./three-viewport.jsx";

function ModelPicker({onClose}){
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
    <div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-2xl border border-zinc-700/50 bg-zinc-900 p-4 shadow-2xl">
      <div className="mb-3 flex items-center gap-2">
        <input className="h-9 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-3 text-sm outline-none" placeholder="Search models..."/>
        <ChipRow items={["All","Single image","Multi-view"]}/>
        <button type="button" onClick={onClose} className="rounded-lg p-1 text-zinc-400"><X size={16}/></button>
      </div>
      <div className="space-y-2">
        {modelCatalog.map(m=><article key={m[0]} className="flex items-start gap-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="w-24 text-[11px] uppercase tracking-wide text-zinc-500">{m[1]}</div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-zinc-100">{m[0]} {m[6]&&<Badge>{m[6]}</Badge>}</h3>
            <p className="text-xs text-zinc-400">{m[2]}</p>
            <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-zinc-500"><span>{m[5]}</span><span>{m[4]}</span><span>{m[3]}</span></div>
          </div>
          <Btn>Select</Btn>
        </article>)}
      </div>
    </div>
  </div>;
}

export function ThreeDWorkspace({mode}){
  const img=mode==="image";
  const [picker,setPicker]=useState(false);
  const [advanced,setAdvanced]=useState(false);
  const [batchGate,setBatchGate]=useState(false);
  const [gen,setGen]=useState("idle");
  const [progress,setProgress]=useState(0);
  const runGenerate=()=>{
    if(gen==="running") return;
    setGen("running"); setProgress(0);
    const t0=Date.now();
    const id=setInterval(()=>{
      const p=Math.min(100,Math.round((Date.now()-t0)/2200*100));
      setProgress(p);
      if(p>=100){clearInterval(id);setGen("done");}
    },90);
  };
  return <>
    <div className="grid min-h-full grid-cols-1 lg:grid-cols-[1fr_360px]">
      <section className="relative flex flex-col border-r border-zinc-800/40 p-4">
        <div className="mb-3"><span className="inline-flex items-center rounded-lg border border-zinc-700/40 bg-zinc-800/40 px-2.5 py-1.5 text-xs text-zinc-200">Default Project</span></div>
        <div className="mb-4">
          <Badge>{img?"IMAGE TO 3D":"TEXT TO 3D"}</Badge>
          <h1 className="mt-2 text-2xl font-semibold text-zinc-50">{img?"Turn Images Into 3D Assets":"Turn Ideas Into 3D Assets"}</h1>
          <p className="text-sm text-zinc-400">Professional models in seconds, not hours</p>
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-zinc-300">
            {[["~90s","Generation"],["GLB · FBX · STL","Exports"],["Commercial","Use"],["1M+","Users"]].map(([a,b])=><span key={a}>{a}<small className="block text-[10px] text-zinc-500">{b}</small></span>)}
          </div>
        </div>
        <div className="relative min-h-[360px] flex-1">
          <Viewport3DUpload
            withToggles
            emptyHint={img?"Drop an image or try an example!":"Describe your idea or try an example!"}
            emptySub="Local Three.js preview · drag to orbit"
          />
          {gen==="running"&&(
            <div className="absolute inset-x-4 bottom-4 rounded-xl border border-zinc-700/60 bg-zinc-950/90 p-3">
              <div className="mb-2 flex justify-between text-xs text-zinc-300"><span>Generating mock mesh…</span><span>{progress}%</span></div>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-800"><div className="h-full bg-indigo-500 transition-all" style={{width:progress+"%"}}/></div>
            </div>
          )}
          {gen==="done"&&(
            <div className="absolute right-4 top-4 rounded-lg border border-emerald-500/30 bg-emerald-950/70 px-3 py-2 text-xs text-emerald-300">
              Mock GLB ready · local only
            </div>
          )}
        </div>
      </section>
      <aside className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-zinc-100">{img?"IMAGE TO 3D":"TEXT TO 3D"}</h2>
          <div className="flex flex-wrap items-center gap-1.5">
            <Btn>Learn more</Btn><Btn>API</Btn>
            <button type="button" className="flex items-center gap-1.5 text-[11px] text-zinc-400" onClick={()=>setBatchGate(true)}><Toggle/>Batch Mode</button>
          </div>
        </div>
        <button type="button" onClick={()=>setPicker(true)} className="flex w-full items-center justify-between rounded-xl border border-zinc-700/50 bg-zinc-800/40 p-3 text-left">
          <div><b className="block text-sm text-zinc-100">Prism 3.1</b><small className="text-xs text-zinc-400">Standard · 35 credits</small></div><ChevronDown size={16} className="text-zinc-400"/>
        </button>
        <div className="flex flex-wrap gap-1.5">{["Prism 3.1","Hunyuan 3.1 Pro","Tripo P2","All models"].map((x,i)=><button type="button" key={x} onClick={()=>x==="All models"&&setPicker(true)} className={"rounded-lg border px-2.5 py-1.5 text-xs "+(i===0?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 bg-zinc-800/40 text-zinc-400")}>{x}</button>)}</div>
        {img?<>
          <PanelLabel required>Upload Image</PanelLabel>
          <div className="flex min-h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-4">
            <Upload size={22} className="text-zinc-400"/><b className="text-sm text-zinc-200">Upload an image</b>
            <span className="text-xs text-zinc-500">Click or drag & drop · Ctrl+V to paste</span>
          </div>
          <PanelLabel>No image? Try one of these</PanelLabel>
          <ChipRow items={["Character","Battle Axe","Orc Bust","Sofa","Turtle"]}/>
        </>:<>
          <PanelLabel required>Text Prompt</PanelLabel>
          <textarea className="min-h-[120px] w-full rounded-xl border border-zinc-700/50 bg-zinc-900/60 p-3 text-sm outline-none placeholder:text-zinc-600" placeholder='Describe what you want to generate, e.g. "a stylized 3D adventurer..."'/>
          <ChipRow items={["🗡️ Knight","⚔️ Battle Axe","🦊 Stylized Fox","👹 Orc Bust"]}/>
        </>}
        <PanelLabel>Texture Quality</PanelLabel><ChipRow items={["Standard","Ultra","Max"]}/>
        <PanelLabel>Mesh Quality</PanelLabel><ChipRow items={["Standard","Ultra"]}/>
        <PanelLabel>Material Type</PanelLabel><ChipRow items={["Shaded","PBR"]}/>
        <button type="button" onClick={()=>setAdvanced(!advanced)} className="flex w-full items-center justify-between rounded-xl border border-zinc-700/40 bg-zinc-900/40 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
          Advanced <Badge>{img?"10":"9"}</Badge><ChevronDown size={14} className={advanced?"rotate-180":""}/>
        </button>
        {advanced&&<div className="divide-y divide-zinc-800 rounded-xl border border-zinc-800 bg-zinc-900/40 px-3">
          <SettingRow title="Polygon Count (Max Faces)" sub="Auto"><input className="w-20 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs" placeholder="Auto"/></SettingRow>
          <SettingRow title="Auto Size" sub="Choose scale automatically"><Toggle on/></SettingRow>
          <SettingRow title="Model Seed" sub="Random"><input className="w-20 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs" placeholder="Random"/></SettingRow>
          <SettingRow title="Texture Seed" sub="Random"><input className="w-20 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs" placeholder="Random"/></SettingRow>
          <SettingRow title="Enable Texturing" sub="Generate textures with geometry"><Toggle on/></SettingRow>
          <SettingRow title="Smart Low-Poly" sub="Optimize polygon distribution"><Toggle/></SettingRow>
          <SettingRow title="Email When Complete" sub="Send completion email"><Toggle/></SettingRow>
          <SettingRow title="Optimize Input Images" sub="Pre-process source images"><Toggle on/></SettingRow>
        </div>}
        <div className="text-xs text-zinc-400">Pro Tip: Edit your image first for better results</div>
        <Btn primary className="w-full !py-2.5" disabled={gen==="running"} onClick={runGenerate}>
          {gen==="running"?"Generating…":"Generate 3D Model"}
          <span className="text-[10px] opacity-80">40 credits · Est. 3-5 min</span>
        </Btn>
      </aside>
    </div>
    {picker&&<ModelPicker onClose={()=>setPicker(false)}/>}
    {batchGate&&<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="relative w-full max-w-sm rounded-2xl border border-zinc-700/50 bg-zinc-900 p-5">
        <button type="button" className="absolute right-3 top-3 text-zinc-400" onClick={()=>setBatchGate(false)}><X size={16}/></button>
        <Badge>PAID FEATURE</Badge>
        <h2 className="mt-2 text-lg font-semibold text-zinc-100">Batch Mode</h2>
        <p className="mt-1 text-sm text-zinc-400">Batch generation is a paid-plan feature. The source product opens an upgrade experience here.</p>
        <Btn primary className="mt-4 w-full">Unlock All Tools</Btn>
      </div>
    </div>}
  </>;
}

export function TextureGenerator(){
  return <>
    <div className="grid min-h-full grid-cols-1 lg:grid-cols-[1fr_360px]">
      <section className="flex flex-col border-r border-zinc-800/40 p-4">
        <Badge>TEXTURE AI</Badge>
        <h1 className="mt-2 text-2xl font-semibold text-zinc-50">Texture Any 3D Model with AI</h1>
        <p className="text-sm text-zinc-400">AI generated textures in seconds, not hours</p>
        <div className="mt-6 flex flex-1 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-800 text-center">
          <Palette size={56} className="text-zinc-600"/>
          <b className="text-sm text-zinc-200">Upload a GLB / FBX / OBJ ≤ 10 MB</b>
          <span className="max-w-sm text-xs text-zinc-500">Upload a 3D model to get started. Drag and drop a GLB, FBX, or OBJ file into the sidebar, or select one from your dashboard.</span>
        </div>
      </section>
      <aside className="space-y-3 p-4">
        <div className="flex gap-1.5"><Btn>Learn more</Btn><Btn>API</Btn></div>
        <PanelLabel>AI Texturing Engine</PanelLabel><ChipRow items={["Forge","Prism","Meshy","Hunyuan","Hitem3D"]}/>
        <PanelLabel required>3D Model</PanelLabel>
        <div className="flex min-h-[120px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-4 text-center">
          <Upload size={20} className="text-zinc-400"/><b className="text-sm text-zinc-200">Upload 3D Model</b>
          <span className="text-xs text-zinc-500">GLB, FBX, OBJ · Max 10MB · or Choose from Dashboard</span>
        </div>
        <PanelLabel>Texture Prompt Type</PanelLabel><ChipRow items={["Text","Image","Multi-View"]}/>
        <Btn className="w-full">Generate reference image with AI</Btn>
        <PanelLabel>Prompt</PanelLabel>
        <textarea className="min-h-[90px] w-full rounded-xl border border-zinc-700/50 bg-zinc-900/60 p-3 text-sm outline-none" placeholder="Weathered bronze with emerald patina..."/>
        <PanelLabel>Texture Quality</PanelLabel><ChipRow items={["Fast","Standard","Detailed","Extreme"]}/>
        <Btn className="w-full">Advanced Settings</Btn>
        <Btn primary className="w-full !py-2.5">Generate Texture</Btn>
      </aside>
    </div>
  </>;
}

export function TexturePainter(){
  return <>
    <div className="border-b border-zinc-800 bg-zinc-800/30 px-4 py-3">
      <div className="flex gap-2">
        <Badge>BETA</Badge>
        <div>
          <b className="block text-[13px] text-zinc-50">Try Texture AI 2.0 BETA</b>
          <span className="block text-xs text-zinc-400">This is the legacy version. Our new Texture AI 2.0 offers improved stability, better results, and more features.</span>
          <small className="mt-1 block text-[11px] text-zinc-500">Open Settings → Join Beta → Access new Texture AI 2.0 in the Sidebar on the left</small>
        </div>
      </div>
    </div>
    <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-2 text-xs text-zinc-400"><b className="text-emerald-400">Texture AI FREE</b><span>Available with any subscription plan</span></div>
    <div className="grid min-h-full grid-cols-1 lg:grid-cols-[1fr_320px]">
      <section className="relative border-r border-zinc-800/40 p-4">
        <div className="mb-3 flex flex-wrap gap-1.5">{["Upload","Save","Help","Documentation"].map(x=><Btn key={x}>{x}</Btn>)}</div>
        <div className="min-h-[420px]">
          <Viewport3DUpload emptyHint="3D Viewer" emptySub="Upload a model to paint directly in 3D"/>
        </div>
      </section>
      <aside className="space-y-3 p-4">
        <div className="flex gap-1">{["Model","Tex 4K","Res 4K","Export"].map((x,i)=><button type="button" key={x} className={"rounded-md px-2.5 py-1.5 text-xs "+(i===0?"bg-indigo-500/15 text-indigo-200 border border-indigo-500/30":"text-zinc-400 border border-transparent")}>{x}</button>)}</div>
        <h3 className="text-sm font-semibold text-zinc-100">Paint Preview</h3>
        {[["Brush Size","0.10"],["Brush Hardness","0.50"],["Brush Strength","0.50"],["Creativity",""]].map(([l,v])=>(
          <div key={l}><label className="text-[11px] uppercase tracking-wide text-zinc-500">{l}{v&&` · ${v}`}</label><input type="range" className="mt-1 w-full"/></div>
        ))}
        <PanelLabel>Prompt</PanelLabel><textarea className="min-h-[70px] w-full rounded-xl border border-zinc-700/50 bg-zinc-900/60 p-2 text-sm"/>
        <PanelLabel>Negative Prompt</PanelLabel><textarea className="min-h-[50px] w-full rounded-xl border border-zinc-700/50 bg-zinc-900/60 p-2 text-sm"/>
        <Btn primary className="w-full !py-2.5">Generate Texture</Btn>
      </aside>
    </div>
  </>;
}
