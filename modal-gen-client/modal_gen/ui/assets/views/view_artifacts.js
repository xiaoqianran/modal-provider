// Screen: 产物 — Primary job: 核验并取回 Connector 产物（SHA-256 校验 + 下载）。
import { h, icon, fmtTime, fmtBytes, apiGet, toast, hashChip, jobBadge, stateEmpty, store } from "../app.js";

export async function mountArtifacts(root) {
  root.append(
    h("div", { class: "screen-head" },
      h("h1", { class: "screen-head__title" }, "产物"),
      h("p", { class: "screen-head__job" }, "浏览 Connector 产物，下载并校验 SHA-256，确认内容完整无损。")
    )
  );

  if (!store.reachable) {
    root.append(stateEmpty("Connector 离线", "无法读取产物。", { iconName: "alert" }));
    return;
  }

  const toolbar = h("div", { class: "toolbar" },
    h("span", { class: "muted" }, "从 Connector 内容寻址缓存取回；下载时会重新校验 SHA-256。"),
    h("div", { style: "margin-left:auto" }, h("button", { class: "btn btn--ghost btn--sm", onclick: load }, "刷新"))
  );
  const host = h("div", { class: "art-grid" });
  root.append(toolbar, host);

  async function load() {
    host.replaceChildren(...Array.from({ length: 6 }, () => h("div", { class: "skeleton", style: "height: 220px; border-radius: var(--r2)" })));
    let data;
    try { data = await apiGet("artifacts"); } catch (e) {
      host.replaceChildren(stateEmpty("无法读取产物", String(e.message || e), { iconName: "alert" }));
      return;
    }
    const items = data.artifacts || [];
    if (!items.length) { host.replaceChildren(stateEmpty("暂无产物", "成功任务产生的产物会出现在这里。")); return; }
    host.replaceChildren(...items.map(card));
  }

  function card(art) {
    const isPng = art.mime === "image/png";
    const preview = isPng
      ? h("img", { src: `/ui/api/artifacts/${art.id}/content`, alt: art.id, loading: "lazy" })
      : h("div", { class: "art-card__prev--file" }, icon(art.mime === "model/gltf-binary" ? "cube" : "file", 28), h("div", {}, art.mime));
    const verifyBadge = h("span", { class: "badge badge--neutral", style: "font-size: var(--fs-11)" }, icon("check", 12), "未校验");
    const dlBtn = h("button", { class: "btn btn--primary btn--sm" }, "下载并校验");
    dlBtn.addEventListener("click", async () => {
      dlBtn.disabled = true;
      verifyBadge.className = "badge badge--info";
      verifyBadge.replaceChildren(icon("spark" === "spark" ? "alert" : "alert", 12), "校验中…");
      try {
        const resp = await fetch(`/ui/api/artifacts/${art.id}/content`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const buf = await resp.arrayBuffer();
        const actual = await sha256Hex(buf);
        const expected = art.hash.replace(/^sha256:/, "");
        if (actual.toLowerCase() === expected.toLowerCase()) {
          verifyBadge.className = "badge badge--ok";
          verifyBadge.replaceChildren(icon("check", 12), "已校验");
          // trigger download
          const blob = new Blob([buf]);
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url; a.download = `${art.id}.${isPng ? "png" : "glb"}`;
          a.click(); URL.revokeObjectURL(url);
        } else {
          verifyBadge.className = "badge badge--danger";
          verifyBadge.replaceChildren(icon("alert", 12), "哈希不符");
          toast("产物 SHA-256 不匹配，已拒绝取回", "danger");
        }
      } catch (e) {
        verifyBadge.className = "badge badge--danger";
        verifyBadge.replaceChildren(icon("alert", 12), "取回失败");
        toast(String(e.message || e), "danger");
      } finally { dlBtn.disabled = false; }
    });
    return h("div", { class: "art-card" },
      h("div", { class: "art-card__prev" }, preview),
      h("div", { class: "art-card__body" },
        h("div", { class: "row spread" },
          h("span", { class: "art-card__role" }, art.role),
          verifyBadge
        ),
        h("div", { class: "art-card__meta" }, `${art.mime} · ${fmtBytes(art.bytes)}`),
        h("div", { class: "art-card__meta" }, jobBadge(art.provider || "connector"))
      ),
      h("div", { class: "art-card__body" }, hashChip(art.hash)),
      h("div", { class: "art-card__foot" }, dlBtn)
    );
  }

  load();
}

async function sha256Hex(buf) {
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
