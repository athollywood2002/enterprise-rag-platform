'use strict';
const $ = id => document.getElementById(id);
let key = '', config, selection, selectedFiles = new Map(), currentJob = null, serverPath = '', polling = false, busy = false;
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
function guarded(fn) { return async event => { try { await fn(event); } catch (error) { say(error.message); } }; }
function metrics(target, entries) { target.replaceChildren(...entries.map(([value, label]) => { const e = node('div', '', 'metric'); e.append(node('strong', String(value)), node('span', label)); return e; })); }
function badge(text) { return node('span', text.replaceAll('_', ' '), 'badge ' + text); }
function clearPreview() { selection = null; $('preview-panel').hidden = true; $('preview-empty').hidden = false; }
function renderPreview(preview) {
  $('preview-source').textContent = `${preview.mode === 'server' ? 'Server' : 'Browser'} source: ${preview.source}${selection?.folder ? '/' + selection.folder : ''}`;
  $('preview-empty').hidden = true; $('preview-panel').hidden = false;
  metrics($('preview-metrics'), [[preview.count, 'files selected'], [bytes(preview.total_size), 'total size'], [preview.count - preview.eligible, 'excluded']]);
  $('preview-rows').replaceChildren(...preview.files.map(file => { const tr = document.createElement('tr'); tr.append(node('td', file.path), node('td', bytes(file.size)), node('td', file.eligible ? 'Ready for parsing' : file.reason)); return tr; }));
  $('start').disabled = !preview.eligible || busy;
}
$('connect-form').addEventListener('submit', guarded(async e => {
  e.preventDefault(); key = $('api-key').value; config = await api('/config'); $('api-key').value = '';
  $('connection').textContent = 'Connected · authenticated'; $('connect-panel').hidden = true; $('workspace').hidden = false;
  $('formats').textContent = `TXT · CSV · Text PDF — up to ${config.max_files} files, ${bytes(config.max_file_bytes)} per file, ${bytes(config.max_batch_bytes)} per selection. PDF limit: ${config.max_pages} pages.`;
  $('destination').textContent = `Destination: ${config.destination}`;
  $('root-select').replaceChildren(...config.roots.map(root => { const o = node('option', root); o.value = root; return o; }));
  await refreshJobs(); await refreshDocuments(); say('Connected. Select a folder or reopen a saved job.');
}));
$('source-mode').addEventListener('change', guarded(async () => {
  const server = document.querySelector('[name=mode]:checked').value === 'server';
  $('browser-fields').hidden = server; $('server-fields').hidden = !server; selection = null; $('preview-panel').hidden = true; $('preview-empty').hidden = false;
  if (server) { serverPath = ''; await browse(); }
}));
$('folder-input').addEventListener('change', guarded(async () => {
  selectedFiles = new Map(Array.from($('folder-input').files).map(f => [f.webkitRelativePath || f.name, f]));
  selection = { mode: 'browser', source: $('source-name').value, files: [...selectedFiles].map(([path, f]) => ({ path, size: f.size })) };
  renderPreview(await post('/preview', selection)); say('Review the selection, then start ingestion.');
}));
$('source-name').addEventListener('change', () => { selection = null; $('preview-panel').hidden = true; say('Source name changed. Reselect the folder to preview it.'); });
async function browse() {
  clearPreview();
  $('folder-list').replaceChildren(); $('server-path').textContent = serverPath || '/';
  if (!config.roots.length) { say('No server roots configured. Add a read-only mount and INGEST_SOURCE_ROOTS, or choose a folder on this computer.'); return; }
  const data = await api(`/browse?root=${encodeURIComponent($('root-select').value)}&path=${encodeURIComponent(serverPath)}`);
  for (const entry of data.entries) {
    const li = document.createElement('li');
    if (entry.kind === 'folder') { const button = node('button', 'Folder · ' + entry.name, 'secondary'); button.onclick = guarded(async () => { serverPath = [serverPath, entry.name].filter(Boolean).join('/'); await browse(); }); li.append(button); }
    else li.textContent = `${entry.name}${entry.kind === 'excluded' ? ' — excluded' : ''}`;
    $('folder-list').append(li);
  }
}
$('root-select').onchange = guarded(async () => { serverPath = ''; await browse(); });
$('browse-up').onclick = guarded(async () => { serverPath = serverPath.split('/').slice(0, -1).join('/'); await browse(); });
$('preview-server').onclick = guarded(async () => { selection = { mode: 'server', source: $('root-select').value, folder: serverPath }; renderPreview(await post('/preview', selection)); });
async function stageBrowser(job) {
  const filesForJob = new Map(selectedFiles);
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
  busy = true; $('start').disabled = true;
  try { const job = await post('/jobs', selection); currentJob = job.id; await refreshJobs(); if (job.mode === 'browser') await stageBrowser(job); say('Job created. Follow the file results below.'); await refreshJobs(); }
  finally { busy = false; $('start').disabled = false; }
});
async function refreshJobs() {
  const jobs = await api('/jobs');
  $('job-select').replaceChildren(...jobs.map(job => { const o = node('option', `${job.source} · ${new Date(job.created * 1000).toLocaleString()} · ${job.status.replaceAll('_', ' ')}`); o.value = job.id; return o; }));
  if (!jobs.length) return;
  if (!jobs.some(j => j.id === currentJob)) currentJob = jobs[0].id;
  $('job-select').value = currentJob; renderJob(jobs.find(j => j.id === currentJob));
}
function renderJob(job) {
  $('job-panel').hidden = false;
  $('job-title').textContent = `${job.source} · ${job.mode === 'server' ? 'Folder on server' : 'Uploaded folder'} · ${job.status.replaceAll('_', ' ')}`;
  metrics($('job-counts'), Object.entries(job.counts).map(([label, value]) => [value, label]));
  const done = job.files.length - job.counts.pending;
  $('job-progress').max = job.files.length || 1; $('job-progress').value = done;
  $('progress-label').textContent = `${done} of ${job.files.length} files finished (including skipped, failed and cancelled)`;
  const active = job.files.find(f => ['uploading', 'parsing', 'chunking', 'embedding', 'indexing'].includes(f.status));
  const text = active ? `${active.status} · ${active.path}${active.total ? ` · ${active.done}/${active.total} chunks` : ''}` : job.status === 'uploading' ? 'Waiting for uploads. Reselect the original folder after a refresh and retry this job.' : job.counts.pending ? 'Waiting for the worker' : 'Processing finished. Completed files are indexed; unchanged files keep their verified index.';
  if ($('current-stage').textContent !== text) $('current-stage').textContent = text;
  $('cancel').disabled = !job.counts.pending || !!job.cancel;
  $('retry').disabled = !!active || !(job.counts.failed || job.counts.cancelled || job.status === 'uploading');
  $('job-rows').replaceChildren(...job.files.map(f => { const tr = document.createElement('tr'); const state = node('td', ''); state.append(badge(f.status)); tr.append(node('td', f.path), state, node('td', f.error || (f.status === 'completed' ? 'Indexed and ready to search' : f.staged ? 'Upload safely staged' : ''))); return tr; }));
}
$('job-select').onchange = guarded(async () => { currentJob = $('job-select').value; renderJob(await api('/jobs/' + currentJob)); });
$('refresh-jobs').onclick = guarded(refreshJobs);
$('cancel').onclick = guarded(async () => { renderJob(await post(`/jobs/${currentJob}/cancel`)); say('Cancellation requested. Waiting for any in-flight operation to return.'); });
$('retry').onclick = guarded(async () => { const job = await post(`/jobs/${currentJob}/retry`); if (job.status === 'uploading') await stageBrowser(job); await refreshJobs(); });
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
    $('answer').textContent = result.answer; $('generation').textContent = `Generation: ${result.generation?.status || 'No generation'}${result.generation?.eval_count != null ? ` · ${result.generation.eval_count} output tokens` : ''}. Inspect each claim against its excerpt.`;
    $('citations').replaceChildren(...result.sources.map((source, i) => { const box = node('div', '', 'citation'); box.append(node('strong', `[${i+1}] ${source.source}${source.page_number ? ` · page ${source.page_number}` : ''} · chunk ${source.chunk}`), node('p', source.text)); return box; }));
    $('answer-panel').hidden = false; $('ask-status').textContent = result.generation?.status === 'complete' ? 'Answer complete. Verify the citations below.' : 'Review required: generation is incomplete, unknown, or returned no sources.';
  } finally { $('ask').disabled = false; if ($('answer-panel').hidden) $('ask-status').textContent = 'Question failed. See the error below.'; }
});
setInterval(async () => {
  if (!key || !config || polling || document.hidden) return;
  polling = true;
  try { if (currentJob) renderJob(await api('/jobs/' + currentJob)); await refreshDocuments(); }
  catch (error) { say(`Status unavailable: ${error.message}`); }
  finally { polling = false; }
}, 1500);
