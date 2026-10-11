import React from "react";
import {fieldClass} from "../studio-ui.js";

/** Provider-owned options; never infer availability from a static catalog. */
export function ModelSelector({label, models, value, onChange, disabled = false}) {
  return <label className="block text-xs">{label}
    <select aria-label={label} className={fieldClass} value={value} disabled={disabled} onChange={event => onChange(event.target.value)}>
      {models.map(model => <option key={model.id} value={model.id} disabled={model.status === "disabled"}>{model.name || model.id}</option>)}
    </select>
  </label>;
}
