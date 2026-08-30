// Screen: 产物 — visual asset library with paged image / GLB previews.
import { h, icon, fmtBytes, fmtTime, apiGet, stateEmpty, store } from "../app.js";

const PAGE_SIZE = 12;
let modelViewerReady = null;

function ensureModelViewer() {
  if (!modelViewerReady) {
    modelViewerReady = import("https://ajax.googleapis.com/ajax/libs/model-viewer/4.3.1/model-viewer.min.js");
  }
  return modelViewerReady;
}
const FILTERS = [
  { id: "all", label: "全部", mime: "" },
  { id: "image", label: "图片", mime: "image/png" },
  { id: "3d", label: "3D", mime: "model/gltf-binary" },
];

export async function mountArtifacts(root) {
  root.append(
    h("div", { class: "screen-head studio-head" },
      h("div", {},
        h("span", { class: "kicker" }, "ASSET LIBRARY"),
        h("h1", { class: "screen-head__title" }, "产物库"),
        h("p", { class: "screen-head__job" }, "按页浏览生成结果；图片直接预览，GLB 只在打开时加载 3D Viewer。")
      )
    )
  );

  if (!store.reachable) {
    root.append(stateEmpty("Connector 离线", "无法读取产物。", { iconName: "alert" }));
    return;
  }

  let page = 1;
  let filter = FILTERS[0];
  let requestSeq = 0;

  const chips = h("div", { class: "row asset-filter" });
  const refreshBtn = h("button", { class: "btn btn--ghost btn--sm", type: "button" }, "刷新");
  const toolbar = h("div", { class: "toolbar asset-toolbar" },
    chips,
    h("div", { class: "row", style: "margin-left:auto" },
      h("span", { class: "muted asset-count" }, ""),
      refreshBtn
    )
  );
  const host = h("div", { class: "art-grid" });
  const pagerHost = h("div", {});
  root.append(toolbar, host, pagerHost);

  for (const item of FILTERS) {
    const chip = h("button", {
      class: "chip",
      type: "button",
      "aria-pressed": String(item.id === filter.id),
    }, item.label);
    chip.addEventListener("click", () => {
      filter = item;
      page = 1;
      [...chips.children].forEach((node, index) => node.setAttribute("aria-pressed", String(FILTERS[index].id === filter.id)));
      load();
    });
    chips.append(chip);
  }
  refreshBtn.addEventListener("click", load);

  async function load() {
    const seq = ++requestSeq;
    host.replaceChildren(...Array.from({ length: 6 }, () => h("div", { class: "skeleton art-skeleton" })));
    pagerHost.replaceChildren();
    const mime = filter.mime ? `&mime=${encodeURIComponent(filter.mime)}` : "";
    let data;
    try {
      data = await apiGet(`artifacts?page=${page}&page_size=${PAGE_SIZE}${mime}`);
    } catch (error) {
      if (seq !== requestSeq) return;
      host.replaceChildren(stateEmpty("无法读取产物", String(error.message || error), { iconName: "alert" }));
      return;
    }
    if (seq !== requestSeq) return;
    const items = data.artifacts || [];
    const total = data.total || 0;
    toolbar.querySelector(".asset-count").textContent = `共 ${total} 个`;
    if (!items.length) {
      host.replaceChildren(stateEmpty("暂无产物", filter.id === "all" ? "成功任务产生的图片和 3D 资产会出现在这里。" : `当前没有${filter.label}产物。`));
      return;
    }
    host.replaceChildren(...items.map(card));
    pagerHost.replaceChildren(pager(total));
  }

  function card(art) {
    const isImage = art.mime?.startsWith("image/");
    const isGlb = art.mime === "model/gltf-binary";
    const preview = h("button", {
      class: `art-card__prev ${isImage ? "is-image" : isGlb ? "is-3d" : "is-file"}`,
      type: "button",
      onclick: () => openArtifactPreview(art),
      "aria-label": `预览 ${art.id}`,
    },
      isImage
        ? h("img", { src: `/ui/api/artifacts/${art.id}/content`, alt: art.id, loading: "lazy", decoding: "async" })
        : h("div", { class: "art-card__prev--file" },
            icon(isGlb ? "cube" : "file", 30),
            h("strong", {}, isGlb ? "GLB · 点击查看 3D" : art.mime),
            h("span", {}, fmtBytes(art.bytes))
          )
    );
    return h("article", { class: "art-card" },
      preview,
      h("div", { class: "art-card__body" },
        h("div", { class: "row spread" },
          h("span", { class: "art-card__role" }, roleLabel(art.role)),
          h("span", { class: `badge ${isGlb ? "badge--accent" : "badge--neutral"}` }, isGlb ? "3D" : isImage ? "PNG" : "FILE")
        ),
        art.model ? h("div", { class: "art-card__model" }, art.model) : null,
        h("div", { class: "art-card__meta" }, `${fmtBytes(art.bytes)} · ${fmtTime(art.updatedAt)}`),
        h("div", { class: "art-card__meta mono cell-trim", title: art.jobId || "" }, art.jobId || art.id)
      ),
      h("div", { class: "art-card__foot" },
        h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: () => openArtifactPreview(art) }, "预览"),
        h("a", { class: "btn btn--primary btn--sm", href: `/ui/api/artifacts/${art.id}/content`, download: suggestedName(art) }, "下载")
      )
    );
  }

  function pager(total) {
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    return h("div", { class: "asset-pager" },
      h("span", { class: "muted" }, `第 ${page} / ${pages} 页`),
      h("div", { class: "row" },
        h("button", { class: "btn btn--sm", type: "button", disabled: page <= 1, onclick: () => { page -= 1; load(); window.scrollTo({ top: 0, behavior: "smooth" }); } }, "上一页"),
        h("button", { class: "btn btn--sm", type: "button", disabled: page >= pages, onclick: () => { page += 1; load(); window.scrollTo({ top: 0, behavior: "smooth" }); } }, "下一页")
      )
    );
  }

  load();
}

async function openArtifactPreview(art) {
  const isImage = art.mime?.startsWith("image/");
  const isGlb = art.mime === "model/gltf-binary";
  const dialog = h("dialog", { class: "artifact-viewer-dialog" });
  const close = () => {
    const viewer = dialog.querySelector("model-viewer");
    if (viewer) viewer.removeAttribute("src");
    dialog.close();
    dialog.remove();
  };
  const stage = h("div", { class: "artifact-viewer__stage" });
  if (isImage) {
    stage.append(h("img", { src: `/ui/api/artifacts/${art.id}/content`, alt: art.id }));
  } else if (isGlb) {
    stage.append(h("div", { class: "artifact-viewer__empty" }, h("span", { class: "spinner" }), "正在加载 3D Viewer…"));
    try {
      await ensureModelViewer();
      stage.replaceChildren(h("model-viewer", {
        src: `/ui/api/artifacts/${art.id}/content`,
        "camera-controls": true,
        "touch-action": "pan-y",
        "auto-rotate": true,
        "shadow-intensity": "1",
        "environment-image": "neutral",
        alt: "生成的 3D GLB 资产",
      }));
    } catch (error) {
      stage.replaceChildren(h("div", { class: "artifact-viewer__empty" }, icon("alert", 36), "3D Viewer 加载失败", h("span", {}, String(error.message || error))));
    }
  } else {
    stage.append(h("div", { class: "artifact-viewer__empty" }, icon("file", 40), art.mime));
  }
  dialog.append(
    h("div", { class: "artifact-viewer__shell" },
      h("div", { class: "artifact-viewer__head" },
        h("div", {}, h("strong", {}, roleLabel(art.role)), h("span", {}, `${art.model || "生成产物"} · ${fmtBytes(art.bytes)}`)),
        h("button", { class: "icon-btn", type: "button", onclick: close, "aria-label": "关闭预览" }, icon("close", 18))
      ),
      stage,
      h("div", { class: "artifact-viewer__foot" },
        h("span", { class: "mono cell-trim", title: art.id }, art.id),
        h("a", { class: "btn btn--primary btn--sm", href: `/ui/api/artifacts/${art.id}/content`, download: suggestedName(art) }, "下载")
      )
    )
  );
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) close(); });
  document.body.append(dialog);
  dialog.showModal();
}

function roleLabel(role) {
  return { "primary-image": "生成图片", "primary-glb": "3D 资产" }[role] || role || "产物";
}

function suggestedName(art) {
  const ext = art.mime === "image/png" ? "png" : art.mime === "model/gltf-binary" ? "glb" : "bin";
  return `${art.id}.${ext}`;
}
