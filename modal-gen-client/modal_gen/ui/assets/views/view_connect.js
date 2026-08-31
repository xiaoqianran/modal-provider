// Screen: 连接 — inspect the Provider Hub and manage in-memory Modal connections.
import {
  h, icon, fmtTime, providerBadge, apiGet, apiPost, toast, store, stateEmpty, openDrawer,
  loadCapabilities, invalidateCapabilities, refreshCurrentRoute, refreshNavCounts,
} from "../app.js";
import { parseModalTokenCommand } from "../modal_credentials.js";
import { capabilityModels, modelStateLabel, runtimeBlockerLabel } from "../runtime_presenter.js";

export async function mountConnect(root) {
  root.append(
    h("div", { class: "screen-head studio-head" },
      h("div", {},
        h("span", { class: "kicker" }, "PROVIDERS"),
        h("h1", { class: "screen-head__title" }, "Provider Hub"),
        h("p", { class: "screen-head__job" }, "统一管理 2D / 3D Provider 与 Modal Workspace 连接。")
      ),
      store.mode === "live"
        ? h("button", { class: "icon-btn", type: "button", onclick: () => openConnectionSettings() }, "连接设置")
        : null
    )
  );

  if (!store.reachable) {
    root.append(
      h("div", { class: "banner banner--offline" },
        icon("alert", 18),
        h("div", { class: "stack" },
          h("strong", {}, "Connector 离线"),
          h("span", {}, "请确认 modal-gen-agent 正在 127.0.0.1 上运行。")
        ),
        h("button", { class: "btn btn--primary", onclick: () => location.reload() }, "重试")
      )
    );
    return;
  }

  const loading = h("div", { class: "panel" }, h("div", { class: "panel__body" }, skeletonRows(3)));
  root.append(loading);

  let snap;
  let connections = [];
  try {
    const [caps, conns] = await Promise.all([
      loadCapabilities().then((snapshot) => ({ snapshot })),
      apiGet("connections").catch(() => ({ providers: [] })),
    ]);
    snap = caps.snapshot;
    connections = conns.providers || [];
  } catch (e) {
    loading.replaceWith(stateEmpty("无法读取 Provider Hub", String(e.message || e)));
    return;
  }
  loading.remove();

  const connectionMap = new Map(connections.map((item) => [item.id, item]));
  const providers = h("div", { class: "provider-service-grid" });
  for (const provider of snap.providers || []) {
    providers.append(providerCard(provider, connectionMap.get(provider.id)));
  }
  root.append(providers);

  // Runtime deployment state is technical detail. Render the useful business
  // capabilities first, then resolve Modal control-plane state in the background.
  const runtimeBody = h("div", { class: "runtime-disclosure__body stack" },
    hubOverview(snap, connections),
    h("div", { class: "runtime-panel-host" }, skeletonRows(3))
  );
  const runtimeDetails = h("details", { class: "disclosure runtime-disclosure" },
    h("summary", { class: "disclosure__head" },
      icon("chevron", 14, "chevron"),
      h("span", {}, "运行时与部署"),
      h("span", { class: "muted runtime-disclosure__summary" }, "技术信息 · 后台刷新")
    ),
    runtimeBody
  );
  root.append(runtimeDetails);
  const runtimeHost = runtimeBody.querySelector(".runtime-panel-host");
  apiGet("deployments").then((deployments) => {
    runtimeHost.replaceChildren(deploymentPanel(deployments.providers || []));
  }).catch((error) => {
    runtimeHost.replaceChildren(
      h("div", { class: "connect-hint" }, `Runtime 状态暂不可用：${String(error.message || error)}`)
    );
  });

  try {
    const pr = await apiGet("pairings");
    const pending = (pr.pairings || []).filter((item) => item.status === "pending");
    if (pending.length) root.append(pairingPanel(pending));
  } catch { /* local control plane may be locked */ }
}

function hubOverview(snapshot, connections) {
  const connected = connections.filter((item) => item.connected).length;
  const total = (snapshot.providers || []).length;
  return h("div", { class: "panel hub-panel" },
    h("div", { class: "panel__head" },
      h("h2", { class: "panel__title" }, "运行链路"),
      h("span", { class: "badge badge--neutral" }, `${connected}/${total} Modal connected`)
    ),
    h("div", { class: "panel__body" },
      h("div", { class: "hub-flow" },
        hubNode("AgentScape", "上层调用"),
        hubArrow(),
        hubNode("modal-gen-client", "Provider Hub", "hub-node--main"),
        hubArrow(),
        h("div", { class: "hub-providers" },
          ...(snapshot.providers || []).map((provider) => {
            const connection = connections.find((item) => item.id === provider.id);
            return hubNode(
              provider.displayName || provider.id,
              connection?.connected ? "client → Modal 已连接" : "client → Modal 未连接",
              connection?.connected ? "hub-node--ok" : "hub-node--off"
            );
          })
        )
      ),
      h("div", { class: "hub-meta" },
        h("span", {}, `Connector ${snapshot.connector?.version || "—"}`),
        h("span", {}, `revision ${snapshot.revision || "—"}`),
        h("span", {}, `更新 ${fmtTime(snapshot.generatedAt)}`)
      )
    )
  );
}

export async function openConnectionSettings() {
  if (store.mode !== "live") {
    toast("演示模式不需要 Modal 凭证");
    return;
  }
  let connections = [];
  let hfSecret = { connected: false, configured: false, secrets: [] };
  try {
    const data = await apiGet("connections");
    connections = data.providers || [];
    if (connections.some((item) => item.connected === true)) {
      hfSecret = await apiGet("secrets/huggingface");
    }
  } catch (error) {
    toast(`读取连接状态失败：${String(error.message || error)}`, "danger");
  }
  openDrawer("连接 Modal", connectionPanel(connections, hfSecret));
}

function connectionPanel(connections, hfSecret) {
  const command = h("input", {
    class: "input input--mono connect-command",
    type: "password",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "modal token set --token-id ak-... --token-secret as-...",
  });
  const tokenId = h("input", {
    class: "input input--mono",
    type: "text",
    autocomplete: "off",
    placeholder: "ak-...",
  });
  const tokenSecret = h("input", {
    class: "input input--mono",
    type: "password",
    autocomplete: "off",
    placeholder: "as-...",
  });
  let connectedNow = connections.some((item) => item.connected === true);
  const status = h(
    "div",
    { class: `connect-hint ${connectedNow ? "connect-hint--ok" : ""}` },
    connectedNow
      ? "Modal 已连接。重新连接会在验证成功后替换本机保存的凭据。"
      : "粘贴完整 Modal CLI 命令会自动提取凭证。验证成功后会保存在本机 .secrets/modal.json，并在下次启动时自动恢复。"
  );
  const connect = h("button", { class: "btn btn--primary connect-action", type: "button" });
  const disconnect = h("button", { class: "btn", type: "button" }, "断开全部");
  const deployAll = h("button", { class: "btn", type: "button" }, "重新部署全部 Runtime");
  const hfToken = h("input", {
    class: "input input--mono",
    type: "password",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "hf_...",
  });
  const hfHint = h("div", { class: `connect-hint ${hfSecret.configured ? "connect-hint--ok" : ""}` },
    hfSecret.connected
      ? (hfSecret.configured ? "已保存到 Modal Secrets。Token 不会回显。" : "尚未配置 Hugging Face Token。")
      : "连接 Modal 后可以保存 Hugging Face Token。"
  );
  const saveHf = h("button", {
    class: "btn", type: "button", disabled: !connectedNow,
  }, "保存 HF Token");
  const connectionIndicators = [];

  function renderConnectionState() {
    connect.disabled = false;
    disconnect.disabled = !connectedNow;
    saveHf.disabled = !connectedNow;
    connect.replaceChildren(
      icon("plug", 15),
      connectedNow ? "重新连接 Modal" : "连接 Modal"
    );
    for (const indicator of connectionIndicators) {
      indicator.dot.className = `connect-provider__dot ${connectedNow ? "is-on" : ""}`;
      indicator.label.textContent = connectedNow ? "Connected" : "Disconnected";
    }
  }

  saveHf.addEventListener("click", async () => {
    const token = hfToken.value.trim();
    if (!token) {
      hfHint.className = "connect-hint connect-hint--error";
      hfHint.textContent = "Hugging Face Token 不能为空。";
      return;
    }
    saveHf.disabled = true;
    hfHint.className = "connect-hint";
    hfHint.textContent = "正在写入 Modal Secrets…";
    try {
      const result = await apiPost("secrets/huggingface", { token });
      hfToken.value = "";
      hfHint.className = "connect-hint connect-hint--ok";
      hfHint.textContent = result.configured
        ? "已写入 huggingface + hyworld2-hf；Token 不会回显。"
        : "已保存，但部分 Secret 状态尚未确认。";
      toast("Hugging Face Token 已保存到 Modal", "ok");
    } catch (e) {
      hfToken.value = "";
      hfHint.className = "connect-hint connect-hint--error";
      hfHint.textContent = String(e.message || e);
    } finally {
      saveHf.disabled = false;
    }
  });

  command.addEventListener("input", () => {
    const parsed = parseModalTokenCommand(command.value);
    status.className = "connect-hint";
    if (!parsed) {
      status.textContent = command.value.trim()
        ? "未识别到完整的 --token-id 和 --token-secret。"
        : "粘贴完整 Modal CLI 命令会自动提取凭证。验证成功后会保存在本机 .secrets/modal.json，并在下次启动时自动恢复。";
      return;
    }
    tokenId.value = parsed.tokenId;
    tokenSecret.value = parsed.tokenSecret;
    status.className = "connect-hint connect-hint--ok";
    status.textContent = "已识别 Token ID / Secret，可以直接连接。";
  });

  connect.addEventListener("click", async () => {
    if (!tokenId.value.trim() || !tokenSecret.value.trim()) {
      status.className = "connect-hint connect-hint--error";
      status.textContent = "Token ID 和 Token Secret 都不能为空。";
      return;
    }
    connect.disabled = true;
    disconnect.disabled = true;
    connect.replaceChildren(h("span", { class: "spinner" }), "正在连接…");
    status.className = "connect-hint";
    status.textContent = "正在验证 Modal 凭证…";
    try {
      const result = await apiPost("providers/connect", {
        tokenId: tokenId.value.trim(),
        tokenSecret: tokenSecret.value,
      });
      const rows = Array.isArray(result.providers) ? result.providers : [];
      connectedNow = rows.length ? rows.some((item) => item.connected === true) : true;
      tokenSecret.value = "";
      command.value = "";
      status.className = "connect-hint connect-hint--ok";
      status.textContent = "Modal 已连接。";
      toast("2D / 3D / World 已连接 Modal", "ok");
      invalidateCapabilities();
      loadCapabilities({ refresh: true }).then(() => {
        refreshCurrentRoute();
        refreshNavCounts();
      }).catch(() => {});
    } catch (e) {
      tokenSecret.value = "";
      status.className = "connect-hint connect-hint--error";
      status.textContent = String(e.message || e);
    } finally {
      renderConnectionState();
    }
  });

  deployAll.addEventListener("click", async () => {
    deployAll.disabled = true;
    status.className = "connect-hint";
    status.textContent = "正在部署全部 Runtime；首次部署可能需要构建镜像。";
    try {
      const result = await apiPost("deployments/deploy", {
        provider: "all",
        force: true,
        strategy: "rolling",
      });
      const job = result.job;
      if (!job?.id) throw new Error("Deployment Job identity 无效");
      const finished = await waitForDeploymentJob(job.id);
      const failed = ["failed", "partial"].includes(finished.status);
      status.className = failed ? "connect-hint connect-hint--error" : "connect-hint connect-hint--ok";
      status.textContent = failed ? "重新部署未全部完成，请查看 Runtime 状态。" : "全部 Runtime 已重新部署。";
      toast(failed ? "部分 Runtime 重新部署失败" : "全部 Runtime 重新部署完成", failed ? "danger" : "ok");
    } catch (e) {
      status.className = "connect-hint connect-hint--error";
      status.textContent = String(e.message || e);
    } finally {
      deployAll.disabled = false;
    }
  });

  disconnect.addEventListener("click", async () => {
    disconnect.disabled = true;
    try {
      await apiPost("providers/disconnect", {});
      connectedNow = false;
      status.className = "connect-hint";
      status.textContent = "Modal 已断开。已保存的本机凭据仍会在下次启动时自动恢复。";
      toast("2D / 3D / World 已断开 Modal", "ok");
      invalidateCapabilities();
      refreshCurrentRoute();
      refreshNavCounts();
    } catch (e) {
      status.className = "connect-hint connect-hint--error";
      status.textContent = String(e.message || e);
    } finally {
      renderConnectionState();
    }
  });

  const managed = connections.filter((item) => item.managed !== false);
  const statusGrid = h("div", { class: "connect-status-grid" });
  for (const item of managed) {
    const dot = h("span", { class: `connect-provider__dot ${connectedNow ? "is-on" : ""}` });
    const label = h("span", {}, connectedNow ? "Connected" : "Disconnected");
    connectionIndicators.push({ dot, label });
    statusGrid.append(
      h("div", { class: "connect-provider" },
        dot,
        h("div", {},
          h("strong", {}, item.id === "modal-2d" ? "Modal 2D" : item.id === "modal-3d" ? "Modal 3D" : item.id === "modal-world" ? "Modal World" : item.id),
          label
        )
      )
    );
  }
  renderConnectionState();

  return h("div", { class: "modal-settings" },
    h("p", { class: "drawer-copy" }, "一组凭证同时用于本机 2D / 3D / World Provider。连接成功后持久化到本机 .secrets/modal.json；新凭据会覆盖旧凭据。"),
    statusGrid,
    h("label", { class: "drawer-field" },
      h("span", {}, "粘贴 modal token set 命令"),
      command
    ),
    status,
    h("label", { class: "drawer-field" }, h("span", {}, "Modal Token ID"), tokenId),
    h("label", { class: "drawer-field" }, h("span", {}, "Modal Token Secret"), tokenSecret),
    h("div", { class: "drawer-actions" }, disconnect, deployAll, connect),
    h("div", { class: "drawer-section" },
      h("div", { class: "drawer-section__title" }, "Hugging Face"),
      h("p", { class: "drawer-copy" },
        "用于 gated / private 模型下载。保存后写入 Modal Secrets：huggingface 与 hyworld2-hf。"
      ),
      h("label", { class: "drawer-field" }, h("span", {}, "HF Token"), hfToken),
      hfHint,
      h("div", { class: "drawer-actions" }, saveHf)
    )
  );
}

function providerCard(provider, connection) {
  const capabilities = provider.capabilities || [];
  const connected = connection?.connected === true;
  const serviceTitle = provider.id === "modal-2d"
    ? "2D 图片生成"
    : provider.id === "modal-3d"
      ? "3D 资产生成"
      : provider.id === "modal-world"
        ? "World 世界生成"
        : provider.displayName || provider.id;
  const serviceCopy = provider.id === "modal-2d"
    ? "Prompt → 图片。选择已就绪模型后直接创建任务。"
    : provider.id === "modal-3d"
      ? "图片 → GLB。前处理与 3D Worker 会分别显示就绪状态。"
      : provider.id === "modal-world"
        ? "图片 + Prompt → Mesh / Semantics / Visual 世界产物。"
        : "生成能力";
  const technical = h("details", { class: "provider-technical" },
    h("summary", {}, "技术信息"),
    kv([
      ["Provider", provider.id],
      ["Health", provider.health || "—"],
      ["Revision", provider.implementationRevision || "—"],
      ["Artifact transport", provider.artifactTransport || "—"],
    ])
  );
  return h("section", { class: "panel provider-service-card" },
    h("div", { class: "provider-service-card__head" },
      h("div", { class: "provider-service-card__identity" },
        h("span", { class: "provider-service-card__provider" }, provider.displayName || provider.id),
        h("h2", {}, serviceTitle),
        h("p", {}, serviceCopy)
      ),
      h("div", { class: "provider-service-card__status" },
        providerBadge(provider.status),
        h("span", { class: `badge badge--${connected ? "ok" : "neutral"}` }, connected ? "Modal 已连接" : "Modal 未连接")
      )
    ),
    h("div", { class: "provider-service-card__body" },
      ...capabilities.map(capabilityCard),
      technical
    )
  );
}

function capabilityCard(capability) {
  const modelReadiness = capabilityModels(capability);
  const roles = capability.output?.roles || [];
  const blockers = Array.isArray(capability.runtimeBlockers) ? capability.runtimeBlockers : [];
  const blockerRows = blockers.map((item) => {
    return h("div", { class: "capability-blocker" },
      icon("alert", 15),
      h("div", {},
        h("strong", {}, "前处理阻塞"),
        h("span", {}, runtimeBlockerLabel(item))
      )
    );
  });
  return h("div", { class: "capability-service" },
    h("div", { class: "row spread capability-service__head" },
      h("div", {},
        h("strong", {}, capability.displayName || capability.operation),
        h("span", { class: "capability-service__output" }, roles.length ? `输出 ${roles.join(" · ")}` : "")
      ),
      providerBadge(capability.status)
    ),
    h("div", { class: "model-chip-list" },
      ...(modelReadiness.length
        ? modelReadiness.map((row) => h(
          "span",
          { class: `model-chip ${row.runnable ? "" : "model-chip--blocked"}` },
          row.model,
          h("small", { class: "muted" }, ` · ${modelStateLabel(row)}`)
        ))
        : [h("span", { class: "muted" }, "没有声明模型")])
    ),
    ...blockerRows,
    h("details", { class: "capability-technical" },
      h("summary", {}, "接口信息"),
      kv([
        ["Operation", capability.operation],
        ["Profiles", Object.keys(capability.profiles || {}).join(" · ") || "—"],
      ])
    )
  );
}

function pairingPanel(pending) {
  const body = h("div", { class: "panel__body stack" });
  for (const item of pending) {
    const button = h("button", { class: "btn btn--primary btn--sm", type: "button" }, "批准");
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await apiPost("pairings/approve", { pairingId: item.id });
        button.textContent = "已批准";
        toast("已批准配对", "ok");
      } catch (e) {
        button.disabled = false;
        toast(String(e.message || e), "danger");
      }
    });
    body.append(h("div", { class: "row spread" },
      h("div", { class: "stack" },
        h("span", { class: "mono" }, item.id),
        h("span", { class: "muted" }, `${item.origin} · ${(item.scopes || []).join(", ")}`)
      ),
      button
    ));
  }
  return h("div", { class: "panel", style: "margin-top: var(--s4)" },
    h("div", { class: "panel__head" }, h("h2", { class: "panel__title" }, `待批准配对 (${pending.length})`)),
    body
  );
}

function hubNode(title, subtitle, extra = "") {
  return h("div", { class: `hub-node ${extra}` },
    h("strong", {}, title),
    h("span", {}, subtitle)
  );
}

function hubArrow() {
  return h("div", { class: "hub-arrow" }, icon("chevron", 18));
}

function kv(rows) {
  const el = h("div", { class: "kv" });
  for (const [key, value] of rows) {
    if (value == null) continue;
    el.append(h("span", { class: "kv__key" }, key), h("span", { class: "kv__val" }, value));
  }
  return el;
}

function skeletonRows(n) {
  return h("div", {}, ...Array.from({ length: n }, () => h("div", { class: "skeleton skel-row" })));
}

function deploymentPanel(rows) {
  const body = h("div", { class: "panel__body stack" });
  const deployAll = deploymentAction("部署全部缺失", "all", null, body, false, true, false);
  const resync = runtimeResyncAction(body);
  body.append(h("div", { class: "row spread" },
    h("p", { class: "muted" }, "部署会修改 Modal Runtime；重新同步只读取 App / revision / weights / capability，不会重新部署。"),
    h("div", { class: "row" }, resync, deployAll)
  ));

  for (const row of rows) {
    const providerLabel = row.id === "modal-2d" ? "2D Runtime" : row.id === "modal-3d" ? "3D Runtime" : row.id === "modal-world" ? "World Runtime" : row.id;
    const providerAction = deploymentAction(
      row.status === "current" ? "重新部署全部" : row.status === "stale" ? "更新全部" : "部署缺失",
      row.id,
      null,
      body,
      false,
      !["current", "stale"].includes(row.status),
      row.status === "current"
    );
    body.append(h("div", { class: "cap-row" },
      h("div", { class: "row spread" },
        h("div", { class: "stack" },
          h("strong", {}, providerLabel),
          h("span", { class: "muted mono" }, `${(row.apps || []).length} apps`)
        ),
        h("div", { class: "row" }, deploymentStatusBadge(row.status), providerAction)
      ),
      h("div", { class: "stack" }, ...(row.apps || []).map((app) => runtimeAppRow(row.id, app, body)))
    ));
  }

  return h("div", { class: "panel" },
    h("div", { class: "panel__head" }, h("h2", { class: "panel__title" }, "Modal Runtime")),
    body
  );
}

function runtimeAppRow(provider, app, refreshHost) {
  const action = deploymentAction(
    app.status === "current" ? "重新部署" : app.status === "stale" ? "更新" : "部署",
    provider,
    app.app,
    refreshHost,
    true,
    false,
    app.status === "current"
  );
  const weightsStatus = app.weights?.status;
  const detail = app.weightError
    ? app.weightError
    : weightsStatus && weightsStatus !== "ready"
      ? `weights: ${weightsStatus}`
      : app.error;
  return h("div", { class: "row spread" },
    h("div", { class: "stack" },
      h("span", { class: "mono" }, app.app || "—"),
      detail ? h("span", { class: "muted" }, detail) : null
    ),
    h("div", { class: "row" }, deploymentStatusBadge(app.status), action)
  );
}

function deploymentStatusBadge(status) {
  const mapped = status === "current" ? "available" : ["partial", "stale"].includes(status) ? "degraded" : "unavailable";
  const label = status === "current" ? "当前版本" : status === "stale" ? "已部署 · 需更新" : status === "missing" ? "未部署" : status === "partial" ? "部分状态" : status === "error" ? "状态异常" : "失败";
  return h("span", { class: `badge badge--${mapped === "available" ? "ok" : mapped === "degraded" ? "warn" : "neutral"}` }, label);
}

function runtimeResyncAction(refreshHost) {
  const button = h("button", { class: "btn", type: "button" }, "重新同步状态");
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.replaceChildren(h("span", { class: "spinner" }), "同步中…");
    try {
      const deployments = await apiGet("deployments?refresh=1");
      invalidateCapabilities();
      await loadCapabilities({ refresh: true });
      if (refreshHost?.parentElement) {
        refreshHost.parentElement.replaceWith(deploymentPanel(deployments.providers || []));
      }
      refreshCurrentRoute();
      refreshNavCounts();
      toast("Runtime / Capability 状态已重新同步", "ok");
    } catch (error) {
      toast(`重新同步失败：${String(error.message || error)}`, "danger");
      button.disabled = false;
      button.textContent = "重新同步状态";
    }
  });
  return button;
}

function deploymentAction(
  label, provider, appName, refreshHost, compact = false, missingOnly = false, force = false
) {
  const button = h("button", { class: `btn ${compact ? "btn--sm" : ""}`, type: "button" }, label);
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "部署中…";
    try {
      const payload = {
        provider,
        missingOnly,
        force,
        strategy: "rolling",
      };
      if (appName) payload.app = appName;
      const response = await apiPost("deployments/deploy", payload);
      const job = response.job;
      if (!job?.id) throw new Error("Deployment Job identity 无效");
      toast("Deployment Job 已提交", "ok");
      const finished = await waitForDeploymentJob(job.id, (current) => {
        const targets = current.targets || [];
        const done = targets.filter((item) => ["current", "failed"].includes(item.status)).length;
        button.textContent = targets.length ? `部署 ${done}/${targets.length}` : "部署中…";
      });
      const failed = ["failed", "partial"].includes(finished.status);
      toast(
        failed ? "Runtime 部署未全部成功" : "Runtime 部署完成",
        failed ? "danger" : "ok"
      );
      await refreshDeploymentPanel(refreshHost);
    } catch (error) {
      toast(String(error.message || error), "danger");
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
  });
  return button;
}

async function waitForDeploymentJob(jobId, onProgress = null) {
  const terminal = new Set(["succeeded", "partial", "failed"]);
  for (let attempt = 0; attempt < 3600; attempt += 1) {
    const response = await apiGet(`deployments/jobs/${encodeURIComponent(jobId)}`);
    const job = response.job;
    if (!job?.id) throw new Error("Deployment Job identity 无效");
    if (onProgress) onProgress(job);
    if (terminal.has(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Deployment Job 查询超时；后台部署可能仍在继续");
}

async function refreshDeploymentPanel(host) {
  if (!host?.parentElement) return;
  try {
    const deployments = await apiGet("deployments");
    host.parentElement.replaceWith(deploymentPanel(deployments.providers || []));
  } catch (error) {
    toast(`读取 Runtime 状态失败：${String(error.message || error)}`, "danger");
  }
}
