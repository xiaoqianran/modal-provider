// Screen: 创建 — batch 2D prompts or create a 3D asset from an existing image artifact.
// Form is generated from the connector capability descriptor (input.schema),
// so the UI never hard-codes provider fields.
import { h, icon, apiGet, apiPost, toast, stateEmpty, store, loadCapabilities, refreshNavCounts } from "../app.js";
import { canSubmitCapability, capabilityModels, modelStateLabel, runtimeBlockerLabel } from "../runtime_presenter.js";

export async function mountCreate(root) {
  root.append(
    h("div", { class: "screen-head" },
      h("h1", { class: "screen-head__title" }, "创建"),
      h("p", { class: "screen-head__job" }, "2D 支持一行一个 Prompt 批量提交；3D 从产物库直接选择来源图片。提交后保留在当前页面。")
    )
  );

  if (!store.reachable) {
    root.append(stateEmpty("Connector 离线", "创建任务需要本地 Connector 可用。", { iconName: "alert" }));
    return;
  }

  const loading = h("div", { class: "panel" }, h("div", { class: "panel__body" }, skeletonRows(3)));
  root.append(loading);

  let snap;
  try {
    snap = await loadCapabilities();
  } catch (e) {
    loading.replaceWith(stateEmpty("无法读取能力快照", String(e.message || e)));
    return;
  }
  loading.remove();

  const providers = (snap.providers || []).map((p) => ({
    p,
    cap: (p.capabilities || []).find(canSubmitCapability) || (p.capabilities || [])[0],
  }));

  const available = providers.filter((o) => o.cap && canSubmitCapability(o.cap));
  if (!available.length) {
    root.append(
      stateEmpty(
        "当前没有可提交的 Provider",
        "Modal 中已有的 App 仍会显示在下面；版本过旧、权重未就绪或未部署的模型不会被误当成可运行。",
        { iconName: "alert" }
      ),
      unavailableProviderPanel(providers)
    );
    return;
  }

  let selected = available[0];

  const formHost = h("div", { class: "stack" });
  root.append(formHost);
  renderForm(formHost, selected);

  // Surface installed-but-not-runnable models instead of making them disappear.
  const unavailable = providers.filter((o) => !o.cap || !canSubmitCapability(o.cap));
  if (unavailable.length) root.append(unavailableProviderPanel(unavailable));

  function renderForm(host, sel) {
    host.replaceChildren();
    const cap = sel.cap;
    const schema = cap.input?.schema || {};
    const props = schema.properties || {};
    const required = new Set(schema.required || []);
    const limits = cap.input?.limits || {};

    // provider + operation (familiar select)
    const providerSel = h("select", { class: "select" },
      ...providers.filter((o) => o.cap).map((o) => h(
        "option",
        {
          value: o.cap.operation,
          disabled: !canSubmitCapability(o.cap),
        },
        `${o.p.displayName} · ${o.cap.displayName}`
      ))
    );
    providerSel.value = cap.operation;
    providerSel.addEventListener("change", () => {
      const next = available.find((o) => o.cap.operation === providerSel.value);
      if (!next) return;
      selected = next;
      renderForm(host, next);
    });

    const fields = h("div", { class: "stack" });
    const values = {};
    const fieldRefs = {};

    // Material required inputs first, advanced (seed/guidance/profile/idempotency) behind disclosure.
    const advancedKeys = ["seed", "guidance", "profile", "options", "outputRoles", "parent", "retention", "metadata"];
    const ordered = Object.keys(props)
      .filter((k) => k !== "sourceArtifact" && (required.has(k) || !advancedKeys.includes(k)))
      .sort((a, b) => (required.has(a) === required.has(b) ? 0 : required.has(a) ? -1 : 1));

    for (const key of ordered) {
      if (key === "sourceArtifact") continue;
      if (key === "prompt" && props[key]?.type === "string") {
        fields.append(buildPromptBatchField(props[key], required.has(key), values, fieldRefs));
      } else {
        fields.append(buildField(key, props[key], required.has(key), limits, values, fieldRefs));
      }
    }

    // 3D source artifact picker (progressive disclosure)
    let sourceErrEl = null;
    if (props.sourceArtifact) {
      sourceErrEl = renderSourcePicker(fields, values, props.sourceArtifact);
    }

    // advanced disclosure
    const advBody = h("div", { class: "stack" });
    for (const key of advancedKeys) {
      if (props[key] && !required.has(key)) advBody.append(buildField(key, props[key], false, limits, values, fieldRefs));
    }
    const adv = h("details", { class: "disclosure" },
      h("summary", { class: "disclosure__head" }, icon("chevron", 14, "chevron"), "高级参数"),
      h("div", { class: "disclosure__body" }, advBody)
    );

    const submitBtn = h("button", { class: "btn btn--primary btn--block", type: "button" }, "提交生成");
    const statusLine = h("div", { class: "muted", style: "font-size: var(--fs-12)" });
    const submissionHost = h("div", { class: "submission-results" });
    const promptRef = fieldRefs.prompt?.batch ? fieldRefs.prompt : null;
    const syncSubmitLabel = () => {
      if (!promptRef) return;
      const count = parsePromptLines(promptRef.control.value).length;
      submitBtn.textContent = count > 1 ? `提交 ${count} 个任务` : "提交生成";
    };
    promptRef?.control.addEventListener("input", syncSubmitLabel);
    syncSubmitLabel();

    const onSubmit = async () => {
      // validate + paint inline errors
      let ok = true;
      for (const [key, ref] of Object.entries(fieldRefs)) {
        if (!ref.batch) values[key] = readFieldControl(ref.control, ref.spec);
        const err = ref.batch
          ? validatePromptBatch(ref.control.value, ref.spec, ref.required)
          : validateField(key, ref.spec, ref.required, limits, values);
        ref.errEl.textContent = err || "";
        ref.control.setAttribute("aria-invalid", err ? "true" : "false");
        if (err) ok = false;
      }
      if (props.sourceArtifact) {
        const err = values.sourceArtifact ? "" : "需选择来源产物";
        if (sourceErrEl) sourceErrEl.textContent = err;
        if (err) ok = false;
      }
      if (!ok) { statusLine.textContent = "请修正标红的字段。"; statusLine.style.color = "var(--danger)"; return; }

      submitBtn.disabled = true;
      const prompts = promptRef ? parsePromptLines(promptRef.control.value) : [null];
      const baseInputs = { ...values };
      if (props.sourceArtifact) baseInputs.sourceArtifact = values.sourceArtifact;
      delete baseInputs.options;
      if (promptRef) delete baseInputs.prompt;
      submissionHost.replaceChildren();
      const results = [];
      let failed = 0;
      for (let index = 0; index < prompts.length; index += 1) {
        const prompt = prompts[index];
        submitBtn.replaceChildren(h("span", { class: "spinner" }), `提交 ${index + 1}/${prompts.length}`);
        statusLine.style.color = "";
        statusLine.textContent = `正在提交 ${index + 1}/${prompts.length}；提交后会留在当前页面。`;
        const inputs = { ...baseInputs };
        if (promptRef) inputs.prompt = prompt;
        try {
          const response = await apiPost("jobs", { provider: sel.p.id, operation: cap.operation, inputs });
          results.push({ prompt, job: response.job, ok: true });
        } catch (error) {
          failed += 1;
          results.push({ prompt, error: String(error.message || error), ok: false });
        }
        renderSubmissionResults(submissionHost, results, prompts.length);
      }
      submitBtn.disabled = false;
      syncSubmitLabel();
      statusLine.style.color = failed ? "var(--warn)" : "var(--ok)";
      statusLine.textContent = failed
        ? `已提交 ${results.length - failed}/${results.length} 个任务，${failed} 个失败。`
        : `已提交 ${results.length} 个任务。你可以继续编辑并再次提交。`;
      toast(failed ? `${results.length - failed} 个任务已提交，${failed} 个失败` : `${results.length} 个任务已提交`, failed ? "danger" : "ok");
      refreshNavCounts();
    };
    submitBtn.addEventListener("click", onSubmit);

    formHost.append(
      h("div", { class: "panel" },
        h("div", { class: "panel__head" }, h("h2", { class: "panel__title" }, "任务输入")),
        h("div", { class: "panel__body stack" },
          field("Provider / Operation", providerSel, "从实时能力快照中选择"),
          fields,
          adv,
          submitBtn,
          statusLine,
          submissionHost
        )
      )
    );

    // stage preview
    formHost.append(
      h("div", { class: "panel" },
        h("div", { class: "panel__head" }, h("h2", { class: "panel__title" }, "执行阶段")),
        h("div", { class: "panel__body" },
          h("div", { class: "flow" },
            stage("1", "提交", "提交到统一 Connector"),
            arrow(),
            stage("2", "运行", (cap.execution?.stages || []).join(" → ")),
            arrow(),
            stage("3", "产物", (cap.output?.roles || []).join(", "))
          )
        )
      )
    );
  }

  // (errors are painted inline by onSubmit via fieldRefs; nothing to clean up here)
}

function unavailableProviderPanel(rows) {
  const panel = h(
    "div",
    { class: "panel" },
    h(
      "div",
      { class: "panel__head" },
      h("h2", { class: "panel__title" }, `暂不可提交 (${rows.length})`)
    ),
    h("div", { class: "panel__body stack" })
  );
  const body = panel.querySelector(".panel__body");
  for (const row of rows) {
    const cap = row.cap || {};
    const models = capabilityModels(cap);
    const blockerText = (cap.runtimeBlockers || []).length
      ? `阻塞：${cap.runtimeBlockers.map(runtimeBlockerLabel).join("；")}`
      : "后端当前标记该能力不可提交。";
    body.append(
      h(
        "div",
        { class: "banner banner--warn" },
        icon("alert", 16),
        h(
          "div",
          { class: "stack" },
          h("strong", {}, `${row.p.displayName || row.p.id} · ${cap.displayName || cap.operation || "能力"}`),
          h("span", {}, blockerText),
          ...(models.length
            ? models.map((model) => h(
              "span",
              { class: "muted" },
              `${model.model} · ${modelStateLabel(model, " / ")}`
            ))
            : [h("span", { class: "muted" }, "没有可用模型状态。")])
        )
      )
    );
  }
  return panel;
}

function renderSourcePicker(host, values, sourceSpec) {
  const wrap = h("div", { class: "source-picker" });
  const grid = h("div", { class: "source-picker__grid" });
  const status = h("div", { class: "field__hint" }, "读取最近的图片产物…");
  const errEl = h("div", { class: "field__error" });
  const pager = h("div", { class: "source-picker__pager" });
  const role = sourceSpec?.properties?.role?.const || "primary-image";
  const mime = sourceSpec?.properties?.mime?.const || "image/png";
  let page = 1;
  let selectedId = null;

  async function load() {
    grid.replaceChildren(...Array.from({ length: 4 }, () => h("div", { class: "skeleton source-picker__skeleton" })));
    pager.replaceChildren();
    try {
      const data = await apiGet(`artifacts?page=${page}&page_size=8&mime=${encodeURIComponent(mime)}`);
      const items = (data.artifacts || []).filter((item) => !role || item.role === role);
      if (!items.length) {
        grid.replaceChildren();
        status.textContent = `还没有符合 ${role} · ${mime} 的图片。请先生成上游图片。`;
        return;
      }
      status.textContent = `选择一张来源图片 · 共 ${data.total || items.length} 张`;
      grid.replaceChildren(...items.map((art) => h("button", {
        class: `source-tile ${selectedId === art.id ? "is-selected" : ""}`,
        type: "button",
        dataset: { id: art.id },
        "aria-pressed": String(selectedId === art.id),
        onclick: () => {
          selectedId = art.id;
          values.sourceArtifact = { id: art.id, role: art.role, mime: art.mime, hash: art.hash };
          errEl.textContent = "";
          grid.querySelectorAll(".source-tile").forEach((node) => {
            const active = node.dataset.id === art.id;
            node.classList.toggle("is-selected", active);
            node.setAttribute("aria-pressed", String(active));
          });
        },
      },
        h("img", { src: `/ui/api/artifacts/${art.id}/content`, alt: art.id, loading: "lazy", decoding: "async" }),
        h("span", {}, art.model || "生成图片")
      )));
      const pages = Math.max(1, Math.ceil((data.total || 0) / 8));
      pager.append(
        h("button", { class: "btn btn--sm", type: "button", disabled: page <= 1, onclick: () => { page -= 1; load(); } }, "上一页"),
        h("span", { class: "muted" }, `${page} / ${pages}`),
        h("button", { class: "btn btn--sm", type: "button", disabled: page >= pages, onclick: () => { page += 1; load(); } }, "下一页")
      );
    } catch (error) {
      grid.replaceChildren();
      status.textContent = `读取图片产物失败：${String(error.message || error)}`;
    }
  }

  wrap.append(
    h("div", { class: "row spread" },
      h("label", { class: "field__label" }, "来源图片", h("span", { class: "field__req" }, "*")),
      h("a", { class: "btn btn--ghost btn--sm", href: "#/artifacts" }, "打开产物库")
    ),
    status, grid, pager, errEl
  );
  host.append(wrap);
  load();
  return errEl;
}

function buildPromptBatchField(spec, required, values, fieldRefs) {
  const control = h("textarea", {
    class: "textarea prompt-batch",
    rows: "9",
    placeholder: "一行一个 Prompt\n\n例如：\n一只坐在窗边的橘猫\n未来感城市夜景\n白色背景上的产品摄影",
  });
  const errEl = h("div", { class: "field__error", dataset: { err: "prompt" } });
  const hint = h("div", { class: "prompt-batch__hint" });
  const sync = () => {
    const prompts = parsePromptLines(control.value);
    values.prompt = prompts[0];
    hint.textContent = prompts.length
      ? `${prompts.length} 个有效 Prompt · 空行和完全重复行自动忽略 · 最多 50 个`
      : "一行一个 Prompt；空行不会提交。";
    const error = validatePromptBatch(control.value, spec, required);
    errEl.textContent = error || "";
    control.setAttribute("aria-invalid", error ? "true" : "false");
  };
  control.addEventListener("input", sync);
  fieldRefs.prompt = { control, errEl, spec, required, batch: true };
  sync();
  return h("div", { class: "field prompt-batch-field" },
    h("div", { class: "row spread" },
      h("label", { class: "field__label" }, "Prompt", required ? h("span", { class: "field__req" }, "*") : null),
      h("span", { class: "badge badge--accent" }, "批量 · 每行一个")
    ),
    control,
    hint,
    errEl
  );
}

function parsePromptLines(text) {
  const seen = new Set();
  const prompts = [];
  for (const raw of String(text || "").split(/\r?\n/)) {
    const prompt = raw.trim();
    if (!prompt || seen.has(prompt)) continue;
    seen.add(prompt);
    prompts.push(prompt);
  }
  return prompts;
}

function validatePromptBatch(text, spec, required) {
  const prompts = parsePromptLines(text);
  if (required && !prompts.length) return "至少填写一个 Prompt";
  if (prompts.length > 50) return "一次最多提交 50 个 Prompt";
  for (let index = 0; index < prompts.length; index += 1) {
    const prompt = prompts[index];
    if (spec.minLength && prompt.length < spec.minLength) return `第 ${index + 1} 个 Prompt 过短`;
    if (spec.maxLength && prompt.length > spec.maxLength) return `第 ${index + 1} 个 Prompt 超过 ${spec.maxLength} 字符`;
  }
  return "";
}

function renderSubmissionResults(host, results, total) {
  const succeeded = results.filter((item) => item.ok).length;
  host.replaceChildren(
    h("div", { class: "submission-results__head" },
      h("strong", {}, `本次提交 ${results.length}/${total}`),
      h("span", { class: "muted" }, `${succeeded} 成功 · ${results.length - succeeded} 失败`)
    ),
    h("div", { class: "submission-results__list" },
      ...results.slice(-8).map((item) => h("div", { class: `submission-result ${item.ok ? "is-ok" : "is-error"}` },
        h("div", { class: "submission-result__main" },
          h("strong", {}, item.ok ? "已进入任务队列" : "提交失败"),
          item.prompt ? h("span", { title: item.prompt }, item.prompt) : null
        ),
        item.ok
          ? h("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: () => { location.hash = "#/jobs"; } }, "查看任务")
          : h("span", { class: "submission-result__error" }, item.error)
      ))
    )
  );
}

function buildField(key, spec, required, limits, values, fieldRefs) {
  const label = h("label", { class: "field__label" }, key, required ? h("span", { class: "field__req" }, "*") : null);
  let control;
  if (spec.enum) {
    control = h("select", { class: "select" }, h("option", { value: "" }, "— 选择 —"), ...spec.enum.map((v) => h("option", { value: v }, v)));
    const preferred = spec.enum.includes(spec.default)
      ? spec.default
      : required && spec.enum.length === 1
        ? spec.enum[0]
        : "";
    control.value = preferred;
  } else if (spec.type === "integer" || spec.type === "number") {
    control = h("input", { class: "input", type: "number", step: spec.type === "number" ? "any" : "1" });
    if (spec.minimum != null) control.min = spec.minimum;
    if (spec.maximum != null) control.max = spec.maximum;
    if (spec.default != null) control.value = String(spec.default);
  } else if (spec.type === "string") {
    if ((spec.maxLength || 0) > 160) control = h("textarea", { class: "textarea" });
    else control = h("input", { class: "input", type: "text", maxLength: spec.maxLength || 4000 });
    if (typeof spec.default === "string") control.value = spec.default;
  } else {
    control = h("input", { class: "input", type: "text" });
    if (spec.default != null) control.value = String(spec.default);
  }
  const errEl = h("div", { class: "field__error", dataset: { err: key } });
  const sync = () => {
    values[key] = readFieldControl(control, spec);
    const e = validateField(key, spec, required, limits, values);
    errEl.textContent = e || "";
    control.setAttribute("aria-invalid", e ? "true" : "false");
  };
  control.addEventListener(spec.enum ? "change" : "input", sync);
  if (fieldRefs) fieldRefs[key] = { control, errEl, spec, required };
  sync();
  return h("div", { class: "field" }, label, control, errEl);
}

function readFieldControl(control, spec) {
  if (control.value === "") return undefined;
  if (spec.type === "integer" || spec.type === "number") return Number(control.value);
  return control.value;
}

function validateField(key, spec, required, limits, values) {
  const v = values[key];
  if (required && (v === undefined || v === null || v === "")) return `${key} 必填`;
  if (v === undefined || v === null) return "";
  if (spec.enum && !spec.enum.includes(v)) return `${key} 取值非法`;
  if (spec.type === "string") {
    if (spec.minLength && String(v).length < spec.minLength) return `${key} 过短`;
    if (spec.maxLength && String(v).length > spec.maxLength) return `${key} 过长`;
  }
  if (spec.type === "number" || spec.type === "integer") {
    const n = Number(v);
    if (Number.isNaN(n)) return `${key} 必须是数字`;
    if (spec.minimum != null && n < spec.minimum) return `${key} 小于下限`;
    if (spec.maximum != null && n > spec.maximum) return `${key} 大于上限`;
  }
  return "";
}

function field(label, control, hint) {
  return h("div", { class: "field" },
    h("label", { class: "field__label" }, label),
    control,
    hint ? h("div", { class: "field__hint" }, hint) : null
  );
}

function stage(num, title, desc) {
  return h("div", { class: "flow__stage" },
    h("div", { style: "font-weight:600" }, h("span", { class: "flow__step-num" }, num), title),
    h("div", { class: "muted", style: "font-size: var(--fs-12); margin-top: 4px" }, desc)
  );
}
function arrow() { return h("div", { class: "flow__arrow" }, icon("chevron", 18)); }

function skeletonRows(n) {
  return h("div", {}, ...Array.from({ length: n }, () => h("div", { class: "skeleton skel-row" })));
}
