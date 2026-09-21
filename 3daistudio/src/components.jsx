import React from "react";
import {Upload,Cuboid} from "lucide-react";

export const chipActiveClass="border-indigo-500/40 bg-indigo-500/15 text-indigo-300";
export const chipIdleClass="border-zinc-700/50 bg-zinc-800/40 text-zinc-400 hover:text-zinc-200";

export const Btn=({children,primary=false,className="",type="button",disabled=false,...props})=>
  <button {...props} type={type} disabled={disabled} className={
    "inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all "+
    (disabled?"cursor-not-allowed opacity-50 ":"")+
    (primary
      ? "border-indigo-500/40 bg-indigo-500/20 text-indigo-200 hover:bg-indigo-500/30 "
      : "border-zinc-700/60 bg-zinc-800/50 text-zinc-300 hover:border-zinc-600 hover:bg-zinc-800 hover:text-zinc-100 ")+
    className
  }>{children}</button>;

/* Official ImageTo3D REQUIRED/badge sample: amber/gold on warm dark */
export const Badge=({children,accent=false})=>children?
  <span className={
    "inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide "+
    (accent
      ? "border-indigo-500/30 bg-indigo-500/15 text-indigo-300"
      : "border-amber-500/30 bg-amber-400/10 text-amber-300")
  }>{children}</span>:null;

export const Toggle=({on=false})=>(
  <span className={"inline-flex h-4 w-7 items-center rounded-full p-0.5 transition-colors "+(on?"bg-indigo-500":"bg-zinc-700")}>
    <i className={"h-3 w-3 rounded-full bg-zinc-200 transition-transform "+(on?"translate-x-3":"")}/>
  </span>
);

export function ChipRow({items}){
  return <div className="flex flex-wrap gap-1.5">{items.map((x,i)=>
    <button type="button" key={x} className={"rounded-lg border px-2.5 py-1.5 text-xs transition-all "+(i===0?chipActiveClass:chipIdleClass)}>{x}</button>
  )}</div>;
}

export function SettingRow({title,sub,children}){
  return <div className="flex items-center justify-between gap-3 py-2">
    <div className="min-w-0">
      <b className="block text-xs font-medium text-zinc-200">{title}</b>
      {sub&&<span className="block text-[11px] text-zinc-500">{sub}</span>}
    </div>
    <div className="shrink-0">{children}</div>
  </div>;
}

export function Section({title,text,children}){
  return <section className="mb-5 rounded-xl border border-zinc-700/40 bg-zinc-900/40 p-4">
    <h3 className="mb-1 text-sm font-semibold text-zinc-100">{title}</h3>
    {text&&<p className="mb-3 text-xs text-zinc-400">{text}</p>}
    <div className="space-y-2">{children}</div>
  </section>;
}

export function FeatureLines({lines}){
  return <div className="space-y-1.5">{lines.map(x=><div key={x} className="flex gap-2 text-xs text-zinc-300"><span className="text-emerald-400">✓</span>{x}</div>)}</div>;
}

export const DropImage=()=> (
  <div className="flex min-h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-600/80 bg-zinc-900/60 p-4 text-center">
    <Upload size={22} className="text-zinc-400"/>
    <b className="text-sm text-zinc-200">Drop, paste, or click to upload</b>
    <span className="text-xs text-zinc-500">PNG, JPG, WebP</span>
  </div>
);

export const DropModel=()=> (
  <div className="flex min-h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-600/80 bg-zinc-900/60 p-4 text-center">
    <Cuboid size={22} className="text-zinc-400"/>
    <b className="text-sm text-zinc-200">Drop your 3D model here</b>
    <span className="text-xs text-zinc-500">GLB / GLTF / FBX / OBJ / STL depending on tool</span>
  </div>
);

export function PanelLabel({children,required}){
  return <label className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-zinc-500">
    {children}{required&&<Badge>REQUIRED</Badge>}
  </label>;
}

export function EmptyState({icon:Icon,title,body,children}){
  return <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-zinc-700/60 bg-zinc-950/40 px-6 py-16 text-center">
    {Icon&&<Icon size={48} className="text-zinc-500"/>}
    <h3 className="text-lg font-semibold text-zinc-100">{title}</h3>
    {body&&<p className="max-w-md text-sm text-zinc-400">{body}</p>}
    {children}
  </div>;
}
