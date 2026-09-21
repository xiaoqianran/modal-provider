import React from "react";
import {createRoot} from "react-dom/client";
import {BrowserRouter,Route,Routes} from "react-router-dom";
import "./tailwind.css";
import {AppLayout} from "./layout.jsx";
import {Dashboard} from "./pages-dashboard.jsx";
import {ImageStudio,ToolDetail} from "./pages-image.jsx";
import {ThreeDWorkspace,TextureGenerator,TexturePainter} from "./pages-3d.jsx";
import {CommunityPage,ToolboxPage,SVGTool,SplatPage} from "./pages-tools.jsx";
import {FlowPage,FlowEditor,Tutorials,VideoStudio,Platform,ModelComparison,UpdatesPage,Placeholder} from "./pages-misc.jsx";
import {SettingsPage} from "./settings.jsx";

function App(){
  return <Routes>
    <Route element={<AppLayout/>}>
      <Route path="/" element={<Dashboard/>}/>
      <Route path="/Dashboard" element={<Dashboard/>}/>
      <Route path="/ImageGeneration" element={<ImageStudio/>}/>
      <Route path="/ImageGeneration/:category" element={<ImageStudio/>}/>
      <Route path="/ImageGeneration/:category/:tool" element={<ToolDetail/>}/>
      <Route path="/ImageTo3D/app" element={<ThreeDWorkspace mode="image"/>}/>
      <Route path="/ImageTo3D" element={<ThreeDWorkspace mode="image"/>}/>
      <Route path="/TextTo3D/app" element={<ThreeDWorkspace mode="text"/>}/>
      <Route path="/TextTo3D" element={<ThreeDWorkspace mode="text"/>}/>
      <Route path="/TextureGenerator/app" element={<TextureGenerator/>}/>
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
  </Routes>;
}

createRoot(document.getElementById("root")).render(<BrowserRouter><App/></BrowserRouter>);
