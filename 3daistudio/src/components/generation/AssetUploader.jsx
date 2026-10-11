import React from "react";

export function AssetUploader({label = "Upload", accept, disabled = false, onFile, className = "", children}) {
  return <label className={className} onDragOver={event => event.preventDefault()} onDrop={event => {
    event.preventDefault();
    if (!disabled) onFile(event.dataTransfer.files?.[0]);
  }}>
    {children || label}
    <input aria-label={label} type="file" accept={accept} disabled={disabled} className="hidden" onChange={event => {
      const file = event.target.files?.[0];
      if (file) onFile(file);
      event.target.value = "";
    }}/>
  </label>;
}
