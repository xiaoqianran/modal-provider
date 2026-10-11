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

  root.append(hubOverview(snap, connections));
  root.append(h("div", { class: "connect-hint" },
    "云端模型部署请运行 deploy-modal.bat；停止云端 App 请运行 delete-modal.bat。"
  ));

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
  try {
    const data = await apiGet("connections");
    connections = data.providers || [];
  } catch (error) {
    toast(`读取连接状态失败：${String(error.message || error)}`, "danger");
  }
  openDrawer("连接 Modal", connectionPanel(connections));
}

function connectionPanel(connections) {
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
  const connectionIndicators = [];
  function renderConnectionState() {
    connect.disabled = false;
    disconnect.disabled = !connectedNow;
    connect.replaceChildren(
      icon("plug", 15),
      connectedNow ? "重新连接 Modal" : "连接 Modal"
    );
    for (const indicator of connectionIndicators) {
      indicator.dot.className = `connect-provider__dot ${connectedNow ? "is-on" : ""}`;
      indicator.label.textContent = connectedNow ? "Connected" : "Disconnected";
    }
  }

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
    h("div", { class: "drawer-actions" }, disconnect, connect),
    h("p", { class: "drawer-copy" }, "Hugging Face Secrets 使用仓库根目录的 modal_provider-create_secrets.bat 配置。")
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
    ? "Prompt → 图片。云端模型部署后可以创建任务。"
    : provider.id === "modal-3d"
      ? "图片 → GLB。前处理和推理由 3D Provider 完成。"
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
