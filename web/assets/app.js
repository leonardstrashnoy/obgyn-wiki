/**
 * OB/GYN Semantic Network - Web UI Application
 * Extracted and refactored from inline script in index.html
 * Supports both live API mode and static file mode (file:// or _STATIC_MODE)
 */

// ============================================================================
// CONSTANTS & CONFIG
// ============================================================================

const COLORS = {
    condition:    { bg: '#1a3a5c', border: '#58a6ff', font: '#58a6ff' },
    drug:         { bg: '#0d2a4a', border: '#0969da', font: '#0969da' },
    procedure:    { bg: '#2d1a4a', border: '#bc8cff', font: '#bc8cff' },
    symptom:      { bg: '#3d1a1a', border: '#ff7b72', font: '#ff7b72' },
    risk_factor:  { bg: '#3d1a1a', border: '#da3633', font: '#da3633' },
    mechanism:    { bg: '#3d2a1a', border: '#f0883e', font: '#f0883e' },
    default:      { bg: '#21262d', border: '#8b949e', font: '#8b949e' },
};

const RELATION_COLORS = {
    causes: '#ff7b72',
    treats: '#3fb950',
    diagnoses: '#58a6ff',
    mechanism_of: '#f0883e',
    risk_factor_for: '#da3633',
    assesses: '#bc8cff',
    prevents: '#238636',
};

// ============================================================================
// GLOBAL STATE
// ============================================================================

let graphData = { nodes: [], edges: [] };
let savedPanelPosition = null;
let network = null;
let nodesDataset = null;
let edgesDataset = null;
let activeFilters = new Set(['all']);
let selectedNode = null;
let apiUrl = detectApiUrl();
let searchResults = [];
let selectedResultIndex = -1;
let searchDebounceTimer = null;
let searchResultsContainer = null;

// ============================================================================
// API / MODE DETECTION
// ============================================================================

function detectApiUrl() {
    if (window._STATIC_MODE || location.protocol === 'file:') {
        return '';
    }
    return '';
}

function api(path) {
    const base = apiUrl || '';
    return base + '/api' + path;
}

async function setIndicator(status, text) {
    const el = document.getElementById('conn-indicator');
    let color = '#6e7681';
    if (status === 'ok') color = '#3fb950';
    if (status === 'err') color = '#da3633';
    el.innerHTML = `<span class=\"dot\" style=\"background:${color}\"></span>${text}`;
    el.className = 'indicator ' + status;
}

// ============================================================================
// DATA LOADING & LIVE UPDATES
// ============================================================================

async function loadGraph() {
    try {
        setIndicator('checking', 'fetching graph...');
        let resp;
        try {
            resp = await fetch(api('/graph'), { mode: 'cors' });
        } catch (e) {
            resp = await fetch('graph_data.json');
        }
        graphData = await resp.json();
        initNetwork();
        updateStats();
        updateLegendCounts();

        // Example dropdown
        const select = document.getElementById("example-select");
        if (select) {
            select.onchange = () => {
                if (select.value) {
                    document.getElementById("query-input").value = select.value;
                    runQuery();
                    select.value = "";
                }
            };
        }

        setIndicator('ok', `${graphData.nodes.length} nodes loaded`);
        startSSE();
        setupSearchEnhancements();
    } catch (e) {
        console.error(e);
        setIndicator('err', 'API offline');
    }
}
function startSSE() {
    if (!window.EventSource) return;
    const evtUrl = api('/events');
    const src = new EventSource(evtUrl, {withCredentials: false});
    src.onmessage = function(ev) {
        const msg = JSON.parse(ev.data);
        if (msg.event === 'graph_rebuilt') {
            setIndicator('ok', 'graph updated — refreshing');
            loadGraph();
        }
    };
    src.onerror = function() {
        setIndicator('err', 'live updates paused');
    };
}

// ============================================================================
// NETWORK INITIALIZATION (vis.js)
// ============================================================================

function initNetwork() {
    const nodes = graphData.nodes.map(n => ({
        id: n.id,
        label: n.label,
        group: n.group,
        title: `${n.label} (${n.group})`,
        color: COLORS[n.group] || COLORS.default,
        font: { color: COLORS[n.group]?.font || '#c9d1d9', size: 16, face: 'Segoe UI' },
        shape: n.group === 'condition' ? 'dot' : 'box',
        size: n.group === 'condition' ? 24 : 14,
        borderWidth: 2,
        shadow: { enabled: true, color: 'rgba(0,0,0,0.5)', size: 10 },
    }));

    const edges = graphData.edges.map((e, i) => ({
        id: `e${i}`,
        from: e.from,
        to: e.to,
        label: e.relation,
        title: `${e.relation}${e.evidence ? ' [' + e.evidence + ']' : ''}`,
        color: { color: RELATION_COLORS[e.relation] || '#8b949e', opacity: 0.6 },
        arrows: { to: { enabled: true, scaleFactor: 0.6 } },
        width: 1 + (e.value || 1),
        font: { color: '#8b949e', size: 12, face: 'Segoe UI', align: 'middle' },
    }));

    nodesDataset = new vis.DataSet(nodes);
    edgesDataset = new vis.DataSet(edges);

    const container = document.getElementById('network');
    const data = { nodes: nodesDataset, edges: edgesDataset };

    const options = {
        layout: { improvedLayout: true },
        physics: {
            enabled: true,
            solver: 'forceAtlas2Based',
            forceAtlas2Based: {
                gravitationalConstant: -80,
                centralGravity: 0.01,
                springLength: 120,
                springConstant: 0.08,
            },
            maxVelocity: 50,
            minVelocity: 0.1,
            timestep: 0.35,
            stabilization: { enabled: true, iterations: 100 },
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            hideEdgesOnDrag: true,
        },
    };

    network = new vis.Network(container, data, options);

    network.on('click', function(params) {
        if (params.nodes.length > 0) {
            showNodeInfo(params.nodes[0]);
        } else {
            document.getElementById('info-panel').innerHTML = '';
            selectedNode = null;
            resetHighlight();
        }
    });

    network.on('doubleClick', function(params) {
        if (params.nodes.length > 0) {
            focusNeighborhood(params.nodes[0]);
        }
    });
}

// ============================================================================
// NODE INFO PANEL & EXPANSION
// ============================================================================

async function showNodeInfo(nodeId) {
    selectedNode = nodeId;
    const node = graphData.nodes.find(n => n.id === nodeId);
    if (!node) return;

    let forward = graphData.edges.filter(e => e.from === nodeId);
    let backward = graphData.edges.filter(e => e.to === nodeId);

    let enriched = null;
    try {
        const resp = await fetch(api('/node/' + encodeURIComponent(nodeId)), {mode: 'cors'});
        if (resp.ok) enriched = await resp.json();
    } catch (e) { /* offline */ }

    if (enriched) {
        forward = enriched.forward.map(r => ({ from: nodeId, to: r.node_id, relation: r.relation, evidence: r.evidence, label: r.label }));
        backward = enriched.backward.map(r => ({ to: nodeId, from: r.node_id, relation: r.relation, evidence: r.evidence, label: r.label }));
    }

    let html = `<h2>${node.label}</h2>`;
    html += `<div class=\"section\"><span class=\"badge ${node.group}\">${node.group}</span>${node.canonical ? '<span class=\"badge\">wiki</span>' : ''}</div>`;

    if (node.page) {
        html += `<div class=\"section\"><a class=\"wiki-link\" href=\"../wiki/${node.page}\" target=\"_blank\">Open wiki page →</a></div>`;
    }

    if (forward.length > 0) {
        html += `<div class=\"section\"><div class=\"section-title\">${node.label} → affects</div>`;
        forward.forEach(e => {
            html += `<div class=\"edge-row\"><span class=\"edge-label\">→ ${e.label || graphData.nodes.find(n=>n.id===e.to)?.label || e.to}</span><span class=\"edge-evidence\"><span class=\"badge evidence-${(e.evidence||'2b').toLowerCase()}\">${e.relation}</span></span></div>`;
        });
        html += `</div>`;
    }

    if (backward.length > 0) {
        html += `<div class=\"section\"><div class=\"section-title\">Related to ${node.label}</div>`;
        backward.forEach(e => {
            html += `<div class=\"edge-row\"><span class=\"edge-label\">← ${e.label || graphData.nodes.find(n=>n.id===e.from)?.label || e.from}</span><span class=\"edge-evidence\"><span class=\"badge evidence-${(e.evidence||'2b').toLowerCase()}\">${e.relation}</span></span></div>`;
        });
        html += `</div>`;
    }

    if (forward.length === 0 && backward.length === 0) {
        html += `<div class=\"no-conn\">No connections in graph.</div>`;
    }

    // Expand from sources - made more prominent (larger/bolder via inline style)
    html += `<button class=\"btn-expand\" style=\"background:#1f6feb; font-weight:700; font-size:15px; padding:12px 16px;\" onclick=\"expandNode('${nodeId}', this)\">🔍 Expand from sources</button>`;
    html += `<button class=\"btn-expand\" onclick=\"focusNeighborhood('${nodeId}')\"><span style=\"margin-right:4px\">🎯</span>Focus on node</button>`;
    html += `<button class=\"btn-expand\" onclick=\"focusNeighborhood('${nodeId}')\"><span style=\"margin-right:4px\">🌐</span>Expand neighborhood</button>`;

    document.getElementById('info-panel').innerHTML = html;
    highlightConnections(nodeId);
}

async function expandNode(nodeId, btn) {
    btn.textContent = 'Expanding...';
    btn.disabled = true;
    try {
        const resp = await fetch(api('/nodes/' + encodeURIComponent(nodeId) + '/expand'), {
            method: 'POST', mode: 'cors',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({background: false})
        });
        if (!resp.ok) throw new Error('expand failed ' + resp.status);
        const data = await resp.json();
        btn.textContent = `✅ ${data.edges_extracted} new edges extracted`;
        await loadGraph();
        showNodeInfo(nodeId);
    } catch (e) {
        btn.textContent = '❌ API offline - cannot expand';
    }
}

// ============================================================================
// QUERY FUNCTIONALITY
// ============================================================================

async function runQuery() {
    const input = document.getElementById('query-input');
    const panel = document.getElementById('query-result');
    const q = input.value.trim();
    if (!q) return;
    panel.style.display = 'block';
    panel.innerHTML = '<div style=\"color:#8b949e\">Thinking...</div>';
    try {
        const resp = await fetch(api('/query?question=' + encodeURIComponent(q)), {});
        if (!resp.ok) throw new Error('query failed');
        const data = await resp.json();
                        let html = `
            <div class="result-header">
                <span>Query Result</span>
                <div>
                    <button onclick="dismissQueryResult()" title="Close">×</button>
                </div>
            </div>
            <div class="result-body">
                <div style="font-weight:600; margin-bottom:10px; color:#79c0ff; font-size:15px;">${q}</div>
        `;

        if (data.mode) {
            html += `<div style="font-size:11px; color:#6e7681; margin-bottom:10px;">Mode: <b>${data.mode}</b></div>`;
        }

        if (data.answer) {
            const formatted = data.answer.replace(/\n/g, '<br>');
            html += `<div style="margin-bottom:14px; line-height:1.55; white-space:pre-wrap;">${formatted}</div>`;
        }

        if (data.structured && data.structured.forward && data.structured.forward.length) {
            html += '<div style="margin-top:12px;"><b style="font-size:13px;">Related:</b><ul style="margin:6px 0 0 18px; font-size:13px;">';
            data.structured.forward.slice(0,6).forEach(item => {
                html += `<li>${item.label} <span style="color:#8b949e;">(${item.relation} ${item.evidence})</span></li>`;
            });
            html += '</ul></div>';
        }

        html += '</div>';
        panel.innerHTML = html;
        panel.style.display = 'flex';

        // Restore saved position if available
        if (savedPanelPosition && savedPanelPosition.top && savedPanelPosition.left) {
            panel.style.top = savedPanelPosition.top;
            panel.style.left = savedPanelPosition.left;
            panel.style.bottom = 'auto';
            panel.style.right = 'auto';
        }

        enableResultDragging();
    } catch (e) {
        panel.innerHTML = `<div style="color:#da3633">Query failed: ${e.message}</div>`;
    }
}

// ============================================================================
// HIGHLIGHTING & FOCUS
// ============================================================================

function highlightConnections(nodeId) {
    const connected = new Set([nodeId]);
    graphData.edges.forEach(e => {
        if (e.from === nodeId) connected.add(e.to);
        if (e.to === nodeId) connected.add(e.from);
    });

    const updates = graphData.nodes.map(n => ({
        id: n.id,
        color: connected.has(n.id)
            ? (COLORS[n.group] || COLORS.default)
            : { background: '#21262d', border: '#30363d' },
        font: { color: connected.has(n.id) ? (COLORS[n.group]?.font || '#c9d1d9') : '#484f58', size: 16 },
    }));
    nodesDataset.update(updates);

    const edgeUpdates = graphData.edges.map((e, i) => ({
        id: `e${i}`,
        color: (e.from === nodeId || e.to === nodeId)
            ? { color: RELATION_COLORS[e.relation] || '#58a6ff', opacity: 1 }
            : { color: '#30363d', opacity: 0.1 },
        width: (e.from === nodeId || e.to === nodeId) ? 2 : 0.5,
    }));
    edgesDataset.update(edgeUpdates);
}

function resetHighlight() {
    const updates = graphData.nodes.map(n => ({
        id: n.id,
        color: COLORS[n.group] || COLORS.default,
        font: { color: COLORS[n.group]?.font || '#c9d1d9', size: 16 },
    }));
    nodesDataset.update(updates);

    const edgeUpdates = graphData.edges.map((e, i) => ({
        id: `e${i}`,
        color: { color: RELATION_COLORS[e.relation] || '#8b949e', opacity: 0.6 },
        width: 1 + (e.value || 1),
    }));
    edgesDataset.update(edgeUpdates);
}

function focusNeighborhood(nodeId) {
    const connected = new Set([nodeId]);
    graphData.edges.forEach(e => {
        if (e.from === nodeId) connected.add(e.to);
        if (e.to === nodeId) connected.add(e.from);
    });
    network.fit({ nodes: Array.from(connected), animation: true });
}

// ============================================================================
// SEARCH HELPERS: fuzzy + debounce + keyboard nav
// ============================================================================

function debounce(fn, delay) {
  return function(...args) {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => fn.apply(this, args), delay);
  };
}

function fuzzyMatch(text, query) {
  if (!query) return true;
  const t = (text || '').toLowerCase();
  const q = query.toLowerCase();
  if (t.includes(q)) return true;
  // simple fuzzy: characters appear in order (allows gaps/typos)
  try {
    const escaped = q.split('').map(c => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*');
    return new RegExp(escaped).test(t);
  } catch (e) {
    return t.includes(q);
  }
}

function updateSearchCount(count, query) {
  let el = document.getElementById('search-count');
  if (!el) {
    const stats = document.querySelector('#search-panel .stats-row');
    if (stats) {
      el = document.createElement('span');
      el.id = 'search-count';
      el.style.marginLeft = '8px';
      el.style.color = '#58a6ff';
      stats.appendChild(el);
    }
  }
  if (el) {
    el.textContent = query ? `Results: ${count}` : '';
  }
}

function createSearchResultsContainer() {
  if (searchResultsContainer) return searchResultsContainer;
  const panel = document.getElementById('search-panel');
  searchResultsContainer = document.createElement('div');
  searchResultsContainer.id = 'search-results';
  searchResultsContainer.style.cssText = 'position:absolute; top:38px; left:0; right:0; background:#161b22; border:1px solid #30363d; border-radius:6px; max-height:240px; overflow-y:auto; z-index:100; display:none; box-shadow:0 4px 12px rgba(0,0,0,0.4);';
  panel.style.position = 'relative';
  panel.appendChild(searchResultsContainer);
  return searchResultsContainer;
}

function renderSearchResults(matches) {
  const container = createSearchResultsContainer();
  if (!matches || matches.length === 0) {
    container.style.display = 'none';
    return;
  }
  let html = '<ul style="list-style:none; margin:0; padding:4px 0; font-size:13px;">';
  matches.slice(0, 12).forEach((n, idx) => {
    const active = idx === selectedResultIndex ? 'background:#1f6feb; color:white;' : '';
    html += `<li data-idx="${idx}" style="padding:6px 12px; cursor:pointer; ${active} border-bottom:1px solid #21262d;" onmouseenter="this.style.background='#21262d'" onmouseleave="this.style.background='${idx===selectedResultIndex?'#1f6feb':'#161b22'}'">${n.label} <span style="opacity:0.6; font-size:11px;">(${n.group})</span></li>`;
  });
  html += '</ul>';
  container.innerHTML = html;
  container.style.display = 'block';

  // click handlers
  container.querySelectorAll('li').forEach(li => {
    li.onclick = () => {
      const idx = parseInt(li.dataset.idx);
      selectSearchResult(idx);
    };
  });
}

function selectSearchResult(idx) {
  if (!searchResults[idx]) return;
  const node = searchResults[idx];
  hideSearchResults();
  document.getElementById('search').value = node.label;
  filterNodes(node.label);
  showNodeInfo(node.id);
  if (network) {
    network.selectNodes([node.id]);
    network.focus(node.id, {scale: 1.2, animation: true});
  }
  selectedResultIndex = -1;
}

function hideSearchResults() {
  if (searchResultsContainer) searchResultsContainer.style.display = 'none';
}

function setupSearchEnhancements() {
  const searchInput = document.getElementById('search');
  if (!searchInput) return;

  // Override inline oninput with debounced version (200-300ms)
  const debouncedFilter = debounce((val) => {
    filterNodes(val);
    // also update fuzzy results for dropdown
    const q = val.trim();
    if (q.length > 0) {
      searchResults = graphData.nodes.filter(n =>
        fuzzyMatch(n.label, q) || fuzzyMatch(n.id, q)
      );
      selectedResultIndex = -1;
      updateSearchCount(searchResults.length, q);
      renderSearchResults(searchResults);
    } else {
      searchResults = [];
      hideSearchResults();
      updateSearchCount(0, '');
    }
  }, 250);

  // remove inline handler effect by overriding
  searchInput.oninput = function() {
    debouncedFilter(this.value);
  };

  // Keyboard navigation
  searchInput.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowDown') {
      if (searchResults.length > 0) {
        selectedResultIndex = (selectedResultIndex + 1) % searchResults.length;
        renderSearchResults(searchResults);
        e.preventDefault();
      }
    } else if (e.key === 'ArrowUp') {
      if (searchResults.length > 0) {
        selectedResultIndex = selectedResultIndex <= 0 ? searchResults.length - 1 : selectedResultIndex - 1;
        renderSearchResults(searchResults);
        e.preventDefault();
      }
    } else if (e.key === 'Enter') {
      if (selectedResultIndex >= 0 && searchResults[selectedResultIndex]) {
        selectSearchResult(selectedResultIndex);
      } else if (searchInput.value.trim()) {
        // fallback: select first match
        filterNodes(searchInput.value);
      }
      e.preventDefault();
    } else if (e.key === 'Escape') {
      hideSearchResults();
      searchResults = [];
      selectedResultIndex = -1;
    }
  });

  // hide dropdown on blur (with delay for clicks)
  searchInput.addEventListener('blur', () => {
    setTimeout(() => hideSearchResults(), 150);
  });

  // initial count
  updateSearchCount(0, '');
}

// ============================================================================
// FILTERING & SEARCH (updated with fuzzy)
// ============================================================================

function filterNodes(query) {
  const q = (query || '').toLowerCase().trim();
  const visible = new Set();
  const matches = [];

  if (!q) {
    // Show all nodes if no query
    graphData.nodes.forEach(n => {
      visible.add(n.id);
      matches.push(n);
    });
  } else {
    const lowerQ = q;

    // Check for OR
    if (lowerQ.includes(' or ')) {
      const terms = lowerQ.split(' or ').map(t => t.trim()).filter(Boolean);
      graphData.nodes.forEach(n => {
        const label = (n.label || '').toLowerCase();
        const id = (n.id || '').toLowerCase();
        if (terms.some(term => fuzzyMatch(label, term) || fuzzyMatch(id, term))) {
          visible.add(n.id);
          matches.push(n);
        }
      });
    }
    // Check for AND
    else if (lowerQ.includes(' and ')) {
      const terms = lowerQ.split(' and ').map(t => t.trim()).filter(Boolean);
      graphData.nodes.forEach(n => {
        const label = (n.label || '').toLowerCase();
        const id = (n.id || '').toLowerCase();
        if (terms.every(term => fuzzyMatch(label, term) || fuzzyMatch(id, term))) {
          visible.add(n.id);
          matches.push(n);
        }
      });
    }
    // Default: contains any word (current behavior)
    else {
      graphData.nodes.forEach(n => {
        if (fuzzyMatch(n.label, q) || fuzzyMatch(n.id, q)) {
          visible.add(n.id);
          matches.push(n);
        }
      });
    }
  }

  // Add connected nodes
  graphData.edges.forEach(e => {
    if (visible.has(e.from)) visible.add(e.to);
    if (visible.has(e.to)) visible.add(e.from);
  });

  const typeFilterActive = !activeFilters.has('all');
  const allowedTypes = activeFilters;

  const updates = graphData.nodes.map(n => {
    const matchesType = !typeFilterActive || allowedTypes.has(n.group);
    const matchesSearch = visible.has(n.id);
    return {
      id: n.id,
      hidden: !(matchesType && matchesSearch),
    };
  });
  nodesDataset.update(updates);

  const edgeUpdates = graphData.edges.map((e, i) => {
    const srcVisible = visible.has(e.from);
    const dstVisible = visible.has(e.to);
    const srcType = graphData.nodes.find(n => n.id === e.from)?.group;
    const dstType = graphData.nodes.find(n => n.id === e.to)?.group;
    const typeOk = !typeFilterActive || allowedTypes.has(srcType) || allowedTypes.has(dstType);
    return {
      id: `e${i}`,
      hidden: !(srcVisible && dstVisible && typeOk),
    };
  });
  edgesDataset.update(edgeUpdates);

  document.getElementById('visible-count').textContent = updates.filter(u => !u.hidden).length;
  updateSearchCount(matches.length, q);
}

function setFilter(type) {
  if (type === 'all') {
    activeFilters = new Set(['all']);
  } else {
    activeFilters.delete('all');
    if (activeFilters.has(type)) {
      activeFilters.delete(type);
    } else {
      activeFilters.add(type);
    }
    if (activeFilters.size === 0) {
      activeFilters.add('all');
    }
  }

  document.querySelectorAll('.chip').forEach(btn => {
    const btnType = btn.dataset.type;
    btn.classList.toggle('active', activeFilters.has(btnType));
  });

  const searchVal = document.getElementById('search').value;
  filterNodes(searchVal);
  if (searchResults.length && searchVal) {
    renderSearchResults(searchResults);
  }
}

// ============================================================================
// UI HELPERS
// ============================================================================

function updateStats() {
  document.getElementById('node-count').textContent = graphData.nodes.length;
  document.getElementById('edge-count').textContent = graphData.edges.length;
  document.getElementById('visible-count').textContent = graphData.nodes.length;
}

function togglePanel() {
  document.getElementById('info-panel').classList.toggle('collapsed');
}

// ============================================================================
// INITIALIZATION
// ============================================================================




function dismissQueryResult() {
    const panel = document.getElementById('query-result');
    panel.style.display = 'none';
    panel.innerHTML = '';
}

function clearQuery() {
    document.getElementById('query-input').value = '';
    document.getElementById('query-result').style.display = 'none';
}

function askExample(question) {
    const input = document.getElementById('query-input');
    const panel = document.getElementById('query-result');
    input.value = question;
    runQuery();
}

document.getElementById('query-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') runQuery();
});


// Make query result panel draggable
function makeDraggable(panel) {
    const header = panel.querySelector('.result-header');
    if (!header) return;

    let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;

    header.onmousedown = dragMouseDown;

    function dragMouseDown(e) {
        e.preventDefault();
        pos3 = e.clientX;
        pos4 = e.clientY;
        document.onmouseup = closeDragElement;
        document.onmousemove = elementDrag;
    }

    function elementDrag(e) {
        e.preventDefault();
        pos1 = pos3 - e.clientX;
        pos2 = pos4 - e.clientY;
        pos3 = e.clientX;
        pos4 = e.clientY;
        panel.style.top = (panel.offsetTop - pos2) + "px";
        panel.style.left = (panel.offsetLeft - pos1) + "px";
        panel.style.bottom = 'auto';
        savePanelPosition(panel);
        panel.style.right = 'auto';
    }

    function closeDragElement() {
        document.onmouseup = null;
        document.onmousemove = null;
    }
}

// Call this after creating the result panel
function enableResultDragging() {
    const panel = document.getElementById('query-result');
    if (panel) makeDraggable(panel);
}


function savePanelPosition(panel) {
    savedPanelPosition = {
        top: panel.style.top,
        left: panel.style.left
    };
}

window.addEventListener('DOMContentLoaded', () => { loadGraph(); initLegend(); });

let legendCollapsed = false;

function toggleLegend() {
    const legend = document.getElementById('legend');
    const toggle = document.getElementById('legend-toggle');
    legendCollapsed = !legendCollapsed;
    legend.classList.toggle('collapsed', legendCollapsed);
    toggle.textContent = legendCollapsed ? '+' : '−';
}

function toggleLegendType(type) {
    // Reuse the existing multi-filter system
    setFilter(type);
    
    // Visual feedback - sync active state
    updateLegendActiveState();
}

function updateLegendActiveState() {
    document.querySelectorAll('#legend .legend-item').forEach(item => {
        const type = item.dataset.type;
        if (activeFilters.has('all')) {
            item.style.opacity = '1';
        } else {
            item.style.opacity = activeFilters.has(type) ? '1' : '0.4';
        }
    });
}

function updateLegendCounts() {
    if (!graphData.nodes.length) return;
    
    const counts = {};
    graphData.nodes.forEach(n => {
        counts[n.group] = (counts[n.group] || 0) + 1;
    });
    
    ['condition','drug','procedure','symptom','risk_factor','mechanism'].forEach(type => {
        const el = document.getElementById('count-' + type);
        if (el) el.textContent = counts[type] || 0;
    });
}

// Call this after graph loads
function initLegend() {
    updateLegendCounts();

    // Example dropdown
    const select = document.getElementById("example-select");
    if (select) {
        select.onchange = () => {
            if (select.value) {
                document.getElementById("query-input").value = select.value;
                runQuery();
                select.value = "";

// Reliable dropdown trigger after "and " / "or " + space
const searchBox = document.getElementById("search");
if (searchBox) {
    searchBox.addEventListener("input", () => {
        const dropdown = document.getElementById("example-select");
        if (!dropdown) return;
        const val = searchBox.value.toLowerCase();
        
        if (val.endsWith(" and ") || val.endsWith(" or ") || 
            val.endsWith(" & ") || val.endsWith(" | ")) {
            const term = val.split(/ and | or | & | \| /)[0].trim();
            if (term.length > 1) {
                dropdown.innerHTML = `
                    <option value="">-- Related to "${term}" --</option>
                    <option value="${term} and hypertension">${term} AND hypertension</option>
                    <option value="${term} and diabetes">${term} AND diabetes</option>
                    <option value="${term} and preeclampsia">${term} AND preeclampsia</option>
                    <option value="${term} or eclampsia">${term} OR eclampsia</option>
                `;
            }
        }
    });
}


// AND/OR dropdown suggestions
const si3 = document.getElementById("search");
if (si) {
    si.addEventListener("input", () => {
        const sel = document.getElementById("example-select");
        if (!sel) return;
        const v = si.value.toLowerCase();
        if (v.includes(" and ") || v.includes(" or ") || v.includes(" & ") || v.includes(" | ")) {
            const term = v.split(/ and | or | & | \| /)[0].trim();
            if (term.length > 1) {
                sel.innerHTML = `
                    <option value="">-- Related to "${term}" --</option>
                    <option value="${term} and hypertension">${term} AND hypertension</option>
                    <option value="${term} and diabetes">${term} AND diabetes</option>
                    <option value="${term} and preeclampsia">${term} AND preeclampsia</option>
                    <option value="${term} or eclampsia">${term} OR eclampsia</option>
                `;
            }
        }
    });
}


const si = document.getElementById("search");
if (si) {
    si.addEventListener("input", () => {
        const sel = document.getElementById("example-select");
        if (!sel) return;
        const v = si.value.toLowerCase();
        if (v.includes(" and ") || v.includes(" or ") || v.includes(" & ") || v.includes(" | ")) {
            const term = v.split(/ and | or | & | \| /)[0].trim();
            if (term.length > 1) {
                sel.innerHTML = ` <option value="">-- Related to "${term}" --</option> <option value="${term} and hypertension">${term} AND hypertension</option> <option value="${term} and diabetes">${term} AND diabetes</option> <option value="${term} and preeclampsia">${term} AND preeclampsia</option> <option value="${term} or eclampsia">${term} OR eclampsia</option> `;
            }
        }
    });
}





// Dynamic AND/OR suggestions in dropdown based on search input
const searchInput = document.getElementById('search');
if (searchInput) {
    searchInput.addEventListener('input', () => {
        const select = document.getElementById('example-select');
        if (!select) return;

        const val = searchInput.value.trim().toLowerCase();
        if (val.length > 2) {
            // Show smart AND/OR suggestions
            select.innerHTML = `
                <option value="">-- Suggestions --</option>
                <option value="${val} and hypertension">${val} AND hypertension</option>
                <option value="${val} and diabetes">${val} AND diabetes</option>
                <option value="${val} or eclampsia">${val} OR eclampsia</option>
                <option value="${val}">${val}</option>
            `;
        }
    });
}

            }
        };
    }

    // Initial active state
    setTimeout(updateLegendActiveState, 500);
}
