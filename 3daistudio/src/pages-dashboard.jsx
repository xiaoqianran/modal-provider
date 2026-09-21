import React,{useState} from "react";
import {NavLink,useSearchParams} from "react-router-dom";
import {BarChart3,Cuboid,Files,FolderKanban,GitBranch,Image,LockKeyhole,Plus,Search,Tag,Trophy,X} from "lucide-react";
import {Badge,Btn} from "./components.jsx";

function MiniModal({type,onClose}){
  const content={
    stats:<><div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-800 text-indigo-300"><BarChart3/></div><h2 className="text-lg font-semibold text-zinc-100">Your Activity</h2><p className="text-sm text-zinc-400">Generations over time</p>
      <div className="my-3 flex flex-wrap gap-1.5">{["24h","7d","1m","2m","6m","12m","All"].map(x=><button type="button" key={x} className="rounded-md border border-zinc-700/50 px-2 py-1 text-[11px] text-zinc-300">{x}</button>)}</div>
      <div className="grid grid-cols-3 gap-2 text-center"><div className="rounded-lg bg-zinc-800/60 p-3"><b className="block text-xl text-zinc-100">0</b><span className="text-[11px] text-zinc-400">Total</span></div><div className="rounded-lg bg-zinc-800/60 p-3"><b className="block text-xl text-zinc-100">0</b><span className="text-[11px] text-zinc-400">3D</span></div><div className="rounded-lg bg-zinc-800/60 p-3"><b className="block text-xl text-zinc-100">0</b><span className="text-[11px] text-zinc-400">Other</span></div></div>
      <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950/50 p-4 text-center text-xs text-zinc-500">2026-09-14 → 2026-09-21</div></>,
    achievements:<><div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-800 text-amber-300"><Trophy/></div><h2 className="text-lg font-semibold text-zinc-100">Achievements</h2><p className="text-sm text-zinc-400">Track your progress</p>
      <div className="my-3 rounded-xl border border-zinc-700/40 bg-zinc-800/40 p-3 text-left"><span className="text-[10px] uppercase tracking-wider text-zinc-500">Current rank</span><h3 className="text-base font-semibold text-zinc-100">Recruit</h3><div className="mt-2 h-1.5 rounded-full bg-zinc-800"><div className="h-full w-0 rounded-full bg-amber-400"/></div><small className="text-[11px] text-zinc-500">0 / 32 unlocked</small></div>
      <div className="grid grid-cols-2 gap-2">{["Secret Hunter","Code Master","Night Owl","First Steps","Getting Started","Century Club","Project Manager","First Share"].map(x=><div key={x} className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-2 text-left"><Trophy size={14} className="mb-1 text-zinc-600"/><b className="block text-[11px] text-zinc-200">{x}</b><span className="text-[10px] text-zinc-500">Locked</span></div>)}</div></>,
    changelog:<><h2 className="text-lg font-semibold text-zinc-100">Changelog</h2><p className="mb-3 text-sm text-zinc-400">What's new in 3D AI Studio</p>
      {[["v6","Latest","Flow, Video Studio and expanded 3D workflows"],["v5","2026","Image Studio, Prism and full pipeline updates"],["v2","2025","New generation models and tooling"],["v1","2024","Image-to-video, sidebar and multi-image foundations"]].map(x=><div key={x[0]} className="mb-2 flex gap-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-3"><Badge>{x[0]}</Badge><div><b className="block text-sm text-zinc-100">{x[1]}</b><span className="text-xs text-zinc-400">{x[2]}</span></div></div>)}</>
  }[type];
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
    <div className="relative w-full max-w-md rounded-2xl border border-zinc-700/50 bg-zinc-900 p-5 shadow-2xl">
      <button type="button" className="absolute right-3 top-3 rounded-lg p-1 text-zinc-400 hover:text-zinc-100" onClick={onClose}><X size={16}/></button>
      {content}
    </div>
  </div>;
}

function TabBtn({active,onClick,children}){
  return <Btn className={active?"!border-indigo-500/25 !bg-indigo-500/10 !text-[#8db4e8]":""} onClick={onClick}>{children}</Btn>;
}

function FilesView(){
  return <div className="p-4">
    <section className="mt-4 grid grid-cols-1 gap-3.5 lg:grid-cols-[1fr_320px]">
      <div className="rounded-xl border border-zinc-700/40 bg-zinc-800/30 p-4">
        <div className="flex items-start justify-between gap-2">
          <div><b className="text-sm text-zinc-100">Projects</b><span className="mt-1 block text-xs text-zinc-400">No projects yet - create one with +</span></div>
          <Btn primary><Plus size={14}/>New</Btn>
        </div>
        <div className="flex h-[165px] flex-col items-center justify-center gap-1.5 text-zinc-500">
          <FolderKanban size={44}/><span className="text-sm text-zinc-200">No projects yet</span><small className="text-xs">Create a project to organize your generations.</small>
        </div>
      </div>
      <div className="rounded-xl border border-zinc-700/40 bg-zinc-800/30 p-4">
        <div className="flex items-center justify-between"><b className="text-sm text-zinc-100">Tags</b><Btn>Manage</Btn></div>
        <div className="mt-3 flex gap-1.5"><TagBtn active>New</TagBtn><TagBtn>All</TagBtn></div>
        <div className="mt-4 flex items-center gap-2 rounded-lg bg-zinc-800/70 p-3 text-xs text-zinc-400"><Tag size={14}/><span className="flex-1">Organize your files with tags - upgrade to unlock</span><LockKeyhole size={13}/></div>
      </div>
    </section>
    <div className="mx-auto mt-14 max-w-3xl text-center">
      <span className="text-[11px] uppercase tracking-[0.12em] text-zinc-400">Use the sidebar to explore all tools</span>
      <h2 className="mt-2 text-[27px] font-semibold text-zinc-50">From Idea to Print Bed</h2>
      <p className="mt-1 text-sm text-zinc-400">Watertight, print-ready models — STL and 3MF out of the box</p>
    </div>
    <div className="mx-auto mt-5 grid max-w-4xl grid-cols-1 gap-4 md:grid-cols-2">
      <NavLink to="/TextTo3D/app" className="rounded-xl border border-zinc-700/40 bg-zinc-800/30 p-3.5 transition hover:border-zinc-600 hover:bg-zinc-800/50">
        <div className="mb-3 flex h-40 items-center justify-center rounded-lg bg-[radial-gradient(circle_at_40%_35%,rgba(99,102,241,.25),transparent_50%),radial-gradient(circle_at_70%_70%,rgba(16,185,129,.12),transparent_40%),#1c1c1f] text-indigo-300"><Cuboid size={56}/></div>
        <Badge>Text to 3D</Badge><h3 className="mb-1.5 mt-2.5 text-lg font-semibold text-zinc-50">Describe a Model</h3><p className="text-[13px] text-zinc-400">Type your idea and get a printable 3D model.</p>
      </NavLink>
      <NavLink to="/ImageTo3D/app" className="rounded-xl border border-zinc-700/40 bg-zinc-800/30 p-3.5 transition hover:border-zinc-600 hover:bg-zinc-800/50">
        <div className="mb-3 flex h-40 items-center justify-center rounded-lg bg-[radial-gradient(circle_at_40%_35%,rgba(99,102,241,.25),transparent_50%),radial-gradient(circle_at_70%_70%,rgba(16,185,129,.12),transparent_40%),#1c1c1f] text-indigo-300"><Image size={56}/></div>
        <Badge>Image to 3D</Badge><h3 className="mb-1.5 mt-2.5 text-lg font-semibold text-zinc-50">Photo to Printable</h3><p className="text-[13px] text-zinc-400">Upload any image and get a print-ready model with auto-repair.</p>
      </NavLink>
    </div>
  </div>;
}

function TagBtn({active,children}){
  return <span className={"rounded-md px-2.5 py-1.5 text-[11px] font-medium "+(active?"bg-indigo-500/15 text-indigo-200 border border-indigo-500/30":"border border-zinc-700/40 text-zinc-400")}>{children}</span>;
}

function ProjectsView(){
  return <div className="p-4">
    <div className="flex flex-wrap items-center gap-2">
      {["My Projects","Shared Projects","Collected Projects","Archived"].map((x,i)=><Btn key={x} className={i===0?"!border-indigo-500/25 !bg-indigo-500/10 !text-[#8db4e8]":""}>{x}</Btn>)}
      <div className="ml-auto flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/70 px-3"><Search size={14} className="text-zinc-500"/><input className="h-8 w-40 bg-transparent text-xs outline-none placeholder:text-zinc-600" placeholder="Search projects..."/></div>
    </div>
    <div className="my-4 flex items-center justify-end gap-2">
      <span className="mr-auto text-[11px] text-zinc-500">2 Projects Until Limit</span>
      <Btn>All</Btn><Btn>Done</Btn><Btn primary><Plus size={14}/>New Project</Btn>
    </div>
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-zinc-800 px-6 py-20 text-center">
      <FolderKanban size={48} className="text-zinc-500"/><h3 className="text-lg font-semibold text-zinc-100">No Projects Yet</h3>
      <p className="max-w-sm text-sm text-zinc-400">Create your first project to organize your work and track progress.</p><Btn primary>Create Project</Btn>
    </div>
  </div>;
}

function BranchesView(){
  return <div className="p-4">
    <div className="flex flex-wrap gap-2">{["My Branches","Shared Branches","Collected Branches","How It Works"].map((x,i)=><Btn key={x} className={i===0?"!border-indigo-500/25 !bg-indigo-500/10 !text-[#8db4e8]":""}>{x}</Btn>)}<select className="ml-auto rounded-lg border border-zinc-700/50 bg-zinc-800/50 px-2 py-1.5 text-xs text-zinc-300"><option>Sort: Modified</option><option>Sort: Created</option><option>Sort: Size</option></select></div>
    <div className="mt-4 flex flex-col items-center gap-2 rounded-xl border border-dashed border-zinc-800 px-6 py-20 text-center">
      <GitBranch size={48} className="text-zinc-500"/><h2 className="text-xl font-semibold text-zinc-100">No branches yet</h2>
      <p className="max-w-lg text-sm text-zinc-400">Branches are created automatically when you generate, edit, or convert models. Save branches from other creators to learn their workflows.</p><Btn>View example</Btn>
    </div>
  </div>;
}

function SharedView(){
  return <div className="p-4">
    <div className="flex flex-wrap gap-2">{["With me","By me","Public links"].map((x,i)=><Btn key={x} className={i===0?"!border-indigo-500/25 !bg-indigo-500/10 !text-[#8db4e8]":""}>{x}</Btn>)}</div>
    <div className="mt-4 flex flex-col items-center gap-2 rounded-xl border border-dashed border-zinc-800 px-6 py-20 text-center">
      <FolderKanban size={48} className="text-zinc-500"/><h3 className="text-lg font-semibold text-zinc-100">Nothing shared yet</h3>
      <p className="max-w-sm text-sm text-zinc-400">Projects and generations you share with teammates will show up here.</p>
    </div>
  </div>;
}

export function Dashboard(){
  const [params,setParams]=useSearchParams();
  const view=params.get("view")||"files";
  const [more,setMore]=useState(false);
  const [modal,setModal]=useState(null);
  const choose=v=>setParams({view:v});
  return <>
    <div className="flex flex-wrap items-center justify-between gap-2 p-3">
      <div className="flex flex-wrap gap-1.5">
        <TabBtn active={view==="files"} onClick={()=>choose("files")}><Files size={14}/>Files</TabBtn>
        <TabBtn active={view==="projects"} onClick={()=>choose("projects")}><FolderKanban size={14}/>Projects</TabBtn>
        <TabBtn active={view==="branches"} onClick={()=>choose("branches")}><GitBranch size={14}/>Branches</TabBtn>
        <TabBtn active={view==="shared"} onClick={()=>choose("shared")}>Shared</TabBtn>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Btn onClick={()=>setModal("changelog")}>What's New</Btn>
        <NavLink to="/Flow/app"><Btn>Flow</Btn></NavLink>
        <Btn>MCP</Btn>
        <NavLink to="/Platform"><Btn>API</Btn></NavLink>
        <div className="relative">
          <Btn onClick={()=>setMore(!more)}>More</Btn>
          {more&&<div className="absolute right-0 top-11 z-40 w-56 rounded-xl border border-zinc-700/50 bg-zinc-900 p-2 shadow-xl">
            <b className="block px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-500">Create</b>
            <button type="button" className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800">Upload Image</button>
            <button type="button" className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800">Default Project</button>
            <b className="mt-2 block px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-500">Connect</b>
            <NavLink to="/Flow/app" className="block rounded-lg px-2 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800">Flow</NavLink>
            <button type="button" className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800">MCP · AI Assistants</button>
            <NavLink to="/Platform" className="block rounded-lg px-2 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800">API Platform</NavLink>
            <b className="mt-2 block px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-500">Insights</b>
            <button type="button" className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800" onClick={()=>{setModal("stats");setMore(false)}}>Statistics</button>
            <button type="button" className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800" onClick={()=>{setModal("achievements");setMore(false)}}>Achievements</button>
            <b className="mt-2 block px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-500">Resources</b>
            <button type="button" className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800" onClick={()=>{setModal("changelog");setMore(false)}}>What's New</button>
            <NavLink to="/Updates" className="block rounded-lg px-2 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800">Updates</NavLink>
            <button type="button" className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800">Join Discord</button>
          </div>}
        </div>
      </div>
    </div>
    {view==="files"?<FilesView/>:view==="projects"?<ProjectsView/>:view==="shared"?<SharedView/>:<BranchesView/>}
    {modal&&<MiniModal type={modal} onClose={()=>setModal(null)}/>}
  </>;
}
