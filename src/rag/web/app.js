'use strict';
const $ = id => document.getElementById(id);
let key = '', config, selection, selectedFiles = new Map(), currentJob = null, serverPath = '', polling = false, busy = false;
let selectionGeneration = 0, browseGeneration = 0, previewFiles = new Map(), previewEligible = 0;
let jobGeneration = 0, jobRequest = 0, jobListRequest = 0, displayedJob = null, jobAction = false, readinessRequest = 0;
const bytes = n => n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`;
const say = text => { $('message').textContent = text; };
const node = (tag, text, className) => { const e = document.createElement(tag); e.textContent = text; if (className) e.className = className; return e; };
async function api(path, options = {}) {
  const response = await fetch('/library' + path, { ...options, headers: { 'x-api-key': key, ...(options.body && typeof options.body === 'string' ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}). Check the selection and limits.`);
  return body;
}
const post = (path, body) => api(path, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) });
function guarded(fn) { return async event => { try { await fn(event); } catch (error) { say(error.message); $('message').scrollIntoView({block: 'nearest'}); } }; }
function metrics(target, entries) { target.replaceChildren(...entries.map(([value, label]) => { const e = node('div', '', 'metric'); e.append(node('strong', String(value)), node('span', label)); return e; })); }
function badge(text) { return node('span', text.replaceAll('_', ' '), 'badge ' + text); }
function clearPreview() { ++selectionGeneration; selection = null; previewFiles = new Map(); previewEligible = 0; $('start').disabled = true; $('preview-panel').hidden = true; $('preview-empty').hidden = false; }
async function approvePreview(candidate, files = new Map()) {
  clearPreview();
  const generation = selectionGeneration;
  try {
    const preview = await post('/preview', candidate);
    if (generation !== selectionGeneration) return;
    selection = Object.freeze({ ...candidate, preview_digest: preview.preview_digest });
    previewFiles = new Map(files); previewEligible = preview.eligible;
    renderPreview(preview); say('Review the selection, then start ingestion.');
  } catch (error) { if (generation === selectionGeneration) throw error; }
}
function renderPreview(preview) {
  $('preview-source').textContent = `${preview.mode === 'server' ? 'Server' : 'Browser'} source: ${preview.source}${selection?.folder ? '/' + selection.folder : ''}`;
  $('preview-empty').hidden = true; $('preview-panel').hidden = false;
  metrics($('preview-metrics'), [[preview.count, 'files selected'], [bytes(preview.total_size), 'total size'], [preview.count - preview.eligible, 'excluded']]);
  $('preview-rows').replaceChildren(...preview.files.map(file => { const tr = document.createElement('tr'); tr.append(node('td', file.path), node('td', bytes(file.size)), node('td', file.eligible ? 'Ready for parsing' : file.reason)); return tr; }));
  $('start').disabled = !preview.eligible || busy;
}
$('connect-form').addEventListener('submit', guarded(async e => {
  e.preventDefault(); key = $('api-key').value; config = await api('/config'); $('api-key').value = '';
  $('connection').textContent = 'API authenticated'; $('connect-panel').hidden = true; $('workspace').hidden = false;
  $('formats').textContent = `${config.formats.map(f => f.slice(1).toUpperCase()).join(" · ")} — up to ${config.max_files} files, ${bytes(config.max_file_bytes)} per file, ${bytes(config.max_batch_bytes)} per selection. PDF limit: ${config.max_pages} pages.`;
  $('destination').textContent = `Destination: ${config.destination}`;
  $('root-select').replaceChildren(...config.roots.map(root => { const o = node('option', root); o.value = root; return o; }));
  await refreshReadiness(); await refreshJobs(); await refreshDocuments(); say('API authenticated. Select a folder or reopen a saved job.');
}));
$('source-mode').addEventListener('change', guarded(async () => {
  const server = document.querySelector('[name=mode]:checked').value === 'server';
  ++browseGeneration; clearPreview();
  $('browser-fields').hidden = server; $('server-fields').hidden = !server;
  if (server) { serverPath = ''; await browse(); }
}));
$('folder-input').addEventListener('change', guarded(async () => {
  selectedFiles = new Map(Array.from($('folder-input').files).map(f => [f.webkitRelativePath || f.name, f]));
  const files = Object.freeze([...selectedFiles].map(([path, f]) => Object.freeze({ path, size: f.size })));
  await approvePreview({ mode: 'browser', source: $('source-name').value, files }, selectedFiles);
}));
$('source-name').addEventListener('input', () => { clearPreview(); say('Source name changed. Reselect the folder to preview it.'); });
async function browse() {
  clearPreview();
  const generation = ++browseGeneration, root = $('root-select').value, path = serverPath;
  $('folder-list').replaceChildren(); $('server-path').textContent = serverPath || '/';
  if (!config.roots.length) { say('No server roots configured. Add a read-only mount and INGEST_SOURCE_ROOTS, or choose a folder on this computer.'); return; }
  let data;
  try { data = await api(`/browse?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`); }
  catch (error) { if (generation === browseGeneration) throw error; return; }
  if (generation !== browseGeneration) return;
  for (const entry of data.entries) {
    const li = document.createElement('li');
    if (entry.kind === 'folder') { const button = node('button', 'Folder · ' + entry.name, 'secondary'); button.onclick = guarded(async () => { serverPath = [serverPath, entry.name].filter(Boolean).join('/'); await browse(); }); li.append(button); }
    else li.textContent = `${entry.name}${entry.kind === 'excluded' ? ' — excluded' : ''}`;
    $('folder-list').append(li);
  }
}
$('root-select').onchange = guarded(async () => { serverPath = ''; await browse(); });
$('browse-up').onclick = guarded(async () => { serverPath = serverPath.split('/').slice(0, -1).join('/'); await browse(); });
$('preview-server').onclick = guarded(async () => { await approvePreview({ mode: 'server', source: $('root-select').value, folder: serverPath }); });
async function stageBrowser(job, filesForJob = new Map(selectedFiles)) {
  for (const file of job.files.filter(f => f.status === 'pending')) {
    const local = filesForJob.get(file.path);
    if (!local || local.size !== file.size) { say(`Reselect the original folder to upload ${file.path}, then retry this job.`); return false; }
    say(`Uploading ${file.path} (${bytes(file.size)}). Not yet indexed.`);
    await api(`/jobs/${job.id}/files/${file.id}`, { method: 'PUT', body: local, headers: { 'Content-Type': 'application/octet-stream' } });
  }
  await post(`/jobs/${job.id}/start`); return true;
}
$('start').onclick = guarded(async () => {
  if (!selection || busy) return;
  const approvedSelection = selection, filesForJob = new Map(previewFiles);
  busy = true; $('start').disabled = true;
  try { const job = await post('/jobs', approvedSelection); selectJob(job.id); await refreshJobs(); if (job.mode === 'browser') await stageBrowser(job, filesForJob); say('Job created. Follow the file results below.'); await refreshJobs(); }
  catch (error) { clearPreview(); throw error; }
  finally { busy = false; $('start').disabled = !selection || !previewEligible; }
});
function clearJobDisplay(message) {
  displayedJob = null; $('job-panel').hidden = true;
  $('cancel').disabled = true; $('retry').disabled = true;
  $('job-status').textContent = message;
}
function selectJob(id) {
  currentJob = id || null; ++jobGeneration; ++jobRequest;
  $('job-select').value = currentJob || '';
  clearJobDisplay(currentJob ? 'Loading selected job…' : 'No jobs yet.');
}
async function loadJob() {
  if (!currentJob) return;
  const id = currentJob, generation = jobGeneration, request = ++jobRequest;
  const current = () => id === currentJob && generation === jobGeneration && request === jobRequest;
  try {
    const job = await api('/jobs/' + id);
    if (current()) renderJob(job);
  } catch (error) {
    if (current()) clearJobDisplay(`Selected job status unavailable: ${error.message}. Refresh jobs to retry.`);
  }
}
async function refreshJobs() {
  const generation = jobGeneration, request = ++jobListRequest;
  let jobs;
  try { jobs = await api('/jobs'); }
  catch (error) { if (generation === jobGeneration && request === jobListRequest) throw error; return; }
  if (generation !== jobGeneration || request !== jobListRequest) return;
  $('job-select').replaceChildren(...jobs.map(job => { const o = node('option', `${job.source} · ${new Date(job.created * 1000).toLocaleString()} · ${job.status.replaceAll('_', ' ')}`); o.value = job.id; return o; }));
  if (!jobs.some(j => j.id === currentJob)) selectJob(jobs[0]?.id);
  $('job-select').value = currentJob || '';
  await loadJob();
}
function renderJob(job) {
  if (job.id !== currentJob) return;
  displayedJob = job.id; $('job-status').textContent = '';
  $('job-panel').hidden = false;
  $('job-title').textContent = `${job.source} · ${job.mode === 'server' ? 'Folder on server' : 'Uploaded folder'} · ${job.status.replaceAll('_', ' ')}`;
  metrics($('job-counts'), Object.entries(job.counts).map(([label, value]) => [value, label]));
  const done = job.files.length - job.counts.pending;
  $('job-progress').max = job.files.length || 1; $('job-progress').value = done;
  $('progress-label').textContent = `${done} of ${job.files.length} files finished (including skipped, failed and cancelled)`;
  const active = job.files.find(f => ['uploading', 'parsing', 'chunking', 'embedding', 'indexing'].includes(f.status));
  const text = active ? `${active.status} · ${active.path}${active.total ? ` · ${active.done}/${active.total} chunks` : ''}` : job.status === 'uploading' ? 'Waiting for uploads. Reselect the original folder after a refresh and retry this job.' : job.counts.pending ? 'Waiting for the worker' : 'Processing finished. Completed files are indexed; unchanged files keep their verified index.';
  if ($('current-stage').textContent !== text) $('current-stage').textContent = text;
  $('cancel').disabled = jobAction || !job.counts.pending || !!job.cancel;
  $('retry').disabled = jobAction || !!active || !(job.counts.failed || job.counts.cancelled || job.status === 'uploading');
  $('job-rows').replaceChildren(...job.files.map(f => { const tr = document.createElement('tr'); const state = node('td', ''); state.append(badge(f.status)); tr.append(node('td', f.path), state, node('td', f.error || (f.status === 'completed' ? 'Indexed and ready to search' : f.staged ? 'Upload safely staged' : ''))); return tr; }));
}
$('job-select').onchange = guarded(async () => { selectJob($('job-select').value); await loadJob(); });
$('refresh-jobs').onclick = guarded(refreshJobs);
async function mutateJob(action) {
  if (jobAction || !currentJob || displayedJob !== currentJob || $('job-select').value !== currentJob || $(action).disabled) return;
  const id = currentJob, files = new Map(selectedFiles);
  jobAction = true; ++jobRequest; $('cancel').disabled = true; $('retry').disabled = true;
  try {
    const job = await post(`/jobs/${id}/${action}`);
    if (action === 'retry' && job.status === 'uploading') await stageBrowser(job, files);
    if (id === currentJob && action === 'cancel') say('Cancellation requested. Waiting for any in-flight operation to return.');
  } catch (error) { say(`Job ${id}: ${error.message}`); }
  finally { jobAction = false; await loadJob(); }
}
$('cancel').onclick = guarded(() => mutateJob('cancel'));
$('retry').onclick = guarded(() => mutateJob('retry'));
async function refreshReadiness() {
  const request = ++readinessRequest;
  $('readiness-status').textContent = 'Checking service metadata…';
  try {
    const state = await api('/readiness');
    if (request !== readinessRequest) return;
    $('model-mode').textContent = `Model mode: ${state.mode} (deployment label)`;
    $('chat-model').textContent = `Chat model: ${state.chat_model.name} — ${state.chat_model.status}`;
    $('embedding-model').textContent = `Embedding model: ${state.embedding_model.name} — ${state.embedding_model.status}`;
    $('readiness-status').textContent = `Ollama: ${state.ollama}. Qdrant: ${state.qdrant}. ${state.metadata_ready ? 'Metadata checks passed' : 'Not ready / unable to verify'}. Checked ${new Date(state.checked_at).toLocaleTimeString()}.`;
  } catch (error) { if (request === readinessRequest) $('readiness-status').textContent = `Readiness unavailable: ${error.message}`; }
}
$('refresh-readiness').onclick = guarded(refreshReadiness);
async function refreshDocuments() {
  const data = await api('/documents'); $('indexed-count').textContent = `${data.documents.length} indexed documents`;
  $('documents').replaceChildren(...data.documents.map(d => node('li', `${d.source}/${d.path} — ${d.chunks} chunks`)));
  if (data.cleanup_pending) say(`${data.cleanup_pending} obsolete revision(s) await database cleanup. They are excluded from search; the worker will retry cleanup.`);
}
$('ask-form').onsubmit = guarded(async e => {
  e.preventDefault(); $('ask').disabled = true; $('ask-status').textContent = 'Retrieving excerpts and generating an answer…'; $('answer-panel').hidden = true;
  try {
    const question = { question: $('question').value, top_k: 5 };
    if ($('search-scope').value === 'job') { if (!currentJob) throw new Error('Choose a job first.'); question.job_id = currentJob; }
    const result = await post('/ask', question);
    const mode = ['unknown', 'synthetic', 'real'].includes(result.model_mode) ? result.model_mode : 'unknown';
    $('answer').textContent = result.generation_notice || result.answer; $('generation').textContent = `Model mode: ${mode} (request-bound deployment label)${mode === 'synthetic' ? ' — simulated reply, not real inference' : ''}. Generation: ${result.generation?.status || 'No generation'}${result.generation?.eval_count != null ? ` · ${result.generation.eval_count} output tokens` : ''}. Mode is operator configuration, not evidence of inference. Inspect each claim against its excerpt.`;
    $('citations').replaceChildren(...result.sources.map((source, i) => { const box = node('div', '', 'citation'); box.append(node('strong', `[${i+1}] ${source.source}${source.location ? ` · ${source.location}` : source.page_number ? ` · page ${source.page_number}` : ''} · chunk ${source.chunk}`), node('p', source.text)); if (source.warnings?.length) box.append(node('p', source.warnings.join(' '), 'muted')); return box; }));
    $('answer-panel').hidden = false; $('ask-status').textContent = result.generation?.status === 'complete' ? 'Answer complete. Verify the citations below.' : 'Review required: generation is incomplete, unknown, or returned no sources.';
  } catch (error) { $('ask-status').textContent = `Question failed: ${error.message}`; throw error; } finally { $('ask').disabled = false; }
});
setInterval(async () => {
  if (!key || !config || polling || document.hidden) return;
  polling = true;
  try { await loadJob(); await refreshDocuments(); }
  catch (error) { say(`Status unavailable: ${error.message}`); }
  finally { polling = false; }
}, 1500);
