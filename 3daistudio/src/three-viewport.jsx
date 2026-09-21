import React,{Suspense} from "react";
import {Canvas} from "@react-three/fiber";
import {OrbitControls,ContactShadows,Center,useGLTF} from "@react-three/drei";

/* Official 3DAI studio-like palette (sampled from live site) */
const CANVAS_BG = "#1a1a1a";
const MESH_MAIN = "#8db4e8";
const MESH_ALT  = "#e8ba3f";
const GRID_A    = "#3f4244";
const GRID_B    = "#2d2f30";

function GltfModel({url}){
  const {scene}=useGLTF(url);
  return <primitive object={scene}/>;
}

function PlaceholderMesh({textMode=false,wireframe=false}){
  const color = textMode ? MESH_ALT : MESH_MAIN;
  return (
    <group>
      <mesh rotation={[0.45,0.85,0]}>
        {textMode
          ? <boxGeometry args={[1.4,0.7,0.35]}/>
          : <icosahedronGeometry args={[1.05,1]}/>}
        <meshStandardMaterial
          color={color}
          metalness={0.42}
          roughness={0.34}
          flatShading={!textMode}
          wireframe={wireframe}
        />
      </mesh>
      <mesh position={[0,-1.05,0]} rotation={[-Math.PI/2,0,0]}>
        <circleGeometry args={[1.35,48]}/>
        <meshBasicMaterial color="#232526" transparent opacity={0.7}/>
      </mesh>
    </group>
  );
}

/**
 * 3D viewport. Parent MUST have a real height (flex-1 / h-full / fixed).
 * Canvas fills the wrapper via absolute inset-0 to avoid the 150px R3F default.
 */
export function Viewport3D({url=null,textMode=false,hint,subhint,className="",wireframe=false,showGrid=true,showHelpers=true,style}){
  return (
    <div
      className={"relative h-full w-full min-h-[240px] overflow-hidden rounded-xl border border-zinc-700/50 bg-[#1a1a1a] "+className}
      style={style}
    >
      <div className="absolute inset-0">
        <Canvas
          dpr={[1,2]}
          camera={{position:[2.5,1.7,3.0],fov:45,near:0.1,far:80}}
          gl={{antialias:true}}
          onCreated={({gl})=>{gl.setClearColor(CANVAS_BG);}}
          style={{width:"100%",height:"100%",display:"block"}}
        >
          <color attach="background" args={[CANVAS_BG]}/>
          <fog attach="fog" args={[CANVAS_BG, 8, 22]}/>
          <ambientLight intensity={0.5}/>
          <directionalLight position={[4,6,3]} intensity={1.05} color="#f5f0e8"/>
          <directionalLight position={[-4,2,-2]} intensity={0.28} color="#9aa4b2"/>
          <hemisphereLight args={["#c2c0b9","#1a1a1a",0.4]}/>
          <Suspense fallback={null}>
            <Center>
              {url?<GltfModel url={url}/>:<PlaceholderMesh textMode={textMode} wireframe={wireframe}/>}
            </Center>
          </Suspense>
          {showHelpers&&<ContactShadows position={[0,-1.05,0]} opacity={0.5} scale={12} blur={2.5} far={4} color="#000000"/>}
          {showGrid&&<gridHelper args={[14,28,GRID_A,GRID_B]}/>}
          <OrbitControls
            makeDefault
            enableDamping
            dampingFactor={0.08}
            minDistance={1.2}
            maxDistance={14}
            maxPolarAngle={Math.PI*0.49}
          />
        </Canvas>
      </div>
      {hint&&(
        <div className="pointer-events-none absolute inset-x-0 bottom-3 flex flex-col items-center gap-1 text-center">
          <b className="text-xs text-zinc-300">{hint}</b>
          {subhint&&<span className="text-[11px] text-zinc-500">{subhint}</span>}
        </div>
      )}
      <div className="pointer-events-none absolute right-2 top-2 rounded-md border border-zinc-700/60 bg-[#1a1a1a]/80 px-2 py-1 text-[10px] text-zinc-400">
        Three.js · R3F{wireframe?" · wire":""}
      </div>
    </div>
  );
}

/** Optional toolbar overlay for tool pages (Upload / Save …). */
export function ViewportToolbar({children,className=""}){
  return (
    <div className={"pointer-events-auto absolute left-3 top-3 z-10 flex flex-wrap gap-1.5 "+className}>
      {children}
    </div>
  );
}

export function Viewport3DUpload({
  textMode=false, emptyHint, emptySub, withToggles=false,
  compact=false, hideChromeToggles=false, toolbar=null, onFileLoaded
}){
  const [url,setUrl]=React.useState(null);
  const [name,setName]=React.useState("");
  const [wireframe,setWireframe]=React.useState(false);
  const [showGrid,setShowGrid]=React.useState(true);
  const urlRef=React.useRef(null);
  React.useEffect(()=>()=>{ if(urlRef.current) URL.revokeObjectURL(urlRef.current); },[]);
  const onFile=(e)=>{
    const file=e.target.files?.[0];
    if(!file) return;
    if(urlRef.current) URL.revokeObjectURL(urlRef.current);
    const next=URL.createObjectURL(file);
    urlRef.current=next;
    setUrl(next);
    setName(file.name);
    onFileLoaded?.(next, file.name);
  };

  const toggles=(!hideChromeToggles && withToggles) && (
    <div className="pointer-events-auto absolute left-3 top-3 z-10 flex flex-wrap gap-1.5">
      <button type="button" onClick={()=>setWireframe(v=>!v)} className={"rounded-lg border px-2.5 py-1.5 text-xs backdrop-blur "+(wireframe?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/50 bg-zinc-900/70 text-zinc-400")}>Wireframe</button>
      <button type="button" onClick={()=>setShowGrid(v=>!v)} className={"rounded-lg border px-2.5 py-1.5 text-xs backdrop-blur "+(showGrid?"border-indigo-500/40 bg-indigo-500/15 text-indigo-200":"border-zinc-700/50 bg-zinc-900/70 text-zinc-400")}>Grid</button>
      <label className="inline-flex cursor-pointer items-center rounded-lg border border-zinc-700/50 bg-zinc-900/70 px-2.5 py-1.5 text-xs text-zinc-300 backdrop-blur">
        Upload
        <input type="file" accept=".glb,.gltf,model/gltf-binary,model/gltf+json" className="hidden" onChange={onFile}/>
      </label>
    </div>
  );

  return (
    <div className={"relative flex h-full w-full min-h-[240px] flex-col "+(compact?"gap-0":"gap-2")}>
      <div className="relative min-h-0 flex-1">
        <Viewport3D
          url={url}
          textMode={textMode}
          wireframe={wireframe}
          showGrid={showGrid}
          hint={url?name:emptyHint}
          subhint={url?"Drag to orbit · scroll to zoom":emptySub}
          className="!rounded-none !border-0"
          style={{height:"100%"}}
        />
        {toggles}
        {toolbar}
      </div>
      {!compact&&(
        <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-zinc-700/60 bg-zinc-800/50 px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100">
          Upload GLB / GLTF preview
          <input type="file" accept=".glb,.gltf,model/gltf-binary,model/gltf+json" className="hidden" onChange={onFile}/>
        </label>
      )}
    </div>
  );
}

export default Viewport3D;
