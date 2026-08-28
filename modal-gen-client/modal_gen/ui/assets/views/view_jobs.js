// Screen: 任务 — Primary job: 跟踪进行中的任务，并在需要时取消或查看详情。
import {
  h, icon, fmtTime, fmtBytes, apiGet, apiPost, toast, openDrawer, openDialog, hashChip, jobBadge, stateEmpty, store,
} from "../app.js";

const STATUS_FILTERS = ["all", "running", "succeeded", "failed"];

export async function mountJobs(root) {
  root.append(
    h("div", { class: "screen-head" },
      h("h1", { class: "screen-head__title" }, "任务"),
      h("p", { class: "screen-head__job" }, "监控所有 Connector 任务到终态；可取消进行中的任务或打开详情。")
    )
  );

  if (!store.reachable) {
    root.append(stateEmpty("Connector 离线", "无法读取任务列表。", { iconName: "alert" }));
    return;
  }

  let status = "all";
  let q = "";
  let page = 1;
  let autoPoll = true;
  let timer = null;
  let busy = false;

  const toolbar = h("div", { class: "toolbar" });
  const filterChips = h("div", { class: "row" });
  const search = h("input", { class: "input", placeholder: "搜索 ID / Operation / 提示詞", style: "max-width: 280px" });
  const pollToggle = h("button", { class: "btn btn--ghost btn--sm" }, "自动刷新：开");
  const refreshBtn = h("button", { class: "btn btn--ghost btn--sm" }, "刷新");
  toolbar.append(filterChips, h("div", { class: "row", style: "margin-left:auto" }, search, refreshBtn, pollToggle));

  STATUS_FILTERS.forEach((s) => {
    const chip = h("button", { class: "chip", dataset: { status: s }, "aria-pressed": String(s === status) }, s === "all" ? "全部" : labelFor(s));
    chip.addEventListener("click", () => { status = s; page = 1; refresh(); });
    filterChips.append(chip);
  });

  search.addEventListener("input", (e) => { q = e.target.value; page = 1; refresh(); });
  refreshBtn.addEventListener("click", refresh);
  pollToggle.addEventListener("click", () => { autoPoll = !autoPoll; pollToggle.textContent = `自动刷新：${autoPoll ? "开" : "关"}`; });

  const tableHost = h("div", {});
  root.append(toolbar, tableHost);

  function highlightFilters() {
    filterChips.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.status === status)));
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    highlightFilters();
    tableHost.replaceChildren(h("div", { class: "panel" }, h("div", { class: "panel__body" }, skeletonRows(5))));
    try {
      const data = await apiGet(`jobs?status=${status}&q=${encodeURIComponent(q)}&page=${page}`);
      renderRows(data);
    } catch (e) {
      tableHost.replaceChildren(stateEmpty("无法读取任务", String(e.message || e), { iconName: "alert" }));
    } finally {
      busy = false;
    }
  }

  function renderRows(data) {
    const rows = data.jobs || [];
    const total = data.total || 0;
    if (!rows.length) {
      tableHost.replaceChildren(
        stateEmpty("暂无任务", status === "all" ? "通过「创建」提交第一个生成任务。" : `当前过滤「${labelFor(status)}」下没有任务。`)
      );
      return;
    }
    const panel = h("div", { class: "panel panel__body--flush" });
    const table = h("table", { class: "table" });
    table.append(
      h("thead", {}, h("tr", {}, ...["ID", "Provider", "Operation", "状态", "模型", "提交时间", "耗时", "操作"].map((t) => h("th", {}, t))))
    );
    const tbody = h("tbody", {});
    for (const row of rows) {
      const dur = durOf(row);
      const tr = h("tr", { class: "row--clickable", onclick: () => openJob(row) },
        h("td", { class: "col-mono" }, trunc(row.id)),
        h("td", {}, row.provider),
        h("td", {}, trunc(row.operation, 16, 10)),
        h("td", {}, jobBadge(row.status)),
        h("td", { class: "mono" }, row.model?.id || "—"),
        h("td", { class: "dim tabular" }, fmtTime(row.createdAt)),
        h("td", { class: "dim tabular" }, dur),
        h("td", {}, h("button", { class: "btn btn--ghost btn--sm", onclick: (e) => { e.stopPropagation(); onCancel(row); } }, cancelLabel(row.status)))
      );
      tbody.append(tr);
    }
    table.append(tbody);
    panel.append(table);
    // pagination
    const pages = Math.max(1, Math.ceil(total / 25));
    const pager = h("div", { class: "toolbar", style: "padding: var(--s3) var(--s4)" },
      h("span", { class: "muted" }, `共 ${total} 条`),
      h("div", { class: "row", style: "margin-left:auto", },
        h("button", { class: "btn btn--sm", disabled: page <= .2, onclick: () => { page--; refresh(); } }, "上一页"),
        h("span", { class: "dim tabular" }, `${page} / ${pages}`),
        h("button", { class: "btn btn--sm", disabled: page >= pages, onclick: () => { page++; refresh(); } }, "下一页")
      )
    );
    panel.append(pager);
    tableHost.replaceChildren(panel);
  }

  function onCancel(row) {
    if (["succeeded", "failed", "cancelled", "expired"].includes(row.status)) {
      toast("终态任务不可取消", "danger");
      return;
    }
    openDialog({
      title: "取消任务",
      body: h("div", {}, `确认取消任务 `, h("span", { class: "mono" }, row.id), `？进行中的阶段会被中断。`),
      confirm: "取消任务",
      danger: true,
      onConfirm: async () => {
        try {
          await apiPost("cancel", { jobId: row.id });
          toast("已请求取消", "ok");
          refresh();
        } catch (e) { toast(String(e.message || e), "danger"); }
      },
    });
  }

  async function openJob(row) {
    const data = await apiGet(`jobs/${row.id}`).catch(() => ({ job: row }));
    const job = data.job || row;
    const body = h("div", { class: "stack" });
    body.append(
      h("div", { class: "row spread" },
        h("span", { class: "mono" }, job.id),
        jobBadge(job.status)
      ),
      kv([["Provider", job.provider], ["Operation", job.operation], ["模型", job.model?.id || "—"], ["阶段", job.stage || "—"], ["提交时间", fmtTime(job.createdAt)], ["完成时间", fmtTime(job.completedAt)], ["更新时间", fmtTime(job.updatedAt)]]),
      job.prompt ? h("div", { class: "field" }, h("label", { class: "field__label" }, "提示词"), h("div", { class: "cell-trim", title: job.prompt }, job.prompt)) : null,
      job.error ? h("div", { class: "banner banner--offline" }, icon("alert", 16), h("span", {}, `${job.error.code || "错误"}${job.error.recoverable ? "（可重试）" : ""}`)) : null,
      h("div", { class: "stack" },
        h("label", { class: "field__label" }, "Request Hash"),
        hashChip(job.requestHash)
      ),
      h("div", { class: "stack" },
        h("label", { class: "field__label" }, "Idempotency Key"),
        hashChip(job.idempotencyKey)
      ),
      h("div", { class: "stack" },
        h("label", { class: "field__label" }, "Capability 来源"),
        h("div", { class: "hash" }, h("span", { class: "hash__val" }, `${job.capabilityHash} · ${job.capabilityRevision}`))
      ),
      job.result?.artifacts?.length
        ? h("div", { class: "stack" },
            h("label", { class: "field__label" }, "产物"),
            ...job.result.artifacts.map((a) => h("div", { class: "row spread" }, h("span", {}, `${a.role} · ${a.mime}`), h("a", { class: "btn btn--ghost btn--sm", href: `/ui/api/artifacts/${a.id}/content` }, "下载")))
          )
        : null
    );
    openDrawer("任务详情", body);
  }

  store.cleanup = () => { if (timer) clearInterval(timer); };
  function tick() {
    if (autoPoll && status === "all" ? true : true) refresh();
  }
  refresh();
  timer = setInterval(() => { if (autoPoll && document.visibilityState === "visible") tick(); }, 4000);

  // helpers
  function trunc(text, head = 12, tail = 8) { return text; }
  function durOf(row) {
    if (!row.startedAt) return "—";
    const end = row.completedAt || row.updatedAt;
    const a = new Date(row.startedAt), b = new Date(end);
    if (isNaN(a) || isNaN(b)) return "—";
    const s = Math.max(0, (b - a) / 1000);
    return `${s.toFixed(0)}s`;
  }
  function cancelLabel(status) {
    return ["succeeded", "failed", "cancelled", "expired"].includes(status) ? "详情" : "取消";
  }
}

function labelFor(status) {
  return { all: "全部", running: "进行中", succeeded: "成功", failed: "失败" }[status] || status;
}
function kv(rows) {
  const el = h("div", { class: "kv" });
  for (const [k, v] of rows) if (v != null) el.append(h("span", { class: "kv__key" }, k), h("span", { class: "kv__val" }, v));
  return el;
}
function skeletonRows(n) {
  return h("div", {}, ...Array.from({ length: n }, () => h("div", { class: "skeleton skel-row" })));
}
