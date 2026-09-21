import React,{useState} from "react";
import {useNavigate} from "react-router-dom";
import {Search,X} from "lucide-react";
import {settingTabs} from "./data.js";
import {Btn,Badge,Toggle,ChipRow,SettingRow,Section,FeatureLines} from "./components.jsx";

const subtitle=t=>({
  "Profile":"Your identity, email and what you're creating",
  "Billing & Credits":"Credits, plan and subscriptions",
  "Team":"Shared workspace, members and team credits",
  "Security":"Login activity and account safety",
  "Passkeys & 2FA":"Passwordless sign-in and two-factor authentication",
  "Appearance & Behavior":"Theme, assistance and workflow preferences",
  "Notifications & Sound":"How the app talks to you",
  "Connect & Export":"Blender, 3D printing and the developer API",
  "AI Assistants (MCP)":"Connect Claude, ChatGPT & Cursor to your account",
  "Help & About":"Support, guides, community and legal"
}[t]||"");

function Profile(){
  return <>
    <Section title="Identity" text="How you appear in the sidebar, shared projects and community posts">
      <div className="flex items-center gap-2"><div className="flex h-12 w-12 items-center justify-center rounded-full bg-zinc-700 text-zinc-200">S</div><Btn>Change profile picture</Btn><Btn>Remove</Btn></div>
      <label className="text-[11px] uppercase tracking-wide text-zinc-500">Display name</label>
      <input className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm" placeholder="Your display name"/>
    </Section>
    <Section title="What are you creating?" text="Helps tailor the product and prioritize the right tools">
      <ChipRow items={["Images & video","Product & design","Art & hobby","Game assets","3D printing","Just exploring"]}/>
      <ChipRow items={["Professional","Indie / freelancer","Hobbyist / student"]}/>
    </Section>
    <Section title="Product Tour" text="Replay the welcome walkthrough anytime"><Btn>Replay tour</Btn></Section>
    <Section title="Privacy Mode" text="Blur personal information for streams and screenshots">
      <SettingRow title="Privacy Mode" sub="Protect account details in shared screens"><Toggle on/></SettingRow>
    </Section>
  </>;
}

function Billing(){
  return <>
    <Section title="Available Credits" text="Credits, plan and subscriptions">
      <div className="text-3xl font-semibold text-zinc-50">80 <small className="text-sm text-zinc-400">credits</small></div>
      <Btn>Breakdown</Btn>
    </Section>
    <Section title="Free Plan" text="Upgrade to unlock full potential"><Btn primary>Upgrade Plan</Btn></Section>
    <Section title="Subscriptions" text="Invoices, renewal dates and cancellation">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-sm text-zinc-400">No Active Subscriptions</div>
      <Btn>Billing Portal</Btn>
    </Section>
  </>;
}

function Team(){
  return <>
    <Section title="Work together, create faster" text="Shared workspace, members and team credits">
      <FeatureLines lines={["Shared credits — one Pro credit pool","One workspace — every model and image in a shared library","Invite with a code — teammates join in seconds"]}/>
      <Btn primary>Upgrade to Pro</Btn>
    </Section>
    <Section title="Join an existing team" text="Have an invite code? Join your team here">
      <input className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm" placeholder="Invite code"/>
    </Section>
  </>;
}

function Security(){
  return <>
    <Section title="Sessions & login activity" text="Devices currently signed in and recent logins">
      <div className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-sm">
        <div className="flex-1"><b className="block text-zinc-100">Chrome on Windows</b><span className="text-xs text-zinc-400">This device · Active now</span></div>
        <Btn>Log out here</Btn>
      </div>
      <Btn>Sign out everywhere</Btn>
    </Section>
    <Section title="Danger zone" text="Irreversible actions live here"><Btn>Delete account…</Btn></Section>
  </>;
}

function Passkeys(){
  return <Section title="Passkeys & two-factor authentication" text="Passwordless sign-in and stronger account security">
    <SettingRow title="Add passkey or security key" sub="Face ID, Windows Hello, or a hardware key"><Btn>Add…</Btn></SettingRow>
    <SettingRow title="Authenticator app" sub="Google Authenticator, Authy, 1Password"><Btn>Set up…</Btn></SettingRow>
    <SettingRow title="Two-factor authentication" sub="Register a passkey or authenticator first"><Toggle/></SettingRow>
  </Section>;
}

function Appearance(){
  return <>
    <Section title="Appearance" text="How 3D AI Studio looks across the app"><ChipRow items={["Dark","Light"]}/></Section>
    <Section title="Assistance" text="How much the app explains itself while you work">
      <SettingRow title="Tooltips" sub="Helpful tooltips when hovering"><Toggle on/></SettingRow>
      <SettingRow title="Quick Tips" sub="Helpful tips while generating"><Toggle on/></SettingRow>
      <SettingRow title="Flat Image & 3D Detection" sub="Detect logos and clipart in Image to 3D"><Toggle on/></SettingRow>
    </Section>
    <Section title="Early access"><SettingRow title="Beta Access" sub="Preview experimental features first"><Btn>Join Beta</Btn></SettingRow></Section>
  </>;
}

function Notifications(){
  return <>
    <Section title="Browser notifications" text="Get notified when generations finish"><SettingRow title="Browser Notifications" sub="Desktop notifications"><Toggle/></SettingRow></Section>
    <Section title="Sound effects" text="Synthesized clicks and pops as you work">
      <SettingRow title="Sound Effects" sub="Live synthesized UI sounds"><Toggle on/></SettingRow>
      <label className="text-[11px] uppercase tracking-wide text-zinc-500">Volume · 70%</label>
      <input type="range" defaultValue="70" className="w-full"/>
    </Section>
  </>;
}

function ConnectExport(){
  return <>
    <Section title="Recommended workflow" text="From a single photo to a file your slicer accepts">
      <FeatureLines lines={["Generate an image","Edit & refine","Image to 3D","Export for printing"]}/><Btn primary>Open Image to 3D</Btn>
    </Section>
    <Section title="Getting your files out" text="Three export paths cover every tool">
      <FeatureLines lines={["Export for 3D Printing — 3MF / STL / OBJ","Download GLB — Blender, Unity, Unreal, Godot","Retopology — GLB / FBX / OBJ / STL / BLEND / USDZ"]}/>
    </Section>
    <Section title="Developer API"><div className="flex flex-wrap gap-2"><Btn>API Platform</Btn><Btn>API Documentation</Btn></div></Section>
  </>;
}

function MCP(){
  return <>
    <Section title="Connect an AI assistant" text="Use 3D AI Studio from Claude, ChatGPT, Cursor and MCP-enabled assistants">
      <FeatureLines lines={["Text & image to 3D","Generate & edit images","Interactive 3D viewer in chat","Export any format","Remove backgrounds","Synced to dashboard"]}/>
      <div className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-xs text-emerald-300">https://mcp.3daistudio.com/mcp</div>
      <Btn primary>Unlock the MCP Connector</Btn>
    </Section>
    <Section title="Connected apps" text="Assistants with access to your account"><div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-sm text-zinc-400">No AI assistants connected yet.</div></Section>
  </>;
}

function Help(){
  return <>
    <Section title="Guides" text="Short reads that improve results">
      <SettingRow title="Fix Flat 3D Models" sub="Flat, pancake-like results? Add depth first"><Badge>COMMON ISSUE</Badge></SettingRow>
      <SettingRow title="Quick Start Guide" sub="Learn the basics in minutes"><Badge>RECOMMENDED</Badge></SettingRow>
    </Section>
    <Section title="Resources"><FeatureLines lines={["Documentation","Status","Pricing","Discord Community","Blog"]}/></Section>
  </>;
}

const panels={
  "Profile":Profile,"Billing & Credits":Billing,"Team":Team,"Security":Security,
  "Passkeys & 2FA":Passkeys,"Appearance & Behavior":Appearance,"Notifications & Sound":Notifications,
  "Connect & Export":ConnectExport,"AI Assistants (MCP)":MCP,"Help & About":Help
};

export function SettingsPage(){
  const nav=useNavigate();
  const [tab,setTab]=useState("Profile");
  const Body=panels[tab]||Profile;
  return <>
    <div className="grid min-h-[calc(100dvh)] grid-cols-1 lg:grid-cols-[260px_1fr]">
      <aside className="border-r border-zinc-800/50 bg-zinc-950/40 p-3">
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/70 px-2">
          <Search size={14} className="text-zinc-500"/>
          <input className="h-9 w-full bg-transparent text-xs outline-none" placeholder="Search settings..."/>
        </div>
        <small className="mb-1 block px-2 text-[10px] uppercase tracking-wider text-zinc-500">Account</small>
        {settingTabs.slice(0,5).map(x=><button type="button" key={x} onClick={()=>setTab(x)} className={"mb-0.5 block w-full rounded-lg px-2.5 py-2 text-left text-sm "+(tab===x?"bg-indigo-500/15 text-indigo-200":"text-zinc-400 hover:bg-zinc-800/50")}>{x}</button>)}
        <small className="mb-1 mt-3 block px-2 text-[10px] uppercase tracking-wider text-zinc-500">Preferences</small>
        {settingTabs.slice(5,7).map(x=><button type="button" key={x} onClick={()=>setTab(x)} className={"mb-0.5 block w-full rounded-lg px-2.5 py-2 text-left text-sm "+(tab===x?"bg-indigo-500/15 text-indigo-200":"text-zinc-400 hover:bg-zinc-800/50")}>{x}</button>)}
        <small className="mb-1 mt-3 block px-2 text-[10px] uppercase tracking-wider text-zinc-500">Resources</small>
        {settingTabs.slice(7).map(x=><button type="button" key={x} onClick={()=>setTab(x)} className={"mb-0.5 block w-full rounded-lg px-2.5 py-2 text-left text-sm "+(tab===x?"bg-indigo-500/15 text-indigo-200":"text-zinc-400 hover:bg-zinc-800/50")}>{x}</button>)}
        <button type="button" className="mt-4 w-full rounded-lg border border-zinc-800 px-2.5 py-2 text-left text-sm text-zinc-400 hover:text-zinc-200">Logout</button>
      </aside>
      <section className="overflow-auto p-5">
        <div className="mb-4 flex items-start justify-between gap-2">
          <div><h2 className="text-xl font-semibold text-zinc-50">{tab}</h2><p className="text-sm text-zinc-400">{subtitle(tab)}</p></div>
          <Btn onClick={()=>nav("/Dashboard")}><X size={14}/></Btn>
        </div>
        <Body/>
      </section>
    </div>
  </>;
}
