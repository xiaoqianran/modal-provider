import React from "react";
import {createRoot} from "react-dom/client";
import {ModelSelector} from "../src/components/generation/ModelSelector.jsx";
import {AssetUploader} from "../src/components/generation/AssetUploader.jsx";
import {ParameterForm} from "../src/components/generation/ParameterForm.jsx";
import {JobProgress} from "../src/components/generation/JobProgress.jsx";

function Fixture() {
  const [model, setModel] = React.useState("a");
  const [values, setValues] = React.useState({model: "a", seed: 42, enabled: false, asset: "", tags: [1,2]});
  const [fileName, setFileName] = React.useState("");
  const [uploaded, setUploaded] = React.useState("");
  const [phase, setPhase] = React.useState("running");
  return <>
    <ModelSelector label="Model" models={[{id:"a",name:"Model A"},{id:"b",name:"Model B"},{id:"c",status:"disabled"}]} value={model} onChange={setModel}/>
    <output data-testid="selected-model">{model}</output>
    <AssetUploader label="Source image" accept="image/*" onFile={file => setFileName(file.name)}>Choose image</AssetUploader>
    <AssetUploader label="Disabled input" disabled onFile={() => setFileName("SHOULD_NOT_CHANGE")}>Disabled</AssetUploader>
    <output data-testid="file-name">{fileName}</output>
    <ParameterForm schema={{required:["seed"], properties:{
      model:{type:"string",enum:["a","b"]},
      seed:{type:"integer",minimum:0,maximum:999},
      enabled:{type:"boolean"},
      tags:{type:"array"},
      asset:{type:"object",properties:{mime:{const:"image/png"}}},
    }}} values={values} onChange={setValues}
      assets={[{id:"png-1",name:"Picture",role:"source",mime:"image/png"},{id:"glb-1",name:"Model",role:"mesh",mime:"model/gltf-binary"}]}
      onUpload={(key,file,set) => {set(file.name);setUploaded(key + ":" + file.name);}}/>
    <output data-testid="form-value">{JSON.stringify(values)}</output>
    <output data-testid="uploaded">{uploaded}</output>
    <button onClick={() => setPhase("artifact")}>Show artifact phase</button>
    <JobProgress job={{id:"j-42",status:"running"}} elapsed={7} phase={phase}/>
  </>;
}
createRoot(document.getElementById("root")).render(<Fixture/>);
