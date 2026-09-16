const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8');
const json = data => ({ ok: true, status: 200, json: async () => data });
const nodes = () => [1, 2, 3].map(i => ({ id: String(i), name: 'Fixture ' + i, address: '192.0.2.' + i, last_delay: null }));

function setup(fetch) {
  let state;
  const mounted = [];
  const context = {
    console, TextDecoder, Uint8Array, AbortController, navigator: {}, fetch,
    localStorage: { getItem: () => null, setItem() {} },
    window: { innerHeight: 1000, location: { hostname: '127.0.0.1' }, addEventListener() {}, removeEventListener() {} },
    document: { body: { style: {}, classList: { toggle() {}, remove() {} } }, addEventListener() {}, removeEventListener() {} },
    EventSource: class { close() {} addEventListener() {} },
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    Vue: {
      createApp: options => ({ mount: () => { state = options.setup(); } }),
      ref: value => ({ value }), computed: fn => ({ get value() { return fn(); } }),
      onMounted: fn => mounted.push(fn), onUnmounted() {}, nextTick: fn => Promise.resolve().then(fn), watch() {},
    },
  };
  vm.runInNewContext(source, context, { filename: 'app.js' });
  return { state, mounted };
}

function sse(events) {
  let read = false;
  return {
    ok: true, headers: { get: () => 'text/event-stream' },
    body: { getReader: () => ({
      read: async () => {
        if (read) return { done: true };
        read = true;
        return { done: false, value: Buffer.from(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join('')) };
      }, cancel: async () => {},
    }) },
  };
}

test('edits entered while saving remain dirty and visible', async () => {
  let resolve;
  const { state } = setup(() => new Promise(r => { resolve = r; }));
  state.routingLoaded.value = true;
  state.categoryTexts.value.direct = 'domain:initial.example';
  const pending = state.saveAllCategories();
  state.categoryTexts.value.direct += '\ndomain:new.example';
  resolve(json({ categories: { direct: ['domain:initial.example'], proxy: [], block: [] } }));
  await pending;
  assert.match(state.categoryTexts.value.direct, /new\.example/);
  assert.equal(state.hasRoutingChanges.value, true);
});

test('commas inside a regex do not split routing rules', async () => {
  let submitted;
  const { state } = setup(async (_, options) => {
    submitted = JSON.parse(options.body);
    return json({ categories: { direct: submitted.direct, proxy: [], block: [] } });
  });
  state.routingLoaded.value = true;
  state.categoryTexts.value.direct = 'regexp:^foo[0-9]{1,3}\\.example$';
  await state.saveAllCategories();
  assert.equal(submitted.direct.length, 1);
});

test('EOF before complete is an error rather than full success', async () => {
  const { state } = setup(async () => sse([{ type: 'result', node_id: '1', success: true, speed: '1 MB/s', done: true }]));
  state.nodes.value = nodes();
  await state.batchTestSpeed();
  assert.equal(state.toasts.value.at(-1).type, 'error');
  assert.match(state.toasts.value.at(-1).message, /结果不完整/);
  assert.equal(state.nodes.value.filter(n => n.last_speed).length, 1);
});

test('complete must include every requested node', async () => {
  const { state } = setup(async () => sse([{ type: 'complete', results: [{ node_id: '1', success: true, speed: '1 MB/s' }] }]));
  state.nodes.value = nodes();
  await state.batchTestSpeed();
  assert.equal(state.toasts.value.at(-1).type, 'error');
});

test('complete results update nodes even without intermediate events', async () => {
  const { state } = setup(async () => sse([{ type: 'complete', results: nodes().map(n => ({ node_id: n.id, success: true, speed: '1 MB/s' })) }]));
  state.nodes.value = nodes();
  await state.batchTestSpeed();
  assert.equal(state.toasts.value.at(-1).type, 'success');
  assert.equal(state.nodes.value.filter(n => n.last_speed === '1 MB/s').length, 3);
});

test('cancel stops every concurrent test request', async () => {
  const signals = [];
  const { state } = setup(async (_, options) => {
    signals.push(options.signal);
    return { ok: true, headers: { get: () => 'text/event-stream' }, body: { getReader: () => ({
      read: () => new Promise((resolve, reject) => {
        const abort = () => reject(Object.assign(new Error('cancelled'), { name: 'AbortError' }));
        if (options.signal.aborted) abort();
        else options.signal.addEventListener('abort', abort, { once: true });
      }), cancel: async () => {},
    }) } };
  });
  state.nodes.value = nodes();
  const requests = [state.testNodeSpeed(state.nodes.value[0]), state.testNodeSpeed(state.nodes.value[1])];
  await Promise.resolve();
  assert.equal(state.cancelActiveTest(), true);
  await Promise.all(requests);
  assert.ok(signals.every(signal => signal.aborted));
  assert.ok(state.nodes.value.every(n => !n.speedTesting));
  assert.equal(state.cancelActiveTest(), false);
});

test('delete confirmation retains its original IDs after selection changes', async () => {
  const fixture = nodes();
  let deletion;
  const { state, mounted } = setup(async (url, options) => {
    if (url === '/api/nodes/batch-delete') {
      deletion = JSON.parse(options.body);
      return json({ success: true, deleted: deletion.node_ids.length });
    }
    if (url === '/api/nodes') return json({ nodes: fixture });
    if (url === '/api/subscriptions') return json({ subscriptions: [] });
    if (url === '/api/status') return json({ service: { active: true }, outbound_network: { success: false } });
    return json({ direct: [], proxy: [], block: [] });
  });
  await Promise.all(mounted.map(fn => fn()));
  state.selectedNodeIds.value = ['1', '2'];
  await state.batchDeleteSelected();
  state.clearSelection(); // A previously started batch test can finish here.
  state.handleConfirmAction();
  await Promise.resolve();
  assert.deepEqual(deletion.node_ids, ['1', '2']);
});
