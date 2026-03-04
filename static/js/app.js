/**
 * CS2 Server Controller — Frontend Application
 * JS-driven tab system + cs16.css visual components
 */
const App = (() => {
    // ──── Config ────
    const API_BASE = window.location.port === '5000' ? '' : 'http://localhost:5000';

    // ──── State ────
    let connected = false;
    let commandHistory = [];
    let historyIndex = -1;
    let statusInterval = null;
    let autoRefreshInterval = null;
    let cvarDefinitions = {};
    let cvarServerValues = {};
    let cvarLocalEdits = {};
    let quickCommands = {};
    let templates = {};
    let recentCommands = [];

    // ──── Helpers ────
    function $(id) { return document.getElementById(id); }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    async function api(url, opts = {}) {
        try {
            const resp = await fetch(API_BASE + url, {
                headers: { 'Content-Type': 'application/json' },
                ...opts
            });
            return await resp.json();
        } catch (e) {
            return { success: false, error: e.message };
        }
    }

    function toast(msg, type = 'info', duration = 3500) {
        const c = $('toastContainer');
        const el = document.createElement('div');
        el.className = `toast ${type}`;
        el.textContent = msg;
        c.appendChild(el);
        setTimeout(() => { el.remove(); }, duration);
    }

    function setStatus(text) {
        $('statusBarLeft').textContent = text;
    }

    function setConnected(state) {
        connected = state;
        const ind = $('connectionIndicator');
        const txt = $('connStatusText');
        const btnC = $('btn-connect');
        const btnD = $('btn-disconnect');
        if (state) {
            ind.className = 'conn-indicator connected';
            txt.textContent = `${$('inp-host').value}:${$('inp-port').value}`;
            btnC.disabled = true;
            btnD.disabled = false;
        } else {
            ind.className = 'conn-indicator disconnected';
            txt.textContent = 'Disconnected';
            btnC.disabled = false;
            btnD.disabled = true;
        }
    }

    // ──── Tab System ────
    function initTabs() {
        // Main tabs
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tabName = btn.dataset.tab;
                // Deactivate all
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
                // Activate clicked
                btn.classList.add('active');
                $('panel-' + tabName).classList.add('active');
            });
        });

        // Sub tabs (Maps, Settings)
        document.querySelectorAll('.sub-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const subtab = btn.dataset.subtab;
                const group = btn.dataset.group;
                // Deactivate group
                document.querySelectorAll(`.sub-tab-btn[data-group="${group}"]`).forEach(b => b.classList.remove('active'));
                document.querySelectorAll(`.sub-tab-panel[data-group="${group}"]`).forEach(p => p.classList.remove('active'));
                // Activate
                btn.classList.add('active');
                $('subpanel-' + subtab).classList.add('active');
            });
        });
    }

    // ──── Connection ────
    async function connect() {
        const host = $('inp-host').value.trim();
        const port = parseInt($('inp-port').value) || 27015;
        const password = $('inp-password').value;
        if (!host || !password) {
            toast('Enter server address and RCON password', 'error');
            return;
        }
        setStatus('Connecting...');
        $('btn-connect').disabled = true;
        const r = await api('/api/connect', {
            method: 'POST',
            body: JSON.stringify({ host, port, password })
        });
        if (r.success) {
            setConnected(true);
            toast('Connected to server', 'success');
            setStatus(`Connected to ${host}:${port}`);
            startStatusPolling();
            refreshServerInfo();
        } else {
            setConnected(false);
            toast(r.error || 'Connection failed', 'error');
            setStatus('Connection failed');
        }
    }

    async function disconnect() {
        await api('/api/disconnect', { method: 'POST' });
        setConnected(false);
        stopStatusPolling();
        toast('Disconnected', 'info');
        setStatus('Disconnected');
        $('serverInfoContent').innerHTML = '<div class="info-placeholder">Connect to server to see info</div>';
        $('quickStatsContent').innerHTML = '<div class="info-placeholder">No data</div>';
    }

    // ──── Status Polling ────
    function startStatusPolling() {
        stopStatusPolling();
        statusInterval = setInterval(refreshServerInfo, 15000);
    }

    function stopStatusPolling() {
        if (statusInterval) clearInterval(statusInterval);
        statusInterval = null;
    }

    async function refreshServerInfo() {
        if (!connected) return;
        const r = await api('/api/status');
        if (!r.connected) {
            setConnected(false);
            toast('Lost connection to server', 'error');
            stopStatusPolling();
            return;
        }

        // Server Info Box
        let html = '<table class="info-table">';
        if (r.hostname) html += `<tr><td>Hostname</td><td>${escapeHtml(r.hostname)}</td></tr>`;
        if (r.map) html += `<tr><td>Map</td><td>${escapeHtml(r.map)}</td></tr>`;
        if (r.players_line) html += `<tr><td>Players</td><td>${escapeHtml(r.players_line)}</td></tr>`;
        if (r.ip_line) html += `<tr><td>Address</td><td>${escapeHtml(r.ip_line)}</td></tr>`;
        html += `<tr><td>Host</td><td>${escapeHtml(r.host || '')}:${r.port || ''}</td></tr>`;
        html += '</table>';
        $('serverInfoContent').innerHTML = html;

        // Quick Stats Box
        let statsHtml = '<table class="info-table">';
        if (r.raw_status) {
            const lines = r.raw_status.split('\n');
            let playerCount = 0;
            for (const line of lines) {
                if (line.trim().startsWith('#') && !line.includes('#end')) playerCount++;
            }
            statsHtml += `<tr><td>Players Online</td><td>${playerCount}</td></tr>`;
        }
        if (r.map) statsHtml += `<tr><td>Current Map</td><td>${escapeHtml(r.map)}</td></tr>`;
        statsHtml += `<tr><td>Status</td><td style="color:#7fff7f">Online</td></tr>`;
        statsHtml += '</table>';
        $('quickStatsContent').innerHTML = statsHtml;

        // Map badge
        if (r.map) {
            $('currentMapDisplay').textContent = `Current: ${r.map}`;
        }
    }

    // ──── Console ────
    function addConsoleLine(text, type = 'response') {
        const out = $('consoleOutput');
        const line = document.createElement('div');
        line.className = `console-line ${type}`;
        line.textContent = text;
        out.appendChild(line);
        out.scrollTop = out.scrollHeight;
    }

    async function sendCommand(cmd) {
        if (!cmd) {
            cmd = $('consoleInput').value.trim();
            $('consoleInput').value = '';
        }
        if (!cmd) return;

        if (!connected) {
            addConsoleLine('Error: Not connected to server', 'error');
            toast('Not connected', 'error');
            return;
        }

        commandHistory.unshift(cmd);
        if (commandHistory.length > 200) commandHistory.pop();
        historyIndex = -1;

        addConsoleLine(cmd, 'cmd');
        trackRecentCommand(cmd);

        const r = await api('/api/command', {
            method: 'POST',
            body: JSON.stringify({ command: cmd })
        });

        if (r.success) {
            if (r.response) {
                r.response.split('\n').forEach(l => {
                    if (l.trim()) addConsoleLine(l, 'response');
                });
            } else {
                addConsoleLine('(no output)', 'sys');
            }
        } else {
            addConsoleLine(`Error: ${r.error}`, 'error');
        }
    }

    function consoleKeyDown(e) {
        if (e.key === 'Enter') {
            sendCommand();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (historyIndex < commandHistory.length - 1) {
                historyIndex++;
                $('consoleInput').value = commandHistory[historyIndex];
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (historyIndex > 0) {
                historyIndex--;
                $('consoleInput').value = commandHistory[historyIndex];
            } else {
                historyIndex = -1;
                $('consoleInput').value = '';
            }
        }
    }

    function clearConsole() {
        $('consoleOutput').innerHTML = '<div class="console-line sys">Console cleared</div>';
    }

    function exportConsole() {
        const lines = $('consoleOutput').innerText;
        const blob = new Blob([lines], { type: 'text/plain' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `cs2_console_${Date.now()}.log`;
        a.click();
        toast('Console log exported', 'success');
    }

    // ──── Chat ────
    async function say() {
        const msg = $('inp-say').value.trim();
        if (!msg) return;
        if (!connected) { toast('Not connected', 'error'); return; }
        const r = await api('/api/say', {
            method: 'POST',
            body: JSON.stringify({ message: msg })
        });
        if (r.success) {
            toast('Message sent', 'success');
            $('inp-say').value = '';
        } else {
            toast(r.error || 'Failed to send', 'error');
        }
    }

    // ──── Players ────
    async function refreshPlayers() {
        if (!connected) { toast('Not connected', 'error'); return; }
        const r = await api('/api/players');
        const c = $('playersContainer');

        if (!r.success || !r.players || r.players.length === 0) {
            c.innerHTML = '<div class="info-placeholder">No players connected (or unable to parse)</div>';
            updatePlayerStats([]);
            return;
        }

        let html = `<table class="players-table">
            <thead><tr><th>#</th><th>Name</th><th>SteamID</th><th>Actions</th></tr></thead>
            <tbody>`;

        r.players.forEach(p => {
            html += `<tr>
                <td>${escapeHtml(p.id)}</td>
                <td>${escapeHtml(p.name)}</td>
                <td>${escapeHtml(p.steamid || '-')}</td>
                <td class="player-actions">
                    <button class="cs-btn" data-action="kick" data-pid="${escapeHtml(p.id)}">Kick</button>
                    <button class="cs-btn" data-action="ban" data-pid="${escapeHtml(p.id)}">Ban</button>
                </td>
            </tr>`;
        });

        html += '</tbody></table>';
        c.innerHTML = html;
        updatePlayerStats(r.players);

        // Attach events via delegation
        c.querySelectorAll('[data-action="kick"]').forEach(btn => {
            btn.addEventListener('click', () => kickPlayer(btn.dataset.pid));
        });
        c.querySelectorAll('[data-action="ban"]').forEach(btn => {
            btn.addEventListener('click', () => banPlayer(btn.dataset.pid));
        });
    }

    async function kickPlayer(id) {
        if (!connected) return;
        const reason = prompt('Kick reason (optional):') || '';
        const r = await api('/api/kick', {
            method: 'POST',
            body: JSON.stringify({ player_id: id, reason })
        });
        toast(r.success ? 'Player kicked' : (r.error || 'Failed'), r.success ? 'success' : 'error');
        refreshPlayers();
    }

    async function banPlayer(id) {
        if (!connected) return;
        const dur = prompt('Ban duration in minutes (0 = permanent):', '30');
        if (dur === null) return;
        const r = await api('/api/ban', {
            method: 'POST',
            body: JSON.stringify({ player_id: id, duration: parseInt(dur) || 0 })
        });
        toast(r.success ? 'Player banned' : (r.error || 'Failed'), r.success ? 'success' : 'error');
        refreshPlayers();
    }

    // ──── Maps ────
    async function loadMaps() {
        const r = await api('/api/maps');
        if (!r.success) return;

        const c = $('mapPoolContainer');
        let html = '';
        for (const [category, maps] of Object.entries(r.maps)) {
            if (category === 'Workshop' || maps.length === 0) continue;
            html += `<div class="map-category">
                <div class="map-category-title">${escapeHtml(category)}</div>
                <div class="map-grid">`;
            maps.forEach(m => {
                html += `<button class="cs-btn map-btn" data-map="${escapeHtml(m)}">${escapeHtml(m)}</button>`;
            });
            html += '</div></div>';
        }
        c.innerHTML = html;

        // Attach map change events
        c.querySelectorAll('[data-map]').forEach(btn => {
            btn.addEventListener('click', () => changeMap(btn.dataset.map));
        });

        loadWorkshopMaps();
    }

    async function changeMap(mapName) {
        if (!connected) { toast('Not connected', 'error'); return; }
        toast(`Changing map to ${mapName}...`, 'info');
        const r = await api('/api/changemap', {
            method: 'POST',
            body: JSON.stringify({ map: mapName })
        });
        toast(r.success ? `Map changed to ${mapName}` : (r.error || 'Failed'), r.success ? 'success' : 'error');
    }

    async function loadWorkshopMaps() {
        const r = await api('/api/workshop/maps');
        const c = $('workshopMapsContainer');
        if (!r.success || !r.maps || r.maps.length === 0) {
            c.innerHTML = '<div class="info-placeholder">No workshop maps saved</div>';
            return;
        }

        let html = '';
        r.maps.forEach(m => {
            html += `<div class="workshop-card">
                <div class="workshop-card-info">
                    <span class="ws-name">${escapeHtml(m.name)}</span>
                    <span class="ws-id">ID: ${escapeHtml(m.id)}</span>
                </div>
                <div class="workshop-card-actions">
                    <button class="cs-btn" data-ws-action="load" data-wsid="${escapeHtml(m.id)}">Load</button>
                    <a class="cs-btn" href="${m.url}" target="_blank" style="text-decoration:none">Steam</a>
                    <button class="cs-btn" data-ws-action="remove" data-wsid="${escapeHtml(m.id)}">Remove</button>
                </div>
            </div>`;
        });
        c.innerHTML = html;

        // Attach events
        c.querySelectorAll('[data-ws-action="load"]').forEach(btn => {
            btn.addEventListener('click', () => loadWorkshopMap(btn.dataset.wsid));
        });
        c.querySelectorAll('[data-ws-action="remove"]').forEach(btn => {
            btn.addEventListener('click', () => removeWorkshopMap(btn.dataset.wsid));
        });
    }

    async function addWorkshopMap() {
        const name = $('inp-ws-name').value.trim();
        const wsid = $('inp-ws-id').value.trim();
        if (!wsid) { toast('Enter a Workshop ID or URL', 'error'); return; }
        const r = await api('/api/workshop/add', {
            method: 'POST',
            body: JSON.stringify({ workshop_id: wsid, name: name || '' })
        });
        toast(r.success ? r.message : (r.error || 'Failed'), r.success ? 'success' : 'error');
        if (r.success) {
            $('inp-ws-name').value = '';
            $('inp-ws-id').value = '';
            loadWorkshopMaps();
        }
    }

    async function removeWorkshopMap(id) {
        const r = await api('/api/workshop/remove', {
            method: 'POST',
            body: JSON.stringify({ workshop_id: id })
        });
        toast(r.success ? 'Map removed' : 'Failed', r.success ? 'success' : 'error');
        loadWorkshopMaps();
    }

    async function loadWorkshopMap(id) {
        if (!connected) { toast('Not connected', 'error'); return; }
        toast(`Loading workshop map ${id}...`, 'info');
        const r = await api('/api/workshop/load', {
            method: 'POST',
            body: JSON.stringify({ workshop_id: id })
        });
        toast(r.success ? r.response : (r.error || 'Failed'), r.success ? 'success' : 'error');
    }

    // ──── Settings ────
    async function loadCvarDefinitions() {
        const r = await api('/api/cvars');
        if (!r.success) return;
        cvarDefinitions = r.cvars;
        renderSettingsTabs();
    }

    function renderSettingsTabs() {
        const tabBar = $('settingsSubTabBar');
        const panels = $('settingsSubPanels');
        const categories = Object.keys(cvarDefinitions);
        let tabHtml = '';
        let panelHtml = '';

        categories.forEach((cat, i) => {
            const catId = `settings-cat-${i}`;
            tabHtml += `<button class="sub-tab-btn${i === 0 ? ' active' : ''}" data-subtab="${catId}" data-group="settings">${escapeHtml(cat)}</button>`;

            panelHtml += `<div class="sub-tab-panel${i === 0 ? ' active' : ''}" id="subpanel-${catId}" data-group="settings">`;
            panelHtml += `<div class="settings-grid">`;

            const cvars = cvarDefinitions[cat];
            for (const [name, info] of Object.entries(cvars)) {
                const servVal = cvarServerValues[name]?.value ?? '';
                const displayVal = cvarLocalEdits[name] ?? servVal ?? info.default;
                const changed = cvarLocalEdits[name] !== undefined && cvarLocalEdits[name] !== servVal;

                panelHtml += `<div class="setting-row${changed ? ' changed' : ''}" data-cvar="${escapeHtml(name)}">`;
                panelHtml += `<div class="setting-label">
                    <span class="setting-name">${escapeHtml(name)}</span>
                    <span class="setting-desc" title="${escapeHtml(info.desc)}">${escapeHtml(info.desc)}</span>
                </div>`;
                panelHtml += `<div class="setting-control">`;

                if (info.type === 'bool') {
                    panelHtml += `<select class="cs-select" data-cvar="${escapeHtml(name)}">
                        <option value="0"${displayVal === '0' ? ' selected' : ''}>0 (Off)</option>
                        <option value="1"${displayVal === '1' ? ' selected' : ''}>1 (On)</option>
                    </select>`;
                } else {
                    panelHtml += `<input type="text" class="cs-input" value="${escapeHtml(displayVal)}" data-cvar="${escapeHtml(name)}">`;
                }

                panelHtml += `<button class="cs-btn setting-apply-btn" data-apply-cvar="${escapeHtml(name)}" title="Apply this setting">Set</button>`;
                if (servVal !== '' && servVal !== undefined) {
                    panelHtml += `<span class="setting-server-val" title="Server value">(was: ${escapeHtml(servVal)})</span>`;
                }

                panelHtml += `</div></div>`;
            }

            panelHtml += `</div></div>`;
        });

        tabBar.innerHTML = tabHtml;
        panels.innerHTML = panelHtml;

        // Wire sub-tab switching
        tabBar.querySelectorAll('.sub-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const subtab = btn.dataset.subtab;
                const group = btn.dataset.group;
                document.querySelectorAll(`.sub-tab-btn[data-group="${group}"]`).forEach(b => b.classList.remove('active'));
                document.querySelectorAll(`.sub-tab-panel[data-group="${group}"]`).forEach(p => p.classList.remove('active'));
                btn.classList.add('active');
                $('subpanel-' + subtab).classList.add('active');
            });
        });

        // Wire setting change events
        panels.querySelectorAll('.setting-control [data-cvar]').forEach(el => {
            el.addEventListener('change', () => {
                onSettingChange(el.dataset.cvar, el.value);
            });
        });

        // Wire individual apply buttons
        panels.querySelectorAll('[data-apply-cvar]').forEach(btn => {
            btn.addEventListener('click', () => {
                applySingleSetting(btn.dataset.applyCvar);
            });
        });
    }

    function onSettingChange(cvar, value) {
        const servVal = cvarServerValues[cvar]?.value ?? '';
        if (value !== servVal) {
            cvarLocalEdits[cvar] = value;
        } else {
            delete cvarLocalEdits[cvar];
        }
        const row = document.querySelector(`.setting-row[data-cvar="${cvar}"]`);
        if (row) {
            row.classList.toggle('changed', cvarLocalEdits[cvar] !== undefined);
        }
    }

    async function applySingleSetting(cvar) {
        if (!connected) { toast('Not connected', 'error'); return; }
        const el = document.querySelector(`.setting-control [data-cvar="${cvar}"]`);
        if (!el) return;
        const value = el.value;

        const r = await api('/api/cvar', {
            method: 'POST',
            body: JSON.stringify({ cvar, value })
        });

        if (r.success) {
            toast(`${cvar} = ${value}`, 'success');
            cvarServerValues[cvar] = { value };
            delete cvarLocalEdits[cvar];
            const row = document.querySelector(`.setting-row[data-cvar="${cvar}"]`);
            if (row) row.classList.remove('changed');
        } else {
            toast(r.error || 'Failed', 'error');
        }
    }

    async function applyAllSettings() {
        if (!connected) { toast('Not connected', 'error'); return; }
        const edits = Object.entries(cvarLocalEdits);
        if (edits.length === 0) {
            const allInputs = document.querySelectorAll('.setting-control [data-cvar]');
            let count = 0;
            for (const el of allInputs) {
                if (el.tagName === 'BUTTON') continue;
                const cvar = el.dataset.cvar;
                const value = el.value;
                if (value === '') continue;
                await api('/api/cvar', { method: 'POST', body: JSON.stringify({ cvar, value }) });
                count++;
            }
            toast(`Applied ${count} settings`, 'success');
            return;
        }

        let applied = 0;
        for (const [cvar, value] of edits) {
            const r = await api('/api/cvar', {
                method: 'POST',
                body: JSON.stringify({ cvar, value })
            });
            if (r.success) {
                cvarServerValues[cvar] = { value };
                applied++;
            }
        }
        cvarLocalEdits = {};
        toast(`Applied ${applied} changed settings`, 'success');
        renderSettingsTabs();
    }

    async function loadAllServerValues() {
        if (!connected) { toast('Not connected', 'error'); return; }

        const allCvars = [];
        for (const cat of Object.values(cvarDefinitions)) {
            for (const name of Object.keys(cat)) {
                allCvars.push(name);
            }
        }

        if (allCvars.length === 0) {
            toast('No settings defined', 'error');
            return;
        }

        const btn = $('btn-load-settings');
        btn.disabled = true;
        btn.textContent = 'Loading...';
        setStatus(`Loading ${allCvars.length} settings from server...`);
        toast(`Loading ${allCvars.length} settings from server...`, 'info');

        const chunkSize = 15;
        let loaded = 0;

        for (let i = 0; i < allCvars.length; i += chunkSize) {
            const chunk = allCvars.slice(i, i + chunkSize);
            const r = await api('/api/cvar/batch', {
                method: 'POST',
                body: JSON.stringify({ cvars: chunk })
            });
            if (r.success) {
                for (const [name, data] of Object.entries(r.values)) {
                    if (data.value !== null && data.value !== undefined) {
                        cvarServerValues[name] = data;
                        loaded++;
                    }
                }
            }
            setStatus(`Loaded ${Math.min(i + chunkSize, allCvars.length)}/${allCvars.length} settings...`);
        }

        cvarLocalEdits = {};
        renderSettingsTabs();
        btn.disabled = false;
        btn.textContent = 'Load from Server';
        setStatus(`Loaded ${loaded}/${allCvars.length} settings from server`);
        toast(`Loaded ${loaded} settings from server`, 'success');
    }

    // ──── Quick Commands ────
    async function loadQuickCommands() {
        const r = await api('/api/quick_commands');
        if (!r.success) return;
        quickCommands = r.commands;
        renderQuickCommands();
    }

    function renderQuickCommands() {
        const c = $('quickCommandsContainer');
        let html = '';

        for (const [category, cmds] of Object.entries(quickCommands)) {
            html += `<div class="qc-category">
                <div class="qc-category-title">${escapeHtml(category)}</div>
                <div class="qc-grid">`;
            cmds.forEach((cmd, i) => {
                html += `<button class="cs-btn qc-btn" data-qcmd="${escapeHtml(cmd.cmd)}" title="${escapeHtml(cmd.cmd)}">${escapeHtml(cmd.label)}</button>`;
            });
            html += '</div></div>';
        }
        c.innerHTML = html;

        // Attach events via delegation — no inline onclick
        c.querySelectorAll('[data-qcmd]').forEach(btn => {
            btn.addEventListener('click', () => {
                execQuickCmd(btn.dataset.qcmd);
            });
        });
    }

    async function execQuickCmd(cmd) {
        if (!connected) { toast('Not connected', 'error'); return; }

        // Handle commands with semicolons (multiple commands)
        const parts = cmd.split(';').map(s => s.trim()).filter(Boolean);
        let lastResp = '';
        for (const part of parts) {
            const r = await api('/api/command', {
                method: 'POST',
                body: JSON.stringify({ command: part })
            });
            if (r.success) {
                lastResp = r.response || '';
            } else {
                toast(r.error || `Failed: ${part}`, 'error');
                return;
            }
        }
        toast(`Executed: ${cmd}`, 'success');
        if (lastResp) addConsoleLine(`[Quick] ${cmd}: ${lastResp}`, 'sys');
    }

    // ──── Templates ────
    async function loadTemplates() {
        const r = await api('/api/templates');
        if (!r.success) return;
        templates = r.templates;
        renderTemplates();
    }

    function renderTemplates() {
        const c = $('templatesContainer');
        let html = '';
        for (const [key, tpl] of Object.entries(templates)) {
            html += `<div class="template-card">
                <div class="template-info">
                    <div class="template-name">${escapeHtml(tpl.name)}</div>
                    <div class="template-desc">${escapeHtml(tpl.description)}</div>
                    <div class="template-meta">${tpl.cvar_count} settings</div>
                </div>
                <button class="cs-btn" data-tpl="${escapeHtml(key)}">Apply</button>
            </div>`;
        }
        c.innerHTML = html;

        // Attach events
        c.querySelectorAll('[data-tpl]').forEach(btn => {
            btn.addEventListener('click', () => applyTemplate(btn.dataset.tpl));
        });
    }

    async function applyTemplate(key) {
        if (!connected) { toast('Not connected', 'error'); return; }
        toast(`Applying template...`, 'info');
        const r = await api('/api/apply_template', {
            method: 'POST',
            body: JSON.stringify({ template: key })
        });
        toast(r.success ? r.response : (r.error || 'Failed'), r.success ? 'success' : 'error');
    }

    // ──── Config Files ────
    async function refreshConfigs() {
        const r = await api('/api/saved_configs');
        const c = $('savedConfigsContainer');
        if (!r.success || !r.configs || r.configs.length === 0) {
            c.innerHTML = '<div class="info-placeholder">No saved configs</div>';
            return;
        }

        let html = '';
        r.configs.forEach(cfg => {
            html += `<div class="config-card">
                <div class="config-card-info">
                    <span class="cfg-name">${escapeHtml(cfg.name)}</span>
                    <span class="cfg-meta">${cfg.size} bytes | ${escapeHtml(cfg.modified)}</span>
                </div>
                <div style="display:flex;gap:4px">
                    <button class="cs-btn" data-cfg-view="${escapeHtml(cfg.name)}">View</button>
                    <button class="cs-btn" data-cfg-exec="${escapeHtml(cfg.name)}">Execute</button>
                </div>
            </div>`;
        });
        c.innerHTML = html;

        // Attach events
        c.querySelectorAll('[data-cfg-view]').forEach(btn => {
            btn.addEventListener('click', () => viewConfig(btn.dataset.cfgView));
        });
        c.querySelectorAll('[data-cfg-exec]').forEach(btn => {
            btn.addEventListener('click', () => execConfig(btn.dataset.cfgExec));
        });
    }

    async function viewConfig(name) {
        const r = await api(`/api/load_config/${encodeURIComponent(name)}`);
        if (!r.success) { toast(r.error || 'Failed to load', 'error'); return; }
        $('configViewerTitle').textContent = name;
        $('configViewerContent').value = r.content;
        $('configViewer').style.display = 'block';
    }

    async function execConfig(name) {
        if (!connected) { toast('Not connected', 'error'); return; }
        const r = await api('/api/command', {
            method: 'POST',
            body: JSON.stringify({ command: `exec ${name}` })
        });
        toast(r.success ? `Executed ${name}` : (r.error || 'Failed'), r.success ? 'success' : 'error');
    }

    async function execConfigContent() {
        if (!connected) { toast('Not connected', 'error'); return; }
        const content = $('configViewerContent').value;
        const lines = content.split('\n').filter(l => l.trim() && !l.trim().startsWith('//'));
        let count = 0;
        for (const line of lines) {
            await api('/api/command', {
                method: 'POST',
                body: JSON.stringify({ command: line.trim() })
            });
            count++;
        }
        toast(`Executed ${count} commands from config`, 'success');
    }

    async function exportConfig() {
        const name = $('inp-config-name').value.trim();
        if (!name) { toast('Enter a config name', 'error'); return; }

        const cvars = {};
        const inputs = document.querySelectorAll('.setting-control [data-cvar]');
        inputs.forEach(el => {
            if (el.tagName === 'BUTTON') return;
            const cvar = el.dataset.cvar;
            const value = el.value;
            if (value !== '') cvars[cvar] = value;
        });

        const r = await api('/api/export_config', {
            method: 'POST',
            body: JSON.stringify({ name, cvars })
        });
        toast(r.success ? `Config exported as ${r.filename}` : (r.error || 'Failed'), r.success ? 'success' : 'error');
        if (r.success) refreshConfigs();
    }

    // ──── Dashboard Quick Actions ────
    async function dashAction(cmd) {
        if (!connected) { toast('Not connected', 'error'); return; }
        const r = await api('/api/command', {
            method: 'POST',
            body: JSON.stringify({ command: cmd })
        });
        if (r.success) {
            toast(`Executed: ${cmd}`, 'success');
            addConsoleLine(`[Action] ${cmd}`, 'sys');
            if (r.response) {
                r.response.split('\n').forEach(l => {
                    if (l.trim()) addConsoleLine(l, 'response');
                });
            }
            trackRecentCommand(cmd);
        } else {
            toast(r.error || 'Failed', 'error');
        }
    }

    function trackRecentCommand(cmd) {
        recentCommands.unshift({ cmd, time: new Date().toLocaleTimeString() });
        if (recentCommands.length > 15) recentCommands.pop();
        updateRecentCommands();
    }

    function updateRecentCommands() {
        const el = $('recentCommandsContent');
        if (!el) return;
        if (recentCommands.length === 0) {
            el.innerHTML = '<div class="info-placeholder">No commands yet</div>';
            return;
        }
        let html = '<div class="recent-cmds-list">';
        recentCommands.forEach(c => {
            html += `<div class="recent-cmd-item"><span class="recent-cmd-time">${escapeHtml(c.time)}</span><span class="recent-cmd-text">${escapeHtml(c.cmd)}</span></div>`;
        });
        html += '</div>';
        el.innerHTML = html;
    }

    // ──── Player Auto-Refresh & Stats ────
    function toggleAutoRefresh() {
        const btn = $('btn-auto-refresh');
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
            btn.textContent = 'Auto: OFF';
            toast('Auto-refresh disabled', 'info');
        } else {
            refreshPlayers();
            autoRefreshInterval = setInterval(refreshPlayers, 5000);
            btn.textContent = 'Auto: ON';
            toast('Auto-refresh every 5s', 'success');
        }
    }

    function updatePlayerStats(players) {
        const total = players ? players.length : 0;
        let humans = 0, bots = 0;
        if (players) {
            players.forEach(p => {
                if (p.steamid && p.steamid !== 'BOT' && p.steamid !== '-') {
                    humans++;
                } else {
                    bots++;
                }
            });
        }
        const elTotal = $('statTotalPlayers');
        const elHumans = $('statHumanPlayers');
        const elBots = $('statBotPlayers');
        if (elTotal) elTotal.textContent = total;
        if (elHumans) elHumans.textContent = humans;
        if (elBots) elBots.textContent = bots;
    }

    // ──── Broadcast ────
    async function broadcastMessage() {
        const inp = $('inp-broadcast');
        if (!inp) return;
        const msg = inp.value.trim();
        if (!msg) { toast('Enter a message', 'error'); return; }
        if (!connected) { toast('Not connected', 'error'); return; }
        const r = await api('/api/say', {
            method: 'POST',
            body: JSON.stringify({ message: msg })
        });
        if (r.success) {
            toast('Broadcast sent', 'success');
            inp.value = '';
        } else {
            toast(r.error || 'Failed', 'error');
        }
    }

    // ──── Custom Config Editor ────
    async function execCustomConfig() {
        if (!connected) { toast('Not connected', 'error'); return; }
        const editor = $('customConfigEditor');
        if (!editor) return;
        const content = editor.value.trim();
        if (!content) { toast('Config editor is empty', 'error'); return; }
        const lines = content.split('\n').filter(l => l.trim() && !l.trim().startsWith('//'));
        let count = 0;
        for (const line of lines) {
            await api('/api/command', {
                method: 'POST',
                body: JSON.stringify({ command: line.trim() })
            });
            count++;
        }
        toast(`Executed ${count} commands`, 'success');
    }

    async function saveCustomConfig() {
        const editor = $('customConfigEditor');
        if (!editor) return;
        const content = editor.value.trim();
        if (!content) { toast('Config editor is empty', 'error'); return; }
        const name = prompt('Config file name (without .cfg):', 'custom_config');
        if (!name) return;

        // Build lines into a CVar dict or send raw content
        const lines = content.split('\n').filter(l => l.trim() && !l.trim().startsWith('//'));
        const cvars = {};
        lines.forEach(l => {
            const parts = l.trim().split(/\s+/);
            if (parts.length >= 2) {
                cvars[parts[0]] = parts.slice(1).join(' ').replace(/"/g, '');
            } else if (parts.length === 1) {
                cvars[parts[0]] = '';
            }
        });

        const r = await api('/api/export_config', {
            method: 'POST',
            body: JSON.stringify({ name, cvars })
        });
        toast(r.success ? `Saved as ${r.filename}` : (r.error || 'Failed'), r.success ? 'success' : 'error');
        if (r.success) refreshConfigs();
    }

    // ──── Delete Config ────
    async function deleteConfig() {
        const titleEl = $('configViewerTitle');
        if (!titleEl) return;
        const name = titleEl.textContent;
        if (!name || name === 'Config File') { toast('No config loaded', 'error'); return; }
        if (!confirm(`Delete "${name}"?`)) return;
        const r = await api(`/api/delete_config/${encodeURIComponent(name)}`, { method: 'DELETE' });
        if (r.success) {
            toast('Config deleted', 'success');
            $('configViewer').style.display = 'none';
            refreshConfigs();
        } else {
            toast(r.error || 'Failed to delete', 'error');
        }
    }

    // ──── Initialization ────
    async function init() {
        // Setup tab system
        initTabs();

        // Load last connection credentials
        const lc = await api('/api/last_connection');
        if (lc.success && lc.connection) {
            $('inp-host').value = lc.connection.host || '';
            $('inp-port').value = lc.connection.port || 27015;
            $('inp-password').value = lc.connection.password || '';
        }

        // Load all data (doesn't require connection)
        await Promise.all([
            loadCvarDefinitions(),
            loadQuickCommands(),
            loadTemplates(),
            loadMaps(),
            refreshConfigs()
        ]);

        // Auto-detect if backend is already connected to game server
        const status = await api('/api/status');
        if (status.connected) {
            // Backend RCON is already connected — sync frontend state
            setConnected(true);
            startStatusPolling();
            refreshServerInfo();
            toast('Server connected', 'success');
            setStatus(`Connected to ${status.host}:${status.port}`);
        } else if (lc.success && lc.connection && lc.connection.host && lc.connection.password) {
            // Not connected but we have saved credentials — auto-connect
            setStatus('Auto-connecting...');
            const r = await api('/api/connect', {
                method: 'POST',
                body: JSON.stringify({
                    host: lc.connection.host,
                    port: lc.connection.port || 27015,
                    password: lc.connection.password
                })
            });
            if (r.success) {
                setConnected(true);
                startStatusPolling();
                refreshServerInfo();
                toast('Auto-connected to server', 'success');
                setStatus(`Connected to ${lc.connection.host}:${lc.connection.port || 27015}`);
            } else {
                setStatus('Ready — click Connect to start');
            }
        } else {
            setStatus('Ready — enter server details and connect');
        }
    }

    // Boot
    document.addEventListener('DOMContentLoaded', init);

    // ──── Public API ────
    return {
        connect,
        disconnect,
        sendCommand,
        consoleKeyDown,
        clearConsole,
        exportConsole,
        say,
        refreshPlayers,
        kickPlayer,
        banPlayer,
        changeMap,
        addWorkshopMap,
        removeWorkshopMap,
        loadWorkshopMap,
        loadAllServerValues,
        onSettingChange,
        applySingleSetting,
        applyAllSettings,
        execQuickCmd,
        applyTemplate,
        refreshConfigs,
        viewConfig,
        execConfig,
        execConfigContent,
        exportConfig,
        dashAction,
        toggleAutoRefresh,
        broadcastMessage,
        execCustomConfig,
        saveCustomConfig,
        deleteConfig
    };
})();
