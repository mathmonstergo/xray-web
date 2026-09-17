const { createApp, ref, computed, onMounted, onUnmounted, nextTick, watch } = Vue

createApp({
  setup() {
    const currentTab = ref('nodes')
    const service = ref({})
    const nodes = ref([])
    const subscriptions = ref([])
    const loadingNodes = ref(true)
    const loadError = ref('')
    const statusError = ref('')
    const searchQuery = ref('')
    const activeSubFilter = ref('all')
    const activeNode = computed(() => nodes.value.find(node => node.is_active) || null)
    const switchingNodeId = ref(null)
    const revealedNodes = ref({})
    const outboundNetwork = ref({ ip: '', country: '', success: false })
    const outboundRevealed = ref(false)
    const ports = computed(() => ({
      socks: service.value.ports?.direct?.[0] || 20170,
      http: service.value.ports?.direct?.[1] || 20171,
      routing: service.value.ports?.routing || 20172,
    }))
    const bridgeIP = computed(() => service.value.bridge_ip || window.location.hostname || '127.0.0.1')
    const showCopyMenu = ref(false)
    const copyMenuRef = ref(null)
    const toasts = ref([])
    const toastTimers = new Set()
    let nextId = 0
    let statusRequestId = 0
    let statusTimer = null

    const showToast = (message, type = 'success', duration = 3000) => {
      const id = ++nextId
      toasts.value = [...toasts.value.slice(-3), { id, message, type }]
      const timer = setTimeout(() => {
        toasts.value = toasts.value.filter(toast => toast.id !== id)
        toastTimers.delete(timer)
      }, duration)
      toastTimers.add(timer)
    }

    const requestJSON = async (url, options = {}) => {
      let response
      try {
        response = await fetch(url, options)
      } catch (err) {
        throw new Error(`网络请求失败：${err.message || '请检查控制台服务连接'}`)
      }
      let data = {}
      try {
        data = await response.json()
      } catch (_) {
        // Non-JSON response payload
      }
      if (!response.ok) {
        const detail = (typeof data.detail === 'string' && data.detail) ||
                       (typeof data.message === 'string' && data.message) ||
                       (typeof data.error === 'string' && data.error) ||
                       `请求失败 (${response.status})`
        throw new Error(detail)
      }
      return data
    }
    const jsonRequest = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

    const fetchNodes = async () => {
      try {
        const data = await requestJSON('/api/nodes')
        const previous = new Map(nodes.value.map(node => [node.id, node]))
        nodes.value = (data.nodes || []).map(node => {
          const prev = previous.get(node.id) || {}
          return {
            ...node,
            testing: prev.testing || false,
            speedTesting: prev.speedTesting || false,
            liveSpeed: prev.speedTesting ? (prev.liveSpeed || '') : '',
            last_delay: prev.testing && prev.last_delay != null ? prev.last_delay : node.last_delay,
            last_speed: prev.speedTesting && prev.last_speed ? prev.last_speed : node.last_speed,
          }
        })
        selectedNodeIds.value = selectedNodeIds.value.filter(id => nodes.value.some(node => node.id === id))
        loadError.value = ''
      } catch (error) {
        loadError.value = error.message
        throw error
      } finally {
        loadingNodes.value = false
      }
    }
    const fetchStatus = async () => {
      const id = ++statusRequestId
      try {
        const data = await requestJSON('/api/status')
        if (id !== statusRequestId) return
        service.value = data.service || {}
        outboundNetwork.value = data.outbound_network || { success: false }
        statusError.value = ''
      } catch (error) {
        if (id === statusRequestId) statusError.value = error.message
      }
    }
    const fetchSubscriptions = async () => {
      try {
        const data = await requestJSON('/api/subscriptions')
        subscriptions.value = data.subscriptions || []
        if (!['all', 'manual'].includes(activeSubFilter.value) && !subscriptions.value.some(sub => sub.id === activeSubFilter.value)) {
          activeSubFilter.value = 'all'
        }
      } catch (error) {
        showToast(`加载订阅失败：${error.message}`, 'error')
      }
    }
    const reloadNodes = () => fetchNodes().catch(error => showToast(error.message, 'error'))

    const maskIPv4 = ip => ip.replace(/^(\d{1,3})\.\d{1,3}\.\d{1,3}\.(\d{1,3})$/, '$1.***.***.$2')
    const maskDomain = domain => {
      const parts = domain.split('.')
      if (parts.length <= 2) return domain
      return `${parts[0]}.*****.${parts.slice(-1)[0]}`
    }
    const formatAddress = (address, port, revealed = false) => {
      if (!address) return '—'
      let raw = String(address).trim().replace(/^[a-z]+:\/\//i, '').replace(/^\[|\]$/g, '').split('/')[0]
      if (raw.includes(':') && !raw.includes('::') && raw.split(':').length === 2) raw = raw.split(':')[0]
      const isIpv6 = raw.includes(':')
      const isIpv4 = /^(\d{1,3}\.){3}\d{1,3}$/.test(raw)
      let value = raw
      if (!revealed) {
        if (isIpv4) {
          value = maskIPv4(raw)
        } else if (isIpv6) {
          value = `${raw.split(':')[0] || '0'}:****:${raw.split(':').at(-1) || '0'}`
        } else if (raw.includes('.')) {
          value = maskDomain(raw)
        }
      }
      return port ? `${isIpv6 ? `[${value}]` : value}:${port}` : value
    }
    const getNodeFeatureTag = node => {
      if (!node) return null
      const enc = (node.encryption || '').toLowerCase()
      if (enc.includes('mlkem')) {
        return { label: 'ML-KEM', class: 'text-cyan-300 bg-cyan-500/10 border-cyan-500/25' }
      }
      let flow = ''
      try {
        flow = node.outbound?.settings?.vnext?.[0]?.users?.[0]?.flow || ''
      } catch (_) {}
      const hasVision = flow.toLowerCase().includes('vision') || (node.tags || []).some(t => String(t).toLowerCase().includes('vision'))
      if (hasVision) {
        return { label: 'Vision', class: 'text-amber-300 bg-amber-500/10 border-amber-500/25' }
      }
      const net = (node.network || '').toLowerCase()
      if (net && net !== 'tcp') {
        return { label: net.toUpperCase(), class: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/25' }
      }
      if (enc && !['none', 'auto', ''].includes(enc)) {
        if (enc.includes('gcm') || enc.includes('aes-256')) return { label: 'AES-GCM', class: 'text-blue-300 bg-blue-500/10 border-blue-500/25' }
        if (enc.includes('chacha')) return { label: 'ChaCha20', class: 'text-indigo-300 bg-indigo-500/10 border-indigo-500/25' }
        return { label: enc.toUpperCase(), class: 'text-gray-300 bg-gray-800 border-gray-700' }
      }
      return null
    }
    const isNodeRevealed = id => !!revealedNodes.value[id]
    const toggleNodeAddressReveal = id => { if (id) revealedNodes.value[id] = !revealedNodes.value[id] }

    const copyText = async (text, message = '已复制') => {
      if (!text) {
        showToast('内容为空，无法复制', 'warning')
        return false
      }
      let copied = false
      // 1. 尝试现代 Clipboard API（仅在安全上下文 HTTPS / Localhost 可用）
      try {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(text)
          copied = true
        }
      } catch (_) {
        // Clipboard API 被拒或非安全源，自动降级
      }
      // 2. 降级方案：动态隐藏 textarea 执行 execCommand
      if (!copied) {
        try {
          const previousFocus = document.activeElement
          const input = document.createElement('textarea')
          input.value = text
          input.setAttribute('readonly', '')
          input.style.cssText = 'position:fixed;opacity:0;left:-9999px;top:-9999px;pointer-events:none'
          document.body.appendChild(input)
          input.select()
          input.setSelectionRange(0, text.length)
          copied = document.execCommand('copy')
          input.remove()
          if (previousFocus && typeof previousFocus.focus === 'function') {
            previousFocus.focus()
          }
        } catch (_) {
          copied = false
        }
      }

      if (copied) {
        showToast(message, 'success')
        return true
      } else {
        showToast('复制失败，请检查浏览器剪贴板权限或手动复制', 'error')
        return false
      }
    }
    const copyLink = link => {
      if (!link) {
        showToast('此节点暂无可复制的分享链接', 'warning')
        return false
      }
      return copyText(link, '节点链接已复制')
    }
    const copyEnvCommand = async type => {
      const host = type.startsWith('bridge') ? bridgeIP.value : '127.0.0.1'
      const address = host.includes(':') ? `[${host.replace(/^\[|\]$/g, '')}]` : host
      const routing = type.endsWith('routing')
      const http = `http://${address}:${routing ? ports.value.routing : ports.value.http}`
      const all = routing ? http : `socks5://${address}:${ports.value.socks}`
      const ok = await copyText(`export http_proxy=${http} https_proxy=${http} all_proxy=${all}`, `已复制${routing ? '规则分流' : '直通代理'}环境变量`)
      if (ok) showCopyMenu.value = false
    }
    const copyHostAddress = async (host, label = '地址') => {
      const value = (typeof host === 'object' && host !== null && 'value' in host) ? host.value : host
      if (!value) return false
      const ok = await copyText(value, `已复制${label}: ${value}`)
      if (ok) showCopyMenu.value = false
      return ok
    }

    const isMultiSelectMode = ref(false)
    const selectedNodeIds = ref([])
    const isNodeSelected = id => selectedNodeIds.value.includes(id)
    const clearSelection = () => { selectedNodeIds.value = [] }
    const toggleMultiSelectMode = () => { isMultiSelectMode.value = !isMultiSelectMode.value; clearSelection() }
    const exitMultiSelectMode = () => { isMultiSelectMode.value = false; clearSelection() }
    const handleNodeClick = node => {
      if (!isMultiSelectMode.value || editingNodeId.value === node.id) return
      selectedNodeIds.value = isNodeSelected(node.id)
        ? selectedNodeIds.value.filter(id => id !== node.id)
        : [...selectedNodeIds.value, node.id]
    }
    const handleNodeDblClick = node => {
      if (!isMultiSelectMode.value && editingNodeId.value !== node.id) fastSwitchNode(node)
    }

    const manualNodesCount = computed(() => nodes.value.filter(node => !node.subscription_id).length)
    const subNames = computed(() => new Map(subscriptions.value.map(sub => [sub.id, sub.name])))
    const getNodeSubName = id => subNames.value.get(id) || ''
    const getSubNodeCount = id => nodes.value.filter(node => node.subscription_id === id).length
    const currentSelectedSub = computed(() => subscriptions.value.find(sub => sub.id === activeSubFilter.value) || null)
    const delaySortOrder = ref('none')
    const delaySortLabel = computed(() => ({ none: '按延迟排序', asc: '延迟从低到高', desc: '延迟从高到低' })[delaySortOrder.value])
    const cycleDelaySort = () => { delaySortOrder.value = ({ none: 'asc', asc: 'desc', desc: 'none' })[delaySortOrder.value] }
    const displayNodes = computed(() => {
      const query = searchQuery.value.trim().toLowerCase()
      let result = nodes.value.filter(node => {
        const matchesSub = activeSubFilter.value === 'all' || (activeSubFilter.value === 'manual' ? !node.subscription_id : node.subscription_id === activeSubFilter.value)
        return matchesSub && (!query || [node.name, node.address].some(value => (value || '').toLowerCase().includes(query)))
      })
      if (delaySortOrder.value !== 'none') {
        result.sort((a, b) => {
          const aValid = a.last_delay != null && a.last_delay >= 0
          const bValid = b.last_delay != null && b.last_delay >= 0
          if (aValid !== bValid) return aValid ? -1 : 1
          if (!aValid) return 0
          return delaySortOrder.value === 'asc' ? a.last_delay - b.last_delay : b.last_delay - a.last_delay
        })
      }
      return result
    })
    const clearFilters = () => { searchQuery.value = ''; activeSubFilter.value = 'all' }
    const allVisibleSelected = computed(() => displayNodes.value.length > 0 && displayNodes.value.every(node => isNodeSelected(node.id)))
    const toggleSelectVisible = () => {
      const visibleIds = new Set(displayNodes.value.map(node => node.id))
      selectedNodeIds.value = allVisibleSelected.value
        ? selectedNodeIds.value.filter(id => !visibleIds.has(id))
        : [...new Set([...selectedNodeIds.value, ...visibleIds])]
    }

    const batchTesting = ref(false)
    const batchSpeedTesting = ref(false)
    const testingAll = computed(() => batchTesting.value)
    const getLatencyClass = delay => delay < 220 ? 'text-emerald-400' : delay < 400 ? 'text-lime-400' : delay < 700 ? 'text-amber-400' : 'text-rose-400'
    const latencyTitle = delay => delay == null ? '点击测试代理实际延迟（Real Ping）' : delay < 0 ? '代理通路超时；点击重测' : `代理延迟 ${delay}ms · <220ms 良好 / <400ms 一般 / <700ms 较高 / ≥700ms 高延迟；点击重测`
    const speedTitle = (speed, liveSpeed) => liveSpeed ? `测速中 ${liveSpeed}` : !speed ? '点击测试真实下行峰值速度' : speed === '超时' ? '测速超时；点击重测' : `下行峰值 ${speed}；点击重测`

    const applyTestEvent = (event, { speed = false } = {}) => {
      const node = nodes.value.find(item => item.id === event.node_id)
      if (!node) return
      if (typeof event.latency === 'number' && event.latency >= 0) node.last_delay = event.latency
      if (speed) {
        const live = event.peak || event.speed
        if (live && live !== '超时' && live !== '测速中') node.liveSpeed = live
        if (event.done) {
          if (event.cancelled) {
            node.liveSpeed = ''
            node.speedTesting = false
            return
          }
          node.last_speed = (event.success && event.speed && event.speed !== '超时') ? event.speed : '超时'
          node.liveSpeed = ''
          node.speedTesting = false
        }
      } else if (event.done) {
        if (!event.cancelled) node.last_delay = (event.success && event.latency >= 0) ? event.latency : -1
        node.testing = false
      }
    }

    const consumeTestStream = async (url, body, { speed = false, onEvent, signal, expectedIds } = {}) => {
      const expected = new Set(expectedIds || body?.node_ids || [])
      const finish = results => {
        if (!Array.isArray(results)) throw new Error('测试结果格式无效')
        const ids = new Set(results.map(result => result.node_id))
        if (ids.size !== results.length || (expected.size && (ids.size !== expected.size || [...ids].some(id => !expected.has(id))))) {
          throw new Error('测试结果不完整，请重试未完成的节点')
        }
        if (results.some(result => !result.cancelled && typeof result.success !== 'boolean')) {
          throw new Error('测试结果缺少完成状态')
        }
        results.forEach(result => applyTestEvent({ ...result, done: true }, { speed }))
        return results
      }
      const response = await fetch(url, { ...jsonRequest('POST', body), signal })
      if (!response.ok) {
        let detail = '请求失败 (' + response.status + ')'
        try {
          const data = await response.json()
          detail = data.detail || data.message || data.error || detail
        } catch (_) {}
        throw new Error(detail)
      }
      if (!(response.headers.get('content-type') || '').includes('text/event-stream') || !response.body) {
        const data = await response.json()
        return finish(data.results || [data])
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      const results = new Map()
      try {
        while (true) {
          const { value, done } = await reader.read()
          buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
          const chunks = buffer.replace(/\r\n/g, '\n').split('\n\n')
          buffer = chunks.pop() || ''
          for (const chunk of chunks) {
            const line = chunk.split('\n').find(item => item.startsWith('data: '))
            if (!line) continue
            let event
            try { event = JSON.parse(line.slice(6)) } catch (_) { throw new Error('测试进度数据损坏') }
            if (event.type === 'error') throw new Error(event.message || '测试失败')
            if (event.type === 'complete') return finish(event.results || [...results.values()])
            if (expected.size && event.node_id && !expected.has(event.node_id)) continue
            applyTestEvent(event, { speed })
            if (typeof onEvent === 'function') onEvent(event)
            if (event.type === 'result') results.set(event.node_id, event)
          }
          if (done) throw new Error('测试连接提前结束，结果不完整')
        }
      } finally {
        try { await reader.cancel?.() } catch (_) {}
        reader.releaseLock?.()
      }
    }

    const fastSwitchNode = async node => {
      if (node.is_active || switchingNodeId.value) return
      switchingNodeId.value = node.id
      addSystemLog('SYSTEM', `正在切换至「${node.name}」…`)
      try {
        const data = await requestJSON(`/api/nodes/${node.id}/switch`, { method: 'POST' })
        if (!data.success) throw new Error(data.message || '切换失败')
        await fetchNodes()
        showToast(data.message || `已切换至「${node.name}」`, 'success')
        addSystemLog('SYSTEM', data.message || `已切换至「${node.name}」`)
        fetchStatus()
      } catch (error) {
        showToast(`切换失败：${error.message}`, 'error')
        addSystemLog('SYSTEM', `切换失败：${error.message}`)
      } finally {
        switchingNodeId.value = null
      }
    }

    const activeTestAborts = new Set()
    const cancelActiveTest = ({ silent = false } = {}) => {
      if (!activeTestAborts.size) return false
      for (const controller of activeTestAborts) controller.abort()
      activeTestAborts.clear()
      if (!silent) {
        showToast('已取消测试', 'warning')
        addSystemLog('SYSTEM', '已取消所有正在进行的延迟/速度测试')
      }
      return true
    }

    const formatDelayDetail = result => {
      if (!result || result.latency == null || result.latency < 0) return '超时'
      const tcp = Number(result.tcp_latency)
      const total = Number(result.latency)
      if (tcp > 0 && total >= 0) {
        const overhead = Math.max(0, total - tcp)
        const expectedHandshake = tcp * 2
        const handshake = Math.min(overhead, expectedHandshake)
        const landing = Math.max(0, overhead - handshake)
        const hsTag = handshake >= expectedHandshake ? '[≈2×RTT]' : ''
        return `真延迟 ${total}ms (直连RTT: ${tcp}ms | 隧道握手: ~${handshake}ms${hsTag} | 落地与回传: ~${landing}ms)`
      }
      return `真延迟 ${total}ms (直连TCP: 未通/超时，经代理通道直达)`
    }

    const testNode = async node => {
      if (node.testing) return
      node.testing = true
      addSystemLog('SYSTEM', `开始测试「${node.name}」代理延迟…`)
      const controller = new AbortController()
      activeTestAborts.add(controller)
      try {
        const results = await consumeTestStream(`/api/nodes/${node.id}/test?stream=true`, {}, { speed: false, signal: controller.signal, expectedIds: [node.id] })
        const result = results.find(item => item.node_id === node.id) || results[results.length - 1] || {}
        if (result.cancelled) {
          showToast(`「${node.name}」延迟测试已取消`, 'warning')
          return
        }
        if (result.success && result.latency >= 0) {
          showToast(`「${node.name}」延迟: ${result.latency}ms`, 'success')
          addSystemLog('SYSTEM', `「${node.name}」${formatDelayDetail(result)}`)
        } else {
          const reason = result.message || '代理通路超时'
          const tcpNote = result.tcp_latency && result.tcp_latency > 0 ? ` (本地直连TCP: ${result.tcp_latency}ms)` : ''
          showToast(`「${node.name}」延迟测试失败：${reason}`, 'error')
          addSystemLog('SYSTEM', `「${node.name}」延迟测试失败：${reason}${tcpNote}`)
        }
      } catch (error) {
        if (error.name === 'AbortError') return
        const current = nodes.value.find(item => item.id === node.id)
        if (current) current.last_delay = -1
        showToast(`「${node.name}」测试异常：${error.message}`, 'error')
        addSystemLog('SYSTEM', `「${node.name}」测试异常：${error.message}`)
      } finally {
        activeTestAborts.delete(controller)
        const current = nodes.value.find(item => item.id === node.id)
        if (current) current.testing = false
      }
    }

    const testNodeSpeed = async node => {
      if (node.speedTesting) return
      node.speedTesting = true
      node.liveSpeed = ''
      addSystemLog('SYSTEM', `开始测试「${node.name}」真实下行峰值…`)
      const controller = new AbortController()
      activeTestAborts.add(controller)
      try {
        const results = await consumeTestStream('/api/nodes/speed-test-batch?stream=true', { node_ids: [node.id] }, { speed: true, signal: controller.signal })
        const result = results.find(item => item.node_id === node.id) || results[results.length - 1] || {}
        if (result.cancelled) {
          showToast(`「${node.name}」速度测试已取消`, 'warning')
          return
        }
        const isSuccess = Boolean(result.success && result.speed && result.speed !== '超时')
        if (isSuccess) {
          showToast(`「${node.name}」下载峰值: ${result.speed}`, 'success')
          const detail = result.latency >= 0 ? ` | ${formatDelayDetail(result)}` : ''
          addSystemLog('SYSTEM', `「${node.name}」速度测试完成: 峰值 ${result.speed}${detail}`)
        } else {
          const reason = result.message || '测速失败'
          const detail = result.latency >= 0 ? ` [${formatDelayDetail(result)}]` : ''
          showToast(`「${node.name}」速度测试失败：${reason}`, 'error')
          addSystemLog('SYSTEM', `「${node.name}」${reason}${detail}`)
        }
      } catch (error) {
        if (error.name === 'AbortError') return
        const current = nodes.value.find(item => item.id === node.id)
        if (current) {
          current.last_speed = '超时'
          current.liveSpeed = ''
        }
        showToast(`「${node.name}」速度测试异常：${error.message}`, 'error')
        addSystemLog('SYSTEM', `「${node.name}」速度测试异常：${error.message}`)
      } finally {
        activeTestAborts.delete(controller)
        const current = nodes.value.find(item => item.id === node.id)
        if (current) {
          current.speedTesting = false
          current.liveSpeed = ''
        }
      }
    }

    const runBatchTest = async (ids, speed = false) => {
      const busy = speed ? batchSpeedTesting : batchTesting
      const flag = speed ? 'speedTesting' : 'testing'
      if (busy.value) return
      const targets = nodes.value.filter(node => ids.includes(node.id) && !node[flag])
      if (!targets.length) return
      busy.value = true
      targets.forEach(node => {
        node[flag] = true
        if (speed) node.liveSpeed = ''
      })
      const label = speed ? '下载速度' : '延迟'
      addSystemLog('SYSTEM', `开始批量测试 ${targets.length} 个节点的${label}…`)
      const controller = new AbortController()
      activeTestAborts.add(controller)
      try {
        const endpoint = speed ? '/api/nodes/speed-test-batch?stream=true' : '/api/nodes/test-batch?stream=true'
        const results = await consumeTestStream(endpoint, { node_ids: targets.map(node => node.id) }, {
          speed,
          signal: controller.signal,
          onEvent: event => {
            if (event.type === 'result' && !event.cancelled) {
              const targetNode = targets.find(item => item.id === event.node_id)
              const name = targetNode?.name || event.node_id
              if (speed) {
                if (event.success && event.speed && event.speed !== '超时') {
                  const detail = event.latency >= 0 ? ` | ${formatDelayDetail(event)}` : ''
                  addSystemLog('SYSTEM', `「${name}」测速完成: 峰值 ${event.speed}${detail}`)
                } else {
                  addSystemLog('SYSTEM', `「${name}」测速失败: ${event.message || '超时'}`)
                }
              } else {
                if (event.success && event.latency >= 0) {
                  addSystemLog('SYSTEM', `「${name}」${formatDelayDetail(event)}`)
                } else {
                  addSystemLog('SYSTEM', `「${name}」延迟测试失败: ${event.message || '超时'}`)
                }
              }
            }
          },
        })
        const unfinished = results.filter(r => r.cancelled).length
        const failed = results.filter(r => {
          if (r.cancelled) return false
          if (speed) return !r.success || !r.speed || r.speed === '超时'
          return !r.success || r.latency == null || r.latency < 0
        }).length
        const succeeded = results.length - failed - unfinished

        if (unfinished && succeeded === 0 && failed === 0) {
          showToast(`已取消${label}测试`, 'warning')
          addSystemLog('SYSTEM', `已取消${label}测试`)
        } else if (succeeded === 0) {
          const msg = `全部 ${targets.length} 个节点${label}测试失败（无法连接）`
          showToast(msg, 'error')
          addSystemLog('SYSTEM', msg)
        } else if (failed > 0 || unfinished > 0) {
          const msg = `${label}测试完成：${succeeded} 项可用` + (failed ? `，${failed} 项失败` : '') + (unfinished ? `，${unfinished} 项取消` : '')
          showToast(msg, 'warning')
          addSystemLog('SYSTEM', msg)
        } else {
          const msg = `全部 ${targets.length} 个节点${label}测试完成`
          showToast(msg, 'success')
          addSystemLog('SYSTEM', msg)
        }
        clearSelection()
      } catch (error) {
        if (error.name !== 'AbortError') {
          showToast(`批量${label}测试失败：${error.message}`, 'error')
          addSystemLog('SYSTEM', `批量${label}测试异常：${error.message}`)
        }
      } finally {
        activeTestAborts.delete(controller)
        busy.value = false
        for (const target of targets) {
          const node = nodes.value.find(item => item.id === target.id)
          if (node) {
            node[flag] = false
            if (speed) node.liveSpeed = ''
          }
        }
      }
    }
    const selectedOrVisible = () => selectedNodeIds.value.length ? [...selectedNodeIds.value] : displayNodes.value.map(node => node.id)
    const batchTestDelay = () => runBatchTest(selectedOrVisible())
    const batchTestSpeed = () => runBatchTest(selectedOrVisible(), true)
    const testAllNodes = () => runBatchTest(nodes.value.map(node => node.id))

    const editingNodeId = ref(null)
    const inlineRenameValue = ref('')
    const inlineRenameInputRef = ref(null)
    const startInlineRename = node => {
      if (isMultiSelectMode.value) return handleNodeClick(node)
      editingNodeId.value = node.id
      inlineRenameValue.value = node.name || ''
      nextTick(() => {
        const input = Array.isArray(inlineRenameInputRef.value) ? inlineRenameInputRef.value[0] : inlineRenameInputRef.value
        input?.focus()
        input?.select()
      })
    }
    const startInlineRenameForActive = () => {
      if (!activeNode.value) return
      currentTab.value = 'nodes'
      clearFilters()
      exitMultiSelectMode()
      startInlineRename(activeNode.value)
    }
    const locateActiveNode = async () => {
      if (!activeNode.value) return
      currentTab.value = 'nodes'
      if (activeSubFilter.value !== 'all') {
        const subId = activeNode.value.subscription_id
        if ((activeSubFilter.value === 'manual' && subId) || (activeSubFilter.value !== 'manual' && subId !== activeSubFilter.value)) {
          activeSubFilter.value = 'all'
        }
      }
      if (searchQuery.value) {
        const q = searchQuery.value.trim().toLowerCase()
        if (!activeNode.value.name?.toLowerCase().includes(q) && !activeNode.value.address?.toLowerCase().includes(q)) {
          searchQuery.value = ''
        }
      }
      await nextTick()
      const row = document.getElementById(`node-row-${activeNode.value.id}`)
      if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' })
        row.classList.remove('node-locate-pulse')
        void row.offsetWidth
        row.classList.add('node-locate-pulse')
        setTimeout(() => row.classList.remove('node-locate-pulse'), 1500)
      }
    }
    const cancelInlineRename = () => { editingNodeId.value = null }
    const saveInlineRename = async node => {
      if (editingNodeId.value !== node.id) return
      const name = inlineRenameValue.value.trim()
      editingNodeId.value = null
      if (!name) {
        showToast('节点名称不能为空', 'warning')
        return
      }
      if (name === node.name) return
      const oldName = node.name
      try {
        await requestJSON(`/api/nodes/${node.id}`, jsonRequest('PUT', { name }))
        const current = nodes.value.find(item => item.id === node.id)
        if (current) current.name = name
        showToast('节点备注已更新', 'success')
        addSystemLog('SYSTEM', `「${oldName}」已更名为「${name}」`)
      } catch (error) {
        showToast(`更名失败：${error.message}`, 'error')
      }
    }

    const editingSubId = ref(null)
    const inlineSubRenameValue = ref('')
    const inlineSubRenameInputRef = ref(null)
    const startInlineSubRename = sub => {
      editingSubId.value = sub.id
      inlineSubRenameValue.value = sub.name || ''
      nextTick(() => {
        const input = Array.isArray(inlineSubRenameInputRef.value) ? inlineSubRenameInputRef.value[0] : inlineSubRenameInputRef.value
        input?.focus()
        input?.select()
      })
    }
    const cancelInlineSubRename = () => {
      editingSubId.value = null
    }
    const saveInlineSubRename = async sub => {
      if (editingSubId.value !== sub.id) return
      const newName = inlineSubRenameValue.value.trim()
      editingSubId.value = null
      if (!newName) {
        showToast('订阅名称不能为空', 'warning')
        return
      }
      if (newName === sub.name) return
      const oldName = sub.name
      try {
        await requestJSON(`/api/subscriptions/${sub.id}`, jsonRequest('PUT', { name: newName }))
        const current = subscriptions.value.find(s => s.id === sub.id)
        if (current) current.name = newName
        showToast('订阅名称已更新', 'success')
        addSystemLog('SYSTEM', `订阅「${oldName}」已更名为「${newName}」`)
      } catch (error) {
        showToast(`修改订阅名称失败：${error.message}`, 'error')
      }
    }
    const handleSubTabClick = sub => {
      if (activeSubFilter.value === sub.id) {
        startInlineSubRename(sub)
      } else {
        activeSubFilter.value = sub.id
      }
    }

    const subTabsContainer = ref(null)
    let targetScrollLeft = null
    let wheelAnimFrame = null
    let autoScrollAnimFrame = null
    let autoReturnTimer = null
    let isAutoScrolling = false

    const cancelAutoScroll = () => {
      isAutoScrolling = false
      if (autoScrollAnimFrame) {
        cancelAnimationFrame(autoScrollAnimFrame)
        autoScrollAnimFrame = null
      }
    }

    const cancelWheelAnim = () => {
      if (wheelAnimFrame) {
        cancelAnimationFrame(wheelAnimFrame)
        wheelAnimFrame = null
      }
      targetScrollLeft = null
    }

    // 丝滑滚轮阻尼动效：上下拨动滚轮累积平滑位移，微动量阻尼减速
    const handleSubTabsWheel = event => {
      const el = subTabsContainer.value
      if (!el) return
      if (el.scrollWidth <= el.clientWidth) return

      if (autoReturnTimer) {
        clearTimeout(autoReturnTimer)
        autoReturnTimer = null
      }
      cancelAutoScroll()

      const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
      if (delta === 0) return

      if (typeof event.preventDefault === 'function') event.preventDefault()

      const maxScroll = Math.max(0, el.scrollWidth - el.clientWidth)
      if (maxScroll <= 0) return

      // 触碰两端边界时严格锁定，严禁任何反向回弹或微扰闪回
      if (delta > 0 && el.scrollLeft >= maxScroll - 1) {
        cancelWheelAnim()
        el.scrollLeft = maxScroll
        return
      }
      if (delta < 0 && el.scrollLeft <= 1) {
        cancelWheelAnim()
        el.scrollLeft = 0
        return
      }

      if (targetScrollLeft === null || Math.abs(targetScrollLeft - el.scrollLeft) > 300) {
        targetScrollLeft = el.scrollLeft
      }
      targetScrollLeft = Math.max(0, Math.min(maxScroll, targetScrollLeft + delta * 1.15))

      if (wheelAnimFrame) cancelAnimationFrame(wheelAnimFrame)
      const stepWheel = () => {
        const diff = targetScrollLeft - el.scrollLeft
        if (Math.abs(diff) > 0.5) {
          el.scrollLeft += diff * 0.22
          wheelAnimFrame = requestAnimationFrame(stepWheel)
        } else {
          el.scrollLeft = targetScrollLeft
          wheelAnimFrame = null
          targetScrollLeft = null
        }
      }
      wheelAnimFrame = requestAnimationFrame(stepWheel)
    }

    // 基础平滑滚动插值执行器 (easeInOutCubic: 平缓起步->逐渐加速->柔和吸附到位)
    const scrollToX = targetX => {
      const el = subTabsContainer.value
      if (!el) return
      const startX = el.scrollLeft
      const distance = targetX - startX
      if (Math.abs(distance) < 2) return

      cancelAutoScroll()
      cancelWheelAnim()

      const duration = Math.min(600, Math.max(280, Math.abs(distance) * 0.7))
      const startTime = performance.now()
      isAutoScrolling = true

      const easeInOutCubic = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

      const step = now => {
        if (!isAutoScrolling) return
        const elapsed = now - startTime
        const progress = Math.min(1, elapsed / duration)
        el.scrollLeft = startX + distance * easeInOutCubic(progress)
        if (progress < 1) {
          autoScrollAnimFrame = requestAnimationFrame(step)
        } else {
          el.scrollLeft = targetX
          isAutoScrolling = false
          autoScrollAnimFrame = null
        }
      }
      autoScrollAnimFrame = requestAnimationFrame(step)
    }

    // 精确平滑滚动至【当前页面选中的标签】(首位对齐；若选中的是冻结项则滚回 0)
    const scrollToActiveSub = (explicitSubId = null) => {
      const el = subTabsContainer.value
      if (!el || el.scrollWidth <= el.clientWidth) return
      const activeId = explicitSubId || activeSubFilter.value || 'all'

      // 若选中项是左侧已冻结固定的【全部节点】或【节点导入】，订阅滚动区平滑归位至最左端 0
      if (activeId === 'all' || activeId === 'manual') {
        scrollToX(0)
        return
      }

      // 否则将选中的订阅标签对齐至独立滚动区的最左侧首位
      const targetBtn = el.querySelector(`[data-sub-id="${activeId}"]`)
      if (!targetBtn) {
        scrollToX(0)
        return
      }

      const btnLeft = (typeof targetBtn.getBoundingClientRect === 'function' && typeof el.getBoundingClientRect === 'function')
        ? (targetBtn.getBoundingClientRect().left - el.getBoundingClientRect().left) + el.scrollLeft
        : (targetBtn.offsetLeft || 0)
      const maxScroll = Math.max(0, el.scrollWidth - el.clientWidth)
      const targetX = Math.max(0, Math.min(maxScroll, btnLeft))
      scrollToX(targetX)
    }

    const scrollToTab = targetId => {
      scrollToActiveSub(targetId)
    }

    const scrollToRunningNodeSub = () => {
      scrollToActiveSub()
    }

    const handleSubTabsMouseLeave = () => {
      if (autoReturnTimer) clearTimeout(autoReturnTimer)
      autoReturnTimer = setTimeout(() => {
        scrollToActiveSub()
      }, 600)
    }

    const handleSubTabsMouseEnter = () => {
      if (autoReturnTimer) {
        clearTimeout(autoReturnTimer)
        autoReturnTimer = null
      }
      cancelAutoScroll()
    }

    const confirmDialog = ref({
      show: false,
      title: '确认删除',
      message: '',
      detail: '',
      checkboxLabel: '',
      checkboxValue: false,
      confirmText: '确认删除',
      confirmType: 'danger',
      onConfirm: null,
      onCancel: null,
    })

    const openConfirm = ({ title, message, detail, confirmText, confirmType, checkboxLabel, onConfirm, onCancel }) => {
      confirmDialog.value = {
        show: true,
        title: title || '确认操作',
        message: message || '确定继续此操作吗？',
        detail: detail || '',
        checkboxLabel: checkboxLabel || '',
        checkboxValue: false,
        confirmText: confirmText || '确认',
        confirmType: confirmType || 'danger',
        onConfirm,
        onCancel,
      }
    }

    const handleConfirmAction = () => {
      const cb = confirmDialog.value.onConfirm
      const checkVal = confirmDialog.value.checkboxValue
      confirmDialog.value.show = false
      if (cb) cb(checkVal)
    }

    const handleCancelAction = () => {
      const cb = confirmDialog.value.onCancel
      confirmDialog.value.show = false
      if (cb) cb()
    }

    const deleteNode = async node => {
      if (node.is_active) {
        showToast('正在运行的节点受保护，不可删除', 'warning')
        return
      }
      openConfirm({
        title: '删除节点',
        message: `确定要删除「${node.name}」吗？`,
        detail: '删除后该节点配置将被彻底移除，不可恢复。',
        confirmText: '确认删除',
        confirmType: 'danger',
        onConfirm: async () => {
          try {
            await requestJSON(`/api/nodes/${node.id}`, { method: 'DELETE' })
            await fetchNodes()
            showToast('节点已删除', 'success')
            addSystemLog('SYSTEM', `已删除「${node.name}」`)
          } catch (error) {
            showToast(`删除失败：${error.message}`, 'error')
          }
        }
      })
    }

    const batchDeleteSelected = async () => {
      if (!selectedNodeIds.value.length) return
      const ids = [...selectedNodeIds.value]
      const count = ids.length
      openConfirm({
        title: '批量删除节点',
        message: `确定要删除选中的 ${count} 个节点吗？`,
        detail: '正在运行的活跃节点会自动受到保护并保留。',
        confirmText: `删除所选 (${count})`,
        confirmType: 'danger',
        onConfirm: async () => {
          try {
            const data = await requestJSON('/api/nodes/batch-delete', jsonRequest('POST', { node_ids: ids }))
            await fetchNodes()
            clearSelection()
            showToast(data.message || '已删除所选节点', 'success')
            addSystemLog('SYSTEM', data.message || '已删除所选节点')
          } catch (error) {
            showToast(`批量删除失败：${error.message}`, 'error')
          }
        }
      })
    }

    const openImportModal = ref(false)
    const importInput = ref('')
    const importCustomName = ref('')
    const importing = ref(false)
    const importTextarea = ref(null)
    let importPreviousFocus = null

    const detectedImportType = computed(() => {
      const text = importInput.value.trim()
      if (!text) return null
      if (/^https?:\/\/\S+$/.test(text)) return 'subscription'
      if (/(?:vless|vmess|trojan|ss):\/\//.test(text)) return 'nodes'
      try { if (/(?:vless|vmess|trojan|ss):\/\//.test(atob(text.replace(/\s/g, '').replace(/-/g, '+').replace(/_/g, '/')))) return 'nodes' } catch (_) {}
      return null
    })

    const pasteFromClipboard = async () => {
      try {
        if (!navigator.clipboard?.readText) throw new Error('剪贴板 API 不可用')
        const text = await navigator.clipboard.readText()
        if (!text.trim()) return showToast('剪贴板内容为空', 'info')
        importInput.value = text
      } catch (_) {
        showToast('无法读取剪贴板，请使用 Ctrl+V、⌘V 或长按粘贴', 'info', 4500)
      } finally {
        importTextarea.value?.focus()
      }
    }

    const submitUnifiedImport = async () => {
      if (importing.value) return
      const text = importInput.value.trim()
      if (!text) return showToast('请粘贴订阅或节点链接', 'warning')
      importing.value = true
      try {
        const data = await requestJSON('/api/nodes/import', jsonRequest('POST', { text, subscription_name: importCustomName.value.trim() || undefined }))
        await Promise.all([fetchNodes(), fetchSubscriptions()])
        openImportModal.value = false
        importInput.value = ''
        importCustomName.value = ''
        if (data.target_tab) {
          activeSubFilter.value = data.target_tab
          await nextTick()
          scrollToActiveSub(data.target_tab)
        } else {
          clearFilters()
        }
        showToast(data.message || '导入成功', 'success')
        addSystemLog('SYSTEM', data.message || '导入成功')
      } catch (error) {
        showToast(`导入失败：${error.message}`, 'error')
        addSystemLog('SYSTEM', `导入失败：${error.message}`)
      } finally {
        importing.value = false
      }
    }

    const updateSub = async sub => {
      if (!sub || sub.updating) return
      sub.updating = true
      try {
        const data = await requestJSON(`/api/subscriptions/${sub.id}/update`, { method: 'POST' })
        await Promise.all([fetchNodes(), fetchSubscriptions()])
        showToast(data.message || `订阅「${sub.name}」已刷新`, 'success')
        addSystemLog('SYSTEM', data.message || `订阅「${sub.name}」已刷新`)
      } catch (error) {
        showToast(`更新订阅失败：${error.message}`, 'error')
        addSystemLog('SYSTEM', `更新订阅失败：${error.message}`)
      } finally {
        sub.updating = false
      }
    }

    const deleteSub = async sub => {
      if (!sub) return
      const count = getSubNodeCount(sub.id)
      openConfirm({
        title: '删除订阅源',
        message: `确定删除订阅「${sub.name}」？`,
        detail: `该订阅源当前关联了 ${count} 个节点。`,
        checkboxLabel: '同时删除该订阅下的所有节点（运行中节点自动保留）',
        confirmText: '确认删除',
        confirmType: 'danger',
        onConfirm: async (deleteNodesChecked) => {
          try {
            await requestJSON(`/api/subscriptions/${sub.id}?delete_nodes=${Boolean(deleteNodesChecked)}`, { method: 'DELETE' })
            await Promise.all([fetchNodes(), fetchSubscriptions()])
            activeSubFilter.value = 'all'
            showToast('订阅已删除', 'success')
            addSystemLog('SYSTEM', `已删除订阅「${sub.name}」${deleteNodesChecked ? '（已清除关联节点）' : ''}`)
          } catch (error) {
            showToast(`删除订阅失败：${error.message}`, 'error')
          }
        }
      })
    }

    const routingTab = ref('direct')
    const categoryTexts = ref({ direct: '', proxy: '', block: '' })
    const savedCategoryTexts = ref({ direct: '', proxy: '', block: '' })
    const savingCat = ref({ direct: false, proxy: false, block: false })
    const routingError = ref('')
    const routingLoaded = ref(false)
    const isCatDirty = category => categoryTexts.value[category].trim() !== savedCategoryTexts.value[category].trim()
    const hasRoutingChanges = computed(() => ['direct', 'proxy', 'block'].some(isCatDirty))
    const savingAllCategories = ref(false)
    const getCatLinesCount = category => categoryTexts.value[category].split('\n').map(line => line.trim()).filter(Boolean).length
    const fetchRoutingCategories = async () => {
      try {
        const data = await requestJSON('/api/routing/categories')
        for (const category of ['direct', 'proxy', 'block']) {
          const text = (data[category] || []).join('\n')
          if (!isCatDirty(category)) categoryTexts.value[category] = text
          savedCategoryTexts.value[category] = text
        }
        routingError.value = ''
        routingLoaded.value = true
      } catch (error) {
        routingError.value = error.message
      }
    }
    const revertCategory = category => {
      categoryTexts.value[category] = savedCategoryTexts.value[category]
      showToast('已撤销修改', 'info')
    }
    const revertAllCategories = () => {
      for (const category of ['direct', 'proxy', 'block']) {
        categoryTexts.value[category] = savedCategoryTexts.value[category]
      }
      showToast('已撤销所有未保存的修改', 'info')
    }
    const saveAllCategories = async () => {
      if (savingAllCategories.value || !routingLoaded.value || !hasRoutingChanges.value) return
      savingAllCategories.value = true
      const submitted = { ...categoryTexts.value }
      const payload = {}
      for (const cat of ['direct', 'proxy', 'block']) {
        if (isCatDirty(cat)) {
          payload[cat] = submitted[cat].split(/\r?\n/).map(line => line.trim()).filter(Boolean)
        }
      }
      try {
        const data = await requestJSON('/api/routing/categories', jsonRequest('PUT', payload))
        for (const cat of ['direct', 'proxy', 'block']) {
          const saved = (data.categories?.[cat] || payload[cat] || []).join('\n')
          savedCategoryTexts.value[cat] = saved
          if (categoryTexts.value[cat] === submitted[cat]) categoryTexts.value[cat] = saved
        }
        showToast(data.message || '分流规则已全部保存并生效', 'success')
        addSystemLog('ROUTING', data.message || '分流规则已全局更新并生效')
      } catch (error) {
        showToast(`保存分流规则失败：${error.message}`, 'error')
      } finally {
        savingAllCategories.value = false
      }
    }
    const saveCategory = async category => {
      if (savingCat.value[category] || !routingLoaded.value) return
      const submitted = categoryTexts.value[category]
      const lines = submitted.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
      savingCat.value[category] = true
      try {
        const data = await requestJSON(`/api/routing/categories/${category}`, jsonRequest('PUT', { lines }))
        const saved = (data.categories?.[category] || lines).join('\n')
        savedCategoryTexts.value[category] = saved
        if (categoryTexts.value[category] === submitted) categoryTexts.value[category] = saved
        showToast(data.message || '规则已保存并生效', 'success')
        addSystemLog('ROUTING', data.message || '分流规则已更新')
      } catch (error) {
        showToast(`保存规则失败：${error.message}`, 'error')
      } finally {
        savingCat.value[category] = false
      }
    }

    const drawerExpanded = ref(false)
    const drawerHeight = ref(230)
    const drawerRef = ref(null)
    const logContainer = ref(null)
    const isResizing = ref(false)
    const logSource = ref('access')
    const logs = ref([])
    const logFilter = ref('')
    const autoScroll = ref(true)
    const isStreaming = ref(false)
    const logStreamError = ref('')
    let eventSource = null
    let finishResize = null
    try {
      const saved = Number(localStorage.getItem('xray_drawer_height'))
      if (saved >= 120) drawerHeight.value = Math.min(saved, window.innerHeight * 0.8)
    } catch (_) {}

    const parseLogLine = line => {
      if (!line || typeof line !== 'string') return null
      const operation = line.match(/^(\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+\[(SYSTEM|ROUTING)\]\s+(.+)$/)
      if (operation) return { type: 'op', time: operation[1].split(' ')[1], tag: operation[2], msg: operation[3] }
      const match = line.match(/^(\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+(?:from\s+)?([^\s]+)\s+(accepted|rejected)\s+([^\s]+)\s+\[([^\]]+)\]/)
      if (!match) return null
      const source = match[2].match(/^((?:tcp:|udp:)?)(\[[^\]]+\]|[^:]+):(\d+)$/)
      const from = source ? source[1] + formatAddress(source[2], source[3]) : formatAddress(match[2])
      const routeTag = ['proxy', 'direct', 'block'].find(tag => match[5].includes(tag)) || 'other'
      return { type: 'conn', time: match[1].split(' ')[1], from, verb: match[3], target: match[4].replace(/^\/\//, ''), routeRaw: match[5], routeTag }
    }

    const appendLog = raw => {
      if (!raw) return
      const element = logContainer.value
      const previousHeight = element?.scrollHeight || 0
      const previousTop = element?.scrollTop || 0
      const id = ++nextId
      logs.value.unshift({ id, idx: id, raw, parsed: parseLogLine(raw) })
      if (logs.value.length > 600) logs.value.length = 600
      nextTick(() => {
        if (!drawerExpanded.value || !logContainer.value) return
        logContainer.value.scrollTop = autoScroll.value ? 0 : previousTop + logContainer.value.scrollHeight - previousHeight
      })
    }
    const latestLogText = computed(() => logs.value[0]?.raw || '')

    const parsedFilteredLogs = computed(() => {
      const filter = logFilter.value.trim().toLowerCase()
      return logs.value.filter(entry => !filter || (filter === 'system' ? entry.parsed?.type === 'op' : entry.raw.toLowerCase().includes(filter)))
    })

    const addSystemLog = (category, message) => {
      const now = new Date()
      const pad = value => String(value).padStart(2, '0')
      const timestamp = `${now.getFullYear()}/${pad(now.getMonth() + 1)}/${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
      appendLog(`${timestamp} [${category}] ${message}`)
      drawerExpanded.value = true
    }

    const startLogStream = () => {
      eventSource?.close()
      isStreaming.value = false
      eventSource = new EventSource(`/api/logs/stream?type=${logSource.value}`)
      eventSource.onopen = () => { isStreaming.value = true; logStreamError.value = '' }
      eventSource.onmessage = event => {
        try {
          const data = JSON.parse(event.data)
          if (data.ready) logStreamError.value = ''
          if (data.line) { appendLog(data.line); logStreamError.value = '' }
        } catch (_) {}
      }
      eventSource.addEventListener('stream-error', event => {
        try { logStreamError.value = JSON.parse(event.data).message } catch (_) {}
      })
      eventSource.onerror = () => { isStreaming.value = false }
    }

    const changeLogSource = source => {
      if (source === logSource.value) return
      logSource.value = source
      logs.value = []
      startLogStream()
    }

    const clearLogs = async () => {
      try {
        await requestJSON(`/api/logs/clear?type=${logSource.value}`, { method: 'POST' })
        logs.value = []
        showToast('日志已清空', 'success')
      } catch (error) {
        showToast(`清空日志失败：${error.message}`, 'error')
      }
    }

    const startResize = event => {
      event.preventDefault()
      finishResize?.()
      isResizing.value = true
      const startY = event.clientY
      const startHeight = drawerHeight.value
      const onMove = move => { drawerHeight.value = Math.max(120, Math.min(window.innerHeight * 0.85, startHeight + startY - move.clientY)) }
      finishResize = () => {
        isResizing.value = false
        try { localStorage.setItem('xray_drawer_height', String(drawerHeight.value)) } catch (_) {}
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', finishResize)
        window.removeEventListener('pointercancel', finishResize)
        finishResize = null
      }
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', finishResize)
      window.addEventListener('pointercancel', finishResize)
    }

    const handleGlobalClick = event => {
      if (copyMenuRef.value && !copyMenuRef.value.contains(event.target)) showCopyMenu.value = false
      if (drawerExpanded.value && drawerRef.value && !drawerRef.value.contains(event.target)) drawerExpanded.value = false
      if (isMultiSelectMode.value) {
        const isInsideSelectionArea = event.target.closest('.list-row') ||
                                      event.target.closest('.batch-actions-bar') ||
                                      event.target.closest('.multi-select-toggle') ||
                                      event.target.closest('[role="dialog"]')
        if (!isInsideSelectionArea) {
          exitMultiSelectMode()
        }
      }
    }

    const handleKeydown = event => {
      if (event.key === 'Escape') {
        if (confirmDialog.value.show) { confirmDialog.value.show = false; return }
        if (cancelActiveTest()) return
        if (!importing.value) openImportModal.value = false
        if (!savingPorts.value) showPortModal.value = false
        showCopyMenu.value = false
        drawerExpanded.value = false
        cancelInlineRename()
        cancelInlineSubRename()
      }
      if (event.key === 'Tab' && openImportModal.value) {
        const dialog = document.querySelector('[role="dialog"]')
        const focusable = dialog ? [...dialog.querySelectorAll('button:not(:disabled), input, textarea, [tabindex="0"]')] : []
        const first = focusable[0]
        const last = focusable.at(-1)
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }

    const handleBeforeUnload = event => {
      if (['direct', 'proxy', 'block'].some(isCatDirty)) { event.preventDefault(); event.returnValue = '' }
    }

    watch(openImportModal, async open => {
      document.body.style.overflow = open ? 'hidden' : ''
      if (open) {
        importPreviousFocus = document.activeElement
        await nextTick()
        importTextarea.value?.focus()
      } else {
        await nextTick()
        importPreviousFocus?.focus()
      }
    })

    watch([autoScroll, drawerExpanded], async () => {
      await nextTick()
      if (autoScroll.value && drawerExpanded.value && logContainer.value) logContainer.value.scrollTop = 0
    })

    watch(isResizing, value => document.body.classList.toggle('is-resizing', value))

    const scrollTimers = new WeakMap()
    const handleScrollActivity = event => {
      const target = event.target
      if (target && target.classList && target.classList.contains('custom-scrollbar')) {
        target.classList.add('is-scrolling')
        const previous = scrollTimers.get(target)
        if (previous) clearTimeout(previous)
        const timer = setTimeout(() => {
          target.classList.remove('is-scrolling')
          scrollTimers.delete(target)
        }, 800)
        scrollTimers.set(target, timer)
      }
    }

    const nodeListScrollRef = ref(null)
    const nodeScrollThumbHeight = ref(30)
    const nodeScrollThumbTop = ref(0)
    const nodeScrollVisible = ref(false)
    const nodeScrollActive = ref(false)
    let nodeScrollTimer = null

    const updateNodeScrollThumb = () => {
      const el = nodeListScrollRef.value
      if (!el) return
      const ch = el.clientHeight
      const sh = el.scrollHeight
      const st = el.scrollTop
      if (sh <= ch + 2) {
        nodeScrollVisible.value = false
        return
      }
      nodeScrollVisible.value = true
      const trackHeight = ch - 8
      const thumbHeight = Math.max(24, Math.round((ch / sh) * trackHeight))
      const maxScroll = sh - ch
      const scrollRatio = maxScroll > 0 ? st / maxScroll : 0
      nodeScrollThumbHeight.value = thumbHeight
      nodeScrollThumbTop.value = Math.round(scrollRatio * (trackHeight - thumbHeight))
    }

    const handleNodeListScroll = () => {
      updateNodeScrollThumb()
      nodeScrollActive.value = true
      if (nodeScrollTimer) clearTimeout(nodeScrollTimer)
      nodeScrollTimer = setTimeout(() => {
        nodeScrollActive.value = false
      }, 700)
    }

    watch(displayNodes, async () => {
      await nextTick()
      updateNodeScrollThumb()
    })

    watch(currentTab, async tab => {
      if (tab === 'nodes') {
        await nextTick()
        updateNodeScrollThumb()
      }
    })

    onMounted(async () => {
      document.addEventListener('click', handleGlobalClick)
      window.addEventListener('keydown', handleKeydown)
      window.addEventListener('beforeunload', handleBeforeUnload)
      window.addEventListener('scroll', handleScrollActivity, true)
      window.addEventListener('resize', updateNodeScrollThumb)
      await nextTick()
      updateNodeScrollThumb()
      startLogStream()
      statusTimer = setInterval(fetchStatus, 15000)
      const results = await Promise.allSettled([fetchNodes(), fetchStatus(), fetchSubscriptions(), fetchRoutingCategories()])
      for (const result of results) {
        if (result.status === 'rejected') showToast(result.reason.message, 'error')
      }
    })

    onUnmounted(() => {
      cancelActiveTest({ silent: true })
      if (statusTimer) clearInterval(statusTimer)
      eventSource?.close()
      finishResize?.()
      toastTimers.forEach(clearTimeout)
      document.body.style.overflow = ''
      document.body.classList.remove('is-resizing')
      document.removeEventListener('click', handleGlobalClick)
      window.removeEventListener('keydown', handleKeydown)
      window.removeEventListener('beforeunload', handleBeforeUnload)
      window.removeEventListener('scroll', handleScrollActivity, true)
      window.removeEventListener('resize', updateNodeScrollThumb)
    })

    const showPortModal = ref(false)
    const savingPorts = ref(false)
    const portFormError = ref('')
    const portForm = ref({ socks: 20170, http: 20171, routing: 20172 })

    const openPortModal = () => {
      showCopyMenu.value = false
      portForm.value = {
        socks: ports.value.socks,
        http: ports.value.http,
        routing: ports.value.routing,
      }
      portFormError.value = ''
      showPortModal.value = true
    }

    const resetDefaultPorts = () => {
      portForm.value = { socks: 20170, http: 20171, routing: 20172 }
      portFormError.value = ''
    }

    const getPortValidationError = key => {
      const val = portForm.value[key]
      if (val === '' || val === null || val === undefined) return '必填'
      const num = Number(val)
      if (isNaN(num) || !Number.isInteger(num) || num < 1 || num > 65535) return '需 1~65535'
      if (num === 2017) return '冲突 2017'
      const otherKeys = ['socks', 'http', 'routing'].filter(k => k !== key)
      if (otherKeys.some(k => Number(portForm.value[k]) === num)) return '端口重复'
      return null
    }

    const isPortFormValid = computed(() => ['socks', 'http', 'routing'].every(k => getPortValidationError(k) === null))

    const submitPortUpdate = async () => {
      if (savingPorts.value || !isPortFormValid.value) return
      const s = Number(portForm.value.socks)
      const h = Number(portForm.value.http)
      const r = Number(portForm.value.routing)
      portFormError.value = ''
      savingPorts.value = true
      try {
        const data = await requestJSON('/api/ports', jsonRequest('PUT', { socks: s, http: h, routing: r }))
        await fetchStatus()
        showPortModal.value = false
        showToast(data.message || '端口设置已应用并生效', 'success')
        addSystemLog('SYSTEM', data.message || `代理端口已更新：直通 ${s}/${h}，分流 ${r}`)
      } catch (error) {
        portFormError.value = error.message
        showToast(`端口更新失败：${error.message}`, 'error')
      } finally {
        savingPorts.value = false
      }
    }

    return {
      confirmDialog, handleConfirmAction, handleCancelAction,
      showPortModal, savingPorts, portFormError, portForm, openPortModal, resetDefaultPorts, submitPortUpdate,
      getPortValidationError, isPortFormValid, getNodeFeatureTag,
      currentTab, service, activeNode, nodes, subscriptions, loadingNodes, loadError, statusError, reloadNodes,
      searchQuery, displayNodes, clearFilters, activeSubFilter, currentSelectedSub, manualNodesCount, getSubNodeCount, getNodeSubName,
      ports, bridgeIP, outboundNetwork, outboundRevealed, formatAddress, isNodeRevealed, toggleNodeAddressReveal,
      showCopyMenu, copyMenuRef, copyEnvCommand, copyHostAddress, copyText, copyLink, toasts,
      isMultiSelectMode, selectedNodeIds, isNodeSelected, clearSelection, toggleMultiSelectMode, exitMultiSelectMode,
      handleNodeClick, handleNodeDblClick, allVisibleSelected, toggleSelectVisible, delaySortOrder, delaySortLabel, cycleDelaySort,
      switchingNodeId, fastSwitchNode, testNode, testNodeSpeed, testAllNodes, testingAll, batchTesting, batchSpeedTesting,
      batchTestDelay, batchTestSpeed, cancelActiveTest, batchDeleteSelected, deleteNode, getLatencyClass, latencyTitle, speedTitle,
      editingNodeId, inlineRenameValue, inlineRenameInputRef, startInlineRename, startInlineRenameForActive, locateActiveNode, cancelInlineRename, saveInlineRename,
      editingSubId, inlineSubRenameValue, inlineSubRenameInputRef, startInlineSubRename, cancelInlineSubRename, saveInlineSubRename, handleSubTabClick,
      subTabsContainer, handleSubTabsWheel, handleSubTabsMouseLeave, handleSubTabsMouseEnter, scrollToActiveSub, scrollToRunningNodeSub, scrollToTab,
      nodeListScrollRef, nodeScrollThumbHeight, nodeScrollThumbTop, nodeScrollVisible, nodeScrollActive, handleNodeListScroll,
      openImportModal, importInput, importCustomName, importing, importTextarea, detectedImportType, pasteFromClipboard, submitUnifiedImport,
      updateSub, deleteSub, routingTab, categoryTexts, savingCat, isCatDirty, getCatLinesCount, revertCategory, saveCategory,
      hasRoutingChanges, savingAllCategories, saveAllCategories, revertAllCategories,
      routingError, routingLoaded, fetchRoutingCategories, drawerExpanded, drawerHeight, drawerRef, logContainer, isResizing,
      logSource, logs, logFilter, autoScroll, isStreaming, logStreamError, parsedFilteredLogs, latestLogText, changeLogSource, clearLogs, startResize,
    }
  },
}).mount('#app')
