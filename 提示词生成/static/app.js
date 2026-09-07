const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = document.querySelectorAll(".tab-panel");

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.remove("active"));
    tabPanels.forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`panel-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "history") loadHistory();
    if (btn.dataset.tab === "products") loadProducts();
  });
});

const resultTabButtons = document.querySelectorAll(".result-tab-btn");
const resultPanels = document.querySelectorAll(".result-panel");

resultTabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    resultTabButtons.forEach((b) => b.classList.remove("active"));
    resultPanels.forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`result-${btn.dataset.resultTab}`).classList.add("active");
  });
});

function escapeHtml(text) {
  return String(text).replace(/</g, "&lt;");
}

function copyText(text) {
  navigator.clipboard.writeText(text);
}

const ROLE_LABELS = {
  hook: "开场钩子（前贴）",
  setup: "引入",
  buildup: "铺垫",
  climax: "高潮/卖点展示",
  cta: "行动号召",
  other: "其他",
};

function roleLabel(role) {
  return ROLE_LABELS[role] || role;
}

// ---- Prompt trace（沿用脚本分析工作台的展示逻辑）----

function formatVarValue(value) {
  if (value === null || value === undefined) return "--";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function promptSection(label, text, { highlight = false } = {}) {
  if (!text) return "";
  const id = `prompt-${Math.random().toString(36).slice(2)}`;
  return `
    <div class="prompt-section${highlight ? " prompt-section-highlight" : ""}">
      <div class="prompt-section-label">
        <span>${label}</span>
        <button class="btn-copy" data-copy-target="${id}">复制</button>
      </div>
      <pre id="${id}">${escapeHtml(text)}</pre>
    </div>`;
}

function variablesSection(variables) {
  const entries = Object.entries(variables || {});
  if (entries.length === 0) return "";
  const items = entries.map(([key, value]) => promptSection(key, formatVarValue(value))).join("");
  return `
    <div class="prompt-section">
      <div class="prompt-section-label"><span>③ Variables（本次注入的变量）</span></div>
      <div class="variables-list">${items}</div>
    </div>`;
}

function badgeRow(title, pairs) {
  const badges = pairs
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `<span class="badge"><b>${k}</b>${v}</span>`)
    .join("");
  return `
    <div class="prompt-section">
      <div class="prompt-section-label"><span>${title}</span></div>
      <div class="badge-row">${badges}</div>
    </div>`;
}

function renderPromptTrace(steps) {
  const promptsEl = document.getElementById("result-prompts");
  promptsEl.innerHTML =
    (steps || [])
      .map((step) => {
        const mp = step.model_params || {};
        const meta = step.metadata || {};
        return `
      <div class="prompt-block">
        <h3>${step.label}</h3>
        ${promptSection("① System Prompt", step.system_prompt)}
        ${promptSection("② User Prompt", step.user_prompt)}
        ${variablesSection(step.variables)}
        ${promptSection("④ Final Prompt（实际发送内容，完整可复制）", step.final_prompt, { highlight: true })}
        ${badgeRow("⑤ Model Config", [
          ["模型: ", mp.model ?? "--"],
          ["Temperature: ", mp.temperature ?? "默认"],
          ["Max Tokens: ", mp.max_tokens ?? "--"],
        ])}
        ${promptSection("⑥ Response", step.response)}
        ${badgeRow("⑦ Metadata", [
          ["Input Tokens: ", meta.input_tokens ?? "--"],
          ["Output Tokens: ", meta.output_tokens ?? "--"],
          ["耗时: ", meta.elapsed_ms !== undefined && meta.elapsed_ms !== null ? `${meta.elapsed_ms}ms` : "--"],
          ["预估费用: ", meta.cost_usd !== undefined && meta.cost_usd !== null ? `$${meta.cost_usd}` : "N/A"],
        ])}
      </div>`;
      })
      .join("") || "<p>无 Prompt 记录</p>";

  promptsEl.querySelectorAll(".btn-copy").forEach((btn) => {
    btn.addEventListener("click", () => copyText(document.getElementById(btn.dataset.copyTarget).textContent));
  });
}

// ---- 生成结果渲染（一次生成 5 条脚本变体，可切换查看）----

let currentResult = null;
let currentScriptIndex = 0;

const STATUS_LABELS = { pending: "待定", adopted: "已采纳", edited: "已优化编辑", discarded: "已弃用" };
const STATUS_CLASS = {
  pending: "status-pending",
  adopted: "status-adopted",
  edited: "status-edited",
  discarded: "status-discarded",
};

function getScriptState(index) {
  return (currentResult.script_states || [])[index] || { status: "pending", edited_plain_script: null, edited_video_prompts: {} };
}

function effectivePlainScript(index) {
  const state = getScriptState(index);
  return state.edited_plain_script || currentResult.plain_scripts[index];
}

function effectivePromptText(index, segIndex, field) {
  const state = getScriptState(index);
  const edit = (state.edited_video_prompts || {})[String(segIndex)];
  if (edit && edit[field]) return edit[field];
  return currentResult.scripts[index].video_prompts[segIndex]?.[field] || "";
}

function renderScriptStatusBar() {
  const bar = document.getElementById("script-status-bar");
  const state = getScriptState(currentScriptIndex);
  bar.innerHTML = `
    <span class="status-badge ${STATUS_CLASS[state.status]}">${STATUS_LABELS[state.status]}</span>
    <button type="button" class="btn-secondary" data-status-action="adopted">采纳</button>
    <button type="button" class="btn-secondary" data-status-action="edit-mode">优化编辑</button>
    <button type="button" class="btn-secondary" data-status-action="discarded">弃用</button>
  `;
  bar.querySelector('[data-status-action="adopted"]').addEventListener("click", () => setScriptStatus("adopted"));
  bar.querySelector('[data-status-action="discarded"]').addEventListener("click", () => setScriptStatus("discarded"));
  bar.querySelector('[data-status-action="edit-mode"]').addEventListener("click", () => {
    document.querySelector('.result-tab-btn[data-result-tab="plain"]').click();
    startPlainEdit();
  });
}

async function setScriptStatus(status) {
  if (!currentResult.id) return;
  const resp = await fetch(`api/history/${currentResult.id}/scripts/${currentScriptIndex}/status`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!resp.ok) return;
  const entry = await resp.json();
  currentResult.script_states = entry.result.script_states;
  renderScriptStatusBar();
}

function renderStructured(script) {
  const el = document.getElementById("result-structured");
  el.innerHTML =
    script.structure
      .map((seg, i) => {
        const lines = script.dialogue.filter((d) => d.segment_index === i);
        const dialogueHtml = lines
          .map((line) => `<div class="dialogue-line">${line.speaker ? `<b>${escapeHtml(line.speaker)}：</b>` : ""}${escapeHtml(line.text)}</div>`)
          .join("");
        return `
        <div class="card">
          <div class="meta">${seg.duration_sec ? `约${seg.duration_sec}秒` : ""}</div>
          <span class="role-badge">${roleLabel(seg.role)}</span>
          <div>${escapeHtml(seg.summary)}</div>
          ${dialogueHtml ? `<div class="dialogue-block">${dialogueHtml}</div>` : ""}
        </div>`;
      })
      .join("") || "<p>无结构化数据</p>";
}

function renderVideoPrompts(elId, promptField, script, scriptIndex) {
  const el = document.getElementById(elId);
  el.innerHTML =
    script.video_prompts
      .map((p, segIndex) => {
        const viewId = `vp-${Math.random().toString(36).slice(2)}`;
        const editId = `${viewId}-edit`;
        const text = effectivePromptText(scriptIndex, segIndex, promptField);
        return `
        <div class="card">
          <div class="meta">${p.duration_sec ? `约${p.duration_sec}秒` : ""}</div>
          <span class="role-badge">${roleLabel(p.role)}</span>
          <div class="prompt-section-label">
            <button class="btn-copy" data-copy-target="${viewId}">复制</button>
            <button class="btn-copy btn-edit-prompt" data-view-target="${viewId}" data-edit-target="${editId}">编辑</button>
          </div>
          <pre id="${viewId}">${escapeHtml(text)}</pre>
          <textarea id="${editId}" class="hidden" rows="6">${escapeHtml(text)}</textarea>
          <div class="form-actions prompt-edit-actions hidden">
            <button type="button" class="btn-secondary btn-save-prompt" data-field="${promptField}" data-seg-index="${segIndex}" data-view-target="${viewId}" data-edit-target="${editId}">保存</button>
            <button type="button" class="btn-secondary btn-cancel-prompt" data-view-target="${viewId}" data-edit-target="${editId}">取消</button>
          </div>
        </div>`;
      })
      .join("") || "<p>无视频提示词数据</p>";

  el.querySelectorAll(".btn-copy[data-copy-target]").forEach((btn) => {
    btn.addEventListener("click", () => copyText(document.getElementById(btn.dataset.copyTarget).textContent));
  });
  el.querySelectorAll(".btn-edit-prompt").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById(btn.dataset.viewTarget).classList.add("hidden");
      document.getElementById(btn.dataset.editTarget).classList.remove("hidden");
      btn.closest(".card").querySelector(".prompt-edit-actions").classList.remove("hidden");
      btn.classList.add("hidden");
    });
  });
  el.querySelectorAll(".btn-cancel-prompt").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".card");
      document.getElementById(btn.dataset.viewTarget).classList.remove("hidden");
      document.getElementById(btn.dataset.editTarget).classList.add("hidden");
      card.querySelector(".prompt-edit-actions").classList.add("hidden");
      card.querySelector(".btn-edit-prompt").classList.remove("hidden");
    });
  });
  el.querySelectorAll(".btn-save-prompt").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const text = document.getElementById(btn.dataset.editTarget).value;
      if (!currentResult.id) return;
      const resp = await fetch(`api/history/${currentResult.id}/scripts/${currentScriptIndex}/edit`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_prompts: { [btn.dataset.segIndex]: { [btn.dataset.field]: text } } }),
      });
      if (!resp.ok) return;
      const entry = await resp.json();
      currentResult.script_states = entry.result.script_states;
      renderCurrentScript();
    });
  });
}

function renderPlainScript() {
  const text = effectivePlainScript(currentScriptIndex);
  document.getElementById("plain-script").textContent = text;
  document.getElementById("plain-script-edit").value = text;
  document.getElementById("plain-script").classList.remove("hidden");
  document.getElementById("plain-script-edit").classList.add("hidden");
  document.getElementById("edit-plain-btn").classList.remove("hidden");
  document.getElementById("save-plain-btn").classList.add("hidden");
  document.getElementById("cancel-plain-btn").classList.add("hidden");
}

function startPlainEdit() {
  document.getElementById("plain-script").classList.add("hidden");
  document.getElementById("plain-script-edit").classList.remove("hidden");
  document.getElementById("edit-plain-btn").classList.add("hidden");
  document.getElementById("save-plain-btn").classList.remove("hidden");
  document.getElementById("cancel-plain-btn").classList.remove("hidden");
}

document.getElementById("edit-plain-btn").addEventListener("click", startPlainEdit);
document.getElementById("cancel-plain-btn").addEventListener("click", renderPlainScript);
document.getElementById("save-plain-btn").addEventListener("click", async () => {
  const text = document.getElementById("plain-script-edit").value;
  if (!currentResult.id) return;
  const resp = await fetch(`api/history/${currentResult.id}/scripts/${currentScriptIndex}/edit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plain_script: text }),
  });
  if (!resp.ok) return;
  const entry = await resp.json();
  currentResult.script_states = entry.result.script_states;
  renderPlainScript();
  renderScriptStatusBar();
});

function renderScriptTabs() {
  const tabsEl = document.getElementById("script-tabs");
  tabsEl.innerHTML = currentResult.scripts
    .map((s, i) => `<button class="tab-btn${i === currentScriptIndex ? " active" : ""}" data-script-index="${i}">脚本${i + 1}</button>`)
    .join("");
  tabsEl.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentScriptIndex = Number(btn.dataset.scriptIndex);
      renderCurrentScript();
    });
  });
}

function renderCurrentScript() {
  renderScriptTabs();
  const script = currentResult.scripts[currentScriptIndex];
  const model = currentResult.prompt_trace?.[0]?.model_params?.model;
  const modelBadge = model ? `<span class="model-badge">调用模型: ${escapeHtml(model)}</span>` : "";
  const parts = [];
  if (script.variant_title) parts.push(`<b>${escapeHtml(script.variant_title)}</b>`);
  if (script.variant_style) parts.push(escapeHtml(script.variant_style));
  const variantMeta = parts.join(" — ");
  document.getElementById("script-variant-meta").innerHTML = `${variantMeta} ${modelBadge}`.trim();
  renderScriptStatusBar();
  renderStructured(script);
  renderPlainScript();
  renderVideoPrompts("result-jimeng", "jimeng_prompt", script, currentScriptIndex);
  renderVideoPrompts("result-kling", "kling_prompt", script, currentScriptIndex);
}

function renderGenerationResult(result) {
  currentResult = result;
  currentScriptIndex = 0;
  renderCurrentScript();
  renderPromptTrace(result.prompt_trace);
  document.getElementById("result").classList.remove("hidden");
  document.getElementById("result").scrollIntoView({ behavior: "smooth" });
}

document.getElementById("copy-plain").addEventListener("click", () => {
  copyText(document.getElementById("plain-script").textContent);
});

// ---- 参考脚本 / 产品 下拉选项 ----

async function loadSourceScripts() {
  const select = document.getElementById("source-select");
  select.innerHTML = "<option>加载中…</option>";
  try {
    const resp = await fetch("api/source-scripts");
    const scripts = await resp.json();
    if (scripts.length === 0) {
      select.innerHTML = '<option value="">暂无可用分析结果，请先去「脚本分析」工作台生成</option>';
      return;
    }
    select.innerHTML = scripts
      .map(
        (s) =>
          `<option value="${s.id}">${escapeHtml(s.title)}${s.hook_type ? ` · ${escapeHtml(s.hook_type)}` : ""}</option>`
      )
      .join("");
  } catch (err) {
    select.innerHTML = `<option value="">加载失败：${escapeHtml(err.message)}</option>`;
  }
}

async function loadProductOptions() {
  const select = document.getElementById("product-select");
  select.innerHTML = "<option>加载中…</option>";
  try {
    const resp = await fetch("api/products");
    const items = await resp.json();
    if (items.length === 0) {
      select.innerHTML = '<option value="">暂无产品，请先去「产品库」创建</option>';
      return;
    }
    select.innerHTML = items.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  } catch (err) {
    select.innerHTML = `<option value="">加载失败：${escapeHtml(err.message)}</option>`;
  }
}

// ---- 生成表单 ----

const generateForm = document.getElementById("generate-form");
const generateProgress = document.getElementById("generate-progress");
const generateError = document.getElementById("generate-error");

generateForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  generateError.classList.add("hidden");
  const sourceId = document.getElementById("source-select").value;
  const productId = document.getElementById("product-select").value;
  const useFeedbackReference = document.getElementById("use-feedback-reference").checked;
  const scriptCount = Number(document.getElementById("script-count").value);
  if (!sourceId || !productId) {
    generateError.textContent = "请先选择参考脚本和产品";
    generateError.classList.remove("hidden");
    return;
  }
  if (!Number.isInteger(scriptCount) || scriptCount < 1 || scriptCount > 5) {
    generateError.textContent = "生成数量需为 1-5 之间的整数";
    generateError.classList.remove("hidden");
    return;
  }
  document.getElementById("generate-progress-text").textContent = `生成中（一次产出 ${scriptCount} 条创意脚本，可能需要1分钟左右）…`;
  generateProgress.classList.remove("hidden");
  try {
    const resp = await fetch("api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_script_id: sourceId,
        product_id: productId,
        use_feedback_reference: useFeedbackReference,
        script_count: scriptCount,
      }),
    });
    if (!resp.ok) {
      let detail = `请求失败（${resp.status}）`;
      try { const err = await resp.clone().json(); detail = err.detail || detail; } catch {}
      throw new Error(detail);
    }
    const result = await resp.json();
    renderGenerationResult(result);
  } catch (err) {
    generateError.textContent = err.message;
    generateError.classList.remove("hidden");
  } finally {
    generateProgress.classList.add("hidden");
  }
});

// ---- 产品库 ----

const productForm = document.getElementById("product-form");
const productError = document.getElementById("product-error");
const productSubmitBtn = document.getElementById("product-submit-btn");
const productCancelBtn = document.getElementById("product-cancel-btn");

function linesToList(text) {
  return text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

function resetProductForm() {
  productForm.reset();
  document.getElementById("product-id").value = "";
  productSubmitBtn.textContent = "新建产品";
  productCancelBtn.classList.add("hidden");
}

productCancelBtn.addEventListener("click", resetProductForm);

productForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  productError.classList.add("hidden");
  const id = document.getElementById("product-id").value;
  const payload = {
    name: document.getElementById("product-name").value.trim(),
    grade: document.getElementById("product-grade").value,
    price: document.getElementById("product-price").value.trim() || null,
    original_price: document.getElementById("product-original-price").value.trim() || null,
    selling_points: linesToList(document.getElementById("product-selling-points").value),
    pain_points: linesToList(document.getElementById("product-pain-points").value),
    target_audience: document.getElementById("product-target-audience").value.trim() || null,
    authenticity_notes: document.getElementById("product-authenticity").value.trim() || null,
    extra_notes: document.getElementById("product-extra-notes").value.trim() || null,
  };
  try {
    const resp = await fetch(id ? `api/products/${id}` : "api/products", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "保存失败");
    }
    resetProductForm();
    await loadProducts();
    await loadProductOptions();
  } catch (err) {
    productError.textContent = err.message;
    productError.classList.remove("hidden");
  }
});

function fillProductForm(p) {
  document.getElementById("product-id").value = p.id;
  document.getElementById("product-name").value = p.name || "";
  document.getElementById("product-grade").value = p.grade || "初中";
  document.getElementById("product-price").value = p.price || "";
  document.getElementById("product-original-price").value = p.original_price || "";
  document.getElementById("product-selling-points").value = (p.selling_points || []).join("\n");
  document.getElementById("product-pain-points").value = (p.pain_points || []).join("\n");
  document.getElementById("product-target-audience").value = p.target_audience || "";
  document.getElementById("product-authenticity").value = p.authenticity_notes || "";
  document.getElementById("product-extra-notes").value = p.extra_notes || "";
  productSubmitBtn.textContent = "更新产品";
  productCancelBtn.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function deleteProduct(id) {
  if (!confirm("确定删除这个产品吗？")) return;
  await fetch(`api/products/${id}`, { method: "DELETE" });
  await loadProducts();
  await loadProductOptions();
}

async function loadProducts(grade) {
  const listEl = document.getElementById("product-list");
  listEl.innerHTML = "<p>加载中…</p>";
  try {
    const url = grade ? `api/products?grade=${encodeURIComponent(grade)}` : "api/products";
    const resp = await fetch(url);
    const items = await resp.json();
    if (items.length === 0) {
      listEl.innerHTML = "<p>暂无产品，请在上方表单创建</p>";
      return;
    }
    listEl.innerHTML = items
      .map(
        (p) => `
        <div class="card product-card" data-id="${p.id}">
          <div class="product-card-header">
            <b>${escapeHtml(p.name)}</b>
            ${p.grade ? `<span class="badge">${escapeHtml(p.grade)}</span>` : ""}
          </div>
          ${p.target_audience ? `<div class="meta">目标人群：${escapeHtml(p.target_audience)}</div>` : ""}
          <div class="product-card-detail">
            ${p.price ? `<div class="meta">现价：${escapeHtml(p.price)}${p.original_price ? ` / 原价：${escapeHtml(p.original_price)}` : ""}</div>` : ""}
            ${
              (p.selling_points || []).length
                ? `<div class="chip-row">${p.selling_points.map((s) => `<span class="chip">${escapeHtml(s)}</span>`).join("")}</div>`
                : ""
            }
            ${
              (p.pain_points || []).length
                ? `<div class="chip-row">${p.pain_points.map((s) => `<span class="chip">${escapeHtml(s)}</span>`).join("")}</div>`
                : ""
            }
            ${p.authenticity_notes ? `<div class="meta">正版特征：${escapeHtml(p.authenticity_notes)}</div>` : ""}
            ${p.extra_notes ? `<div class="meta">备注：${escapeHtml(p.extra_notes)}</div>` : ""}
            <div class="form-actions">
              <button type="button" class="btn-secondary btn-edit-product">编辑</button>
              <button type="button" class="btn-secondary btn-delete-product">删除</button>
            </div>
          </div>
        </div>`
      )
      .join("");
    listEl.querySelectorAll(".product-card").forEach((card) => {
      const id = card.dataset.id;
      const product = items.find((p) => p.id === id);
      card.addEventListener("click", (e) => {
        if (e.target.closest(".btn-edit-product") || e.target.closest(".btn-delete-product")) return;
        card.classList.toggle("expanded");
      });
      card.querySelector(".btn-edit-product").addEventListener("click", (e) => {
        e.stopPropagation();
        fillProductForm(product);
      });
      card.querySelector(".btn-delete-product").addEventListener("click", (e) => {
        e.stopPropagation();
        deleteProduct(id);
      });
    });
  } catch (err) {
    listEl.innerHTML = `<p>${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("product-filter-btn").addEventListener("click", () => {
  loadProducts(document.getElementById("product-grade-filter").value);
});

// ---- 历史记录 ----

function formatHistoryTime(createdAt) {
  return new Date(createdAt * 1000).toLocaleString();
}

async function loadHistory() {
  const listEl = document.getElementById("history-list");
  listEl.innerHTML = "<p>加载中…</p>";
  try {
    const resp = await fetch("api/history");
    const entries = await resp.json();
    if (entries.length === 0) {
      listEl.innerHTML = "<p>暂无脚本记录</p>";
      return;
    }
    const groups = new Map();
    entries.forEach((entry) => {
      const key = entry.product_id || "__unknown__";
      if (!groups.has(key)) {
        groups.set(key, { name: entry.product_name || "未分类产品", grade: entry.product_grade, items: [] });
      }
      groups.get(key).items.push(entry);
    });
    listEl.innerHTML = Array.from(groups.values())
      .map(
        (group) => `
        <div class="history-group">
          <div class="product-card-header">
            <b>${escapeHtml(group.name)}</b>
            ${group.grade ? `<span class="badge">${escapeHtml(group.grade)}</span>` : ""}
          </div>
          ${group.items
            .map(
              (entry) => `
              <div class="history-card" data-history-id="${entry.id}">
                <span class="history-title">${escapeHtml(entry.title)}</span>
                <span class="history-time">${formatHistoryTime(entry.created_at)}</span>
              </div>`
            )
            .join("")}
        </div>`
      )
      .join("");
    listEl.querySelectorAll(".history-card").forEach((card) => {
      card.addEventListener("click", () => openHistoryEntry(card.dataset.historyId));
    });
  } catch (err) {
    listEl.innerHTML = `<p>${escapeHtml(err.message)}</p>`;
  }
}

async function openHistoryEntry(entryId) {
  const resp = await fetch(`api/history/${entryId}`);
  if (!resp.ok) return;
  const entry = await resp.json();
  renderGenerationResult(entry.result);
}

// ---- API 设置 ----

const $ = (selector) => document.querySelector(selector);

async function apiRequest(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `请求失败（${response.status}）`); }
  return response.json();
}

async function loadSettingsStatus() {
  const status = await apiRequest('api/settings/openai');
  const target = $('#key-status');
  target.textContent = status.configured
    ? `已配置：模型 ${status.model}`
    : '未配置：保存 API Key 和模型后才能使用生成功能。';
  target.classList.toggle('configured', status.configured);
  $('#api-key').value = '';
  $('#base-url').value = status.base_url || '';
  $('#model-select').value = status.model;
}

async function loadModels() {
  const models = await apiRequest('api/settings/models');
  const select = $('#model-select');
  select.innerHTML = models.map(m => `<option value="${m.id}">${m.label}</option>`).join('');
}

function closeSettings() {
  $('#settings-error').textContent = '';
  $('#settings-panel').classList.add('hidden');
}

async function saveSettings(event) {
  event.preventDefault();
  const errorTarget = $('#settings-error');
  errorTarget.textContent = '';
  const apiKey = $('#api-key').value;
  const model = $('#model-select').value;
  const baseUrl = $('#base-url').value;
  try {
    await apiRequest('api/settings/openai', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey, model, base_url: baseUrl }),
    });
    await loadSettingsStatus();
    await loadCurrentModel();
    closeSettings();
  } catch {
    errorTarget.textContent = '保存失败，请检查输入后重试。';
  }
}

$('#open-settings').addEventListener('click', async () => {
  $('#settings-panel').classList.remove('hidden');
  await loadModels();
  await loadSettingsStatus();
});
$('#close-settings').addEventListener('click', closeSettings);
$('#cancel-settings').addEventListener('click', closeSettings);
$('#settings-form').addEventListener('submit', saveSettings);

// ---- 初始化 ----

async function loadCurrentModel() {
  const resp = await fetch("api/config");
  if (!resp.ok) return;
  const config = await resp.json();
  document.getElementById("current-model-badge").textContent = `调用模型: ${config.model}`;
}

loadCurrentModel();
loadSourceScripts();
loadProductOptions();
