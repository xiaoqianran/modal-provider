// Screen: 连接 — inspect the Provider Hub and manage in-memory Modal connections.
import {
  h, icon, fmtTime, providerBadge, apiGet, apiPost, toast, store, stateEmpty,
} from "../app.js";

export async function mountConnect(root) {
  root.append(
    h("div", { class: "screen-head" },
      h("h1", { class: "screen-head__title" }, "Provider Hub"),
      h("p", { class: "screen-head__job" }, "modal-gen 聚合本机 Provider；2D / 3D client 直接连接已部署的 Modal App。")
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
      apiGet("capabilities"),
      apiGet("connections").catch(() => ({ providers: [] })),
    ]);
    snap = caps.snapshot;
    connections = conns.providers || [];
  } catch (e) {
    loading.replaceWith(stateEmpty("无法读取 Provider Hub", String(e.message || e)));
    return;
  }
  loading.remove();

  root.append(hubOverview(snap, connections));

  if (store.mode === "live") {
    root.append(connectionPanel(connections));
  }

  const providers = h("div", { class: "stack" });
  const connectionMap = new Map(connections.map((item) => [item.id, item]));
  for (const provider of snap.providers || []) {
    providers.append(providerCard(provider, connectionMap.get(provider.id)));
  }
  root.append(providers);

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

function connectionPanel(connections) {
  const tokenId = h("input", {
    class: "input input--mono",
    type: "text",
    autocomplete: "off",
    placeholder: "Modal token id",
  });
  const tokenSecret = h("input", {
    class: "input input--mono",
    type: "password",
    autocomplete: "off",
    placeholder: "Modal token secret",
  });
  const status = h("div", { class: "field__hint" }, "凭证只用于当前进程内存，不写入 Connector DB。以部署了 2D / 3D App 的 Modal Workspace 凭证为准。");
  const connect = h("button", { class: "btn btn--primary", type: "button" }, "连接 2D + 3D");
  const disconnect = h("button", { class: "btn", type: "button" }, "断开全部");

  connect.addEventListener("click", async () => {
    if (!tokenId.value.trim() || !tokenSecret.value.trim()) {
      status.textContent = "Token ID / Secret 均不能为空。";
      return;
    }
    connect.disabled = true;
    connect.replaceChildren(h("span", { class: "spinner" }), "连接中…");
    try {
      await apiPost("providers/connect", {
        tokenId: tokenId.value.trim(),
        tokenSecret: tokenSecret.value,
      });
      tokenSecret.value = "";
      toast("2D / 3D Provider 已连接 Modal", "ok");
      location.reload();
    } catch (e) {
      tokenSecret.value = "";
      status.textContent = String(e.message || e);
      connect.disabled = false;
      connect.textContent = "连接 2D + 3D";
    }
  });

  disconnect.addEventListener("click", async () => {
    disconnect.disabled = true;
    try {
      await apiPost("providers/disconnect", {});
      toast("Provider 已断开 Modal", "ok");
      location.reload();
    } catch (e) {
      status.textContent = String(e.message || e);
      disconnect.disabled = false;
    }
  });

  const count = connections.filter((item) => item.connected).length;
  return h("div", { class: "panel", style: "margin-bottom: var(--s4)" },
    h("div", { class: "panel__head" },
      h("h2", { class: "panel__title" }, "Modal 连接"),
      h("span", { class: `badge badge--${count ? "ok" : "neutral"}` }, `${count} connected`)
    ),
    h("div", { class: "panel__body stack" },
      h("div", { class: "grid-2" },
        field("Token ID", tokenId),
        field("Token Secret", tokenSecret)
      ),
      h("div", { class: "row" }, connect, disconnect),
      status
    )
  );
}

function providerCard(provider, connection) {
  const capabilities = provider.capabilities || [];
  const connected = connection?.connected === true;
  return h("div", { class: "panel" },
    h("div", { class: "panel__head" },
      h("h2", { class: "panel__title" }, provider.displayName || provider.id),
      providerBadge(provider.status),
      h("span", { class: `badge badge--${connected ? "ok" : "neutral"}` }, connected ? "Modal 已连接" : "Modal 未连接")
    ),
    h("div", { class: "panel__body stack" },
      kv([
        ["Provider", provider.id],
        ["Health", provider.health || "—"],
        ["Revision", provider.implementationRevision || "—"],
        ["Artifact transport", provider.artifactTransport || "—"],
      ]),
      ...capabilities.map(capabilityCard)
    )
  );
}

function capabilityCard(capability) {
  const schema = capability.input?.schema || {};
  const modelIds = schema.properties?.model?.enum || [];
  const roles = capability.output?.roles || [];
  return h("div", { class: "cap-row" },
    h("div", { class: "row spread" },
      h("strong", {}, capability.displayName || capability.operation),
      providerBadge(capability.status)
    ),
    kv([
      ["Operation", capability.operation],
      ["Models", modelIds.join(" · ") || "—"],
      ["Output", roles.join(" · ") || "—"],
      ["Profiles", Object.keys(capability.profiles || {}).join(" · ") || "—"],
    ])
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

function field(label, control) {
  return h("label", { class: "field" }, h("span", { class: "field__label" }, label), control);
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
