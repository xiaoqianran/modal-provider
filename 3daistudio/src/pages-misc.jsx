import React,{useMemo,useState} from "react";
import {NavLink,useNavigate} from "react-router-dom";
import {Box,ChevronDown,ChevronRight,Clapperboard,Play,Plus,Search,Upload,Workflow,X,WandSparkles} from "lucide-react";
import {Badge,Btn,ChipRow} from "./components.jsx";
import {modelCatalog,tutorials,changelog,platformFaqs,videoModels} from "./data.js";

const YOUTUBE_FLOW="https://www.youtube.com/playlist?list=PL9V4KpAz06FJkQei8b_cUu7gE-XWljeLj";
const FLOW_DOCS="https://docs.3daistudio.com/flow/overview";

const seedFlows=[
  {id:"f1",name:"Stylized prop pipeline",mode:"canvases",updated:"just now",nodes:3},
  {id:"f2",name:"Character turnaround",mode:"canvases",updated:"yesterday",nodes:5},
  {id:"f3",name:"Asset pack batch",mode:"templates",updated:"2 days ago",nodes:7},
  {id:"f4",name:"Public: product shots",mode:"gallery",updated:"last week",nodes:4},
];

function NewFlowModal({onClose,onCreate}){
  const options=[
    {title:"Blank canvas",body:"Start empty and build it yourself.",key:"blank"},
    {title:"Build with AI",body:"Describe it - Bob builds it for you.",badge:"BETA",key:"ai"},
    {title:"My templates",body:"Reuse one of your saved flows.",key:"mine"},
    {title:"Public templates",body:"Start from an official community flow.",key:"public"}
  ];
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
    <div className="w-full max-w-xl rounded-2xl border border-zinc-700/50 bg-zinc-900 p-5">
      <button type="button" className="float-right text-zinc-400" onClick={onClose}><X size={16}/></button>
      <h2 className="mb-3 text-lg font-semibold text-zinc-100">Create a new flow</h2>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {options.map(o=><button type="button" key={o.key} onClick={()=>onCreate(o.key)} className="rounded-xl border border-zinc-700/40 bg-zinc-800/30 p-3 text-left hover:border-indigo-500/40">
          <b className="flex items-center gap-1.5 text-sm text-zinc-100">{o.title}{o.badge&&<Badge>{o.badge}</Badge>}</b>
          <p className="mt-1.5 text-xs text-zinc-400">{o.body}</p>
        </button>)}
      </div>
      <div className="mt-4 flex justify-end gap-2"><Btn onClick={onClose}>Close</Btn><Btn primary onClick={()=>onCreate("blank")}>Create flow</Btn></div>
    </div>
  </div>;
}

export function FlowPage(){
  const nav=useNavigate();
  const [tab,setTab]=useState("canvases");
  const [banner,setBanner]=useState(true);
  const [modal,setModal]=useState(false);
  const [q,setQ]=useState("");
  const [flows,setFlows]=useState(seedFlows);
  const list=useMemo(()=>{
    const needle=q.trim().toLowerCase();
    return flows.filter(f=>f.mode===tab&&(!needle||f.name.toLowerCase().includes(needle)));
  },[flows,tab,q]);

  return <>
    <div className="p-4">
      {banner&&<div className="mb-3.5 flex items-start justify-between gap-3 rounded-xl border border-zinc-700/40 bg-zinc-800/25 p-4">
        <div>
          <Badge>Free · 7-part course</Badge>
          <h2 className="mt-1.5 text-base font-semibold text-zinc-50">New to Flow? Start with the full course</h2>
          <p className="text-sm text-zinc-400">From a blank canvas to reusable AI apps - watch the free 7-part series.</p>
        </div>
        <div className="flex items-center gap-2"><a className="btn inline-flex rounded-lg border border-zinc-700/50 bg-zinc-800/50 px-3 py-2 text-xs text-zinc-300" href={YOUTUBE_FLOW} target="_blank" rel="noreferrer">Watch the series</a><button type="button" className="rounded p-1 text-zinc-400" onClick={()=>setBanner(false)} aria-label="Dismiss tutorial banner"><X size={14}/></button></div>
      </div>}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5">
          {[["canvases","My Canvases"],["templates","My Templates"],["gallery","Public Gallery"]].map(([id,l])=>(
            <Btn key={id} className={tab===id?"!border-indigo-500/40 !bg-indigo-500/15 !text-indigo-200":""} onClick={()=>setTab(id)}>{l}</Btn>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <a className="text-xs text-zinc-400 hover:text-zinc-200" href={YOUTUBE_FLOW} target="_blank" rel="noreferrer">Tutorials</a>
          <a className="text-xs text-zinc-400 hover:text-zinc-200" href={FLOW_DOCS} target="_blank" rel="noreferrer">Docs</a>
          <Btn>Feedback</Btn>
          <div className="flex items-center gap-2 rounded-lg border border-zinc-700/50 bg-zinc-900/70 px-2">
            <Search size={13} className="text-zinc-500"/>
            <input value={q} onChange={e=>setQ(e.target.value)} className="h-8 w-32 bg-transparent text-xs outline-none" placeholder="Search…"/>
          </div>
          <Btn primary onClick={()=>setModal(true)}><Plus size={14}/>New flow</Btn>
        </div>
      </div>
      {list.length===0?(
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-zinc-700 px-6 py-20 text-center">
          <Workflow size={48} className="text-zinc-500"/>
          <h3 className="text-lg font-semibold text-zinc-100">{q?"No matching flows":tab==="templates"?"No templates yet":tab==="gallery"?"Public gallery":"Create your first flow"}</h3>
          <p className="max-w-lg text-sm text-zinc-400">Build a node-based AI workflow from scratch, or learn the ropes first with our free 7-part video course.</p>
          <div className="mt-1 flex flex-wrap justify-center gap-2"><Btn primary onClick={()=>setModal(true)}><Plus size={14}/>New flow</Btn><a className="inline-flex items-center rounded-lg border border-zinc-700/50 bg-zinc-800/50 px-3 py-2 text-xs text-zinc-300" href={YOUTUBE_FLOW} target="_blank" rel="noreferrer">Watch the Flow guide</a></div>
        </div>
      ):(
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {list.map(f=><article key={f.id} className="rounded-xl border border-zinc-700/40 bg-zinc-900/40 p-4">
            <div className="flex items-start justify-between gap-2">
              <div><h3 className="text-sm font-semibold text-zinc-100">{f.name}</h3>
              <p className="mt-1 text-xs text-zinc-400">{f.nodes} nodes · {f.updated}</p></div>
              <Badge>{f.mode}</Badge>
            </div>
            <div className="mt-3 flex gap-2"><Btn primary onClick={()=>nav("/Flow/editor")}>Open</Btn><Btn onClick={()=>setFlows(list2=>list2.filter(x=>x.id!==f.id))}>Delete</Btn></div>
          </article>)}
        </div>
      )}
    </div>
    {modal&&<NewFlowModal onClose={()=>setModal(false)} onCreate={(kind)=>{
      const name=kind==="ai"?"AI draft flow":kind==="mine"?"From template":"Untitled flow";
      const id="f"+Date.now();
      setFlows(prev=>[{id,name,mode:"canvases",updated:"just now",nodes:1},...prev]);
      setModal(false);
      nav("/Flow/editor");
    }}/>}
  </>;
}

const NODE_PALETTE=["Text Prompt","Generate Image","Edit Image","Image to 3D","Multi-view","Pose","Batch","Style Reference","Texture","Retopology","Convert","LLM","Switch","Comment"];

export function FlowEditor(){
  const [title,setTitle]=useState("Untitled Flow");
  const [mode,setMode]=useState("Fast");
  const [nodes,setNodes]=useState([
    {id:1,type:"Text Prompt",x:80,y:90,sub:"A stylized fantasy prop"},
    {id:2,type:"Generate Image",x:320,y:200,sub:"Image Studio"},
    {id:3,type:"Image to 3D",x:560,y:150,sub:"Prism 3.1"},
  ]);
  const [saved,setSaved]=useState(false);
  const [runState,setRunState]=useState("idle");
  const [dragId,setDragId]=useState(null);

  const addNode=(type)=>{
    const id=Date.now();
    setNodes(n=>[...n,{id,type,x:40+((n.length*36)%280),y:40+((n.length*48)%300),sub:type==="Image to 3D"?"Prism 3.1":""}]);
  };
  const onPointerDown=(e,id)=>{
    e.preventDefault();
    setDragId(id);
    const startX=e.clientX, startY=e.clientY;
    const node=nodes.find(n=>n.id===id);
    const origin={x:node.x,y:node.y};
    const move=(ev)=>{
      setNodes(ns=>ns.map(n=>n.id===id?{...n,x:origin.x+(ev.clientX-startX),y:origin.y+(ev.clientY-startY)}:n));
    };
    const up=()=>{
      setDragId(null);
      window.removeEventListener("pointermove",move);
      window.removeEventListener("pointerup",up);
    };
    window.addEventListener("pointermove",move);
    window.addEventListener("pointerup",up);
  };
  const run=()=>{
    setRunState("running");
    setTimeout(()=>setRunState("done"),1200);
  };

  return <>
    <div className="flex h-full min-h-[calc(100dvh)] flex-col">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <input value={title} onChange={e=>{setTitle(e.target.value);setSaved(false);}} className="w-56 rounded-lg border border-transparent bg-transparent px-2 py-1 text-sm text-zinc-100 outline-none hover:border-zinc-700 focus:border-indigo-500/40"/>
        <div className="flex items-center gap-1.5">
          <Btn className={mode==="Fast"?"!border-indigo-500/40 !bg-indigo-500/15 !text-indigo-200":""} onClick={()=>setMode("Fast")}>Fast</Btn>
          <Btn className={mode==="Sharp"?"!border-indigo-500/40 !bg-indigo-500/15 !text-indigo-200":""} onClick={()=>setMode("Sharp")}>Sharp</Btn>
          <Btn onClick={()=>setSaved(true)}>{saved?"Saved":"Save"}</Btn>
          <Btn primary onClick={run} disabled={runState==="running"}>{runState==="running"?"Running…":runState==="done"?"Done":"Run"}</Btn>
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <aside className="w-48 shrink-0 overflow-auto border-r border-zinc-800 p-2">
          <b className="mb-2 block px-2 text-[11px] uppercase tracking-wide text-zinc-500">Nodes</b>
          {NODE_PALETTE.map(x=>
            <button type="button" key={x} onClick={()=>addNode(x)} className="mb-1 block w-full rounded-lg px-2 py-1.5 text-left text-xs text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200">{x}</button>)}
        </aside>
        <div className="relative flex-1 overflow-hidden bg-[linear-gradient(rgba(63,63,70,.25)_1px,transparent_1px),linear-gradient(90deg,rgba(63,63,70,.25)_1px,transparent_1px)] bg-[size:24px_24px]">
          <svg className="pointer-events-none absolute inset-0 h-full w-full">
            {nodes.slice(0,-1).map((n,i)=>{
              const m=nodes[i+1];
              return <path key={n.id+"-"+m.id} d={`M${n.x+100} ${n.y+40} C${n.x+160} ${n.y+40} ${m.x-40} ${m.y+40} ${m.x} ${m.y+40}`} fill="none" stroke="#4a7fc1" strokeWidth="1.5" opacity="0.7"/>;
            })}
          </svg>
          {nodes.map(n=>(
            <div key={n.id}
              onPointerDown={e=>onPointerDown(e,n.id)}
              className={"absolute w-48 cursor-move rounded-xl border bg-zinc-900/95 p-3 shadow-xl "+(dragId===n.id?"border-indigo-500/60":"border-zinc-700")}
              style={{left:n.x,top:n.y}}>
              <b className="text-sm text-zinc-100">{n.type}</b>
              {n.sub&&<span className="mt-1 block text-xs text-zinc-400">{n.sub}</span>}
              {n.type==="Text Prompt"&&<textarea defaultValue={n.sub} onChange={e=>setNodes(ns=>ns.map(x=>x.id===n.id?{...x,sub:e.target.value}:x))} className="mt-2 h-14 w-full rounded-lg border border-zinc-700 bg-zinc-950 p-2 text-xs"/>}
              <button type="button" className="mt-2 text-[11px] text-zinc-500 hover:text-red-400" onClick={e=>{e.stopPropagation();setNodes(ns=>ns.filter(x=>x.id!==n.id));}}>Remove</button>
            </div>
          ))}
          {runState==="done"&&(
            <div className="absolute bottom-3 left-3 rounded-lg border border-emerald-500/30 bg-emerald-950/60 px-3 py-2 text-xs text-emerald-300">
              Mock run complete · {nodes.length} nodes · mode {mode}
            </div>
          )}
        </div>
      </div>
    </div>
  </>;
}

export function Tutorials(){
  const [filter,setFilter]=useState("All 62");
  const [q,setQ]=useState("");
  const filtered=useMemo(()=>{
    const needle=q.trim().toLowerCase();
    let list=tutorials;
    if(filter.startsWith("Flow")) list=list.filter(t=>/Flow/i.test(t.title)||/Flow/i.test(t.meta||""));
    else if(filter.startsWith("Beginner")) list=list.filter(t=>/Beginner/i.test(t.meta||""));
    else if(filter.startsWith("Guides")) list=list.filter(t=>/Guide|Documentation/i.test(t.badge||t.title));
    if(needle) list=list.filter(t=>(t.title+" "+(t.desc||"")+" "+(t.meta||"")).toLowerCase().includes(needle));
    return list;
  },[filter,q]);
  return <>
    <div className="p-4">
      <h1 className="text-2xl font-semibold text-zinc-50">3D AI Studio tutorials</h1>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {["All 62","Recommended 32","Flow 8","Beginner 6","Workflow 24","Tools 14","Advanced 2","3D Printing 5","Guides 2"].map(x=>
          <Btn key={x} className={filter===x?"!border-indigo-500/40 !bg-indigo-500/15 !text-indigo-200":""} onClick={()=>setFilter(x)}>{x}</Btn>)}
      </div>
      <div className="my-3 flex items-center gap-2 rounded-lg border border-zinc-700/50 bg-zinc-900/70 px-3">
        <Search size={14} className="text-zinc-500"/>
        <input value={q} onChange={e=>setQ(e.target.value)} className="h-10 w-full bg-transparent text-sm outline-none" placeholder="Search tutorials"/>
      </div>
      <h2 className="mb-2 text-sm font-semibold text-zinc-200">All tutorials <span className="font-normal text-zinc-500">{filtered.length} shown</span></h2>
      {filtered.length===0?(
        <div className="rounded-xl border border-dashed border-zinc-700 px-6 py-16 text-center text-sm text-zinc-400">No tutorials match your filters</div>
      ):(
      <div className="space-y-2">
        {filtered.map(t=><article key={t.title} className="flex items-center gap-3 rounded-xl border border-zinc-800/70 bg-zinc-900/40 p-3 hover:border-zinc-700">
          <div className="flex h-16 w-24 shrink-0 items-center justify-center rounded-lg bg-zinc-800/80 text-zinc-400"><Play size={20}/></div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5"><Badge>{t.badge}</Badge><span className="text-[11px] text-zinc-500">{t.meta}</span></div>
            <h3 className="mt-1 truncate text-sm font-semibold text-zinc-100">{t.title}</h3>
            <p className="line-clamp-2 text-xs text-zinc-400">{t.desc}</p>
          </div>
          <ChevronRight size={16} className="shrink-0 text-zinc-500"/>
        </article>)}
      </div>)}
    </div>
  </>;
}

export function VideoStudio(){
  return <>
    <div className="grid min-h-full grid-cols-1 lg:grid-cols-[1fr_360px]">
      <section className="relative border-r border-zinc-800/40 p-4">
        <div className="flex h-full min-h-[480px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-800 text-center">
          <Clapperboard size={56} className="text-zinc-600"/>
          <h2 className="text-lg font-semibold text-zinc-100">Upload or choose an image here</h2>
        </div>
        <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="text-base font-semibold text-zinc-50">All of this. Generated with AI.</h2>
          <p className="text-sm text-zinc-400">{videoModels.length} AI video models. One studio.</p>
        </div>
      </section>
      <aside className="space-y-3 p-4">
        <h1 className="text-lg font-semibold text-zinc-50">What do you want to animate?</h1>
        <ChipRow items={["Image to Video","Text to Video","Reference to Video","Video Tools"]}/>
        <div className="flex gap-2">
          <div className="flex min-h-[120px] flex-1 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 p-3 text-center">
            <Upload size={20} className="text-zinc-400"/><b className="text-sm text-zinc-200">Upload Image</b>
            <span className="text-xs text-zinc-500">or From Dashboard</span>
          </div>
        </div>
        <label className="text-[11px] uppercase tracking-wide text-zinc-500">Aspect Ratio</label><ChipRow items={["Auto","16:9","9:16"]}/>
        <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/40 p-3">
          <b className="block text-sm text-zinc-100">{videoModels[0].name}</b>
          <small className="text-xs text-zinc-400">{videoModels[0].meta}</small>
        </div>
        <Btn className="w-full">Change AI Model</Btn>
        <textarea className="min-h-[90px] w-full rounded-xl border border-zinc-700/50 bg-zinc-900/60 p-3 text-sm outline-none" placeholder="Describe the motion and camera..."/>
        <Btn className="w-full">Help me create a good prompt</Btn>
        <Btn primary className="w-full !py-2.5">Generate Video</Btn>
      </aside>
    </div>
  </>;
}

export function Platform(){
  return <div className="min-h-dvh bg-zinc-950 text-zinc-300">
    <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-3">
      <div className="flex items-center gap-2 font-semibold text-zinc-100"><Box size={18}/>3D AI Studio</div>
      <nav className="flex items-center gap-3 text-sm text-zinc-400">
        <NavLink to="/ImageTo3D/app" className="hover:text-zinc-100">Image to 3D</NavLink>
        <NavLink to="/Dashboard" className="hover:text-zinc-100">Dashboard</NavLink>
        <NavLink to="/Platform" className="text-zinc-100">API</NavLink>
      </nav>
    </header>
    <main className="mx-auto max-w-4xl px-5 py-10">
      <Badge>Developer Platform</Badge>
      <h1 className="mt-3 text-4xl font-semibold text-zinc-50">Build with<br/>3D AI Studio_</h1>
      <p className="mt-3 max-w-2xl text-zinc-400">Integrate 3D model generation, texturing, and image editing into your applications through a simple REST API.</p>
      <div className="mt-4 flex gap-2"><Btn primary>Get Started</Btn><Btn>API Documentation</Btn><Btn>Docs</Btn></div>
      <div className="mt-6 rounded-xl border border-zinc-800 bg-zinc-900/70 p-4 font-mono text-xs leading-6 text-emerald-300/90">
        POST /v1/generate/image-to-3d<br/>Authorization: Bearer YOUR_API_KEY<br/><br/>{"{"}"image_url": "...", "model": "prism-3.1"{"}"}
      </div>
      <h2 className="mt-10 text-xl font-semibold text-zinc-50">Everything you need to ship 3D at scale</h2>
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {["Hunyuan 3D API","TRELLIS.2 API","Tripo API","Texturing API","Image Generation API","Mesh Tools API"].map(x=>
          <div key={x} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
            <WandSparkles size={16} className="mb-2 text-indigo-300"/><b className="block text-sm text-zinc-100">{x}</b>
            <span className="text-xs text-zinc-400">Async task API · status polling · download URLs</span>
          </div>)}
      </div>
      <h2 className="mt-10 text-xl font-semibold text-zinc-50">Built for every 3D workflow</h2>
      <div className="mt-4 space-y-2">
        {platformFaqs.map(f=><details key={f.q} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
          <summary className="cursor-pointer text-sm font-medium text-zinc-100">{f.q}</summary>
          <p className="mt-2 text-sm text-zinc-400">{f.a}</p>
        </details>)}
      </div>
    </main>
  </div>;
}

export function ModelComparison(){
  const [mode,setMode]=useState("All Models 38");
  return <div className="min-h-dvh bg-zinc-950 text-zinc-300">
    <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-3">
      <div className="flex items-center gap-2 font-semibold text-zinc-100"><Box size={18}/>3D AI Studio</div>
      <nav className="flex gap-3 text-sm text-zinc-400">
        <NavLink to="/ImageTo3D/app" className="hover:text-zinc-100">Image to 3D</NavLink>
        <NavLink to="/TextTo3D/app" className="hover:text-zinc-100">Text to 3D</NavLink>
      </nav>
    </header>
    <main className="mx-auto max-w-5xl px-5 py-8">
      <Badge>Model Comparison</Badge>
      <h1 className="mt-3 text-3xl font-semibold text-zinc-50">Compare every AI 3D generation model</h1>
      <p className="mt-2 text-sm text-zinc-400">38 models across 8 families including Prism, Hunyuan, Forge, Meshy and more. Text to 3D, image to 3D and multi-image workflows.</p>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {["All Models 38","Text to 3D 10","Image to 3D 16","Multi-Image 12"].map(x=>
          <Btn key={x} className={mode===x?"!border-indigo-500/40 !bg-indigo-500/15 !text-indigo-200":""} onClick={()=>setMode(x)}>{x}</Btn>)}
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {["All","Hunyuan","Prism","Meshy","Forge","hitem3d","miora3d","Trellis","Seed3D","Legacy"].map(x=><Btn key={x}>{x}</Btn>)}
      </div>
      <h2 className="mt-6 text-lg font-semibold text-zinc-50">Best models</h2>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        {modelCatalog.slice(0,6).map(m=><article key={m[0]} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <Badge>{m[1]}</Badge><h3 className="mt-2 text-base font-semibold text-zinc-50">{m[0]}</h3>
          <p className="mt-1 text-xs text-zinc-400">{m[2]}</p>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
            <div className="rounded-lg bg-zinc-800/50 p-2"><span className="block text-[10px] text-zinc-500">Credits</span>{m[3]}</div>
            <div className="rounded-lg bg-zinc-800/50 p-2"><span className="block text-[10px] text-zinc-500">Time</span>{m[4]}</div>
            <div className="rounded-lg bg-zinc-800/50 p-2"><span className="block text-[10px] text-zinc-500">Features</span>{m[5]}</div>
          </div>
          <Btn className="mt-3 w-full">Try {m[0]}</Btn>
        </article>)}
      </div>
    </main>
  </div>;
}

export function UpdatesPage(){
  return <>
    <div className="p-4">
      <h1 className="text-2xl font-semibold text-zinc-50">Updates & Changelog</h1>
      <p className="mt-1 text-sm text-zinc-400">Continuous Innovation</p>
      <div className="mt-4 flex gap-2"><Btn>Filters</Btn><NavLink to="/ImageTo3D/app"><Btn>Launch Image to 3D</Btn></NavLink><NavLink to="/TextTo3D/app"><Btn>Launch Text to 3D</Btn></NavLink></div>
      <div className="mt-6 space-y-3">
        {changelog.map(c=><article key={c.version} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <div className="flex items-center gap-2"><Badge>{c.version}</Badge><span className="text-xs text-zinc-500">{c.date}</span></div>
          <h3 className="mt-2 text-sm font-semibold text-zinc-100">{c.title}</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-zinc-400">{c.items.map(i=><li key={i}>{i}</li>)}</ul>
        </article>)}
      </div>
    </div>
  </>;
}

export const Placeholder=({title})=><><div className="flex flex-col items-center justify-center gap-3 py-24"><WandSparkles size={48} className="text-zinc-500"/><h1 className="text-xl font-semibold text-zinc-100">{title}</h1><p className="text-sm text-zinc-400">Shared 3D AI Studio shell and local interaction model.</p></div></>;
