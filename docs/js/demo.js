/**
 * Xray Web Console - Pure Static Demo Engine
 * 100% Client-Side Interactive Playground (No Backend Required)
 */

const { createApp, ref, computed, watch, onMounted, onUnmounted, nextTick } = Vue;

createApp({
  setup() {
    const isDark = ref(true);
    const initTheme = () => {
      try {
        const saved = localStorage.getItem('xray_web_theme') || 'dark';
        isDark.value = saved === 'dark';
        document.documentElement.className = saved === 'light' ? 'light' : 'dark';
      } catch (_) {}
    };
    const toggleTheme = () => {
      isDark.value = !isDark.value;
      const theme = isDark.value ? 'dark' : 'light';
      try { localStorage.setItem('xray_web_theme', theme); } catch (_) {}
      document.documentElement.className = theme;
      showToast(isDark.value ? '已切换至深色模式' : '已切换至浅色模式', 'info');
    };
    initTheme();

    // Toasts
    const toasts = ref([]);
    let toastSeq = 1;
    const showToast = (message, type = 'info') => {
      const id = toastSeq++;
      toasts.value.push({ id, message, type });
      setTimeout(() => {
        toasts.value = toasts.value.filter(t => t.id !== id);
      }, 3000);
    };

    // System Status
    const service = ref({
      active: true,
      version: 'Xray 26.7.28',
      bridge_ip: '172.25.217.166'
    });
    const ports = ref({ socks: 20170, http: 20171, routing: 20172 });
    const bridgeIP = computed(() => service.value.bridge_ip);
    const statusError = ref('');

    // Navigation
    const currentTab = ref('nodes');

    // Subscriptions
    const subscriptions = ref([
      { id: 'sub-1', name: '香港 BGP 高速专线', url: 'https://sub.demo.xyz/api/v1/client/subscribe?token=hk_bgp_vip', updating: false },
      { id: 'sub-2', name: '日本东京 NTT / IIJ', url: 'https://sub.demo.xyz/api/v1/client/subscribe?token=tokyo_fast_iij', updating: false },
      { id: 'sub-3', name: '美西 9929 优质线路', url: 'https://sub.demo.xyz/api/v1/client/subscribe?token=us_west_9929', updating: false },
      { id: 'sub-4', name: '新加坡流媒体解锁', url: 'https://sub.demo.xyz/api/v1/client/subscribe?token=sg_sgp_media', updating: false },
    ]);
    const activeSubFilter = ref('all');

    // Realistic Mock Nodes (24 nodes)
    const nodes = ref([
      // 香港
      { id: 'n-hk-01', name: 'HK 香港 01 [BGP专线] ML-KEM', protocol: 'vless', address: '103.***.***.12', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@103.1.2.3:443?security=reality', is_active: true, last_delay: 28, last_speed: '68.5 MB/s', subscription_id: 'sub-1', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-hk-02', name: 'HK 香港 02 [CN2 GIA] 4K', protocol: 'vless', address: '103.***.***.15', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@103.1.2.4:443?security=reality', is_active: false, last_delay: 34, last_speed: '54.2 MB/s', subscription_id: 'sub-1', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-hk-03', name: 'HK 香港 03 [国际出口] 备用', protocol: 'trojan', address: '103.***.***.18', port: 8443, security: 'tls', network: 'tcp', raw_link: 'trojan://demo@103.1.2.5:8443?security=tls', is_active: false, last_delay: 42, last_speed: '38.0 MB/s', subscription_id: 'sub-1', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-hk-04', name: 'HK 香港 04 [游戏优化] 低抖动', protocol: 'shadowsocks', address: '103.***.***.22', port: 20900, security: 'none', network: 'tcp', raw_link: 'ss://demo@103.1.2.6:20900', is_active: false, last_delay: 25, last_speed: '45.1 MB/s', subscription_id: 'sub-1', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-hk-05', name: 'HK 香港 05 [大带宽] 流媒体', protocol: 'vless', address: '103.***.***.28', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@103.1.2.7:443?security=reality', is_active: false, last_delay: 39, last_speed: '62.0 MB/s', subscription_id: 'sub-1', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-hk-06', name: 'HK 香港 06 [企业级专线]', protocol: 'vless', address: '103.***.***.35', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@103.1.2.8:443?security=reality', is_active: false, last_delay: 31, last_speed: '75.8 MB/s', subscription_id: 'sub-1', testing: false, speedTesting: false, liveSpeed: '' },

      // 日本
      { id: 'n-jp-01', name: 'JP 东京 01 [NTT] 极速', protocol: 'vless', address: '133.***.***.44', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@133.1.2.3:443?security=reality', is_active: false, last_delay: 58, last_speed: '48.2 MB/s', subscription_id: 'sub-2', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-jp-02', name: 'JP 东京 02 [IIJ] 原生IP', protocol: 'trojan', address: '133.***.***.56', port: 8443, security: 'tls', network: 'tcp', raw_link: 'trojan://demo@133.1.2.4:8443?security=tls', is_active: false, last_delay: 64, last_speed: '35.4 MB/s', subscription_id: 'sub-2', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-jp-03', name: 'JP 大阪 01 [软银软银] 4K', protocol: 'vless', address: '133.***.***.72', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@133.1.2.5:443?security=reality', is_active: false, last_delay: 52, last_speed: '59.1 MB/s', subscription_id: 'sub-2', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-jp-04', name: 'JP 东京 03 [Netflix 解锁]', protocol: 'vmess', address: '133.***.***.80', port: 443, security: 'tls', network: 'ws', raw_link: 'vmess://demo@133.1.2.6:443', is_active: false, last_delay: 68, last_speed: '28.6 MB/s', subscription_id: 'sub-2', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-jp-05', name: 'JP 东京 04 [AbemaTV 专线]', protocol: 'vless', address: '133.***.***.91', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@133.1.2.7:443?security=reality', is_active: false, last_delay: 72, last_speed: '41.0 MB/s', subscription_id: 'sub-2', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-jp-06', name: 'JP 东京 05 [低延迟直连]', protocol: 'shadowsocks', address: '133.***.***.99', port: 31088, security: 'none', network: 'tcp', raw_link: 'ss://demo@133.1.2.8:31088', is_active: false, last_delay: 55, last_speed: '50.3 MB/s', subscription_id: 'sub-2', testing: false, speedTesting: false, liveSpeed: '' },

      // 美国
      { id: 'n-us-01', name: 'US 洛杉矶 01 [9929] 顶配', protocol: 'vless', address: '107.***.***.18', port: 31078, security: 'reality', network: 'tcp', raw_link: 'vless://demo@107.1.2.3:31078?security=reality', is_active: false, last_delay: 145, last_speed: '82.4 MB/s', subscription_id: 'sub-3', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-us-02', name: 'US 圣何塞 02 [CMIN2] 4K', protocol: 'vless', address: '104.***.***.62', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@104.1.2.4:443?security=reality', is_active: false, last_delay: 152, last_speed: '66.8 MB/s', subscription_id: 'sub-3', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-us-03', name: 'US 洛杉矶 03 [OpenAI 解锁]', protocol: 'trojan', address: '107.***.***.88', port: 8443, security: 'tls', network: 'tcp', raw_link: 'trojan://demo@107.1.2.5:8443?security=tls', is_active: false, last_delay: 168, last_speed: '45.0 MB/s', subscription_id: 'sub-3', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-us-04', name: 'US 西雅图 04 [千兆直连]', protocol: 'vless', address: '198.***.***.112', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@198.1.2.6:443?security=reality', is_active: false, last_delay: 160, last_speed: '71.2 MB/s', subscription_id: 'sub-3', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-us-05', name: 'US 纽约 05 [东海岸测试]', protocol: 'vless', address: '199.***.***.210', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@199.1.2.7:443?security=reality', is_active: false, last_delay: 210, last_speed: '32.1 MB/s', subscription_id: 'sub-3', testing: false, speedTesting: false, liveSpeed: '' },

      // 新加坡
      { id: 'n-sg-01', name: 'SG 新加坡 01 [BGP直连]', protocol: 'vless', address: '128.***.***.15', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@128.1.2.3:443?security=reality', is_active: false, last_delay: 48, last_speed: '65.0 MB/s', subscription_id: 'sub-4', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-sg-02', name: 'SG 新加坡 02 [Disney+ 解锁]', protocol: 'trojan', address: '128.***.***.28', port: 8443, security: 'tls', network: 'tcp', raw_link: 'trojan://demo@128.1.2.4:8443?security=tls', is_active: false, last_delay: 53, last_speed: '52.7 MB/s', subscription_id: 'sub-4', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-sg-03', name: 'SG 新加坡 03 [原生IP] 高速', protocol: 'vless', address: '128.***.***.66', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@128.1.2.5:443?security=reality', is_active: false, last_delay: 50, last_speed: '58.3 MB/s', subscription_id: 'sub-4', testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-sg-04', name: 'SG 新加坡 04 [备用容灾]', protocol: 'shadowsocks', address: '128.***.***.89', port: 20188, security: 'none', network: 'tcp', raw_link: 'ss://demo@128.1.2.6:20188', is_active: false, last_delay: 65, last_speed: '29.4 MB/s', subscription_id: 'sub-4', testing: false, speedTesting: false, liveSpeed: '' },

      // 独立导入节点 (Manual)
      { id: 'n-man-01', name: 'self-work-pc (家宽直连)', protocol: 'vless', address: '155.***.***.218', port: 20900, security: 'reality', network: 'tcp', raw_link: 'vless://demo@155.1.2.3:20900?security=reality', is_active: false, last_delay: 18, last_speed: '95.0 MB/s', subscription_id: null, testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-man-02', name: 'oracle-cloud-free-arm (首尔)', protocol: 'vless', address: '150.***.***.88', port: 443, security: 'reality', network: 'tcp', raw_link: 'vless://demo@150.1.2.4:443?security=reality', is_active: false, last_delay: 45, last_speed: '31.2 MB/s', subscription_id: null, testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-man-03', name: 'racknerd-budget-vps (西雅图)', protocol: 'trojan', address: '192.***.***.55', port: 8443, security: 'tls', network: 'tcp', raw_link: 'trojan://demo@192.1.2.5:8443?security=tls', is_active: false, last_delay: 175, last_speed: '18.5 MB/s', subscription_id: null, testing: false, speedTesting: false, liveSpeed: '' },
      { id: 'n-man-04', name: 'aws-lightsail-tokyo', protocol: 'shadowsocks', address: '54.***.***.102', port: 10086, security: 'none', network: 'tcp', raw_link: 'ss://demo@54.1.2.6:10086', is_active: false, last_delay: 62, last_speed: '44.0 MB/s', subscription_id: null, testing: false, speedTesting: false, liveSpeed: '' }
    ]);

    // Revealed Address toggle
    const revealedNodes = ref(new Set());
    const isNodeRevealed = id => revealedNodes.value.has(id);
    const toggleNodeAddressReveal = id => {
      if (revealedNodes.value.has(id)) revealedNodes.value.delete(id);
      else revealedNodes.value.add(id);
    };
    const formatAddress = (addr, port, revealed) => {
      if (revealed) return `${addr.replace(/\*\*\*\.\*\*\*/g, '123.45')}:${port}`;
      return `${addr}:${port}`;
    };

    // Subscriptions count & labels
    const manualNodesCount = computed(() => nodes.value.filter(n => !n.subscription_id).length);
    const subNames = computed(() => new Map(subscriptions.value.map(s => [s.id, s.name])));
    const getNodeSubName = subId => subNames.value.get(subId) || '';
    const getSubNodeCount = subId => nodes.value.filter(n => n.subscription_id === subId).length;
    const currentSelectedSub = computed(() => subscriptions.value.find(s => s.id === activeSubFilter.value) || null);

    // Filtered & Sorted Display Nodes
    const searchQuery = ref('');
    const isSearchExpanded = ref(false);
    const searchInputRef = ref(null);
    const expandSearch = async () => {
      isSearchExpanded.value = true;
      await nextTick();
      searchInputRef.value?.focus();
    };
    const collapseSearchIfEmpty = () => {
      if (!searchQuery.value.trim()) isSearchExpanded.value = false;
    };
    const clearSearchQuery = () => {
      searchQuery.value = '';
      isSearchExpanded.value = false;
    };
    const handleSearchEsc = () => {
      if (searchQuery.value) searchQuery.value = '';
      else isSearchExpanded.value = false;
    };

    const delaySortOrder = ref('none');
    const delaySortLabel = computed(() => ({ none: '按延迟排序', asc: '延迟从低到高', desc: '延迟从高到低' })[delaySortOrder.value]);
    const cycleDelaySort = () => {
      delaySortOrder.value = { none: 'asc', asc: 'desc', desc: 'none' }[delaySortOrder.value];
    };

    const displayNodes = computed(() => {
      let list = nodes.value;
      if (activeSubFilter.value === 'manual') {
        list = list.filter(n => !n.subscription_id);
      } else if (activeSubFilter.value !== 'all') {
        list = list.filter(n => n.subscription_id === activeSubFilter.value);
      }
      const q = searchQuery.value.trim().toLowerCase();
      if (q) {
        list = list.filter(n => n.name.toLowerCase().includes(q) || n.address.toLowerCase().includes(q) || n.protocol.toLowerCase().includes(q));
      }
      if (delaySortOrder.value === 'asc') {
        list = [...list].sort((a, b) => (a.last_delay ?? 99999) - (b.last_delay ?? 99999));
      } else if (delaySortOrder.value === 'desc') {
        list = [...list].sort((a, b) => (b.last_delay ?? -1) - (a.last_delay ?? -1));
      }
      return list;
    });

    // Multi-Select
    const isMultiSelectMode = ref(false);
    const selectedNodeIds = ref([]);
    const isNodeSelected = id => selectedNodeIds.value.includes(id);
    const toggleMultiSelectMode = () => {
      isMultiSelectMode.value = !isMultiSelectMode.value;
      selectedNodeIds.value = [];
    };
    const exitMultiSelectMode = () => {
      isMultiSelectMode.value = false;
      selectedNodeIds.value = [];
    };
    const clearSelection = () => { selectedNodeIds.value = []; };
    const allVisibleSelected = computed(() => displayNodes.value.length > 0 && displayNodes.value.every(n => isNodeSelected(n.id)));
    const toggleSelectVisible = () => {
      if (allVisibleSelected.value) {
        selectedNodeIds.value = [];
      } else {
        selectedNodeIds.value = Array.from(new Set([...selectedNodeIds.value, ...displayNodes.value.map(n => n.id)]));
      }
    };
    const handleNodeClick = (node) => {
      if (!isMultiSelectMode.value) return;
      if (isNodeSelected(node.id)) {
        selectedNodeIds.value = selectedNodeIds.value.filter(id => id !== node.id);
      } else {
        selectedNodeIds.value.push(node.id);
      }
    };
    const handleNodeDblClick = node => {
      if (!isMultiSelectMode.value) fastSwitchNode(node);
    };

    // Node Actions
    const switchingNodeId = ref(null);
    const fastSwitchNode = async node => {
      if (node.is_active || switchingNodeId.value) return;
      switchingNodeId.value = node.id;
      setTimeout(() => {
        nodes.value.forEach(n => n.is_active = n.id === node.id);
        switchingNodeId.value = null;
        showToast(`已切换节点至「${node.name}」`, 'success');
        addSystemLog('SYSTEM', `切换活跃出口节点至 [${node.name}] (${node.address})`);
      }, 400);
    };

    // Latency & Speed Titles / Classes
    const getLatencyClass = delay => {
      if (delay === null || delay === undefined) return 'text-gray-600';
      if (delay < 0) return 'text-rose-400';
      if (delay < 80) return 'text-emerald-400';
      if (delay < 160) return 'text-cyan-400';
      return 'text-amber-400';
    };
    const latencyTitle = delay => delay ? `延迟 ${delay}ms` : '点击测试真实延迟';
    const speedTitle = speed => speed ? `峰值速度 ${speed}` : '点击测试下行测速';

    // Single Node Latency Test
    const testNode = async node => {
      if (node.testing) return;
      node.testing = true;
      const fakeDelay = Math.floor(Math.random() * 45) + (node.name.includes('HK') ? 22 : node.name.includes('JP') ? 50 : 135);
      setTimeout(() => {
        node.last_delay = fakeDelay;
        node.testing = false;
        showToast(`${node.name}: ${fakeDelay}ms`, 'success');
      }, 350);
    };

    // Single Node Speed Test
    const testNodeSpeed = async node => {
      if (node.speedTesting) return;
      node.speedTesting = true;
      node.liveSpeed = '10.2 MB/s';
      let step = 1;
      const timer = setInterval(() => {
        step++;
        node.liveSpeed = (step * 14.5 + Math.random() * 5).toFixed(1) + ' MB/s';
        if (step >= 4) {
          clearInterval(timer);
          node.last_speed = node.liveSpeed;
          node.speedTesting = false;
          showToast(`${node.name} 测速完成: ${node.last_speed}`, 'success');
        }
      }, 250);
    };

    // Batch Testing
    const batchTesting = ref(false);
    const batchSpeedTesting = ref(false);
    let cancelTesting = false;
    const cancelActiveTest = () => {
      cancelTesting = true;
      batchTesting.value = false;
      batchSpeedTesting.value = false;
      nodes.value.forEach(n => { n.testing = false; n.speedTesting = false; });
      showToast('已停止测速', 'warning');
    };

    const batchTestDelay = async () => {
      const targetNodes = (selectedNodeIds.value.length ? nodes.value.filter(n => isNodeSelected(n.id)) : displayNodes.value);
      if (!targetNodes.length) return;
      batchTesting.value = true;
      cancelTesting = false;
      for (const n of targetNodes) {
        if (cancelTesting) break;
        n.testing = true;
        await new Promise(r => setTimeout(r, 120));
        n.last_delay = Math.floor(Math.random() * 50) + (n.name.includes('HK') ? 25 : n.name.includes('JP') ? 55 : 140);
        n.testing = false;
      }
      batchTesting.value = false;
      showToast(`已完成 ${targetNodes.length} 个节点的延迟测试`, 'success');
    };

    const batchTestSpeed = async () => {
      const targetNodes = (selectedNodeIds.value.length ? nodes.value.filter(n => isNodeSelected(n.id)) : displayNodes.value);
      if (!targetNodes.length) return;
      batchSpeedTesting.value = true;
      cancelTesting = false;
      for (const n of targetNodes) {
        if (cancelTesting) break;
        n.speedTesting = true;
        n.liveSpeed = '15.0 MB/s';
        await new Promise(r => setTimeout(r, 200));
        n.liveSpeed = (Math.random() * 50 + 20).toFixed(1) + ' MB/s';
        await new Promise(r => setTimeout(r, 200));
        n.last_speed = n.liveSpeed;
        n.speedTesting = false;
      }
      batchSpeedTesting.value = false;
      showToast(`已完成 ${targetNodes.length} 个节点的速度测试`, 'success');
    };

    // Deletion
    const deleteNode = node => {
      confirmDialog.value = {
        show: true,
        title: '删除节点',
        message: `确定要删除节点「${node.name}」吗？`,
        confirmText: '立即删除',
        confirmType: 'danger',
        onConfirm: () => {
          nodes.value = nodes.value.filter(n => n.id !== node.id);
          confirmDialog.value.show = false;
          showToast('节点已删除', 'info');
        }
      };
    };
    const batchDeleteSelected = () => {
      const count = selectedNodeIds.value.length;
      if (!count) return;
      confirmDialog.value = {
        show: true,
        title: '批量删除',
        message: `确定要删除选中的 ${count} 个节点吗？`,
        confirmText: `删除 (${count})`,
        confirmType: 'danger',
        onConfirm: () => {
          nodes.value = nodes.value.filter(n => !selectedNodeIds.value.includes(n.id));
          selectedNodeIds.value = [];
          confirmDialog.value.show = false;
          showToast(`已成功删除 ${count} 个节点`, 'info');
        }
      };
    };

    // Inline Rename Node
    const editingNodeId = ref(null);
    const inlineRenameValue = ref('');
    const inlineRenameInputRef = ref(null);
    const startInlineRename = node => {
      editingNodeId.value = node.id;
      inlineRenameValue.value = node.name;
      nextTick(() => {
        inlineRenameInputRef.value?.focus();
        inlineRenameInputRef.value?.select();
      });
    };
    const saveInlineRename = node => {
      if (!editingNodeId.value) return;
      const val = inlineRenameValue.value.trim();
      if (val) {
        node.name = val;
        showToast('备注已更新', 'success');
      }
      editingNodeId.value = null;
    };
    const cancelInlineRename = () => { editingNodeId.value = null; };

    // Subscriptions Update & Rename
    const editingSubId = ref(null);
    const inlineSubRenameValue = ref('');
    const inlineSubRenameInputRef = ref(null);
    const handleSubTabClick = sub => {
      if (activeSubFilter.value === sub.id) {
        editingSubId.value = sub.id;
        inlineSubRenameValue.value = sub.name;
        nextTick(() => inlineSubRenameInputRef.value?.focus());
      } else {
        activeSubFilter.value = sub.id;
      }
    };
    const saveInlineSubRename = sub => {
      if (!editingSubId.value) return;
      const val = inlineSubRenameValue.value.trim();
      if (val) {
        sub.name = val;
        showToast('订阅名称已修改', 'success');
      }
      editingSubId.value = null;
    };
    const cancelInlineSubRename = () => { editingSubId.value = null; };
    const updateSub = sub => {
      sub.updating = true;
      setTimeout(() => {
        sub.updating = false;
        showToast(`订阅「${sub.name}」已更新 (同步 6 个节点)`, 'success');
      }, 600);
    };
    const deleteSub = sub => {
      confirmDialog.value = {
        show: true,
        title: '删除订阅',
        message: `确定要删除订阅源「${sub.name}」吗？`,
        checkboxLabel: '同时删除该订阅下的所有节点',
        checkboxValue: true,
        confirmText: '确认删除',
        confirmType: 'danger',
        onConfirm: () => {
          if (confirmDialog.value.checkboxValue) {
            nodes.value = nodes.value.filter(n => n.subscription_id !== sub.id);
          }
          subscriptions.value = subscriptions.value.filter(s => s.id !== sub.id);
          activeSubFilter.value = 'all';
          confirmDialog.value.show = false;
          showToast('订阅已删除', 'info');
        }
      };
    };

    // Sub Tabs Strip Scrolling
    const subTabsContainer = ref(null);
    const subTabsScrollCue = ref({ canLeft: false, canRight: false });
    const updateSubTabsScrollCue = () => {
      const el = subTabsContainer.value;
      if (!el) return;
      const hasOverflow = el.scrollWidth > el.clientWidth + 2;
      subTabsScrollCue.value = {
        canLeft: hasOverflow && el.scrollLeft > 4,
        canRight: hasOverflow && (el.scrollLeft + el.clientWidth < el.scrollWidth - 4),
      };
    };
    const scrollSubTabs = direction => {
      const el = subTabsContainer.value;
      if (!el) return;
      el.scrollBy({ left: direction === 'left' ? -150 : 150, behavior: 'smooth' });
    };
    const handleSubTabsWheel = e => {
      const el = subTabsContainer.value;
      if (!el || el.scrollWidth <= el.clientWidth) return;
      e.preventDefault();
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      el.scrollLeft += delta * 0.8;
      updateSubTabsScrollCue();
    };
    const scrollToActiveSub = (explicitId = null) => {
      const el = subTabsContainer.value;
      if (!el || el.scrollWidth <= el.clientWidth) return;
      const id = explicitId || activeSubFilter.value;
      if (id === 'all' || id === 'manual') {
        el.scrollTo({ left: 0, behavior: 'smooth' });
        return;
      }
      const target = el.querySelector(`[data-sub-id="${id}"]`);
      if (target) {
        const left = target.offsetLeft;
        el.scrollTo({ left: Math.max(0, left - 40), behavior: 'smooth' });
      }
    };
    let subTabsTimer = null;
    const handleSubTabsMouseLeave = () => {
      clearTimeout(subTabsTimer);
      subTabsTimer = setTimeout(() => scrollToActiveSub(), 300);
    };
    const handleSubTabsMouseEnter = () => { clearTimeout(subTabsTimer); };

    // Node List Scroll & Easing Auto-Return
    const nodeListScrollRef = ref(null);
    const nodeScrollCue = ref({ canUp: false, canDown: false });
    const updateNodeScrollCue = () => {
      const el = nodeListScrollRef.value;
      if (!el) return;
      const hasOverflow = el.scrollHeight > el.clientHeight + 2;
      nodeScrollCue.value = {
        canUp: hasOverflow && el.scrollTop > 4,
        canDown: hasOverflow && (el.scrollTop + el.clientHeight < el.scrollHeight - 4),
      };
    };
    const handleNodeListScroll = () => updateNodeScrollCue();
    const scrollNodeList = direction => {
      const el = nodeListScrollRef.value;
      if (!el) return;
      el.scrollBy({ top: direction === 'up' ? -140 : 140, behavior: 'smooth' });
    };

    const easeFluid = t => 1 - Math.pow(1 - t, 3.6);
    const smoothScrollElementToTop = (el, onStep) => {
      if (!el || el.scrollTop <= 0) return null;
      const startY = el.scrollTop;
      const duration = Math.min(520, Math.max(340, Math.sqrt(startY) * 20));
      const startTime = performance.now();
      let cancelled = false;
      const step = now => {
        if (cancelled) return;
        const elapsed = now - startTime;
        const progress = Math.min(1, elapsed / duration);
        el.scrollTop = Math.max(0, startY * (1 - easeFluid(progress)));
        if (typeof onStep === 'function') onStep();
        if (progress < 1 && el.scrollTop > 0) requestAnimationFrame(step);
        else { el.scrollTop = 0; if (typeof onStep === 'function') onStep(); }
      };
      requestAnimationFrame(step);
      return () => { cancelled = true; };
    };

    let nodeReturnTimer = null;
    let cancelNodeScroll = null;
    let isNodeListHovered = false;
    const handleNodeListMouseEnter = () => {
      isNodeListHovered = true;
      clearTimeout(nodeReturnTimer);
      if (cancelNodeScroll) cancelNodeScroll();
    };
    const handleNodeListMouseLeave = () => {
      isNodeListHovered = false;
      const el = nodeListScrollRef.value;
      if (!el || el.scrollTop <= 0) return;
      clearTimeout(nodeReturnTimer);
      nodeReturnTimer = setTimeout(() => {
        if (!isNodeListHovered) {
          cancelNodeScroll = smoothScrollElementToTop(el, updateNodeScrollCue);
        }
      }, 180);
    };

    // Routing Rules
    const categoryTexts = ref({
      direct: `geosite:cn
geoip:cn
geoip:private
cursor.sh
api.cursor.sh
domain:push.apple.com
domain:mail.qq.com
geosite:category-scholar-cn
geosite:category-scholar-!cn
npmmirror.com
jingshizhuxin.com
researchgate.net
rugao.me
yiyuan.co
muyuan.do
iamsen.com
linuxdo.org
yzf.qq.com
albiononline.com
jianzhide.vip
domain:apple.com
domain:icloud.com
domain:microsoft.com
domain:steampowered.com
domain:epicgames.com`,
      proxy: `geosite:google
geosite:openai
geosite:github
geosite:telegram
geosite:twitter
geosite:youtube
geosite:netflix
geosite:disney
geosite:spotify
geoip:hk
geoip:mo
geoip:sg
geoip:jp
domain:anthropic.com
domain:claude.ai
domain:chatgpt.com
domain:oaistatic.com
domain:v2ex.com
domain:notion.so
domain:figma.com`,
      block: `geosite:category-ads-all
geosite:win-spy
domain:adservice.google.com
domain:ads.twitter.com
domain:telemetry.microsoft.com
domain:data.flurry.com`
    });

    const initialCategoryTexts = JSON.parse(JSON.stringify(categoryTexts.value));
    const isCatDirty = cat => categoryTexts.value[cat] !== initialCategoryTexts[cat];
    const hasRoutingChanges = computed(() => ['direct', 'proxy', 'block'].some(c => isCatDirty(c)));
    const getCatLinesCount = cat => categoryTexts.value[cat].split('\n').filter(l => l.trim()).length;

    const savingAllCategories = ref(false);
    const saveAllCategories = () => {
      savingAllCategories.value = true;
      setTimeout(() => {
        Object.assign(initialCategoryTexts, JSON.parse(JSON.stringify(categoryTexts.value)));
        savingAllCategories.value = false;
        showToast('分流规则已保存并重载核心', 'success');
        addSystemLog('ROUTING', '分流三栏规则更新已热重载 (直连/代理/拦截)');
      }, 500);
    };
    const revertAllCategories = () => {
      Object.assign(categoryTexts.value, JSON.parse(JSON.stringify(initialCategoryTexts)));
      showToast('已撤销所有未保存的修改', 'info');
    };

    // Routing Scroll & Easing Auto-Return
    const routingDirectTextareaRef = ref(null);
    const routingProxyTextareaRef = ref(null);
    const routingBlockTextareaRef = ref(null);
    const getRoutingEl = cat => ({ direct: routingDirectTextareaRef, proxy: routingProxyTextareaRef, block: routingBlockTextareaRef })[cat]?.value;

    const routingScrollCues = ref({
      direct: { canUp: false, canDown: false },
      proxy: { canUp: false, canDown: false },
      block: { canUp: false, canDown: false }
    });
    const updateRoutingScrollCue = cat => {
      const el = getRoutingEl(cat);
      if (!el) return;
      const hasOverflow = el.scrollHeight > el.clientHeight + 2;
      routingScrollCues.value[cat] = {
        canUp: hasOverflow && el.scrollTop > 4,
        canDown: hasOverflow && (el.scrollTop + el.clientHeight < el.scrollHeight - 4),
      };
    };
    const updateAllRoutingScrollCues = () => {
      ['direct', 'proxy', 'block'].forEach(updateRoutingScrollCue);
    };
    const scrollRoutingTextarea = (cat, direction) => {
      const el = getRoutingEl(cat);
      if (!el) return;
      el.scrollBy({ top: direction === 'up' ? -140 : 140, behavior: 'smooth' });
    };

    const routingHovered = { direct: false, proxy: false, block: false };
    const routingReturnTimers = { direct: null, proxy: null, block: null };
    const routingCancels = { direct: null, proxy: null, block: null };

    const triggerRoutingReturnToTop = (cat, delay = 180) => {
      const el = getRoutingEl(cat);
      if (!el || el.scrollTop <= 0) return;
      if (routingHovered[cat] || document.activeElement === el) return;
      clearTimeout(routingReturnTimers[cat]);
      routingReturnTimers[cat] = setTimeout(() => {
        if (!routingHovered[cat] && document.activeElement !== el) {
          if (routingCancels[cat]) routingCancels[cat]();
          routingCancels[cat] = smoothScrollElementToTop(el, () => updateRoutingScrollCue(cat));
        }
      }, delay);
    };
    const handleRoutingMouseEnter = cat => {
      routingHovered[cat] = true;
      clearTimeout(routingReturnTimers[cat]);
      if (routingCancels[cat]) routingCancels[cat]();
    };
    const handleRoutingMouseLeave = cat => {
      routingHovered[cat] = false;
      triggerRoutingReturnToTop(cat, 180);
    };
    const handleRoutingBlur = cat => {
      triggerRoutingReturnToTop(cat, 60);
    };

    // Unified Import Modal
    const openImportModal = ref(false);
    const importInput = ref('');
    const importCustomName = ref('');
    const importing = ref(false);
    const detectedImportType = computed(() => {
      const str = importInput.value.trim();
      if (!str) return '';
      if (str.startsWith('http://') || str.startsWith('https://')) return 'subscription';
      if (str.includes('://')) return 'nodes';
      return 'nodes';
    });
    const pasteFromClipboard = async () => {
      try {
        const text = await navigator.clipboard.readText();
        importInput.value = text;
      } catch (_) {
        showToast('无法读取剪贴板，请手动粘贴', 'warning');
      }
    };
    const submitUnifiedImport = () => {
      const val = importInput.value.trim();
      if (!val) {
        showToast('请输入有效的订阅或节点链接', 'warning');
        return;
      }
      importing.value = true;
      setTimeout(() => {
        importing.value = false;
        openImportModal.value = false;
        const name = importCustomName.value.trim() || (detectedImportType.value === 'subscription' ? '新导入订阅' : '新节点');
        if (detectedImportType.value === 'subscription') {
          const newSubId = 'sub-new-' + Date.now();
          subscriptions.value.push({ id: newSubId, name, url: val, updating: false });
          nodes.value.unshift({
            id: 'n-new-' + Date.now(),
            name: `${name} - 节点 01`,
            protocol: 'vless',
            address: '104.***.***.99',
            port: 443,
            security: 'reality',
            network: 'tcp',
            raw_link: val,
            is_active: false,
            last_delay: 45,
            last_speed: '50 MB/s',
            subscription_id: newSubId
          });
          activeSubFilter.value = newSubId;
          showToast(`已成功导入订阅「${name}」并同步节点`, 'success');
        } else {
          nodes.value.unshift({
            id: 'n-new-' + Date.now(),
            name,
            protocol: val.split('://')[0] || 'vless',
            address: '198.***.***.18',
            port: 443,
            security: 'reality',
            network: 'tcp',
            raw_link: val,
            is_active: false,
            last_delay: 38,
            last_speed: '40 MB/s',
            subscription_id: null
          });
          showToast(`已成功导入节点「${name}」`, 'success');
        }
        importInput.value = '';
        importCustomName.value = '';
      }, 600);
    };

    // Port Modal
    const showPortModal = ref(false);
    const portForm = ref({ socks: 20170, http: 20171, routing: 20172 });
    const savingPorts = ref(false);
    const isPortFormValid = computed(() => {
      const { socks, http, routing } = portForm.value;
      return socks > 0 && socks < 65536 && http > 0 && http < 65536 && routing > 0 && routing < 65536;
    });
    const getPortValidationError = field => {
      const val = portForm.value[field];
      if (!val || val < 1 || val > 65535) return '1-65535';
      return '';
    };
    const openPortModal = () => {
      portForm.value = { ...ports.value };
      showPortModal.value = true;
    };
    const submitPortUpdate = () => {
      savingPorts.value = true;
      setTimeout(() => {
        ports.value = { ...portForm.value };
        savingPorts.value = false;
        showPortModal.value = false;
        showToast('代理服务端口已更新', 'success');
      }, 400);
    };
    const resetDefaultPorts = () => {
      portForm.value = { socks: 20170, http: 20171, routing: 20172 };
    };

    // Top Dropdown Menu
    const showCopyMenu = ref(false);
    const copyMenuRef = ref(null);
    const copyText = (txt, msg = '已复制') => {
      try {
        navigator.clipboard.writeText(txt);
        showToast(msg, 'success');
      } catch (_) {
        showToast('复制失败，请手动复制', 'error');
      }
    };
    const copyLink = link => copyText(link, '分享链接已复制至剪贴板');
    const copyHostAddress = (ip, label) => copyText(ip, `${label}已复制`);
    const copyEnvCommand = type => {
      const ip = type.startsWith('bridge') ? bridgeIP.value : '127.0.0.1';
      const p = type.endsWith('routing') ? ports.value.routing : ports.value.http;
      const cmd = `export http_proxy=http://${ip}:${p} https_proxy=http://${ip}:${p} all_proxy=socks5://${ip}:${ports.value.socks}`;
      copyText(cmd, '终端代理环境变量已复制');
      showCopyMenu.value = false;
    };

    // Confirmation Dialog
    const confirmDialog = ref({
      show: false,
      title: '',
      message: '',
      confirmText: '确定',
      confirmType: 'danger',
      checkboxLabel: '',
      checkboxValue: false,
      onConfirm: null,
    });
    const handleConfirmAction = () => {
      if (typeof confirmDialog.value.onConfirm === 'function') confirmDialog.value.onConfirm();
    };
    const handleCancelAction = () => { confirmDialog.value.show = false; };

    // Log Drawer & Simulation
    const drawerExpanded = ref(false);
    const drawerHeight = ref(240);
    const drawerRef = ref(null);
    const logContainer = ref(null);
    const logFilter = ref('');
    const autoScroll = ref(true);
    const logStreamError = ref('');
    const isResizing = ref(false);

    const logs = ref([
      { id: 1, raw: '2026/09/18 15:02:11 [SYSTEM] Xray-core v26.7.28 initialized successfully' },
      { id: 2, raw: '2026/09/18 15:02:12 [SYSTEM] Inbound [http-in-20172] routing proxy started on :20172' },
      { id: 3, raw: '2026/09/18 15:02:12 [SYSTEM] Inbound [socks-in-20170] direct proxy started on :20170' },
      { id: 4, raw: '2026/09/18 15:02:15 127.0.0.1:51712 accepted //api.openai.com:443 [http-in-20172 -> proxy]' },
      { id: 5, raw: '2026/09/18 15:02:18 127.0.0.1:51714 accepted //www.baidu.com:443 [http-in-20172 -> direct]' },
      { id: 6, raw: '2026/09/18 15:02:22 127.0.0.1:51716 accepted //adservice.google.com:443 [http-in-20172 -> block]' },
      { id: 7, raw: '2026/09/18 15:02:25 127.0.0.1:51718 accepted //github.com:443 [http-in-20172 -> proxy]' },
      { id: 8, raw: '2026/09/18 15:02:30 127.0.0.1:51720 accepted //cursor.sh:443 [http-in-20172 -> direct]' },
    ]);
    let logTimer = null;
    const addSystemLog = (tag, msg) => {
      const now = new Date().toLocaleTimeString('zh-CN', { hour12: false });
      logs.value.unshift({ id: Date.now() + Math.random(), raw: `${now} [${tag}] ${msg}` });
    };
    const startMockLogStream = () => {
      const targets = [
        { host: 'api.github.com:443', route: 'proxy' },
        { host: 'www.bilibili.com:443', route: 'direct' },
        { host: 'chatgpt.com:443', route: 'proxy' },
        { host: 'telemetry.microsoft.com:443', route: 'block' },
        { host: 'v2ex.com:443', route: 'proxy' },
        { host: 'cdn.jsdelivr.net:443', route: 'direct' },
        { host: 'cloudflare.com:443', route: 'proxy' },
      ];
      logTimer = setInterval(() => {
        const item = targets[Math.floor(Math.random() * targets.length)];
        const port = Math.floor(Math.random() * 10000) + 50000;
        const now = new Date().toLocaleTimeString('zh-CN', { hour12: false });
        logs.value.unshift({
          id: Date.now() + Math.random(),
          raw: `${now} 127.0.0.1:${port} accepted //${item.host} [http-in-20172 -> ${item.route}]`
        });
        if (logs.value.length > 200) logs.value.pop();
      }, 2400);
    };

    const parseLogLine = raw => {
      if (typeof raw !== 'string') return null;
      const opMatch = raw.match(/^([^\s]+)\s+\[([A-Z]+)\]\s+(.*)$/);
      if (opMatch) return { type: 'op', time: opMatch[1], tag: opMatch[2], msg: opMatch[3] };
      const connMatch = raw.match(/^([^\s]+)\s+([^\s]+)\s+accepted\s+([^\s]+)\s+\[([^\]]+)\]/);
      if (connMatch) {
        const routeRaw = connMatch[4];
        let routeTag = 'proxy';
        if (routeRaw.includes('direct')) routeTag = 'direct';
        else if (routeRaw.includes('block')) routeTag = 'block';
        return { type: 'conn', time: connMatch[1], from: connMatch[2], target: connMatch[3], routeRaw, routeTag };
      }
      return null;
    };
    const parsedFilteredLogs = computed(() => {
      const f = logFilter.value.trim().toLowerCase();
      return logs.value.map((entry, idx) => ({ ...entry, idx, parsed: parseLogLine(entry.raw) })).filter(entry => {
        if (!f) return true;
        if (f === 'system') return entry.parsed?.type === 'op';
        if (f === 'proxy' || f === 'direct' || f === 'block') return entry.parsed?.routeTag === f;
        return entry.raw.toLowerCase().includes(f);
      });
    });
    const latestLogText = computed(() => logs.value[0]?.raw || '');
    const clearLogs = () => { logs.value = []; showToast('日志已清空', 'info'); };

    // Drawer Resize
    const startResize = e => {
      isResizing.value = true;
      const startY = e.clientY;
      const startH = drawerHeight.value;
      const onMove = ev => {
        const dh = startY - ev.clientY;
        drawerHeight.value = Math.max(140, Math.min(window.innerHeight * 0.75, startH + dh));
      };
      const onUp = () => {
        isResizing.value = false;
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    };

    onMounted(() => {
      startMockLogStream();
      nextTick(() => {
        updateSubTabsScrollCue();
        updateNodeScrollCue();
        updateAllRoutingScrollCues();
      });
      window.addEventListener('resize', () => {
        updateSubTabsScrollCue();
        updateNodeScrollCue();
        updateAllRoutingScrollCues();
      });
    });

    onUnmounted(() => {
      clearInterval(logTimer);
    });

    return {
      isDark, toggleTheme, toasts, showToast, service, ports, bridgeIP, statusError,
      currentTab, subscriptions, activeSubFilter, manualNodesCount, currentSelectedSub,
      nodes, displayNodes, revealedNodes, isNodeRevealed, toggleNodeAddressReveal, formatAddress,
      searchQuery, isSearchExpanded, searchInputRef, expandSearch, collapseSearchIfEmpty, clearSearchQuery, handleSearchEsc,
      delaySortOrder, delaySortLabel, cycleDelaySort,
      isMultiSelectMode, selectedNodeIds, isNodeSelected, toggleMultiSelectMode, exitMultiSelectMode, clearSelection, allVisibleSelected, toggleSelectVisible, handleNodeClick, handleNodeDblClick,
      switchingNodeId, fastSwitchNode, getLatencyClass, latencyTitle, speedTitle, testNode, testNodeSpeed,
      batchTesting, batchSpeedTesting, cancelActiveTest, batchTestDelay, batchTestSpeed,
      deleteNode, batchDeleteSelected,
      editingNodeId, inlineRenameValue, inlineRenameInputRef, startInlineRename, saveInlineRename, cancelInlineRename,
      editingSubId, inlineSubRenameValue, inlineSubRenameInputRef, handleSubTabClick, saveInlineSubRename, cancelInlineSubRename, updateSub, deleteSub,
      subTabsContainer, subTabsScrollCue, scrollSubTabs, updateSubTabsScrollCue, handleSubTabsWheel, handleSubTabsMouseLeave, handleSubTabsMouseEnter, scrollToActiveSub,
      nodeListScrollRef, nodeScrollCue, scrollNodeList, handleNodeListScroll, handleNodeListMouseEnter, handleNodeListMouseLeave,
      categoryTexts, isCatDirty, hasRoutingChanges, getCatLinesCount, saveAllCategories, revertAllCategories, savingAllCategories,
      routingDirectTextareaRef, routingProxyTextareaRef, routingBlockTextareaRef, routingScrollCues, updateRoutingScrollCue, updateAllRoutingScrollCues, scrollRoutingTextarea,
      handleRoutingMouseEnter, handleRoutingMouseLeave, handleRoutingBlur,
      openImportModal, importInput, importCustomName, importing, detectedImportType, pasteFromClipboard, submitUnifiedImport,
      showPortModal, portForm, savingPorts, isPortFormValid, getPortValidationError, openPortModal, submitPortUpdate, resetDefaultPorts,
      showCopyMenu, copyMenuRef, copyText, copyLink, copyHostAddress, copyEnvCommand,
      confirmDialog, handleConfirmAction, handleCancelAction,
      drawerExpanded, drawerHeight, drawerRef, logContainer, logFilter, autoScroll, logStreamError, isResizing, logs, parsedFilteredLogs, latestLogText, clearLogs, startResize,
      getNodeSubName, getSubNodeCount
    };
  }
}).mount('#app');
