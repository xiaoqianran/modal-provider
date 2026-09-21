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

const TEX_ENGINES=["Prism","Forge","Meshy","Hunyuan","Hitem3D"];

const ENGINE_META={
  Prism:{
    blurb:"Best overall · 4K/8K · Prism 3.2 default",
    credits:"20 fast/standard · 30 HD · 35 max",
    promptTypes:["Text","Image","Multi-View"],
    qualities:["Fast","Standard","HD","Max"],
  },
  Forge:{
    blurb:"Image reference-based texturing",
    credits:"20",
    promptTypes:["Image"],
    qualities:["Basic","High"],
  },
  Meshy:{
    blurb:"Clean UV · Meshy-7 recommended",
    credits:"25",
    promptTypes:["Text","Image"],
    qualities:["Standard","HD"],
  },
  Hunyuan:{
    blurb:"Tencent PBR · text OR image (not both)",
    credits:"20",
    promptTypes:["Text","Image"],
    qualities:["Standard","HD"],
    maxMB:200,
  },
  Hitem3D:{
    blurb:"Extra engine listed in product UI",
    credits:"—",
    promptTypes:["Text","Image","Multi-View"],
    qualities:["Standard","HD"],
  },
};

function engineCredits(engine,quality){
  if(engine==="Prism"){
    if(quality==="HD") return 30;
    if(quality==="Max") return 35;
    return 20;
  }
  const n=Number(ENGINE_META[engine]?.credits);
  return Number.isFinite(n)?n:null;
}

export function TextureGenerator(){
  const [engine,setEngine]=useState("Prism");
  const [promptType,setPromptType]=useState("Text");
  const [quality,setQuality]=useState("Standard");
  const [pbr,setPbr]=useState(true);
  const [neutralLight,setNeutralLight]=useState(true);
  const [alignment,setAlignment]=useState("Original image");
  const [meshyModel,setMeshyModel]=useState("Meshy-7");
  const [preserveUv,setPreserveUv]=useState(false);
  const [materialType,setMaterialType]=useState("PBR");
  const [forgeRes,setForgeRes]=useState("Basic");
  const [hunyuanMode,setHunyuanMode]=useState("Text prompt");
  const [textureSeed,setTextureSeed]=useState("");
  const [advanced,setAdvanced]=useState(false);
  const [prompt,setPrompt]=useState("");
  const [hasModel,setHasModel]=useState(false);
  const [hasRef,setHasRef]=useState(false);
  const [gen,setGen]=useState("idle");
  const [progress,setProgress]=useState(0);
  const meta=ENGINE_META[engine];
  const credits=engineCredits(engine,quality);
  const maxMB=meta.maxMB||120;

  const onEngine=(name)=>{
    setEngine(name);
    const types=ENGINE_META[name].promptTypes;
    if(!types.includes(promptType)) setPromptType(types[0]);
    const qs=ENGINE_META[name].qualities;
    if(!qs.includes(quality)) setQuality(qs[Math.min(1,qs.length-1)]);
  };

  const runGenerate=()=>{
    if(gen==="running") return;
    if(!hasModel) return;
    if(engine==="Forge"&&!hasRef) return;
    if(engine==="Hunyuan"&&!prompt.trim()&&!hasRef) return;
    if(engine!=="Prism"&&!prompt.trim()&&!hasRef&&engine!=="Forge") {
      if(engine!=="Forge"&&!prompt.trim()&&!hasRef) return;
    }
    setGen("running"); setProgress(0);
    const t0=Date.now();
    const id=setInterval(()=>{
      const p=Math.min(100,Math.round((Date.now()-t0)/2000*100));
      setProgress(p);
      if(p>=100){clearInterval(id);setGen("done");}
    },90);
  };

  return <>
    <div className="grid min-h-full grid-cols-1 lg:grid-cols-[1fr_380px]">
      <section className="flex flex-col border-r border-zinc-800/40 p-4">
        <Badge>TEXTURE AI</Badge>
        <h1 className="mt-2 text-2xl font-semibold text-zinc-50">Texture Any 3D Model with AI</h1>
        <p className="text-sm text-zinc-400">Retexture entire models · PBR maps packed into GLB · ~1–3 min</p>
        <div className="relative min-h-[360px] flex-1" style={{height:"100%"}}>
          <Viewport3DUpload
            withToggles
            emptyHint={hasModel?"Model loaded · prompt or reference required":"Upload a GLB / FBX / OBJ"}
            emptySub={hasModel?`${engine} · ${quality}`:`Max ${maxMB}MB · Choose from Dashboard`}
          />
          {gen==="running"&&(
            <div className="absolute inset-x-4 bottom-4 rounded-xl border border-zinc-700/60 bg-zinc-950/90 p-3">
              <div className="mb-2 flex justify-between text-xs text-zinc-300"><span>{engine} mock retexture…</span><span>{progress}%</span></div>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-800"><div className="h-full bg-indigo-500 transition-all" style={{width:progress+"%"}}/></div>
            </div>
          )}
          {gen==="done"&&(
            <div className="absolute right-4 top-4 rounded-lg border border-emerald-500/30 bg-emerald-950/70 px-3 py-2 text-xs text-emerald-300">
              Mock textured GLB · {engine} · {pbr?"PBR maps":"base color"}
            </div>
          )}
        </div>
        <div className="mt-3 text-[11px] text-zinc-500">
          After generation (official): download GLB · open in Texture Painter · save to dashboard · convert format
        </div>
      </section>
      <aside className="space-y-3 p-4">
        <div className="flex flex-wrap gap-1.5"><Btn>Learn more</Btn><Btn>API</Btn></div>
        <PanelLabel required>AI Texturing Engine</PanelLabel>
        <div className="flex flex-wrap gap-1.5">
          {TEX_ENGINES.map(name=>(
            <button type="button" key={name} onClick={()=>onEngine(name)}
              className={"rounded-lg border px-2.5 py-1.5 text-xs "+(engine===name?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 bg-zinc-800/40 text-zinc-400")}>
              {name}
            </button>
          ))}
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-2.5 text-[11px] text-zinc-400">
          <b className="text-zinc-200">{engine}</b> · {meta.blurb}<br/>
          Credits: {meta.credits}{credits!=null&&quality?` · this run ~${engine==="Prism"?engineCredits(engine,quality):credits} cr`:""} · Max {maxMB}MB
        </div>
        <PanelLabel required>3D Model</PanelLabel>
        <div className="flex min-h-[100px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-3 text-center">
          <Upload size={18} className="text-zinc-400"/>
          <b className="text-sm text-zinc-200">{hasModel?"model.glb ready":"Upload 3D Model"}</b>
          <span className="text-xs text-zinc-500">GLB, FBX, OBJ · Max {maxMB}MB</span>
          <div className="flex gap-1.5">
            <Btn onClick={()=>setHasModel(true)}>{hasModel?"Replace":"Choose from Dashboard"}</Btn>
          </div>
        </div>
        <PanelLabel required={engine!=="Prism"||true}>Texture Prompt Type</PanelLabel>
        <div className="flex flex-wrap gap-1.5">
          {["Text","Image","Multi-View"].map(t=>{
            const enabled=meta.promptTypes.includes(t);
            return <button type="button" key={t} disabled={!enabled} onClick={()=>enabled&&setPromptType(t)}
              className={"rounded-lg border px-2.5 py-1.5 text-xs "+(promptType===t&&enabled?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":enabled?"border-zinc-700/40 text-zinc-400":"border-zinc-800 text-zinc-600 opacity-50")}>{t}</button>;
          })}
        </div>
        {engine==="Forge"&&<div className="rounded-lg border border-amber-500/30 bg-amber-400/10 px-2.5 py-2 text-[11px] text-amber-200">Forge requires a reference image</div>}
        {engine==="Hunyuan"&&<div className="rounded-lg border border-indigo-500/25 bg-indigo-500/10 px-2.5 py-2 text-[11px] text-indigo-200">Hunyuan: text prompt OR image — not both</div>}
        {promptType!=="Image"&&engine!=="Forge"&&<>
          <PanelLabel>Prompt</PanelLabel>
          <textarea value={prompt} onChange={e=>setPrompt(e.target.value)}
            className="min-h-[80px] w-full rounded-xl border border-zinc-700/50 bg-zinc-900/60 p-3 text-sm outline-none placeholder:text-zinc-600"
            placeholder="Weathered bronze with emerald patina…"/>
        </>}
        {engine!=="Prism"&&promptType==="Text"&&engine!=="Forge"&&<>
          <PanelLabel>Texture Prompt Type note</PanelLabel>
          <p className="text-[11px] text-zinc-500">{engine} accepts text without required reference.</p>
        </>}
        {(promptType==="Image"||promptType==="Multi-View"||engine==="Forge")&&<>
          <PanelLabel required={engine==="Forge"}>{promptType==="Multi-View"?"Reference Views":"Reference / Style Image"}</PanelLabel>
          <div className="flex min-h-[88px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-3 text-center">
            <Upload size={16} className="text-zinc-400"/>
            <b className="text-xs text-zinc-200">{hasRef?"reference ready":promptType==="Multi-View"?"Upload 4 views":"Upload reference image"}</b>
            <Btn onClick={()=>setHasRef(true)}>{hasRef?"Replace":"Choose / Upload"}</Btn>
          </div>
          {promptType!=="Multi-View"&&<Btn className="w-full" onClick={()=>setHasRef(true)}>Generate reference image with AI</Btn>}
        </>}
        <PanelLabel>Texture Quality</PanelLabel>
        <div className="flex flex-wrap gap-1.5">
          {meta.qualities.map(q=>(
            <button type="button" key={q} onClick={()=>setQuality(q)}
              className={"rounded-lg border px-2.5 py-1.5 text-xs "+(quality===q?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{q}</button>
          ))}
        </div>
        {engine==="Prism"&&<PanelLabel>Texture Alignment</PanelLabel>}
        {engine==="Prism"&&<div className="flex flex-wrap gap-1.5">
          {["Original image","Geometry"].map(a=>(
            <button type="button" key={a} onClick={()=>setAlignment(a)}
              className={"rounded-lg border px-2.5 py-1.5 text-xs "+(alignment===a?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{a}</button>
          ))}
        </div>}
        {engine==="Forge"&&<>
          <PanelLabel>Material Type</PanelLabel>
          <ChipRow items={["PBR","Shaded"]}/>
          <PanelLabel>Resolution</PanelLabel>
          <div className="flex gap-1.5">{["Basic","High"].map(r=>(
            <button type="button" key={r} onClick={()=>setForgeRes(r)} className={"rounded-lg border px-2.5 py-1.5 text-xs "+(forgeRes===r?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{r}</button>
          ))}</div>
        </>}
        {engine==="Meshy"&&<>
          <PanelLabel>AI Model</PanelLabel>
          <div className="flex flex-wrap gap-1.5">{["Meshy-7","Meshy-6","Meshy-6 Lite"].map(m=>(
            <button type="button" key={m} onClick={()=>setMeshyModel(m)} className={"rounded-lg border px-2.5 py-1.5 text-xs "+(meshyModel===m?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{m}</button>
          ))}</div>
          <SettingRow title="Preserve original UV" sub="Keep existing UV layout"><Toggle on={preserveUv}/></SettingRow>
        </>}
        {engine==="Hunyuan"&&<>
          <PanelLabel>Input Mode</PanelLabel>
          <div className="flex gap-1.5">{["Text prompt","Image prompt"].map(m=>(
            <button type="button" key={m} onClick={()=>{setHunyuanMode(m);setPromptType(m==="Text prompt"?"Text":"Image");}}
              className={"rounded-lg border px-2.5 py-1.5 text-xs "+(hunyuanMode===m?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/40 text-zinc-400")}>{m}</button>
          ))}</div>
        </>}
        <SettingRow title="PBR material maps" sub="Base color + roughness + metalness + normal"><Toggle on={pbr}/></SettingRow>
        {engine==="Prism"&&<SettingRow title="Neutral Lighting" sub="Strip lighting from reference (Prism 3.2)"><Toggle on={neutralLight}/></SettingRow>}
        <button type="button" onClick={()=>setAdvanced(v=>!v)} className="flex w-full items-center justify-between rounded-xl border border-zinc-700/40 bg-zinc-900/40 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
          Advanced Settings <ChevronDown size={14} className={advanced?"rotate-180":""}/>
        </button>
        {advanced&&<div className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
          {engine==="Prism"&&<SettingRow title="Texture seed" sub="Repeatable results"><input value={textureSeed} onChange={e=>setTextureSeed(e.target.value)} className="w-24 rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs" placeholder="Random"/></SettingRow>}
          <SettingRow title="Output" sub="Packed GLB download"><span className="text-[11px] text-zinc-500">GLB</span></SettingRow>
        </div>}
        {!hasModel&&<div className="text-[11px] text-amber-300">Upload or select a 3D model first</div>}
        {engine==="Forge"&&hasModel&&!hasRef&&<div className="text-[11px] text-amber-300">Forge needs a reference image</div>}
        <Btn primary className="w-full !py-2.5" disabled={gen==="running"||!hasModel} onClick={runGenerate}>
          {gen==="running"?"Generating…":"Generate Texture"}
          <span className="text-[10px] opacity-80">{credits!=null?`${credits} cr · ${engine} · ${quality}`:"—"}</span>
        </Btn>
        <div className="text-[10px] text-zinc-500">Local mock · official API is async POST + poll (1–3 min)</div>
      </aside>
    </div>
  </>;
}

export function TexturePainter(){
  const [tab,setTab]=useState("Model");
  const [brushSize,setBrushSize]=useState(0.1);
  const [brushHardness,setBrushHardness]=useState(0.5);
  const [brushStrength,setBrushStrength]=useState(0.5);
  const [creativity,setCreativity]=useState(0.5);
  const [resemblance,setResemblance]=useState(1);
  const [prompt,setPrompt]=useState("");
  const [negPrompt,setNegPrompt]=useState("");
  const [gen,setGen]=useState("idle");
  const [progress,setProgress]=useState(0);
  const tabs=["Model","Tex 4K","Res 4K","Export"];
  const runPaint=()=>{
    if(gen==="running") return;
    setGen("running"); setProgress(0);
    const t0=Date.now();
    const id=setInterval(()=>{
      const p=Math.min(100,Math.round((Date.now()-t0)/1800*100));
      setProgress(p);
      if(p>=100){clearInterval(id);setGen("done");}
    },80);
  };
  return <div className="flex h-[calc(100dvh)] min-h-[640px] flex-col">
    {/* compact banners — keep workspace full height */}
    <div className="flex shrink-0 items-center gap-2 border-b border-zinc-800 bg-zinc-800/30 px-3 py-1.5 text-xs">
      <Badge>BETA</Badge>
      <b className="text-zinc-100">Try Texture AI 2.0 BETA</b>
      <span className="truncate text-zinc-400">Legacy painter · Settings → Join Beta for Texture AI 2.0</span>
      <span className="ml-auto whitespace-nowrap text-zinc-500"><b className="text-emerald-400">Texture AI FREE</b> · brushes + AI projection</span>
    </div>
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_320px]">
      {/* left: full-height paint viewport */}
      <section className="relative flex min-h-[360px] flex-col border-r border-zinc-800/50 bg-[#121212]">
        <div className="relative min-h-0 flex-1">
          <Viewport3DUpload
            compact
            withToggles
            emptyHint={tab==="Tex 4K"?"Texture map preview":"3D Viewer · paint on model"}
            emptySub="Orbit / zoom · upload GLB or use Example-style model"
            toolbar={
              <div className="pointer-events-auto absolute right-3 top-3 z-10 flex flex-wrap gap-1.5">
                {["Upload","Save","Help","Documentation"].map(x=><Btn key={x}>{x}</Btn>)}
              </div>
            }
          />
          {gen==="running"&&(
            <div className="absolute inset-x-4 bottom-4 z-10 rounded-xl border border-zinc-700/60 bg-zinc-950/90 p-3">
              <div className="mb-2 flex justify-between text-xs text-zinc-300"><span>AI projection (mock)…</span><span>{progress}%</span></div>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-800"><div className="h-full bg-indigo-500 transition-all" style={{width:progress+"%"}}/></div>
            </div>
          )}
          {gen==="done"&&(
            <div className="absolute bottom-4 left-4 z-10 rounded-lg border border-emerald-500/30 bg-emerald-950/70 px-3 py-2 text-xs text-emerald-300">
              Mock texture applied · {tab}
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-zinc-800 px-3 py-2 text-[11px] text-zinc-500">
          <span>Brush {brushSize.toFixed(2)}</span>
          <span>Hard {brushHardness.toFixed(2)}</span>
          <span>Strength {brushStrength.toFixed(2)}</span>
          <span className="ml-auto">Creativity {creativity.toFixed(2)} · Resemblance {resemblance.toFixed(1)}</span>
        </div>
      </section>
      {/* right: settings panel — tabs sticky at top like official */}
      <aside className="flex min-h-0 flex-col border-l border-zinc-800/50 bg-[#1a1a1a]">
        <div className="flex shrink-0 gap-1 border-b border-zinc-800 px-2 py-2">
          {tabs.map(t=>(
            <button type="button" key={t} onClick={()=>setTab(t)}
              className={"rounded-md px-2.5 py-1.5 text-xs "+(tab===t?"border border-indigo-500/30 bg-indigo-500/15 text-indigo-200":"border border-transparent text-zinc-400 hover:text-zinc-200")}>{t}</button>
          ))}
        </div>
        <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-3">
          {tab==="Export"?(
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-zinc-100">Export</h3>
              <p className="text-[11px] text-zinc-400">Download textured GLB / maps after paint (local mock).</p>
              <Btn className="w-full">Download textured GLB</Btn>
              <Btn className="w-full">Download PNG preview</Btn>
            </div>
          ):tab==="Tex 4K"?(
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-zinc-100">Tex 4K</h3>
              <div className="flex h-40 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-950 text-[11px] text-zinc-500">Texture atlas · 4K mock</div>
              <Btn className="w-full">Regenerate UV texture</Btn>
            </div>
          ):tab==="Res 4K"?(
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-zinc-100">Res 4K</h3>
              <div className="flex h-40 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-950 text-[11px] text-zinc-500">Resolution map · 4K mock</div>
            </div>
          ):(
            <>
              <h3 className="text-sm font-semibold text-zinc-100">Paint Preview</h3>
              {[
                ["Brush Size",brushSize,setBrushSize,0.01,1,0.01],
                ["Brush Hardness",brushHardness,setBrushHardness,0,1,0.01],
                ["Brush Strength",brushStrength,setBrushStrength,0,1,0.01],
              ].map(([l,v,set,mn,mx,st])=>(
                <div key={l}>
                  <label className="text-[11px] uppercase tracking-wide text-zinc-500">{l} · {Number(v).toFixed(2)}</label>
                  <input type="range" min={mn} max={mx} step={st} value={v} onChange={e=>set(Number(e.target.value))} className="mt-1 w-full"/>
                </div>
              ))}
              <PanelLabel>Prompt</PanelLabel>
              <textarea value={prompt} onChange={e=>setPrompt(e.target.value)}
                className="min-h-[64px] w-full rounded-xl border border-zinc-700/50 bg-zinc-900/60 p-2 text-sm outline-none"
                placeholder="Describe what you want to generate..."/>
              <PanelLabel>Negative Prompt</PanelLabel>
              <textarea value={negPrompt} onChange={e=>setNegPrompt(e.target.value)}
                className="min-h-[48px] w-full rounded-xl border border-zinc-700/50 bg-zinc-900/60 p-2 text-sm outline-none"
                placeholder="Enter negative prompt (e.g., worst quality, low quality)"/>
              <div>
                <label className="text-[11px] uppercase tracking-wide text-zinc-500">Creativity (0-1) · {creativity.toFixed(2)}</label>
                <input type="range" min="0" max="1" step="0.01" value={creativity} onChange={e=>setCreativity(Number(e.target.value))} className="mt-1 w-full"/>
              </div>
              <div>
                <label className="text-[11px] uppercase tracking-wide text-zinc-500">Resemblance (0.1-3) · {resemblance.toFixed(2)}</label>
                <input type="range" min="0.1" max="3" step="0.1" value={resemblance} onChange={e=>setResemblance(Number(e.target.value))} className="mt-1 w-full"/>
              </div>
              <details className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Advanced Settings</summary>
                <div className="mt-2 text-[11px] text-zinc-500">Legacy painter · Texture AI 2.0 under Settings (beta)</div>
              </details>
            </>
          )}
        </div>
        {tab!=="Export"&&(
          <div className="shrink-0 border-t border-zinc-800 p-3">
            <Btn primary className="w-full !py-2.5" disabled={gen==="running"} onClick={runPaint}>
              {gen==="running"?"Generating…":"Generate Texture"}
            </Btn>
          </div>
        )}
      </aside>
    </div>
  </div>;
}
