// Runs the exported Code-node bodies; this is not an n8n engine/import test.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const workflow = JSON.parse(fs.readFileSync(path.join(__dirname, 'text-csv-demo.json')));
const nodes = Object.fromEntries(workflow.nodes.map(n => [n.name, n]));
const txt = fs.readFileSync(path.join(__dirname, '../fixtures/runbook.txt'), 'utf8').trim();
const row = { asset: 'demo-router-01', owner: 'NetworkOps', location: 'Synthetic Lab' };
const context = {
  'Read runbook': { fileName: 'runbook.txt' },
  'Read inventory': { fileName: 'inventory.csv' },
  'Demo configuration': { question: 'Demo question' },
  'Prepare runbook': { text: txt },
};
function run(name, input, extra = {}) {
  const items = input.map(json => ({ json }));
  const refs = { ...context, ...extra };
  return vm.runInNewContext(`(function() {${nodes[name].parameters.jsCode}\n})()`, {
    $input: { all: () => items, first: () => items[0] },
    $: name => ({ first: () => ({ json: refs[name] }) }),
  });
}
const csvText = run('Label inventory rows', [row])[0].json.text;
context['Label inventory rows'] = { text: csvText };
function result() {
  return {
    answer: 'The code is ORION [2]. The owner is NetworkOps [1].',
    generation: { status: 'complete' },
    sources: [
      { source: 'inventory.csv', chunk: 0, text: csvText },
      { source: 'runbook.txt', chunk: 0, text: txt.replace(/\s+/g, ' ') },
    ],
  };
}
test('export has manual trigger, serial ingest-before-ask and no secrets/credential IDs', () => {
  assert.equal(workflow.active, false);
  assert.equal(workflow.nodes[0].type, 'n8n-nodes-base.manualTrigger');
  for (const n of workflow.nodes) {
    if (n.type === 'n8n-nodes-base.readWriteFile') assert.equal(n.typeVersion, 1.1);
    assert.equal(n.credentials, undefined);
    assert.equal(n.retryOnFail, undefined);
    assert.equal(n.continueOnFail, undefined);
  }
  const http = workflow.nodes.filter(n => n.type === 'n8n-nodes-base.httpRequest');
  assert.equal(http.length, 3);
  for (const n of http) {
    assert.equal(n.parameters.genericAuthType, 'httpHeaderAuth');
    assert.equal(n.parameters.headerParameters, undefined);
    assert.equal(n.parameters.options.timeout, 240000);
  }
  workflow.nodes.slice(0, -1).forEach((n, i) => {
    assert.equal(workflow.connections[n.name].main[0][0].node, workflow.nodes[i+1].name);
  });
});
test('text source and CSV labels preserve filenames', () => {
  assert.equal(run('Prepare runbook', [{ text: txt }])[0].json.source, 'runbook.txt');
  assert.equal(run('Label inventory rows', [row])[0].json.source, 'inventory.csv');
  assert.equal(csvText, 'Inventory row 1: asset: demo-router-01; owner: NetworkOps; location: Synthetic Lab');
  const quoted = run('Label inventory rows', [{ ...row, location: 'Lab, west' }])[0].json.text;
  assert.ok(quoted.includes('location: Lab, west'));
});
test('empty and malformed rows cannot silently ingest', () => {
  assert.throws(() => run('Label inventory rows', []));
  assert.throws(() => run('Label inventory rows', [{ asset: 'demo-router-01' }]));
  assert.throws(() => run('Prepare runbook', [{ text: '' }]));
  assert.throws(() => run('Check inventory ingestion', [{ source: 'inventory.csv', chunks_indexed: 0 }]));
});
test('paraphrase and reordered sources pass fixture checks', () => {
  assert.equal(run('Check answer and sources', [result()])[0].json.demoCheck, 'PASS');
});
test('wrong answer, missing source, wrong citation, changed payload and limit fail', () => {
  for (const mutate of [
    r => { r.answer = 'SCORPION [2] NetworkOps [1]'; },
    r => { r.answer = 'ORION [3] NetworkOps [1]'; },
    r => { r.answer = 'ORION [1] NetworkOps [1]'; },
    r => { r.sources.pop(); },
    r => { r.sources[0].text = 'wrong'; },
    r => { r.generation.status = 'limit'; },
  ]) {
    const r = result(); mutate(r);
    assert.throws(() => run('Check answer and sources', [r]));
  }
});
