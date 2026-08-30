export function canSubmitCapability(capability) {
  return capability?.status === "available";
}

export function capabilityModels(capability) {
  if (Array.isArray(capability?.modelReadiness)) return capability.modelReadiness;

  const declared = Array.isArray(capability?.declaredModels)
    ? capability.declaredModels
    : capability?.input?.schema?.properties?.model?.enum;
  if (!Array.isArray(declared)) return [];

  return declared.map((model) => ({
    model,
    state: "unknown",
    runnable: false,
  }));
}

export function modelStateLabel(row, separator = " · ") {
  const parts = [];
  switch (row?.state) {
    case "ready":
      return "可用";
    case "outdated":
      parts.push("已部署", "版本过旧");
      break;
    case "weights_missing":
      parts.push("已部署", "权重未就绪");
      break;
    case "not_deployed":
      return "未部署";
    case "error":
      return row?.error ? `状态异常${separator}${row.error}` : "状态异常";
    default:
      return "暂不可用";
  }

  if (row?.weightsStatus === "missing" && !parts.includes("权重未就绪")) {
    parts.push("权重未就绪");
  }
  return parts.join(separator);
}

export function runtimeBlockerLabel(blocker) {
  if (blocker?.error) return `${blocker.app || "required runtime"} · ${blocker.error}`;

  const state = {
    missing: "未部署",
    stale: "版本过旧",
    error: "状态异常",
    failed: "运行失败",
  }[blocker?.status] || blocker?.status || "不可用";
  return `${blocker?.app || "required runtime"} · ${state}`;
}
