// Screen: 连接 — Primary job: 确认本机 Connector 与 Provider 可用，或在需要时批准配对。
import {
  h, icon, fmtTime, providerBadge, apiGet, apiPost, toast, store, stateEmpty,
} from "../app.js";

export async function mountConnect(root) {
  root.append(
    h("div", { class: "screen-head" },
      h("h1", { class: "screen-head__title" }, "连接"),
      h("p", { class: "screen-head__job" }, "确认本机 Connector 与两个 Provider 可用；若收到配对请求，在此批准。")
    )
  );

  if (!store.reachable) {
    root.append(
      h("div", { class: "banner banner--offline" },
        icon("alert", 18),
        h("div", { class: "stack" },
          h("strong", {}, "Connector 离线"),
          h("span", {}, "无法连接本机 Connector。请确认 modal-gen-agent 正在运行，且监听 127.0.0.1。")
        ),
        h("button", { class: "btn btn--primary", onclick: () => location.reload() }, "重试")
      )
    );
    root.append(stateEmpty("先启动 Connector", "本机控制台依赖本地 Connector 提供 /connector/v1/* 与 /v1/* 接口。"));
    return;
  }

  const loading = h("div", { class: "panel" }, h("div", { class: "panel__body" }, skeletonRows(3)));
  root.append(loading);

  let data;
  try {
    data = await apiGet("capabilities");
  } catch (e) {
    loading.replaceWith(stateEmpty("无法读取能力快照", String(e.message || e)));
    return;
  }
  loading.remove();

  const snap = data.snapshot;
  root.append(
    h("div", { class: "panel", style: "margin-bottom: var(--s4)" },
      h("div", { class: "panel__head" },
        h("h2", { class: "panel__title" }, "本地 Connector"),
        h("span", { class: "badge badge--neutral" }, snap.contractVersion)
      ),
      h("div", { class: "panel__body" },
        kv([
          ["实例", snap.connector?.id || "—"],
          ["版本", snap.connector?.version || "—"],
          ["快照 revision", snap.revision],
          ["快照 hash", snap.hash],
          ["生成于", fmtTime(snap.generatedAt)],
          ["过期于", fmtTime(snap.expiresAt)],
        ])
      )
    )
  );

  const providers = h("div", { class: "stack" });
  root.append(providers);
  for (const p of snap.providers) {
    providers.append(providerCard(p));
  }

  // live: pending pairings
  try {
    const pr = await apiGet("pairings");
    const pending = (pr.pairings || []).filter((x) => x.status === "pending");
    if (pending.length) {
      const panel = h("div", { class: "panel", style: "margin-top: var(--s4)" },
        h("div", { class: "panel__head" }, h("h2", { class: "panel__title" }, `待批准配对 (${pending.length})`)),
        h("div", { class: "panel__body stack" })
      );
      const body = panel.querySelector(".panel__body");
      for (const item of pending) {
        body.append(
          h("div", { class: "row spread" },
            h("div", { class: "stack" },
              h("span", { class: "mono" }, item.id),
              h("span", { class: "muted" }, `${item.origin} · ${item.scopes.join(", ")}`)
            ),
            h("button", {
              class: "btn btn--primary btn--sm", onclick: async (ev) => {
                ev.target.disabled = true;
                try { await apiPost("pairings/approve", { pairingId: item.id }); toast("已批准配对", "ok"); ev.target.textContent = "已批准"; }
                catch (e) { toast(String(e.message || e), "danger"); }
              },
            }, "批准")
          )
        );
      }
      root.append(panel);
    }
  } catch { /* pairing list optional */ }
}

function providerCard(p) {
  const cap = (p.capabilities || [])[0] || {};
  const schema = cap.input?.schema || {};
  const props = schema.properties || {};
  const enumModels = props.model?.enum || [];
  const roles = (cap.output?.roles || []).join(", ");
  const limits = cap.input?.limits || {};
  const disabled = p.status === "disabled" || p.status === "unavailable";
  return h("div", { class: "panel" },
    h("div", { class: "panel__head" },
      h("h2", { class: "panel__title" }, p.displayName || p.id),
      providerBadge(p.status),
      h("span", { class: "muted" }, cap.displayName || cap.operation)
    ),
    h("div", { class: "panel__body" },
      disabled
        ? h("div", { class: "banner banner--warn" }, icon("alert", 16), "当前不可用（fail closed）。未配置或未就绪时 Connector 不会伪装可用。")
        : h("div", { class: "grid-2" },
            kv([
              ["提供商 ID", p.id],
              ["Operation", cap.operation || "—"],
              ["类别", cap.category || "—"],
              ["输出角色", roles || "—"],
              ["可用模型", enumModels.join(" · ") || "—"],
              ["限制", Object.entries(limits).map(([k, v]) => `${k}=${v}`).join(" ") || "—"],
            ])
          ),
      cap.profiles && Object.keys(cap.profiles).length
        ? h("div", { class: "muted", style: "margin-top: var(--s3)" }, "支持 profile：", Object.keys(cap.profiles).join(", "))
        : null
    )
  );
}

function kv(rows) {
  const el = h("div", { class: "kv" });
  for (const [k, v] of rows) {
    if (v == null) continue;
    el.append(h("span", { class: "kv__key" }, k), h("span", { class: "kv__val" }, v));
  }
  return el;
}

function skeletonRows(n) {
  return h("div", {}, ...Array.from({ length: n }, () => h("div", { class: "skeleton skel-row" })));
}
