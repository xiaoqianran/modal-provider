// Screen: 连接 — inspect the Provider Hub and manage in-memory Modal connections.
import {
  h, icon, fmtTime, providerBadge, apiGet, apiPost, toast, store, stateEmpty,
} from "../app.js";
import { parseModalTokenCommand } from "../modal_credentials.js";

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
  const command = h("textarea", {
    class: "textarea input--mono connect-command",
    rows: "3",
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
  const status = h("div", { class: "connect-hint" },
    "粘贴完整 Modal CLI 命令会自动提取凭证。Secret 仅保存在当前进程内存。"
  );
  const connect = h("button", { class: "btn btn--primary connect-action", type: "button" },
    icon("plug", 15), "连接 Modal"
  );
  const disconnect = h("button", { class: "btn", type: "button" }, "断开全部");

  command.addEventListener("input", () => {
    const parsed = parseModalTokenCommand(command.value);
    status.className = "connect-hint";
    if (!parsed) {
      status.textContent = command.value.trim()
        ? "未识别到完整的 --token-id 和 --token-secret。"
        : "粘贴完整 Modal CLI 命令会自动提取凭证。Secret 仅保存在当前进程内存。";
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
      await apiPost("providers/connect", {
        tokenId: tokenId.value.trim(),
        tokenSecret: tokenSecret.value,
      });
      tokenSecret.value = "";
      command.value = "";
      status.className = "connect-hint connect-hint--ok";
      status.textContent = "Modal 已连接。";
      toast("2D / 3D 已连接 Modal", "ok");
      setTimeout(() => location.reload(), 250);
    } catch (e) {
      tokenSecret.value = "";
      status.className = "connect-hint connect-hint--error";
      status.textContent = String(e.message || e);
      connect.disabled = false;
      disconnect.disabled = false;
      connect.replaceChildren(icon("plug", 15), "连接 Modal");
    }
  });

  disconnect.addEventListener("click", async () => {
    disconnect.disabled = true;
    try {
      await apiPost("providers/disconnect", {});
      toast("2D / 3D 已断开 Modal", "ok");
      setTimeout(() => location.reload(), 200);
    } catch (e) {
      status.className = "connect-hint connect-hint--error";
      status.textContent = String(e.message || e);
      disconnect.disabled = false;
    }
  });

  const managed = connections.filter((item) => item.managed !== false);
  const count = managed.filter((item) => item.connected).length;
  const allConnected = managed.length > 0 && count === managed.length;

  return h("section", { class: "connect-card" },
    h("div", { class: "connect-card__head" },
      h("div", {},
        h("div", { class: "connect-card__eyebrow" }, "MODAL CONNECTION"),
        h("h2", { class: "connect-card__title" }, "连接 Modal Workspace"),
        h("p", { class: "connect-card__copy" }, "一组凭证同时用于本机 2D / 3D Provider。")
      ),
      h("span", { class: `badge badge--${allConnected ? "ok" : count ? "warn" : "neutral"}` },
        h("span", { class: "badge__dot" }),
        allConnected ? `${count}/${managed.length} 已连接` : count ? `${count}/${managed.length} 部分连接` : "未连接"
      )
    ),
    h("div", { class: "connect-card__body" },
      h("div", { class: "connect-status-grid" },
        ...managed.map((item) => h("div", { class: "connect-provider" },
          h("span", { class: `connect-provider__dot ${item.connected ? "is-on" : ""}` }),
          h("div", {},
            h("strong", {}, item.id === "modal-2d" ? "Modal 2D" : item.id === "modal-3d" ? "Modal 3D" : item.id),
            h("span", {}, item.connected ? "Connected" : "Disconnected")
          )
        ))
      ),
      h("div", { class: "connect-section" },
        h("div", { class: "connect-section__label" }, "Modal CLI 命令"),
        command,
        status
      ),
      h("div", { class: "connect-credentials" },
        field("Token ID", tokenId),
        field("Token Secret", tokenSecret)
      ),
      h("div", { class: "connect-footer" },
        h("span", { class: "connect-footer__note" }, "凭证不会写入数据库或前端存储。"),
        h("div", { class: "row" }, disconnect, connect)
      )
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
