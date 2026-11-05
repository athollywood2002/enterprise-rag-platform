// The shipped app.js, with deterministic DOM/fetch fixtures. No browser or network.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() { this.value = ''; this.textContent = ''; this.hidden = false; this.disabled = false; this.handlers = {}; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  replaceChildren(...nodes) { this.children = nodes; }
  append(...nodes) { this.children = [...(this.children || []), ...nodes]; }
  scrollIntoView() {}
}
const response = body => ({ ok: true, json: async () => body });
function fixture() {
  const elements = new Map(), requests = [];
  const $ = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const state = { mode: 'browser', job: null, deferJob: false };
  const context = vm.createContext({
    document: { getElementById: $, createElement: () => new Element(), querySelector: () => ({ value: state.mode }) },
    setInterval: () => {},
    fetch: (url, options) => {
      const call = { url, options }; requests.push(call);
      if (url === '/library/jobs' && options.method === 'POST') {
        const manifest = JSON.parse(options.body);
        state.job = { id: 'job', mode: manifest.mode, source: manifest.source, status: 'uploading', created: 1,
          files: (manifest.files || []).map((f, i) => ({ ...f, id: String(i), status: 'pending' })),
          counts: { successful: 0, failed: 0, skipped: 0, cancelled: 0, pending: (manifest.files || []).length } };
        if (!state.deferJob) return Promise.resolve(response(state.job));
      } else if (url === '/library/jobs') return Promise.resolve(response([state.job]));
      else if (options.method === 'PUT') return Promise.resolve(response({ status: 'staged' }));
      else if (url.endsWith('/start')) return Promise.resolve(response(state.job));
      return new Promise(resolve => { call.resolve = body => resolve(response(body)); call.reject = error => resolve({ ok: false, status: 400, json: async () => ({ detail: error }) }); });
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/rag/web/app.js'), 'utf8'), context);
  vm.runInContext("config = {roots:['root-a','root-b']}", context);
  function select(source, name) {
    const file = { webkitRelativePath: name, size: 3 };
    $('source-name').value = source; $('folder-input').files = [file];
    const done = $('folder-input').handlers.change();
    return { done, request: requests.at(-1), file };
  }
  function approve(selected, digest = 'a'.repeat(64)) {
    const candidate = JSON.parse(selected.request.options.body);
    selected.request.resolve({ ...candidate, files: candidate.files.map(f => ({ ...f, eligible: true })), count: 1, total_size: 3, eligible: 1, preview_digest: digest });
    return selected.done;
  }
  return { $, state, requests, select, approve };
}

test('late preview cannot replace the displayed and submitted selection/digest', async () => {
  const f = fixture(), a = f.select('source-A', 'folder-A/a.txt'), b = f.select('source-B', 'folder-B/b.txt');
  await f.approve(b, 'b'.repeat(64)); await f.approve(a);
  assert.equal(f.$('preview-rows').children[0].children[0].textContent, 'folder-B/b.txt');
  await f.$('start').onclick();
  const job = JSON.parse(f.requests.find(r => r.url === '/library/jobs' && r.options.method === 'POST').options.body);
  assert.equal(job.source, 'source-B'); assert.equal(job.files[0].path, 'folder-B/b.txt');
  assert.equal(job.preview_digest, 'b'.repeat(64));
  assert.equal(f.requests.find(r => r.options.method === 'PUT').options.body, b.file);
});

test('source edits invalidate an in-flight preview and disable Start', async () => {
  const f = fixture(), a = f.select('source-A', 'A/a.txt');
  f.$('source-name').value = 'changed'; f.$('source-name').handlers.input();
  await f.approve(a);
  assert.equal(f.$('preview-panel').hidden, true); assert.equal(f.$('start').disabled, true);
  await f.$('start').onclick();
  assert.equal(f.requests.filter(r => r.url === '/library/jobs').length, 0);
});

test('switching modes invalidates pending browser preview and pending server browse', async () => {
  const f = fixture(), a = f.select('source-A', 'A/a.txt');
  f.state.mode = 'server'; f.$('root-select').value = 'root-a';
  const switching = f.$('source-mode').handlers.change(), browse = f.requests.at(-1);
  await f.approve(a);
  assert.equal(f.$('preview-panel').hidden, true); assert.equal(f.$('start').disabled, true);
  f.state.mode = 'browser'; await f.$('source-mode').handlers.change();
  browse.resolve({ entries: [{ name: 'obsolete', kind: 'folder' }] }); await switching;
  assert.equal(f.$('folder-list').children.length, 0);
});

test('late browse response cannot overwrite a newly selected root', async () => {
  const f = fixture(); f.state.mode = 'server'; f.$('root-select').value = 'root-a';
  const a = f.$('root-select').onchange(), ra = f.requests.at(-1);
  f.$('root-select').value = 'root-b';
  const b = f.$('root-select').onchange(), rb = f.requests.at(-1);
  rb.resolve({ entries: [{ name: 'new-root.txt', kind: 'file' }] }); await b;
  ra.resolve({ entries: [{ name: 'old-root.txt', kind: 'file' }] }); await a;
  assert.equal(f.$('folder-list').children[0].textContent, 'new-root.txt');
});

test('pending server preview is invalidated by root navigation', async () => {
  const f = fixture(); f.state.mode = 'server'; f.$('root-select').value = 'root-a';
  const a = f.$('preview-server').onclick(), preview = f.requests.at(-1);
  f.$('root-select').value = 'root-b';
  const b = f.$('root-select').onchange(), browse = f.requests.at(-1);
  preview.resolve({ mode: 'server', source: 'root-a', files: [], eligible: 1, count: 1, total_size: 3, preview_digest: 'a'.repeat(64) }); await a;
  browse.resolve({ entries: [] }); await b;
  assert.equal(f.$('preview-panel').hidden, true); assert.equal(f.$('start').disabled, true);
});

test('uploads keep the approved File objects even if a later selection arrives during create', async () => {
  const f = fixture(), a = f.select('source-A', 'A/a.txt'); await f.approve(a);
  f.state.deferJob = true;
  const starting = f.$('start').onclick(), create = f.requests.at(-1);
  const b = f.select('source-B', 'B/b.txt'); await f.approve(b, 'b'.repeat(64));
  create.resolve(f.state.job); await starting;
  assert.equal(f.requests.find(r => r.options.method === 'PUT').options.body, a.file);
  assert.equal(JSON.parse(create.options.body).source, 'source-A');
});

test('failed current preview never leaves an approved Start; stale errors are ignored', async () => {
  const f = fixture(), a = f.select('source-A', 'A/a.txt'), b = f.select('source-B', 'B/b.txt');
  await f.approve(b, 'b'.repeat(64)); a.request.reject('obsolete error'); await a.done;
  assert.equal(f.$('start').disabled, false);
  assert.notEqual(f.$('message').textContent, 'obsolete error');
  const c = f.select('source-C', 'C/c.txt'); c.request.reject('invalid selection'); await c.done;
  assert.equal(f.$('preview-panel').hidden, true); assert.equal(f.$('start').disabled, true);
});
