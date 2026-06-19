const DATA_SYNC_STEP_DEFINITIONS = [
    { number: 1, name: '环境检查' },
    { number: 2, name: '数据采集' },
    { number: 3, name: '指标计算' },
    { number: 4, name: '资产刷新' },
];

const DATA_SYNC_STEP_SHORT_NAMES = {
    环境检查: '准备中',
    数据采集: '获取行情',
    指标计算: '计算指标',
    资产刷新: '刷新账户',
};

const DATA_SYNC_STEP_DESCRIPTIONS = {
    环境检查: '正在检查运行环境',
    数据采集: '正在获取行情数据',
    指标计算: '正在计算技术指标',
    资产刷新: '正在刷新账户数据',
};

const DATA_SYNC_FAILED_STEP_DESCRIPTIONS = {
    1: '准备阶段中断',
    2: '行情获取阶段中断',
    3: '指标计算阶段中断',
    4: '账户刷新阶段中断',
};

const DATA_SYNC_SSE_RECONNECT_BASE = 2000;
const DATA_SYNC_SSE_RECONNECT_MAX = 30000;

const dataSyncState = {
    featureEnabled: false,
    cardOpen: false,
    running: false,
    taskId: null,
    currentStep: 0,
    totalSteps: DATA_SYNC_STEP_DEFINITIONS.length,
    stepName: '',
    stepStatus: '',
    progress: null,
    subProgress: null,
    detail: null,
    startedAt: null,
    elapsedSeconds: 0,
    lastResult: null,
    statusKind: 'idle',
    statusLabel: '空闲',
    logEntries: [],
    maxLogs: 300,
    lastSeq: 0,
    eventSource: null,
    pollTimer: null,
    reconnectTimer: null,
    resetTimer: null,
    successResetPending: false,
    announcedResultTaskId: null,
    failedAssetNameMap: {},
    pendingNameLookups: new Set(),
    sseReconnectAttempts: 0,
};

let isDataSyncRenderPending = false;

async function initDataSyncUI() {
    const refs = getDataSyncDomRefs();
    if (!refs.triggerButton || !refs.card) {
        return;
    }

    refs.triggerButton.addEventListener('click', handleDataSyncButtonClick);
    document.getElementById('syncRetryBtnPartial')?.addEventListener('click', handleSyncRetry);
    document.getElementById('syncRetryBtnFailed')?.addEventListener('click', handleSyncRetry);
    document.getElementById('syncErrorToggleBtn')?.addEventListener('click', toggleSyncErrorDetail);
    document.addEventListener('keydown', handleDataSyncKeydown);
    window.addEventListener('resize', renderDataSyncState);

    const probe = await probeDataSyncAvailability();
    if (!probe.available) {
        return;
    }

    enableDataSyncFeature();
    if (probe.status) {
        applyDataSyncStatus(probe.status, { suppressAnnouncements: true, resetLogs: true });
    }
    renderDataSyncState();

    if (dataSyncState.running) {
        connectDataSyncEventSource();
        startDataSyncPolling();
    }
}

function getDataSyncDomRefs() {
    return {
        triggerButton: document.getElementById('navSyncButton'),
        card: document.getElementById('syncCard'),
    };
}

async function probeDataSyncAvailability() {
    try {
        const response = await fetch(`${API_BASE}/data-sync/status`, {
            headers: {
                Accept: 'application/json',
            },
        });
        if (response.status === 404) {
            return { available: false, status: null };
        }
        if (!response.ok) {
            console.error('Data sync probe failed:', response.status);
            return { available: false, status: null };
        }
        return {
            available: true,
            status: await response.json(),
        };
    } catch (error) {
        console.error('Data sync probe error:', error);
        return { available: false, status: null };
    }
}

function enableDataSyncFeature() {
    dataSyncState.featureEnabled = true;
    const refs = getDataSyncDomRefs();
    refs.triggerButton.hidden = false;
    refs.card.hidden = true;
}

async function handleDataSyncButtonClick() {
    if (!dataSyncState.featureEnabled) return;

    if (dataSyncState.statusKind === 'idle' && !dataSyncState.running) {
        await triggerDataSync(false);
        return;
    }

    toggleSyncCard();
}

async function handleSyncRetry() {
    closeSyncCard();
    await triggerDataSync(true);
}

function handleDataSyncKeydown(event) {
    if (event.key !== 'Escape' || !dataSyncState.cardOpen) {
        return;
    }
    closeSyncCard();
    document.getElementById('navSyncButton')?.focus();
}

async function triggerDataSync(isRetry = false) {
    if (!dataSyncState.featureEnabled || dataSyncState.running) {
        return;
    }

    try {
        const result = await fetchApiOrThrow('/data-sync/trigger', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ retry: isRetry }),
        });
        prepareDataSyncForNewRun(result.task_id);
        renderDataSyncState();
        showToast('info', isRetry ? '已重新启动数据更新' : '数据更新已启动');
        connectDataSyncEventSource(true);
        startDataSyncPolling();
    } catch (error) {
        showToast('error', `启动失败: ${error.message}`);
    }
}

function prepareDataSyncForNewRun(taskId) {
    dataSyncState.running = true;
    dataSyncState.taskId = taskId;
    dataSyncState.currentStep = 0;
    dataSyncState.totalSteps = DATA_SYNC_STEP_DEFINITIONS.length;
    dataSyncState.stepName = '';
    dataSyncState.stepStatus = '';
    dataSyncState.progress = null;
    dataSyncState.subProgress = null;
    dataSyncState.detail = null;
    dataSyncState.startedAt = formatCurrentDateTime();
    dataSyncState.elapsedSeconds = 0;
    dataSyncState.lastResult = null;
    dataSyncState.statusKind = 'running';
    dataSyncState.statusLabel = '运行中';
    dataSyncState.logEntries = [];
    dataSyncState.lastSeq = 0;
    dataSyncState.failedAssetNameMap = {};
    dataSyncState.pendingNameLookups.clear();
    dataSyncState.successResetPending = false;
    dataSyncState.announcedResultTaskId = null;
    resetDataSyncResetTimer();
}

async function refreshDataSyncStatus({ suppressAnnouncements = false, resetLogs = false } = {}) {
    const status = await fetchApi('/data-sync/status');
    if (!status) return;

    applyDataSyncStatus(status, { suppressAnnouncements, resetLogs });
    renderDataSyncState();

    if (dataSyncState.running) {
        startDataSyncPolling();
        connectDataSyncEventSource();
    } else {
        stopDataSyncPolling();
    }
}

function applyDataSyncStatus(status, { suppressAnnouncements = false, resetLogs = false } = {}) {
    const previousRunning = dataSyncState.running;
    dataSyncState.running = !!status.running;
    dataSyncState.taskId = status.task_id || status.last_result?.task_id || null;
    dataSyncState.currentStep = Number(status.current_step || 0);
    dataSyncState.totalSteps = Number(status.total_steps || DATA_SYNC_STEP_DEFINITIONS.length);
    dataSyncState.stepName = status.step_name || '';
    dataSyncState.stepStatus = status.step_status || '';
    dataSyncState.progress = status.progress ?? null;
    dataSyncState.subProgress = status.sub_progress ?? null;
    dataSyncState.detail = status.detail ?? null;
    dataSyncState.startedAt = status.started_at || null;
    dataSyncState.elapsedSeconds = Number(status.elapsed_seconds || 0);
    dataSyncState.lastResult = status.last_result || null;

    if (resetLogs) {
        dataSyncState.logEntries = [];
        dataSyncState.lastSeq = 0;
    }

    if (dataSyncState.running) {
        dataSyncState.statusKind = 'running';
        dataSyncState.statusLabel = '运行中';
        resetDataSyncResetTimer();
        return;
    }

    dataSyncState.statusKind = deriveDataSyncStatusKind(dataSyncState.lastResult);
    dataSyncState.statusLabel = mapDataSyncStatusLabel(dataSyncState.statusKind);
    requestFailedAssetNames();

    if (dataSyncState.statusKind === 'success') {
        scheduleDataSyncButtonReset();
    } else {
        resetDataSyncResetTimer();
    }

    if (!suppressAnnouncements && previousRunning) {
        announceDataSyncResultIfNeeded(dataSyncState.lastResult);
    }
}

function startDataSyncPolling() {
    if (dataSyncState.pollTimer) {
        return;
    }
    dataSyncState.pollTimer = setInterval(() => {
        refreshDataSyncStatus();
    }, 4000);
}

function stopDataSyncPolling() {
    if (dataSyncState.pollTimer) {
        clearInterval(dataSyncState.pollTimer);
        dataSyncState.pollTimer = null;
    }
}

function connectDataSyncEventSource(forceReset = false) {
    if (!dataSyncState.featureEnabled) {
        return;
    }
    if (!dataSyncState.running && !dataSyncState.cardOpen) {
        disconnectDataSyncEventSource();
        return;
    }
    if (!window.EventSource) {
        startDataSyncPolling();
        return;
    }

    if (forceReset) {
        disconnectDataSyncEventSource();
        dataSyncState.lastSeq = 0;
        dataSyncState.logEntries = [];
    }
    if (dataSyncState.eventSource) {
        return;
    }

    const eventSource = new EventSource(`${API_BASE}/data-sync/logs?limit=200&after_seq=${dataSyncState.lastSeq}`);
    dataSyncState.eventSource = eventSource;

    ['log', 'step', 'progress', 'done'].forEach((eventName) => {
        eventSource.addEventListener(eventName, handleDataSyncStreamEvent);
    });
    eventSource.addEventListener('error', (event) => {
        if (event?.data) {
            handleDataSyncStreamEvent(event);
        }
    });
    eventSource.addEventListener('open', () => {
        dataSyncState.sseReconnectAttempts = 0;
    });
    eventSource.onerror = (event) => {
        if (event?.data) {
            return;
        }
        handleDataSyncConnectionError();
    };
}

function handleDataSyncConnectionError() {
    disconnectDataSyncEventSource();
    startDataSyncPolling();
    if (!dataSyncState.running) {
        return;
    }

    const delay = Math.min(
        DATA_SYNC_SSE_RECONNECT_BASE * (2 ** dataSyncState.sseReconnectAttempts),
        DATA_SYNC_SSE_RECONNECT_MAX,
    );
    dataSyncState.sseReconnectAttempts += 1;
    dataSyncState.reconnectTimer = setTimeout(() => {
        dataSyncState.reconnectTimer = null;
        connectDataSyncEventSource();
    }, delay);
}

function disconnectDataSyncEventSource() {
    if (dataSyncState.eventSource) {
        dataSyncState.eventSource.close();
        dataSyncState.eventSource = null;
    }
    if (dataSyncState.reconnectTimer) {
        clearTimeout(dataSyncState.reconnectTimer);
        dataSyncState.reconnectTimer = null;
    }
}

function handleDataSyncStreamEvent(event) {
    if (!event?.data) return;
    let payload = null;
    try {
        payload = JSON.parse(event.data);
    } catch (error) {
        return;
    }

    if (typeof payload.seq === 'number') {
        dataSyncState.lastSeq = Math.max(dataSyncState.lastSeq, payload.seq);
    }

    if (payload.event === 'log') {
        appendDataSyncLog(payload);
    } else if (payload.event === 'step') {
        dataSyncState.running = true;
        dataSyncState.statusKind = 'running';
        dataSyncState.currentStep = Number(payload.step || dataSyncState.currentStep || 0);
        dataSyncState.stepName = payload.name || dataSyncState.stepName;
        dataSyncState.stepStatus = payload.status || dataSyncState.stepStatus;
        dataSyncState.progress = payload.progress ?? dataSyncState.progress;
        dataSyncState.subProgress = payload.sub_progress ?? dataSyncState.subProgress;
    } else if (payload.event === 'progress') {
        dataSyncState.running = true;
        dataSyncState.statusKind = 'running';
        dataSyncState.currentStep = Number(payload.step || dataSyncState.currentStep || 0);
        dataSyncState.stepName = payload.name || dataSyncState.stepName;
        dataSyncState.stepStatus = payload.status || dataSyncState.stepStatus;
        dataSyncState.progress = payload.progress ?? dataSyncState.progress;
        dataSyncState.subProgress = payload.sub_progress ?? dataSyncState.subProgress;
        dataSyncState.detail = payload.detail ?? dataSyncState.detail;
    } else if (payload.event === 'done' || payload.event === 'error') {
        dataSyncState.lastResult = {
            task_id: payload.task_id || dataSyncState.taskId,
            status: payload.status,
            success: payload.success,
            started_at: dataSyncState.startedAt,
            summary: payload.summary || {},
            error: payload.error || null,
            elapsed_seconds: payload.elapsed_seconds,
            finished_at: payload.finished_at,
            failed_step: payload.failed_step,
            current_step: dataSyncState.currentStep,
            total_steps: dataSyncState.totalSteps,
        };
        dataSyncState.running = false;
        dataSyncState.elapsedSeconds = Number(payload.elapsed_seconds || dataSyncState.elapsedSeconds || 0);
        dataSyncState.statusKind = deriveDataSyncStatusKind(dataSyncState.lastResult);
        dataSyncState.statusLabel = mapDataSyncStatusLabel(dataSyncState.statusKind);
        requestFailedAssetNames();
        announceDataSyncResultIfNeeded(dataSyncState.lastResult);
        if (dataSyncState.statusKind === 'success') {
            scheduleDataSyncButtonReset();
        } else {
            resetDataSyncResetTimer();
        }
        stopDataSyncPolling();
        disconnectDataSyncEventSource();
    }

    scheduleRenderDataSyncState();
}

function appendDataSyncLog(payload) {
    dataSyncState.logEntries.push({
        seq: payload.seq ?? null,
        time: payload.time || '--:--:--',
        level: payload.level || 'INFO',
        source: payload.source || 'runtime',
        message: payload.message || '',
    });
    if (dataSyncState.logEntries.length > dataSyncState.maxLogs) {
        dataSyncState.logEntries = dataSyncState.logEntries.slice(-dataSyncState.maxLogs);
    }
}

function scheduleRenderDataSyncState() {
    if (isDataSyncRenderPending) return;
    isDataSyncRenderPending = true;
    requestAnimationFrame(() => {
        isDataSyncRenderPending = false;
        renderDataSyncState();
    });
}

function renderDataSyncState() {
    if (!dataSyncState.featureEnabled) return;

    renderDataSyncButton();
    if (dataSyncState.cardOpen) {
        renderSyncCard();
    }
}

function renderDataSyncButton() {
    const button = document.getElementById('navSyncButton');
    const icon = document.getElementById('navSyncBtnIcon');
    const label = document.getElementById('navSyncBtnLabel');
    const barFill = document.getElementById('navSyncBtnBarFill');
    if (!button || !icon || !label) return;

    button.classList.remove('is-running', 'is-success', 'is-partial', 'is-failed');
    button.setAttribute('aria-busy', dataSyncState.running ? 'true' : 'false');
    button.setAttribute('aria-expanded', dataSyncState.cardOpen ? 'true' : 'false');

    if (dataSyncState.running) {
        button.classList.add('is-running');
        icon.textContent = '●';
        label.textContent = dataSyncState.currentStep > 0
            ? `${mapStepShortName(dataSyncState.stepName)} ${dataSyncState.currentStep}/${dataSyncState.totalSteps}`
            : '更新中';
        if (barFill) {
            barFill.style.width = `${Math.max(8, computeDataSyncProgressPercent())}%`;
        }
        return;
    }

    if (dataSyncState.statusKind === 'success') {
        button.classList.add('is-success');
        icon.textContent = '✓';
        label.textContent = '更新完成';
        if (barFill) barFill.style.width = '0%';
        return;
    }

    if (dataSyncState.statusKind === 'partial') {
        button.classList.add('is-partial');
        icon.textContent = '⚠';
        label.textContent = `${getFailedAssets().length}个标的未更新`;
        if (barFill) barFill.style.width = '0%';
        return;
    }

    if (dataSyncState.statusKind === 'failed') {
        button.classList.add('is-failed');
        icon.textContent = '⊗';
        label.textContent = '更新失败';
        if (barFill) barFill.style.width = '0%';
        return;
    }

    icon.textContent = '⟳';
    label.textContent = '数据更新';
    if (barFill) barFill.style.width = '0%';
}

function openSyncCard() {
    if (dataSyncState.cardOpen) return;
    dataSyncState.cardOpen = true;

    const card = document.getElementById('syncCard');
    if (!card) return;
    card.hidden = false;
    card.classList.remove('is-closing');
    requestAnimationFrame(() => card.classList.add('is-open'));
    document.getElementById('navSyncButton')?.setAttribute('aria-expanded', 'true');

    setTimeout(() => {
        document.addEventListener('click', handleSyncCardOutsideClick, true);
    }, 0);

    renderSyncCard();
    if (dataSyncState.running) {
        connectDataSyncEventSource();
    }
}

function closeSyncCard() {
    if (!dataSyncState.cardOpen) return;
    dataSyncState.cardOpen = false;

    const card = document.getElementById('syncCard');
    if (!card) return;
    card.classList.remove('is-open');
    card.classList.add('is-closing');
    document.getElementById('navSyncButton')?.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', handleSyncCardOutsideClick, true);

    setTimeout(() => {
        card.classList.remove('is-closing');
        card.hidden = true;
        if (dataSyncState.successResetPending) {
            resetDataSyncToIdle();
        }
        if (!dataSyncState.running) {
            disconnectDataSyncEventSource();
        }
        renderDataSyncState();
    }, 160);
}

function toggleSyncCard() {
    dataSyncState.cardOpen ? closeSyncCard() : openSyncCard();
}

function handleSyncCardOutsideClick(event) {
    const card = document.getElementById('syncCard');
    const button = document.getElementById('navSyncButton');
    if (card && !card.contains(event.target) && button && !button.contains(event.target)) {
        closeSyncCard();
    }
}

function renderSyncCard() {
    const panels = {
        running: document.getElementById('syncCardRunning'),
        success: document.getElementById('syncCardSuccess'),
        partial: document.getElementById('syncCardPartial'),
        failed: document.getElementById('syncCardFailed'),
    };

    Object.values(panels).forEach((panel) => {
        if (panel) panel.hidden = true;
    });

    if (dataSyncState.running) {
        renderSyncCardRunning();
        if (panels.running) panels.running.hidden = false;
        return;
    }
    if (dataSyncState.statusKind === 'success') {
        renderSyncCardSuccess();
        if (panels.success) panels.success.hidden = false;
        return;
    }
    if (dataSyncState.statusKind === 'partial') {
        renderSyncCardPartial();
        if (panels.partial) panels.partial.hidden = false;
        return;
    }
    if (dataSyncState.statusKind === 'failed') {
        renderSyncCardFailed();
        if (panels.failed) panels.failed.hidden = false;
    }
}

function renderSyncCardRunning() {
    const desc = document.getElementById('syncCardDesc');
    if (desc) {
        let text = mapStepDescription(dataSyncState.stepName);
        if (dataSyncState.subProgress) {
            text += ` · ${dataSyncState.subProgress}`;
        }
        desc.textContent = text;
    }

    const elapsed = document.getElementById('syncCardElapsed');
    if (elapsed) elapsed.textContent = formatElapsedSeconds(dataSyncState.elapsedSeconds);

    const fill = document.getElementById('syncCardProgressFill');
    if (fill) {
        fill.style.width = `${Math.max(4, computeDataSyncProgressPercent())}%`;
    }
}

function renderSyncCardSuccess() {
    const result = dataSyncState.lastResult;
    const elapsed = document.getElementById('syncCardSuccessElapsed');
    if (elapsed) elapsed.textContent = formatElapsedSeconds(result?.elapsed_seconds);

    const desc = document.getElementById('syncCardSuccessDesc');
    if (desc) {
        const col = result?.summary?.collection_result || {};
        const count = (col.market_success_codes || []).length + (col.fund_success_codes || []).length;
        const date = result?.summary?.target_date || '--';
        desc.textContent = `${count} 个标的已更新 · ${date}`;
    }
    renderGapFillResult('syncGapSuccessSummary', 'syncGapSuccessDetail');
}

function renderSyncCardPartial() {
    const failedAssets = getFailedAssets();
    const title = document.getElementById('syncCardPartialTitle');
    const gapFill = getGapFillResult();
    if (title) {
        title.textContent = failedAssets.length
            ? `${failedAssets.length} 个标的未更新`
            : (gapFill ? '历史行情补采部分完成' : '数据更新部分完成');
    }

    renderAssetList('syncCardPartialList', failedAssets);

    const sub = document.getElementById('syncCardPartialSub');
    if (sub) {
        const col = dataSyncState.lastResult?.summary?.collection_result || {};
        const totalSuccess = (col.market_success_codes || []).length + (col.fund_success_codes || []).length;
        sub.textContent = `其余 ${totalSuccess} 个标的已正常更新`;
    }
    renderGapFillResult('syncGapPartialSummary', 'syncGapPartialDetail');
}

function getGapFillResult() {
    return dataSyncState.lastResult?.summary?.collection_result
        ?.market_gap_fill_result || null;
}

function renderGapFillResult(summaryId, detailId) {
    const summary = document.getElementById(summaryId);
    const detail = document.getElementById(detailId);
    const gapFill = getGapFillResult();
    if (!summary || !detail) return;
    if (!gapFill?.gate || !gapFill?.tasks) {
        summary.hidden = true;
        detail.hidden = true;
        return;
    }

    const tasks = gapFill.tasks || {};
    const tickflow = gapFill.tickflow || {};
    const discovery = gapFill.history_discovery || {};
    const reconciliation = gapFill.metadata_reconciliation || {};
    summary.textContent = [
        `历史缺口补入 ${Number(tasks.filled || 0)} 条`,
        `延期 ${Number(tasks.deferred || 0)} 条`,
        `确认 ${Number(tasks.confirmed || 0)} 条`,
        `TickFlow 请求 ${Number(tickflow.requested_assets || 0)} 个标的`,
        `发现完成/待处理/失败 ${Number(discovery.tickflow_completed_assets || 0)}/${Number(discovery.tickflow_pending_assets || 0)}/${Number(discovery.tickflow_failed_assets || 0)} 个标的`,
        `元数据纠正/冲突 ${Number(reconciliation.corrected_assets || 0)}/${Number(reconciliation.conflict_assets || 0)} 个标的`,
    ].join(' · ');
    summary.hidden = false;

    const body = detail.querySelector('.sync-gap-detail-body');
    if (body) {
        const sections = [
            ['门禁', gapFill.gate],
            ['TDX', gapFill.tdx],
            ['TickFlow', gapFill.tickflow],
            ['任务', gapFill.tasks],
            ['历史发现', gapFill.history_discovery],
            ['元数据治理', gapFill.metadata_reconciliation],
            ['下游修复', gapFill.downstream],
            ['耗时', gapFill.timing],
        ];
        body.textContent = '';
        sections.forEach(([label, value]) => {
            const row = document.createElement('div');
            row.className = 'sync-gap-detail-row';
            const heading = document.createElement('strong');
            heading.textContent = `${label}: `;
            const content = document.createElement('span');
            content.textContent = JSON.stringify(value || {});
            row.append(heading, content);
            body.appendChild(row);
        });
    }
    detail.hidden = false;
}

function renderSyncCardFailed() {
    renderAssetList('syncCardFailedList', getFailedAssets());

    const interrupt = document.getElementById('syncCardInterrupt');
    if (interrupt) {
        interrupt.textContent = mapFailedStepDesc(dataSyncState.lastResult?.failed_step);
    }
    renderSyncErrorDetail();
}

function renderAssetList(listId, assets) {
    const list = document.getElementById(listId);
    if (!list) return;
    list.textContent = '';

    if (!assets.length) {
        const item = document.createElement('li');
        item.className = 'sync-asset-empty';
        item.textContent = '未捕获到具体标的，请查看错误详情';
        list.appendChild(item);
        return;
    }

    assets.forEach(({ code, name }) => {
        const item = document.createElement('li');
        item.className = 'sync-asset-item';

        const codeNode = document.createElement('span');
        codeNode.className = 'sync-asset-code';
        codeNode.textContent = code;
        item.appendChild(codeNode);

        if (name) {
            const nameNode = document.createElement('span');
            nameNode.className = 'sync-asset-name';
            nameNode.textContent = name;
            item.appendChild(nameNode);
        }

        list.appendChild(item);
    });
}

function toggleSyncErrorDetail() {
    const detail = document.getElementById('syncErrorDetail');
    const button = document.getElementById('syncErrorToggleBtn');
    if (!detail || !button) return;

    const isOpen = detail.classList.contains('is-open');
    if (isOpen) {
        detail.classList.remove('is-open');
        button.setAttribute('aria-expanded', 'false');
        button.textContent = '查看错误详情 ▾';
        setTimeout(() => {
            if (!detail.classList.contains('is-open')) {
                detail.hidden = true;
            }
        }, 200);
        return;
    }

    detail.hidden = false;
    requestAnimationFrame(() => detail.classList.add('is-open'));
    button.setAttribute('aria-expanded', 'true');
    button.textContent = '收起详情 ▴';
    renderSyncErrorDetail();
}

function renderSyncErrorDetail() {
    const list = document.getElementById('syncErrorList');
    if (!list) return;
    list.textContent = '';

    const errors = dataSyncState.logEntries.filter((entry) => {
        const level = String(entry.level || '').toUpperCase();
        return level === 'ERROR' || level === 'CRITICAL';
    });
    if (!errors.length && dataSyncState.lastResult?.error?.message) {
        errors.push({ message: dataSyncState.lastResult.error.message });
    }

    errors.forEach((entry) => {
        const item = document.createElement('div');
        item.className = 'sync-error-item';
        item.textContent = entry.message || '';
        list.appendChild(item);
    });
}

function deriveDataSyncStatusKind(result) {
    if (!result?.status) return 'idle';
    if (result.status === 'failed') return 'failed';
    if (result.status === 'partial_success') return 'partial';
    if (result.status === 'success') {
        return getFailedAssets(result).length > 0 ? 'partial' : 'success';
    }
    return 'idle';
}

function getFailedAssets(result = dataSyncState.lastResult) {
    const col = result?.summary?.collection_result || {};
    const codes = Array.from(new Set([
        ...(col.market_failed_codes || []),
        ...(col.fund_failed_codes || []),
    ]));
    return codes.map((code) => ({
        code,
        name: dataSyncState.failedAssetNameMap[code] || '',
    }));
}

function requestFailedAssetNames() {
    const codes = getFailedAssets()
        .map((asset) => asset.code)
        .filter((code) => code && !dataSyncState.failedAssetNameMap[code] && !dataSyncState.pendingNameLookups.has(code));
    if (!codes.length) {
        return;
    }

    codes.forEach((code) => dataSyncState.pendingNameLookups.add(code));
    Promise.all(codes.map(async (code) => {
        const name = await lookupFailedAssetName(code);
        if (name) {
            dataSyncState.failedAssetNameMap[code] = name;
        }
        dataSyncState.pendingNameLookups.delete(code);
    })).then(() => {
        renderDataSyncState();
    }).catch(() => {
        codes.forEach((code) => dataSyncState.pendingNameLookups.delete(code));
        renderDataSyncState();
    });
}

async function lookupFailedAssetName(code) {
    const params = new URLSearchParams({
        keyword: String(code || ''),
        page: '1',
        page_size: '1',
    });
    try {
        const result = await fetchApiOrThrow(`/v1/catalog/search?${params.toString()}`);
        return result?.items?.[0]?.name || '';
    } catch (error) {
        return '';
    }
}

function mapStepShortName(stepName) {
    return DATA_SYNC_STEP_SHORT_NAMES[stepName] || '处理中';
}

function mapStepDescription(stepName) {
    return DATA_SYNC_STEP_DESCRIPTIONS[stepName] || '处理中，请稍候';
}

function mapFailedStepDesc(failedStep) {
    return DATA_SYNC_FAILED_STEP_DESCRIPTIONS[Number(failedStep)] || '执行过程中断';
}

function mapDataSyncStatusLabel(kind) {
    if (kind === 'success') return '更新完成';
    if (kind === 'partial') return '部分完成';
    if (kind === 'failed') return '更新失败';
    if (kind === 'running') return '运行中';
    return '空闲';
}

function computeDataSyncProgressPercent() {
    if (!dataSyncState.totalSteps) return 0;
    if (dataSyncState.running) {
        const completedSteps = Math.max(0, dataSyncState.currentStep - 1);
        const stepWeight = 100 / dataSyncState.totalSteps;
        const innerProgress = typeof dataSyncState.progress === 'number'
            ? Math.max(0, Math.min(100, dataSyncState.progress)) / 100
            : 0.35;
        return Math.max(0, Math.min(100, (completedSteps * stepWeight) + (innerProgress * stepWeight)));
    }
    if (dataSyncState.statusKind === 'success' || dataSyncState.statusKind === 'partial') return 100;
    if (dataSyncState.statusKind === 'failed') {
        const failedStep = Number(dataSyncState.lastResult?.failed_step || dataSyncState.currentStep || 1);
        return Math.max(10, Math.min(95, (failedStep / dataSyncState.totalSteps) * 100));
    }
    return 0;
}

function announceDataSyncResultIfNeeded(result) {
    if (!result?.task_id) return;
    if (dataSyncState.announcedResultTaskId === result.task_id) return;
    dataSyncState.announcedResultTaskId = result.task_id;
    if (dataSyncState.statusKind === 'success') {
        showToast('success', '数据更新完成');
    } else if (dataSyncState.statusKind === 'partial') {
        showToast('warning', '数据更新有标的未完成，点击查看');
    } else if (dataSyncState.statusKind === 'failed') {
        showToast('error', '数据更新失败，请查看错误详情');
    }
}

function scheduleDataSyncButtonReset() {
    resetDataSyncResetTimer();
    dataSyncState.resetTimer = setTimeout(() => {
        if (!dataSyncState.running && dataSyncState.statusKind === 'success') {
            if (dataSyncState.cardOpen) {
                dataSyncState.successResetPending = true;
            } else {
                resetDataSyncToIdle();
            }
        }
        dataSyncState.resetTimer = null;
    }, 5000);
}

function resetDataSyncResetTimer() {
    if (dataSyncState.resetTimer) {
        clearTimeout(dataSyncState.resetTimer);
        dataSyncState.resetTimer = null;
    }
    dataSyncState.successResetPending = false;
}

function resetDataSyncToIdle() {
    dataSyncState.statusKind = 'idle';
    dataSyncState.statusLabel = '空闲';
    dataSyncState.lastResult = null;
    dataSyncState.successResetPending = false;
    renderDataSyncState();
}

function formatElapsedSeconds(seconds) {
    if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return '--';
    const total = Math.max(0, Math.round(Number(seconds)));
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    if (mins <= 0) return `${secs}s`;
    return `${mins}m ${String(secs).padStart(2, '0')}s`;
}

function formatCurrentDateTime() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}
