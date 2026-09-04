const state = { sources: [], source: null, variant: null, batches: [], models: [] };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const statusText = { draft:'等待提交', submitting:'正在提交', submitted:'已提交', queued:'排队等待', running:'正在生成', succeeded:'生成完成', downloading:'正在下载', completed:'已完成', cancel_requested:'正在取消', cancelled:'已取消', failed:'生成失败', processing:'处理中', partial_failed:'部分失败' };

async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `请求失败（${response.status}）`); }
  return response.json();
}
function formatTime(seconds) { return seconds ? `${seconds} 秒` : '时长未标注'; }
function statusClass(status) { return ['completed','failed','partial_failed','processing','running','queued','downloading'].includes(status) ? status : ''; }

async function loadSettingsStatus() {
  const status = await api('api/settings/seedance');
  const target = $('#key-status');
  target.textContent = status.configured ? '已配置：可直接创建视频任务。' : '未配置：保存 API Key 后才能创建远端任务。';
  target.classList.toggle('configured', status.configured);
}
function closeSettings() { $('#api-key').value = ''; $('#settings-error').textContent = ''; $('#settings-panel').classList.add('hidden'); }
async function saveSettings(event) {
  event.preventDefault(); const input = $('#api-key'); const apiKey = input.value; const errorTarget = $('#settings-error'); errorTarget.textContent = '';
  try { await api('api/settings/seedance', { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({api_key: apiKey}) }); input.value = ''; await loadSettingsStatus(); closeSettings(); }
  catch { input.value = ''; errorTarget.textContent = '保存失败，请检查 API Key 格式后重试。'; }
}

async function loadSources() {
  state.sources = await api('api/sources');
  const select = $('#source-select');
  select.innerHTML = state.sources.length ? state.sources.map(source => `<option value="${escapeHtml(source.id)}">${escapeHtml(source.title)}（${source.variant_count} 条变体）</option>`).join('') : '<option>未找到提示词生成结果</option>';
  if (state.sources.length) await selectSource();
}
async function selectSource() {
  state.source = await api(`api/sources/${encodeURIComponent($('#source-select').value)}`);
  const select = $('#variant-select'); select.disabled = false;
  select.innerHTML = state.source.variants.map((variant, index) => `<option value="${index}">${index + 1}. ${escapeHtml(variant.variant_title)}</option>`).join('');
  await selectVariant();
}
async function selectVariant() {
  state.variant = state.source.variants[Number($('#variant-select').value)];
  $('#variant-info').textContent = state.variant.variant_style || '未提供变体说明。';
  const container = $('#segments'); container.innerHTML = ''; const template = $('#segment-template');
  state.variant.video_prompts.forEach((segment, index) => {
    const node = template.content.cloneNode(true); const article = node.querySelector('.segment'); const checkbox = node.querySelector('.segment-check'); const source = node.querySelector('.prompt-source'); const text = node.querySelector('.prompt');
    node.querySelector('.segment-name').textContent = `第 ${index + 1} 段 · ${segment.role}`;
    node.querySelector('.duration').textContent = `脚本建议 ${formatTime(segment.duration_sec)}`;
    node.querySelector('.segment-role').textContent = `成片时长以“生成设置”的选择为准。`;
    text.value = segment.jimeng_prompt;
    checkbox.addEventListener('change', () => { article.classList.toggle('selected', checkbox.checked); text.disabled = !checkbox.checked; updateSelection(); });
    source.addEventListener('change', () => { text.value = segment[`${source.value}_prompt`]; }); article.dataset.index = String(index); container.appendChild(node);
  });
  updateSelection();
}
function selectedSegments() { return [...document.querySelectorAll('.segment')].filter(node => node.querySelector('.segment-check').checked).map(node => ({ segment_index:Number(node.dataset.index), prompt_source:node.querySelector('.prompt-source').value, prompt:node.querySelector('.prompt').value.trim() })); }
function updateSelection() {
  const selected = selectedSegments(); const quantity = Number($('#quantity').value); const total = selected.length * quantity;
  $('#selection-summary').textContent = selected.length ? `已选 ${selected.length} 段 × 每段 ${quantity} 条 = 将创建 ${total} 个独立远端任务` : '尚未选择分段';
  $('#submit').disabled = !selected.length || total > 5;
  if (total > 5) $('#form-error').textContent = '单次最多创建 5 个视频任务，请减少分段或生成数量。';
  else if ($('#form-error').textContent.includes('单次最多')) $('#form-error').textContent = '';
}
function setOptions(selector, values, format, preferred) {
  const select = $(selector); const current = preferred ?? select.value;
  select.innerHTML = values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(format(value))}</option>`).join('');
  select.value = values.includes(current) ? current : values[0];
}
function currentCapability() { return state.models.find(model => model.id === $('#model').value); }
function syncModelCapabilities() {
  const capability = currentCapability(); if (!capability) return;
  setOptions('#duration', capability.durations, value => value === -1 ? '自动时长（由服务决定）' : `${value} 秒`, capability.defaults.duration);
  setOptions('#ratio', capability.ratios, value => value === 'adaptive' ? '自适应比例（由服务决定）' : `${value}${value === '9:16' ? ' 竖屏' : value === '16:9' ? ' 横屏' : ''}`, capability.defaults.ratio);
  setOptions('#resolution', capability.resolutions, value => value, capability.defaults.resolution);
  const audio = $('#generate-audio'); audio.disabled = !capability.audio; if (!capability.audio) audio.checked = false;
  $('#audio-notice').textContent = capability.audio ? `${capability.label} 可请求原生音频；下载后会检测 MP4 音轨。` : `${capability.label} 不保证原生音频，已关闭音频选项。`;
}
async function loadModels() {
  state.models = await api('api/models');
  const mode = $('#mode').value; const select = $('#model');
  const candidates = state.models.filter(model => model.modes.includes(mode));
  select.disabled = false;
  select.innerHTML = candidates.map(model => `<option value="${escapeHtml(model.id)}">${escapeHtml(model.label)}</option>`).join('');
  syncModelCapabilities();
}
function syncMode() {
  const image = $('#mode').value === 'image'; $('#image-url-row').classList.toggle('hidden', !image); $('#image-notice').classList.toggle('hidden', !image);
  loadModels().catch(error => { $('#form-error').textContent = error.message; });
}
async function submitBatch() {
  $('#form-error').textContent = ''; const segments = selectedSegments(); const quantity = Number($('#quantity').value);
  if (segments.length * quantity > 5) { $('#form-error').textContent = '单次最多创建 5 个视频任务。'; return; }
  const request = { source_id:state.source.id, variant_index:Number($('#variant-select').value), segments, mode:$('#mode').value, model:$('#model').value, generate_audio:$('#generate-audio').checked, service_tier:$('#service-tier').value || null, duration:Number($('#duration').value), ratio:$('#ratio').value, resolution:$('#resolution').value, quantity };
  if (request.mode === 'image') request.image_url = $('#image-url').value.trim() || null;
  const button = $('#submit'); button.disabled = true; button.textContent = '正在创建…';
  try { await api('api/batches', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(request) }); await loadBatches(); }
  catch (error) { $('#form-error').textContent = error.message; }
  finally { button.textContent = '创建视频任务'; updateSelection(); }
}
function audioText(task) { const messages = { requested:'已请求音频，下载后将检测音轨', detected:'已检测到 MP4 音轨', not_detected:'未检测到 MP4 音轨', unknown:'无法检测音轨，请在播放器确认', not_requested:'未请求音频' }; return messages[task.audio_status] || '音频状态未知'; }
function renderTask(task, batch) {
  const files = task.local_video_filenames?.length ? task.local_video_filenames : task.local_video_filename ? [task.local_video_filename] : [];
  const media = files.map((file, index) => `<div class="media-item"><video controls src="/media/videos/${encodeURIComponent(file)}"></video><a href="/media/videos/${encodeURIComponent(file)}" download>下载视频 ${files.length > 1 ? index + 1 : ''}</a></div>`).join('');
  const remote = '';
  const cancel = !['completed','failed','cancelled'].includes(task.status) ? `<button data-cancel="${task.job_id}" data-batch="${batch.batch_id}">取消任务</button>` : '';
  const retry = task.download_error ? `<button data-retry="${task.job_id}" data-batch="${batch.batch_id}">重试下载</button>` : '';
  const actual = task.actual_media?.length ? task.actual_media.map(item => `${item.probe_status === 'available' ? `${item.duration_sec ?? '?'} 秒 · ${item.width ?? '?'}×${item.height ?? '?'} · ${item.ratio ?? '比例未知'} · ${item.audio_streams ? '有音轨' : '无音轨'}` : '未安装或无法运行 ffprobe，无法检测实际规格'}`).join('；') : '成片下载后将检测';
  return `<article class="task"><div class="task-top"><div><strong>第 ${task.segment_index + 1} 段 · ${escapeHtml(task.role)} · 变体 ${task.variation_index}</strong><p><b>请求：</b>${escapeHtml(task.requested_duration)} 秒 · ${escapeHtml(task.ratio)} · ${escapeHtml(task.resolution)} · ${escapeHtml(task.model)} · ${task.generate_audio ? '请求音频' : '未请求音频'}</p><p><b>实测：</b>${escapeHtml(actual)}</p></div><span class="status ${statusClass(task.status)}">${statusText[task.status] || escapeHtml(task.status)}</span></div><div class="progress-line"><div class="progress-bar"><span style="width:${task.progress || 0}%"></span></div><strong>${task.progress || 0}%</strong><small>${escapeHtml(task.progress_label || '处理中')}</small></div><p>Provider：${escapeHtml(task.provider_status || '待提交')} · 轮询 ${task.poll_attempts || 0} 次 · <code>${escapeHtml(task.provider_task_id || task.job_id)}</code></p><p>音频：${audioText(task)}</p>${task.error_code ? `<p class="error">错误码：${escapeHtml(task.error_code)}${task.error_message ? ` · ${escapeHtml(task.error_message)}` : ''}</p>` : ''}${task.error_message && !task.error_code ? `<p class="error">${escapeHtml(task.error_message)}</p>` : ''}${task.download_error ? `<p class="warning">${escapeHtml(task.download_error)}</p>` : ''}<div class="task-actions">${cancel}${retry}${remote}${media}</div></article>`;
}
async function loadBatches() {
  const batches = await api('api/batches'); state.batches = await Promise.all(batches.map(batch => api(`api/batches/${encodeURIComponent(batch.batch_id)}`)));
  const container = $('#batches');
  container.innerHTML = state.batches.length ? state.batches.map(batch => `<article class="batch"><div class="batch-header"><div><h3>${escapeHtml(batch.source_title)}</h3><p class="batch-meta">${escapeHtml(batch.variant_title)} · ${batch.completed_items}/${batch.total_items} 完成 · ${batch.failed_items} 失败 · ${new Date(batch.created_at * 1000).toLocaleString()}</p><div class="progress-bar batch-progress"><span style="width:${batch.progress}%"></span></div></div><span class="status ${statusClass(batch.status)}">${statusText[batch.status] || escapeHtml(batch.status)} ${batch.progress}%</span></div>${batch.items.map(item => renderTask(item,batch)).join('')}</article>`).join('') : '<p class="hint">尚无视频任务。选择分段后即可开始。</p>';
  container.querySelectorAll('[data-cancel]').forEach(button => button.addEventListener('click', async () => { await api(`api/batches/${button.dataset.batch}/items/${button.dataset.cancel}`, {method:'DELETE'}); await loadBatches(); }));
  container.querySelectorAll('[data-retry]').forEach(button => button.addEventListener('click', async () => { await api(`api/batches/${button.dataset.batch}/items/${button.dataset.retry}/retry-download`, {method:'POST'}); await loadBatches(); }));
}
$('#source-select').addEventListener('change', selectSource); $('#variant-select').addEventListener('change', selectVariant); $('#mode').addEventListener('change', syncMode); $('#model').addEventListener('change', syncModelCapabilities); $('#quantity').addEventListener('change', updateSelection); $('#submit').addEventListener('click', submitBatch); $('#refresh-batches').addEventListener('click', loadBatches);
$('#open-settings').addEventListener('click', async () => { $('#settings-panel').classList.remove('hidden'); try { await loadSettingsStatus(); } catch { $('#key-status').textContent = '无法读取配置状态。'; } }); $('#close-settings').addEventListener('click', closeSettings); $('#cancel-settings').addEventListener('click', closeSettings); $('#settings-form').addEventListener('submit', saveSettings);
Promise.all([loadSources(), loadBatches(), loadSettingsStatus(), loadModels()]).catch(error => { $('#form-error').textContent = error.message; }); setInterval(() => loadBatches().catch(() => {}), 5000);
