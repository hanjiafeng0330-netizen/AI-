const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = document.querySelectorAll(".tab-panel");

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.remove("active"));
    tabPanels.forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`panel-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "history") {
      loadHistory();
    }
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

function formatTime(sec) {
  if (sec === null || sec === undefined) return "--";
  const m = Math.floor(sec / 60);
  const s = (sec % 60).toFixed(1);
  return `${m}:${s.padStart(4, "0")}`;
}

function renderResult(result) {
  const structureEl = document.getElementById("result-structure");
  structureEl.innerHTML = result.structure
    .map(
      (seg) => `
      <div class="card">
        <div class="meta">${formatTime(seg.start)} - ${formatTime(seg.end)}</div>
        <span class="role-badge">${seg.role}</span>
        <span>${seg.summary}</span>
      </div>`
    )
    .join("") || "<p>无结构拆解数据</p>";

  const dialogueEl = document.getElementById("result-dialogue");
  dialogueEl.innerHTML = result.dialogue
    .map(
      (line) => `
      <div class="card">
        <div class="meta">${formatTime(line.start)} - ${formatTime(line.end)}${
          line.speaker ? ` · ${line.speaker}` : ""
        }</div>
        <span>${line.text}</span>
      </div>`
    )
    .join("") || "<p>无台词数据</p>";

  const visualEl = document.getElementById("result-visual");
  if (result.source_type === "text" || result.visual.length === 0) {
    visualEl.innerHTML = "<p>纯文字输入无视觉元素分析</p>";
  } else {
    visualEl.innerHTML = result.visual
      .map(
        (v) => `
        <div class="card">
          <div class="meta">${formatTime(v.timestamp)}</div>
          <span class="role-badge">${v.technique}</span>
          <span>${v.description}</span>
        </div>`
      )
      .join("");
  }

  const templateJsonEl = document.getElementById("template-json");
  templateJsonEl.textContent = JSON.stringify(result.template, null, 2);

  document.getElementById("result").classList.remove("hidden");
}

function copyText(text) {
  navigator.clipboard.writeText(text);
}

document.getElementById("copy-template").addEventListener("click", () => {
  copyText(document.getElementById("template-json").textContent);
});

function escapeHtml(text) {
  return String(text).replace(/</g, "&lt;");
}

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
  const items = entries
    .map(([key, value]) => promptSection(key, formatVarValue(value)))
    .join("");
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
  promptsEl.innerHTML = (steps || [])
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
    btn.addEventListener("click", () => {
      const target = document.getElementById(btn.dataset.copyTarget);
      copyText(target.textContent);
    });
  });
}

// ---- 历史记录 ----

const historyVideoPlayer = document.getElementById("history-video-player");

function hideHistoryVideoPlayer() {
  historyVideoPlayer.innerHTML = "";
  historyVideoPlayer.classList.add("hidden");
}

function showHistoryVideoPlayer(videoFilename) {
  historyVideoPlayer.innerHTML = `<video controls src="/media/videos/${encodeURIComponent(videoFilename)}"></video>`;
  historyVideoPlayer.classList.remove("hidden");
}

function formatHistoryTime(createdAt) {
  return new Date(createdAt * 1000).toLocaleString();
}

async function loadHistory() {
  const listEl = document.getElementById("history-list");
  listEl.innerHTML = "<p>加载中…</p>";
  try {
    const resp = await fetch("/api/history");
    if (!resp.ok) throw new Error("加载历史记录失败");
    const entries = await resp.json();
    if (entries.length === 0) {
      listEl.innerHTML = "<p>暂无历史记录</p>";
      return;
    }
    listEl.innerHTML = entries
      .map(
        (entry) => `
        <div class="history-card" data-history-id="${entry.id}">
          <span class="role-badge">${entry.source_type === "video" ? "视频" : "文字"}</span>
          <span class="history-title">${escapeHtml(entry.title)}</span>
          <span class="history-time">${formatHistoryTime(entry.created_at)}</span>
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
  const resp = await fetch(`/api/history/${entryId}`);
  if (!resp.ok) return;
  const entry = await resp.json();

  if (entry.video_filename) {
    showHistoryVideoPlayer(entry.video_filename);
  } else {
    hideHistoryVideoPlayer();
  }

  renderResult(entry.result);
  renderPromptTrace(entry.prompt_trace);
  document.getElementById("result").scrollIntoView({ behavior: "smooth" });
}

// ---- 文字分析 ----

const textForm = document.getElementById("text-form");
const textProgress = document.getElementById("text-progress");
const textError = document.getElementById("text-error");

textForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  textError.classList.add("hidden");
  textProgress.classList.remove("hidden");
  hideHistoryVideoPlayer();
  const scriptText = document.getElementById("script-text").value;

  try {
    const resp = await fetch("/api/analyze/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script_text: scriptText }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "分析失败");
    }
    const data = await resp.json();
    renderResult(data.result);
    renderPromptTrace(data.prompt_trace);
  } catch (err) {
    textError.textContent = err.message;
    textError.classList.remove("hidden");
  } finally {
    textProgress.classList.add("hidden");
  }
});

// ---- 视频分析 ----

const videoForm = document.getElementById("video-form");
const videoProgress = document.getElementById("video-progress");
const videoProgressText = document.getElementById("video-progress-text");
const videoError = document.getElementById("video-error");

videoForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  videoError.classList.add("hidden");
  videoProgress.classList.remove("hidden");
  videoProgressText.textContent = "上传并处理中…";
  hideHistoryVideoPlayer();

  const file = document.getElementById("video-file").files[0];
  const frameInterval = document.getElementById("frame-interval").value;

  const formData = new FormData();
  formData.append("file", file);
  formData.append("frame_interval_sec", frameInterval);

  try {
    const resp = await fetch("/api/analyze/video", {
      method: "POST",
      body: formData,
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "提交失败");
    }
    const { job_id } = await resp.json();
    await pollJob(job_id);
  } catch (err) {
    videoError.textContent = err.message;
    videoError.classList.remove("hidden");
    videoProgress.classList.add("hidden");
  }
});

function pollJob(jobId) {
  return new Promise((resolve, reject) => {
    const interval = setInterval(async () => {
      try {
        const resp = await fetch(`/api/jobs/${jobId}`);
        if (!resp.ok) {
          throw new Error("查询任务状态失败");
        }
        const job = await resp.json();
        if (job.status === "done") {
          clearInterval(interval);
          videoProgress.classList.add("hidden");
          renderResult(job.result);
          renderPromptTrace(job.prompt_trace);
          resolve();
        } else if (job.status === "error") {
          clearInterval(interval);
          videoProgress.classList.add("hidden");
          videoError.textContent = job.error || "分析失败";
          videoError.classList.remove("hidden");
          reject(new Error(job.error));
        } else {
          videoProgressText.textContent =
            job.status === "processing" ? "分析中（抽帧/转写/AI 分析）…" : "等待处理…";
        }
      } catch (err) {
        clearInterval(interval);
        videoProgress.classList.add("hidden");
        videoError.textContent = err.message;
        videoError.classList.remove("hidden");
        reject(err);
      }
    }, 2000);
  });
}
