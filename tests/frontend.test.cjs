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
    requestAnimationFrame: (() => {
      let time = 1000;
      return fn => { time += 80; fn(time); return 1; };
    })(),
    cancelAnimationFrame: () => {},
    performance: { now: () => 1000 },
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

test('every auto-scrolling container reuses the shared themed scrollbar', () => {
  const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
  const scrollable = [...html.matchAll(/class="([^"]*)"/g)]
    .map(match => match[1])
    .filter(classes => /overflow(-[xy])?-auto/.test(classes));
  assert.ok(scrollable.length >= 3, 'expected the tab strip, node list and log panel to scroll');
  assert.deepEqual(
    scrollable.filter(classes => !classes.includes('custom-scrollbar')),
    [],
    'auto-scrolling containers must reuse .custom-scrollbar',
  );
});

test('subscription tab strip scrolls horizontally without squeezing its tags', () => {
  const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
  const strip = html.match(/<div[^>]*class="([^"]*overflow-x-auto[^"]*)"/);
  assert.ok(strip, 'subscription tab strip must exist');
  for (const token of ['custom-scrollbar', 'min-w-0', 'flex-1']) {
    assert.ok(strip[1].includes(token), 'tab strip should keep ' + token);
  }
  assert.ok((html.match(/flex-shrink-0 cursor-pointer/g) || []).length > 0, 'tags must not shrink');
});

test('handleSubTabsWheel converts vertical mouse wheel into horizontal scroll on overflow', () => {
  const { state } = setup(() => json({}));
  const el = { scrollWidth: 600, clientWidth: 200, scrollLeft: 50 };
  state.subTabsContainer.value = el;

  let prevented = false;
  state.handleSubTabsWheel({ deltaX: 0, deltaY: 100, preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.ok(el.scrollLeft > 50, 'scrollLeft should smoothly advance with wheel delta');

  prevented = false;
  state.handleSubTabsWheel({ deltaX: 0, deltaY: -40, preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
});

test('auto-return scrolls back to active subscription with easing when mouse leaves', () => {
  const { state } = setup(() => json({}));
  const targetBtn = { offsetLeft: 300, offsetWidth: 80 };
  const el = {
    scrollWidth: 800,
    clientWidth: 200,
    scrollLeft: 600,
    querySelector: () => targetBtn,
    firstElementChild: targetBtn,
  };
  state.subTabsContainer.value = el;
  state.activeNode.value = { subscription_id: 'sub-1' };

  state.scrollToRunningNodeSub();
  assert.ok(el.scrollLeft < 600, 'scrollLeft should glide towards centered active tab');
});

test('handleSubTabsWheel allows normal page scroll when tabs do not overflow', () => {
  const { state } = setup(() => json({}));
  const el = { scrollWidth: 150, clientWidth: 200, scrollLeft: 0 };
  state.subTabsContainer.value = el;

  let prevented = false;
  state.handleSubTabsWheel({ deltaX: 0, deltaY: 100, preventDefault: () => { prevented = true; } });
  assert.equal(prevented, false);
  assert.equal(el.scrollLeft, 0);
});

test('node and subscription names have max-width limits and truncation to prevent squeezing', () => {
  const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
  const nodeNameSpan = html.match(/<span v-if="editingNodeId !== node\.id"[^>]*class="([^"]*)"/);
  assert.ok(nodeNameSpan, 'node name span must exist');
  assert.ok(nodeNameSpan[1].includes('truncate'), 'node name must have truncate');
  assert.ok(nodeNameSpan[1].includes('min-w-'), 'node name must protect minimum width');

  const subNameSpan = html.match(/<span v-if="getNodeSubName\(node\.subscription_id\)"[^>]*class="([^"]*)"/);
  assert.ok(subNameSpan, 'sub name span in row must exist');
  assert.ok(subNameSpan[1].includes('truncate'), 'sub name must truncate');
  assert.ok(subNameSpan[1].includes('max-w-'), 'sub name must have max-width');

  const tabSpan = html.match(/<span v-if="editingSubId !== sub\.id"[^>]*class="([^"]*)"/);
  assert.ok(tabSpan, 'tab title span must exist');
  assert.ok(tabSpan[1].includes('truncate'), 'tab title must truncate');
  assert.ok(tabSpan[1].includes('max-w-'), 'tab title must have max-width');
});

test('manual nodes empty state displays custom hint and omits import button', () => {
  const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
  assert.ok(html.includes('导入独立节点以在此显示'), 'manual empty hint must exist');
  assert.ok(html.includes("activeSubFilter !== 'manual'"), 'import button should be hidden for manual empty state');
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

test('import failure raises error toast, logs system message and preserves input without altering modal body', async () => {
  const { state } = setup(async (url) => {
    if (url === '/api/nodes/import') {
      return { ok: false, status: 400, json: async () => ({ detail: '未检测到有效节点链接或订阅地址' }) };
    }
    return json({});
  });
  state.openImportModal.value = true;
  state.importInput.value = 'invalid://link';
  await state.submitUnifiedImport();

  assert.equal(state.openImportModal.value, true);
  assert.equal(state.importInput.value, 'invalid://link');
  assert.equal(state.toasts.value.at(-1).type, 'error');
  assert.match(state.toasts.value.at(-1).message, /未检测到有效节点链接/);
  assert.ok(state.logs.value.some(l => l.raw.includes('导入失败') && l.raw.includes('未检测到有效节点链接')));
});

test('search morphing expands, preserves text on blur, and collapses gracefully on escape or empty blur', async () => {
  const { state } = setup(async () => json({}));
  assert.equal(state.isSearchExpanded.value, false);

  // 展开搜索
  await state.expandSearch();
  assert.equal(state.isSearchExpanded.value, true);

  // 空值失焦收回
  state.collapseSearchIfEmpty();
  assert.equal(state.isSearchExpanded.value, false);

  // 输入搜索词后失焦不收回
  await state.expandSearch();
  state.searchQuery.value = 'hk';
  state.collapseSearchIfEmpty();
  assert.equal(state.isSearchExpanded.value, true);

  // Esc 优先清空内容
  state.handleSearchEsc();
  assert.equal(state.searchQuery.value, '');
  assert.equal(state.isSearchExpanded.value, true);

  // 再次 Esc 顺滑收回
  state.handleSearchEsc();
  assert.equal(state.isSearchExpanded.value, false);
});

test('scroll cues fade mask and indicator buttons respond to overflow state', () => {
  const { state } = setup(async () => json({}));
  assert.ok(state.nodeScrollCue.value);
  assert.equal(state.nodeScrollCue.value.canUp, false);
  assert.equal(state.nodeScrollCue.value.canDown, false);

  assert.ok(state.routingScrollCues.value.direct);
  assert.equal(state.routingScrollCues.value.direct.canUp, false);
  assert.equal(state.routingScrollCues.value.direct.canDown, false);

  // 模拟节点列表溢出
  state.nodeListScrollRef.value = {
    scrollHeight: 1000,
    clientHeight: 400,
    scrollTop: 100,
    scrollBy() {},
  };
  state.updateNodeScrollCue();
  assert.equal(state.nodeScrollCue.value.canUp, true);
  assert.equal(state.nodeScrollCue.value.canDown, true);

  // 模拟滚动到顶部
  state.nodeListScrollRef.value.scrollTop = 0;
  state.updateNodeScrollCue();
  assert.equal(state.nodeScrollCue.value.canUp, false);
  assert.equal(state.nodeScrollCue.value.canDown, true);

  // 模拟节点列表滚动到底部
  state.nodeListScrollRef.value.scrollTop = 600;
  state.updateNodeScrollCue();
  assert.equal(state.nodeScrollCue.value.canUp, true);
  assert.equal(state.nodeScrollCue.value.canDown, false);

  // 模拟订阅横轴溢出与滚动指示
  assert.ok(state.subTabsScrollCue.value);
  assert.equal(state.subTabsScrollCue.value.canLeft, false);
  assert.equal(state.subTabsScrollCue.value.canRight, false);

  state.subTabsContainer.value = {
    scrollWidth: 800,
    clientWidth: 300,
    scrollLeft: 100,
    scrollBy() {},
  };
  state.updateSubTabsScrollCue();
  assert.equal(state.subTabsScrollCue.value.canLeft, true);
  assert.equal(state.subTabsScrollCue.value.canRight, true);

  // 滚回最左侧
  state.subTabsContainer.value.scrollLeft = 0;
  state.updateSubTabsScrollCue();
  assert.equal(state.subTabsScrollCue.value.canLeft, false);
  assert.equal(state.subTabsScrollCue.value.canRight, true);

  // 滚至最右端
  state.subTabsContainer.value.scrollLeft = 500;
  state.updateSubTabsScrollCue();
  assert.equal(state.subTabsScrollCue.value.canLeft, true);
  assert.equal(state.subTabsScrollCue.value.canRight, false);
});


