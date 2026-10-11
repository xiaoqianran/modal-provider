import React from "react";
import {fieldClass} from "../studio-ui.js";
import {AssetUploader} from "./AssetUploader.jsx";

/** Render provider JSON Schema fields while leaving upload/persistence to callers. */
export function ParameterForm({schema, values, onChange, assets = [], busy = false, onUpload}) {
  return <>{Object.entries(schema?.properties || {}).map(([key, property]) => {
    const value = values[key];
    const set = next => onChange(current => ({...current, [key]: next}));
    const required = schema.required?.includes(key);
    return <label key={key} className="block space-y-1 text-xs text-zinc-300">
      <span>{key}{required ? " *" : ""}</span>
      {property.type === "object" ? <>
        <select aria-label={key} className={fieldClass} value={value || ""} onChange={event => set(event.target.value)}>
          <option value="">Select an asset</option>
          {assets.filter(asset => !property.properties?.mime?.const || asset.mime === property.properties.mime.const).map(asset =>
            <option key={asset.id} value={asset.id}>{asset.name} · {asset.role}</option>)}
        </select>
        {property.properties?.mime?.const !== "application/json" && onUpload &&
          <AssetUploader label={`Upload ${key}`} accept={property.properties?.mime?.const === "image/png" ? "image/*" : ".glb"}
            disabled={busy} onFile={file => onUpload(key, file, set)} className="inline-block cursor-pointer rounded border border-zinc-700 px-2 py-1">Upload {key}</AssetUploader>}
      </> : property.enum ? <select aria-label={key} className={fieldClass} value={value ?? ""} onChange={event => set(event.target.value)}>
        {property.enum.map(option => <option key={option} value={option}>{option}</option>)}
      </select> : property.type === "boolean" ? <input aria-label={key} type="checkbox" checked={!!value} onChange={event => set(event.target.checked)}/>
        : <input aria-label={key} className={fieldClass} type={["integer", "number"].includes(property.type) ? "number" : "text"}
            min={property.minimum} max={property.maximum} step={property.type === "integer" ? 1 : "any"}
            value={Array.isArray(value) ? value.join(",") : value ?? ""}
            onChange={event => set(property.type === "array" ? event.target.value.split(",").map(Number) :
              ["integer", "number"].includes(property.type) ? (event.target.value === "" ? "" : Number(event.target.value)) : event.target.value)}/>}
    </label>;
  })}</>;
}
