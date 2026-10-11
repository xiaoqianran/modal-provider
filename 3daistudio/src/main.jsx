import React, {Suspense, lazy} from "react";
import {createRoot} from "react-dom/client";
import {BrowserRouter,Route,Routes} from "react-router-dom";
import "./tailwind.css";
import {AppLayout} from "./layout.jsx";
const Dashboard = lazy(() => import("./features/dashboard/StudioDashboard.jsx").then(m => ({default: m.StudioDashboard})));
const StudioWorkbench = lazy(() => import("./features/studio/StudioWorkbench.jsx").then(m => ({default: m.StudioWorkbench})));
const ImageTo3DWorkspace = lazy(() => import("./features/image-to-3d/ImageTo3DWorkspace.jsx").then(m => ({default: m.ImageTo3DWorkspace})));
const ImageStudio = lazy(() => import("./pages-image.jsx").then(m => ({default: m.ImageStudio})));
const ToolDetail = lazy(() => import("./pages-image.jsx").then(m => ({default: m.ToolDetail})));
const TexturePainter = lazy(() => import("./pages-3d.jsx").then(m => ({default: m.TexturePainter})));
const CommunityPage = lazy(() => import("./pages-tools.jsx").then(m => ({default: m.CommunityPage})));
const ToolboxPage = lazy(() => import("./pages-tools.jsx").then(m => ({default: m.ToolboxPage})));
const SVGTool = lazy(() => import("./pages-tools.jsx").then(m => ({default: m.SVGTool})));
const SplatPage = lazy(() => import("./pages-tools.jsx").then(m => ({default: m.SplatPage})));
const FlowPage = lazy(() => import("./pages-misc.jsx").then(m => ({default: m.FlowPage})));
const FlowEditor = lazy(() => import("./pages-misc.jsx").then(m => ({default: m.FlowEditor})));
const Tutorials = lazy(() => import("./pages-misc.jsx").then(m => ({default: m.Tutorials})));
const VideoStudio = lazy(() => import("./pages-misc.jsx").then(m => ({default: m.VideoStudio})));
const Platform = lazy(() => import("./pages-misc.jsx").then(m => ({default: m.Platform})));
const ModelComparison = lazy(() => import("./pages-misc.jsx").then(m => ({default: m.ModelComparison})));
const UpdatesPage = lazy(() => import("./pages-misc.jsx").then(m => ({default: m.UpdatesPage})));
const Placeholder = lazy(() => import("./pages-misc.jsx").then(m => ({default: m.Placeholder})));
const SettingsPage = lazy(() => import("./settings.jsx").then(m => ({default: m.SettingsPage})));

function App(){
  return <Suspense fallback={<main className="p-5 text-sm text-zinc-400" role="status">Loading workspace…</main>}><Routes>
    <Route element={<AppLayout/>}>
      <Route path="/" element={<Dashboard/>}/>
      <Route path="/Dashboard" element={<Dashboard/>}/>
      <Route path="/ImageGeneration" element={<ImageStudio/>}/>
      <Route path="/Studio/operations" element={<StudioWorkbench/>}/>
      <Route path="/ImageGeneration/generate" element={<StudioWorkbench mode="image"/>}/>
      <Route path="/ImageGeneration/generate/:tool" element={<StudioWorkbench mode="image"/>}/>
      <Route path="/ImageGeneration/:category" element={<ImageStudio/>}/>
      <Route path="/ImageGeneration/:category/:tool" element={<ToolDetail/>}/>
      <Route path="/ImageTo3D/app" element={<ImageTo3DWorkspace/>}/>
      <Route path="/ImageTo3D" element={<ImageTo3DWorkspace/>}/>
      <Route path="/TextTo3D/app" element={<StudioWorkbench mode="text"/>}/>
      <Route path="/TextTo3D" element={<StudioWorkbench mode="text"/>}/>
      <Route path="/TextureGenerator/app" element={<StudioWorkbench/>}/>
      <Route path="/TexturePainter" element={<TexturePainter/>}/>
      <Route path="/Flow/app" element={<FlowPage/>}/>
      <Route path="/Flow/editor" element={<FlowEditor/>}/>
      <Route path="/Tools/Tutorials" element={<Tutorials/>}/>
      <Route path="/Tools/CommunityCreations" element={<CommunityPage mode="3d"/>}/>
      <Route path="/Tools/CommunityGenerations" element={<CommunityPage mode="2d"/>}/>
      <Route path="/Tools/:tool" element={<ToolboxPage/>}/>
      <Route path="/svgTo3D" element={<SVGTool/>}/>
      <Route path="/font3d" element={<SVGTool text/>}/>
      <Route path="/ImageToGaussianSplat" element={<SplatPage/>}/>
      <Route path="/GaussianSplatViewer" element={<SplatPage viewer/>}/>
      <Route path="/VideoStudio" element={<VideoStudio/>}/>
      <Route path="/Updates" element={<UpdatesPage/>}/>
      <Route path="/Settings" element={<SettingsPage/>}/>
      <Route path="*" element={<Placeholder title="3D AI Studio"/>}/>
    </Route>
    {/* marketing pages keep their own chrome */}
    <Route path="/Platform" element={<Platform/>}/>
    <Route path="/ModelComparison" element={<ModelComparison/>}/>
  </Routes></Suspense>;
}

createRoot(document.getElementById("root")).render(<BrowserRouter><App/></BrowserRouter>);
