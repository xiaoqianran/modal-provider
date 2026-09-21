import React,{useEffect,useRef,useState} from "react";
import {NavLink,Outlet,useLocation,useNavigate} from "react-router-dom";
import {
  Box,Clapperboard,Cuboid,GraduationCap,Home,Image,LockKeyhole,Paintbrush,
  Settings,Sparkles,Workflow,Globe2,Wrench,ChevronDown,ChevronRight,X,ArrowRight
} from "lucide-react";
import {toolboxGroups} from "./data.js";

const SIDEBAR_SCROLL_KEY="3dai-sidebar-scroll";
const TOOLBOX_EXTRA_PATHS=new Set([
  "/ImageToGaussianSplat","/GaussianSplatViewer","/svgTo3D","/font3d"
]);

function isToolboxPath(pathname){
  if(TOOLBOX_EXTRA_PATHS.has(pathname)) return true;
  return toolboxGroups.some(([,items])=>items.some(([,p])=>p===pathname))
    || (pathname.startsWith("/Tools/")
      && !pathname.startsWith("/Tools/Tutorials")
      && !pathname.startsWith("/Tools/Community"));
}
function isCommunityPath(pathname){
  return pathname.includes("Community");
}

function Divider(){return <div className="mx-3 my-1 border-t border-zinc-800" aria-hidden/>;}

function NavItem({to,label,Icon,badge,onClick,expandable,open,innerRef}){
  const content=<>
    {Icon&&<Icon size={18} className="mr-2.5 shrink-0 text-zinc-300"/>}
    <span className="flex-1 text-sm">{label}</span>
    {badge&&<em className="ml-auto rounded-md border border-amber-500/30 bg-amber-400/10 px-2 py-0.5 text-[9px] font-bold uppercase not-italic text-amber-300">{badge}</em>}
    {expandable&&<ChevronDown size={14} className={"transition-transform "+(open?"rotate-180":"")}/>}
  </>;
  const base="flex w-full items-center justify-start rounded-xl border border-transparent px-3 py-2.5 my-1.5 text-left text-zinc-400 transition-all duration-200 hover:border-zinc-700/40 hover:bg-zinc-800/40 hover:text-zinc-200";
  // blur after click so the browser does not scroll containers to reveal focus
  const handleClick=(e)=>{
    if(to){
      requestAnimationFrame(()=>{ try{e.currentTarget?.blur?.();}catch{} });
    }
    onClick?.(e);
  };
  if(to) return <NavLink ref={innerRef} to={to} onClick={handleClick} className={({isActive})=>base+(isActive?" border-transparent bg-zinc-800 text-white":"")}>{content}</NavLink>;
  return <button type="button" onClick={handleClick} className={base}>{content}</button>;
}

function resetMainScroll(){
  const main=document.getElementById("app-main");
  if(main) main.scrollTop=0;
  // window too, in case anything scrolled the document
  if(window.scrollY) window.scrollTo(0,0);
}

function ScrollReset(){
  const {pathname,search}=useLocation();
  const prev=useRef(pathname);
  useEffect(()=>{
    if(prev.current===pathname) return;
    prev.current=pathname;
    resetMainScroll();
  },[pathname,search]);
  return null;
}

export function Shell({children}){
  const loc=useLocation();
  const nav=useNavigate();
  const sideNavRef=useRef(null);
  const didRestoreScroll=useRef(false);
  const [community,setCommunity]=useState(()=>isCommunityPath(loc.pathname));
  const [toolbox,setToolbox]=useState(()=>isToolboxPath(loc.pathname));

  // keep toolbox/community open when navigating between related pages
  useEffect(()=>{
    if(isToolboxPath(loc.pathname)) setToolbox(true);
    if(isCommunityPath(loc.pathname)) setCommunity(true);
  },[loc.pathname]);

  // restore sidebar scroll ONLY once on mount (not on every route change)
  useEffect(()=>{
    const el=sideNavRef.current;
    if(!el||didRestoreScroll.current) return;
    const saved=sessionStorage.getItem(SIDEBAR_SCROLL_KEY);
    if(saved!=null) el.scrollTop=Number(saved)||0;
    didRestoreScroll.current=true;
  },[]);

  // when toolbox/community expand, keep current scroll — do NOT yank to a saved value
  useEffect(()=>{
    const el=sideNavRef.current;
    if(!el) return;
    const onScroll=()=>sessionStorage.setItem(SIDEBAR_SCROLL_KEY,String(el.scrollTop));
    el.addEventListener("scroll",onScroll,{passive:true});
    return ()=>el.removeEventListener("scroll",onScroll);
  },[]);

  return <div className="flex h-dvh overflow-hidden bg-[#1a1a1a] text-zinc-300">
    <aside className="flex h-dvh w-[300px] shrink-0 flex-col border-r border-zinc-800/60 bg-[#1a1a1a]/95 shadow-2xl">
      <div className="p-3">
        <div className="cursor-pointer rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-4 shadow-lg transition-all hover:border-zinc-700/80 hover:bg-zinc-800/80">
          <div className="mb-5 flex items-center justify-between">
            <div className="rounded-md bg-gray-100/0 p-1.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-md border border-zinc-600/40 text-zinc-300"><Box size={16}/></div>
            </div>
            <button type="button" className="flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-400/10 px-3.5 py-2 text-xs font-medium text-amber-300 transition-all hover:bg-amber-400/20">
              <LockKeyhole size={13}/><span>Unlock All Tools</span>
            </button>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-zinc-200">Ready to Create</div>
              <div className="text-xs text-zinc-400">3D AI Studio</div>
            </div>
            <div className="cursor-pointer text-right">
              <div className="text-sm font-medium text-zinc-300">80</div>
              <div className="text-xs text-zinc-400">Credits</div>
            </div>
          </div>
        </div>
      </div>
      <nav ref={sideNavRef} className="side-nav sleek-scrollbar flex-1 overflow-y-auto overflow-x-visible overscroll-contain px-3">
        <NavItem to="/Dashboard" label="Dashboard" Icon={Home}/>
        <Divider/>
        <NavItem to="/ImageGeneration/generate" label="Image Studio" Icon={Image}/>
        <Divider/>
        <NavItem to="/ImageTo3D/app" label="Image to 3D" Icon={Cuboid}/>
        <NavItem to="/TextTo3D/app" label="Text to 3D" Icon={Box}/>
        <NavItem to="/TextureGenerator/app" label="Texture Generator" Icon={Sparkles}/>
        <NavItem to="/TexturePainter" label="Texture Painter" Icon={Paintbrush}/>
        <Divider/>
        <NavItem to="/Flow/app" label="Flow" Icon={Workflow} badge="NEW"/>
        <Divider/>
        <NavItem to="/Tools/Tutorials" label="Learning Studio" Icon={GraduationCap}/>
        <NavItem label="Community Creations" Icon={Globe2} expandable open={community} onClick={()=>setCommunity(v=>!v)}/>
        {community&&<div className="mb-1 ml-6 space-y-1 border-l border-zinc-800 pl-3">
          <NavLink to="/Tools/CommunityCreations" className={({isActive})=>"block rounded-lg px-2 py-1.5 text-sm hover:bg-zinc-800/40 "+(isActive?"bg-zinc-800 text-zinc-100":"text-zinc-400 hover:text-zinc-200")}>3D Creations</NavLink>
          <NavLink to="/Tools/CommunityGenerations" className={({isActive})=>"block rounded-lg px-2 py-1.5 text-sm hover:bg-zinc-800/40 "+(isActive?"bg-zinc-800 text-zinc-100":"text-zinc-400 hover:text-zinc-200")}>2D Creations</NavLink>
        </div>}
        <Divider/>
        <NavItem label="Toolbox" Icon={Wrench} expandable open={toolbox} onClick={()=>setToolbox(v=>!v)}/>
        {toolbox&&<div className="mb-2 ml-2 space-y-2 rounded-xl border border-zinc-800/60 bg-zinc-900/40 p-2">
          {toolboxGroups.map(([group,items])=><div key={group}>
            <b className="block px-1 py-0.5 text-[10px] uppercase tracking-wider text-zinc-500">{group}</b>
            {items.map(([l,p,b])=><NavLink key={p} to={p} onClick={(e)=>{requestAnimationFrame(()=>{try{e.currentTarget.blur();}catch{}});}} className={({isActive})=>"flex items-center gap-1 rounded-lg px-2 py-1 text-xs hover:bg-zinc-800/50 "+(isActive?"bg-zinc-800 text-zinc-100":"text-zinc-400 hover:text-zinc-200")}>{l}{b&&<em className="ml-auto text-[9px] not-italic text-emerald-400">{b}</em>}</NavLink>)}
          </div>)}
        </div>}
        <NavItem to="/VideoStudio" label="Video Studio" Icon={Clapperboard}/>
        <Divider/>
        <NavItem label="Settings" Icon={Settings} onClick={()=>nav("/Settings")}/>
        <NavItem to="/Updates" label="Updates" Icon={Sparkles}/>
        <NavItem to="/ModelComparison" label="Model Comparison" Icon={Box}/>
        <NavItem to="/Platform" label="API Platform" Icon={Workflow}/>
      </nav>
      <div className="border-t border-zinc-800/50 bg-zinc-900/50">
        <div className="relative m-2 overflow-hidden rounded-xl border border-zinc-700/40 px-3 py-2.5">
          <div className="relative flex items-center gap-2">
            <button type="button" onClick={()=>nav("/ImageGeneration/generate")} className="flex min-w-0 flex-1 items-center gap-2 text-left text-zinc-200 hover:text-white">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-zinc-700/60 text-zinc-400"><Home size={12}/></span>
              <span className="truncate text-xs font-semibold">Your first printable model</span>
              <ChevronRight size={12}/>
            </button>
            <button type="button" aria-label="Hide the getting-started guide" className="rounded p-1 text-zinc-600 hover:text-zinc-300"><X size={12}/></button>
          </div>
          <div className="relative mt-2 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-800"><div className="h-full w-[13%] rounded-full bg-zinc-500"/></div>
            <span className="font-mono text-[9px] font-bold tabular-nums text-zinc-500">13 %</span>
          </div>
          <div className="relative mt-1.5 flex items-center gap-1.5">
            <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-500">Finish the guide, get 100 free credits</span>
          </div>
          <button type="button" onClick={()=>nav("/ImageGeneration/generate")} className="mt-2 flex w-full items-center gap-2 rounded-lg border border-zinc-700/40 px-2.5 py-2 text-left transition-all hover:-translate-y-px">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-zinc-800/60"><Image size={12}/></span>
            <span className="min-w-0 flex-1">
              <span className="block font-mono text-[8.5px] uppercase tracking-widest text-zinc-400">First step</span>
              <span className="block truncate text-[11.5px] font-medium text-zinc-100">Generate your first image</span>
            </span>
            <ArrowRight size={12}/>
          </button>
        </div>
      </div>
      <div className="mt-auto w-full border-t border-zinc-800/50 bg-zinc-900/80">
        <div className="flex items-center gap-3 px-4 py-4">
          <div className="relative">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-zinc-700 text-xs text-zinc-200">S</div>
            <div className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-zinc-900 bg-emerald-500"/>
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-zinc-200">Studio User</div>
            <div className="truncate text-xs text-zinc-400">Local recreation</div>
          </div>
        </div>
      </div>
    </aside>
    <main id="app-main" className="min-w-0 flex-1 overflow-auto overscroll-contain bg-[#232526]">
      <ScrollReset/>
      {children ?? <Outlet/>}
    </main>
  </div>;
}

export function AppLayout(){
  return <Shell><Outlet/></Shell>;
}
