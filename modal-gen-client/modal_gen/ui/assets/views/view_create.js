// Screen: 创建 — Primary job: 用一句提示词产出一个生成任务（2D 图片 或 3D 资产）。
// Form is generated from the connector capability descriptor (input.schema),
// so the UI never hard-codes provider fields.
import { h, icon, apiGet, apiPost, toast, stateEmpty, store } from "../app.js";

export async function mountCreate(root) {
  root.append(
    h("div", { class: "screen-head" },
      h("h1", { class: "screen-head__title" }, "创建"),
      h("p", { class: "screen-head__job" }, "选择一个 Provider 与 Operation，填写输入并提交一次生成任务。")
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
    snap = (await apiGet("capabilities")).snapshot;
  } catch (e) {
    loading.replaceWith(stateEmpty("无法读取能力快照", String(e.message || e)));
    return;
  }
  loading.remove();

  const providers = (snap.providers || []).map((p) => ({
    p,
    cap: (p.capabilities || []).find((c) => c.status === "available" || c.status === "degraded")
      || (p.capabilities || [])[0],
  }));

  const available = providers.filter((o) => o.cap && (o.cap.status === "available" || o.cap.status === "degraded"));
  if (!available.length) {
    root.append(stateEmpty("暂无可用的 Provider", "当前没有可用 Provider（fail closed）。请先在「Provider Hub」连接 Modal，并确认远程 App 已部署。", { iconName: "alert" }));
    return;
  }

  let selected = available[0];

  const formHost = h("div", { class: "stack" });
  root.append(formHost);
  renderForm(formHost, selected);

  // surface unavailable providers (fail closed) below the form
  const unavailable = providers.filter((o) => !o.cap || (o.cap.status !== "available" && o.cap.status !== "degraded"));
  if (unavailable.length) {
    const panel = h("div", { class: "panel" },
      h("div", { class: "panel__head" }, h("h2", { class: "panel__title" }, `不可用 Provider (${unavailable.length})`)),
      h("div", { class: "panel__body stack" })
    );
    const body = panel.querySelector(".panel__body");
    for (const o of unavailable) {
      body.append(
        h("div", { class: "banner banner--warn" },
          icon("alert", 16),
          h("div", { class: "stack" },
            h("strong", {}, `${o.p.displayName || o.p.id} · ${o.cap.displayName || o.cap.operation}`),
            h("span", {}, "当前不可用（fail closed）。未配置或未就绪时 Connector 不会伪装可用；解决 Provider 侧连接或本地预处理模型后可在此提交。")
          )
        )
      );
    }
    root.append(panel);
  }

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
          disabled: o.cap.status !== "available" && o.cap.status !== "degraded",
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
      .filter((k) => k !== "sourceArtifact")
      .sort((a, b) => (required.has(a) === required.has(b) ? 0 : required.has(a) ? -1 : 1));

    for (const key of ordered) {
      if (key === "sourceArtifact") continue;
      fields.append(buildField(key, props[key], required.has(key), limits, values, fieldRefs));
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

    const onSubmit = async () => {
      // validate + paint inline errors
      let ok = true;
      for (const [key, ref] of Object.entries(fieldRefs)) {
        const err = validateField(key, ref.spec, ref.required, limits, values);
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
      submitBtn.replaceChildren(h("span", { class: "spinner" }), "提交中…");
      try {
        const inputs = { ...values };
        if (props.sourceArtifact) inputs.sourceArtifact = values.sourceArtifact;
        delete inputs.options;
        const payload = { provider: sel.p.id, operation: cap.operation, inputs };
        await apiPost("jobs", payload);
        toast(`${sel.p.displayName} 任务已提交`, "ok");
        location.hash = "#/jobs";
      } catch (e) {
        statusLine.textContent = String(e.message || e);
        submitBtn.disabled = false;
        submitBtn.textContent = "提交生成";
      }
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
          statusLine
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

function renderSourcePicker(host, values, sourceSpec) {
  const pickerWrap = h("div", { class: "stack" });
  const sourceErrEl = h("div", { class: "field__error" });
  const role = sourceSpec?.properties?.role?.const || "compatible artifact";
  const mime = sourceSpec?.properties?.mime?.const || "supported MIME";
  const note = h("div", { class: "field__hint" }, `选择一份 ${role} · ${mime} 产物作为输入。`);
  const sel = h("select", { class: "select" }, h("option", { value: "" }, "— 选择来源产物 —"));
  async function load() {
    try {
      const a = await apiGet("artifacts");
      const role = sourceSpec?.properties?.role?.const || null;
      const mime = sourceSpec?.properties?.mime?.const || null;
      const imgs = (a.artifacts || []).filter((x) =>
        (!role || x.role === role) && (!mime || x.mime === mime)
      );
      if (!imgs.length) {
        pickerWrap.append(h("div", { class: "banner banner--warn" }, icon("alert", 16), `还没有符合 ${role} · ${mime} 的来源产物。请先生成上游 Artifact。`));
        return;
      }
      for (const art of imgs) {
        sel.append(h("option", { value: art.id }, `${art.id} · ${art.hash.slice(0, 16)}…`));
      }
      sel.addEventListener("change", () => {
        if (!sel.value) { values.sourceArtifact = null; return; }
        const art = imgs.find((x) => x.id === sel.value);
        values.sourceArtifact = { id: art.id, role: art.role, mime: art.mime, hash: art.hash };
      });
    } catch (e) {
      pickerWrap.append(h("div", { class: "banner banner--warn" }, icon("alert", 16), "读取产物失败：" + String(e.message || e)));
    }
  }
  pickerWrap.append(field("来源产物 (sourceArtifact)", sel, "必填"), sourceErrEl, note);
  host.append(pickerWrap);
  sel.addEventListener("change", () => { if (sel.value) sourceErrEl.textContent = ""; });
  load();
  return sourceErrEl;
}

function buildField(key, spec, required, limits, values, fieldRefs) {
  const label = h("label", { class: "field__label" }, key, required ? h("span", { class: "field__req" }, "*") : null);
  let control;
  if (spec.enum) {
    control = h("select", { class: "select" }, h("option", { value: "" }, "— 选择 —"), ...spec.enum.map((v) => h("option", { value: v }, v)));
    control.addEventListener("change", () => { values[key] = control.value || undefined; });
  } else if (spec.type === "integer" || spec.type === "number") {
    control = h("input", { class: "input", type: "number", step: spec.type === "number" ? "any" : "1" });
    if (spec.minimum != null) control.min = spec.minimum;
    if (spec.maximum != null) control.max = spec.maximum;
    control.addEventListener("input", () => { values[key] = control.value === "" ? undefined : Number(control.value); });
  } else if (spec.type === "string") {
    if ((spec.maxLength || 0) > 160) control = h("textarea", { class: "textarea" });
    else control = h("input", { class: "input", type: "text", maxLength: spec.maxLength || 4000 });
    control.addEventListener("input", () => { values[key] = control.value || undefined; });
  } else {
    control = h("input", { class: "input", type: "text" });
    control.addEventListener("input", () => { values[key] = control.value || undefined; });
  }
  const errEl = h("div", { class: "field__error", dataset: { err: key } });
  if (fieldRefs) fieldRefs[key] = { control, errEl, spec, required };
  control.addEventListener("input", () => {
    const e = validateField(key, spec, required, limits, values);
    errEl.textContent = e || "";
    control.setAttribute("aria-invalid", e ? "true" : "false");
  });
  return h("div", { class: "field" }, label, control, errEl);
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
