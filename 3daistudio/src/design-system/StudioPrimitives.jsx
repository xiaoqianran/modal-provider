import React from "react";

export function StudioButton({children,pressed=false,className="",...props}){
  return <button type="button" aria-pressed={pressed} className={"studio-tool "+className} {...props}>{children}</button>;
}

export function StudioToolGroup({children,label}){
  return <section aria-label={label} className="studio-toolbar rounded-xl">{children}</section>;
}

export function StudioField({label,children}){
  return <label className="block space-y-2 text-xs text-zinc-300"><span className="studio-heading block">{label}</span>{children}</label>;
}
