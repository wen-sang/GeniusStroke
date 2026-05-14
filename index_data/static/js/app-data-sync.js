const DATA_SYNC_STEP_DEFINITIONS = [
    { number: 1, name: '环境检查' },
    { number: 2, name: '数据采集' },
    { number: 3, name: '指标计算' },
    { number: 4, name: '资产刷新' },
];

const dataSyncState = {
    featureEnabled: false,
    isOpen: false,
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
    statusLabel: '空闲',
    statusKind: 'idle',
    steps: createDataSyncStepsState(),
    logEntries: [],
    maxLogs: 300,
    logsExpanded: false,
    lastSeq: 0,
    eventSource: null,
    pollTimer: null,
    reconnectTimer: null,
    resetTimer: null,
    autoScrollPinned: true,
    announcedResultTaskId: null,
    // 横幅与倒计时
    bannerVisible: false,
    countdownTimer: null,
    countdownSeconds: 0,
    autoRefreshCancelled: false,
};

// ==================== 数据同步 UI 逻辑 ====================
async function initDataSyncUI() {
    const refs = getDataSyncDomRefs();
    if (!refs.triggerButton || !refs.panel || !refs.overlay) {
        return;
    }

    refs.triggerButton.addEventListener('click', handleDataSyncButtonClick);
    refs.closeButton?.addEventListener('click', closeDataSyncPanel);
    refs.footerCloseButton?.addEventListener('click', closeDataSyncPanel);
    refs.refreshButton?.addEventListener('click', handleDataSyncRefreshClick);
    refs.retryButton?.addEventListener('click', handleDataSyncRetryClick);
    refs.toggleLogsButton?.addEventListener('click', toggleDataSyncLogs);
    refs.overlay?.addEventListener('click', () => {
        if (window.innerWidth < 900) {
            closeDataSyncPanel();
        }
    });
    refs.logList?.addEventListener('scroll', handleDataSyncLogScroll);
    refs.scrollToBottom?.addEventListener('click', scrollDataSyncLogsToBottom);
    refs.bannerDetailBtn?.addEventListener('click', () => {
        openDataSyncPanel();
        connectDataSyncEventSource();
    });
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
        startDataSyncPolling();
    }
}

function getDataSyncDomRefs() {
    return {
        triggerButton: document.getElementById('navSyncButton'),
        panel: document.getElementById('dataSyncPanel'),
        overlay: document.getElementById('dataSyncPanelOverlay'),
        closeButton: document.getElementById('dataSyncCloseButton'),
        footerCloseButton: document.getElementById('dataSyncCloseFooterButton'),
        refreshButton: document.getElementById('dataSyncRefreshPageButton'),
        retryButton: document.getElementById('dataSyncRetryButton'),
        toggleLogsButton: document.getElementById('dataSyncToggleLogsButton'),
        logSection: document.getElementById('dataSyncLogSection'),
        logList: document.getElementById('dataSyncLogList'),
        scrollToBottom: document.getElementById('dataSyncScrollToBottom'),
        errorSection: document.getElementById('dataSyncErrorDetailSection'),
        errorDetail: document.getElementById('dataSyncErrorDetail'),
        // 横幅元素
        banner: document.getElementById('dataSyncBanner'),
        bannerText: document.getElementById('dataSyncBannerText'),
        bannerSub: document.getElementById('dataSyncBannerSub'),
        bannerPulse: document.getElementById('dataSyncBannerPulse'),
        bannerActions: document.getElementById('dataSyncBannerActions'),
        bannerDetailBtn: document.getElementById('dataSyncBannerDetailBtn'),
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
    refs.panel.hidden = false;
    refs.overlay.hidden = false;
}

async function handleDataSyncButtonClick() {
    if (!dataSyncState.featureEnabled) return;

    openDataSyncPanel();
    if (dataSyncState.running) {
        connectDataSyncEventSource();
        return;
    }

    if (dataSyncState.statusKind === 'success' || dataSyncState.statusKind === 'partial' || dataSyncState.statusKind === 'failed') {
        connectDataSyncEventSource();
        return;
    }

    await triggerDataSync();
}

function openDataSyncPanel() {
    dataSyncState.isOpen = true;
    renderDataSyncPanelVisibility();
}

function closeDataSyncPanel() {
    dataSyncState.isOpen = false;
    disconnectDataSyncEventSource();
    renderDataSyncPanelVisibility();
}

async function handleDataSyncRetryClick() {
    openDataSyncPanel();
    await triggerDataSync(true);
}

function handleDataSyncRefreshClick() {
    loadPageData();
    showToast('success', '页面数据已刷新');
}

function toggleDataSyncLogs() {
    dataSyncState.logsExpanded = !dataSyncState.logsExpanded;
    if (dataSyncState.logsExpanded && dataSyncState.isOpen) {
        connectDataSyncEventSource();
    }
    renderDataSyncLogs();
}

async function triggerDataSync(isRetry = false) {
    if (!dataSyncState.featureEnabled || dataSyncState.running) {
        return;
    }

    try {
        const result = await fetchApiOrThrow('/data-sync/trigger', {
            method: 'POST'
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
    dataSyncState.steps = createDataSyncStepsState();
    dataSyncState.logEntries = [];
    dataSyncState.logsExpanded = false;
    dataSyncState.lastSeq = 0;
    dataSyncState.autoScrollPinned = true;
    clearCountdownTimer();
    dataSyncState.countdownSeconds = 0;
    dataSyncState.autoRefreshCancelled = false;
    dataSyncState.bannerVisible = false;
    resetDataSyncResetTimer();
}

async function refreshDataSyncStatus({ suppressAnnouncements = false, resetLogs = false } = {}) {
    const status = await fetchApi('/data-sync/status');
    if (!status) return;

    applyDataSyncStatus(status, { suppressAnnouncements, resetLogs });
    renderDataSyncState();

    if (dataSyncState.running) {
        startDataSyncPolling();
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
        dataSyncState.autoScrollPinned = true;
        dataSyncState.logsExpanded = false;
    }

    syncDataSyncStepsFromStatus(status);

    if (dataSyncState.running) {
        dataSyncState.statusKind = 'running';
        dataSyncState.statusLabel = '运行中';
        resetDataSyncResetTimer();
        return;
    }

    const lastStatus = dataSyncState.lastResult?.status || 'idle';
    if (lastStatus === 'success') {
        dataSyncState.statusKind = 'success';
        dataSyncState.statusLabel = '更新完成';
        scheduleDataSyncButtonReset();
    } else if (lastStatus === 'partial_success') {
        dataSyncState.statusKind = 'partial';
        dataSyncState.statusLabel = '部分完成';
        resetDataSyncResetTimer();
    } else if (lastStatus === 'failed') {
        dataSyncState.statusKind = 'failed';
        dataSyncState.statusLabel = '更新失败';
        resetDataSyncResetTimer();
    } else {
        dataSyncState.statusKind = 'idle';
        dataSyncState.statusLabel = '空闲';
        resetDataSyncResetTimer();
    }

    if (!suppressAnnouncements && previousRunning) {
        announceDataSyncResultIfNeeded(dataSyncState.lastResult);
    } else if (suppressAnnouncements && dataSyncState.lastResult?.task_id) {
        dataSyncState.announcedResultTaskId = dataSyncState.lastResult.task_id;
    }
}

function startDataSyncPolling() {
    stopDataSyncPolling();
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
    if (!dataSyncState.featureEnabled || !dataSyncState.isOpen) {
        return;
    }

    if (forceReset) {
        disconnectDataSyncEventSource();
        dataSyncState.lastSeq = 0;
        dataSyncState.logEntries = [];
        dataSyncState.autoScrollPinned = true;
    }
    if (dataSyncState.eventSource) {
        return;
    }

    if (!dataSyncState.running && !dataSyncState.lastResult) {
        return;
    }

    const eventSource = new EventSource(`${API_BASE}/data-sync/logs?limit=200&after_seq=${dataSyncState.lastSeq}`);
    dataSyncState.eventSource = eventSource;

    ['log', 'step', 'progress', 'done', 'error'].forEach((eventName) => {
        eventSource.addEventListener(eventName, handleDataSyncStreamEvent);
    });

    eventSource.addEventListener('done', () => {
        stopDataSyncPolling();
        disconnectDataSyncEventSource();
    });

    eventSource.onerror = () => {
        disconnectDataSyncEventSource();
        if (dataSyncState.running && dataSyncState.isOpen) {
            dataSyncState.reconnectTimer = setTimeout(() => {
                dataSyncState.reconnectTimer = null;
                connectDataSyncEventSource();
            }, 2000);
        }
    };
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
    }

    if (payload.event === 'step') {
        dataSyncState.currentStep = Number(payload.step || dataSyncState.currentStep || 0);
        dataSyncState.stepName = payload.name || dataSyncState.stepName;
        dataSyncState.stepStatus = payload.status || dataSyncState.stepStatus;
        updateDataSyncStepStatus(dataSyncState.currentStep, payload.status || 'running', {
            subProgress: payload.sub_progress ?? null,
            detail: payload.detail ?? null,
        });
    } else if (payload.event === 'progress') {
        dataSyncState.currentStep = Number(payload.step || dataSyncState.currentStep || 0);
        dataSyncState.stepName = payload.name || dataSyncState.stepName;
        dataSyncState.stepStatus = payload.status || dataSyncState.stepStatus;
        dataSyncState.progress = payload.progress ?? dataSyncState.progress;
        dataSyncState.subProgress = payload.sub_progress ?? dataSyncState.subProgress;
        dataSyncState.detail = payload.detail ?? dataSyncState.detail;
        updateDataSyncStepStatus(dataSyncState.currentStep, dataSyncState.stepStatus || 'running', {
            subProgress: dataSyncState.subProgress,
            detail: dataSyncState.detail,
        });
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
        dataSyncState.statusKind = getDataSyncStatusKind(payload.status);
        dataSyncState.statusLabel = mapDataSyncStatusLabel(dataSyncState.statusKind);
        markDataSyncStepsFromResult(dataSyncState.lastResult);
        announceDataSyncResultIfNeeded(dataSyncState.lastResult);
        if (dataSyncState.statusKind === 'success') {
            scheduleDataSyncButtonReset();
        } else {
            resetDataSyncResetTimer();
        }
    }

    renderDataSyncState();
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

function renderDataSyncState() {
    if (!dataSyncState.featureEnabled) return;

    renderDataSyncPanelVisibility();
    renderDataSyncButton();
    renderDataSyncBanner();
    renderDataSyncStatusCard();
    renderDataSyncSteps();
    renderDataSyncSummary();
    renderDataSyncLogs();
    renderDataSyncErrorDetail();
    renderDataSyncFooterActions();
}

function renderDataSyncPanelVisibility() {
    const refs = getDataSyncDomRefs();
    const useBackdrop = dataSyncState.isOpen && window.innerWidth < 900;
    refs.panel?.classList.toggle('is-open', dataSyncState.isOpen);
    refs.overlay?.classList.toggle('is-open', useBackdrop);
}

function renderDataSyncButton() {
    const button = document.getElementById('navSyncButton');
    const icon = document.getElementById('navSyncButtonIcon');
    const label = document.getElementById('navSyncButtonLabel');
    if (!button || !icon || !label) return;

    button.classList.remove('running', 'success', 'partial', 'failed');
    button.classList.toggle('is-busy', dataSyncState.running);
    button.setAttribute('aria-busy', dataSyncState.running ? 'true' : 'false');
    button.setAttribute('aria-disabled', dataSyncState.running ? 'true' : 'false');

    if (dataSyncState.running) {
        button.classList.add('running');
        icon.textContent = '◎';
        label.textContent = '更新中';
        return;
    }

    if (dataSyncState.statusKind === 'success') {
        button.classList.add('success');
        icon.textContent = '✓';
        label.textContent = '更新完成';
        return;
    }

    if (dataSyncState.statusKind === 'partial') {
        button.classList.add('partial');
        icon.textContent = '⚠';
        label.textContent = '部分完成';
        return;
    }

    if (dataSyncState.statusKind === 'failed') {
        button.classList.add('failed');
        icon.textContent = '⚠';
        label.textContent = '更新失败';
        return;
    }

    icon.textContent = '⟳';
    label.textContent = '数据更新';
}

function renderDataSyncStatusCard() {
    const badge = document.getElementById('dataSyncStatusBadge');
    const stepText = document.getElementById('dataSyncStepText');
    const taskId = document.getElementById('dataSyncTaskId');
    const elapsed = document.getElementById('dataSyncElapsed');
    const startedAt = document.getElementById('dataSyncStartedAt');
    const finishedAt = document.getElementById('dataSyncFinishedAt');
    const progressBar = document.getElementById('dataSyncProgressBar');
    if (!badge || !stepText || !taskId || !elapsed || !startedAt || !finishedAt || !progressBar) return;

    badge.className = 'data-sync-status-badge';
    if (dataSyncState.statusKind === 'success') badge.classList.add('success');
    if (dataSyncState.statusKind === 'partial') badge.classList.add('partial');
    if (dataSyncState.statusKind === 'failed') badge.classList.add('failed');

    badge.textContent = dataSyncState.statusLabel;
    stepText.textContent = buildDataSyncStepText();
    taskId.textContent = dataSyncState.taskId || '--';
    elapsed.textContent = formatElapsedSeconds(dataSyncState.elapsedSeconds);
    startedAt.textContent = dataSyncState.startedAt || '--';
    finishedAt.textContent = dataSyncState.lastResult?.finished_at || '--';
    progressBar.style.width = `${computeDataSyncProgressPercent()}%`;
}

function renderDataSyncSteps() {
    const stepItems = document.querySelectorAll('#dataSyncSteps .data-sync-step-item');
    stepItems.forEach((item) => {
        const stepNumber = Number(item.getAttribute('data-step'));
        const step = getDataSyncStepRecord(stepNumber);
        const statusNode = item.querySelector('.data-sync-step-status');
        const metaNode = item.querySelector('.data-sync-step-meta');
        item.classList.remove('is-running', 'is-completed', 'is-failed', 'is-skipped');
        if (!step) return;

        if (step.status === 'running') item.classList.add('is-running');
        if (step.status === 'completed') item.classList.add('is-completed');
        if (step.status === 'failed') item.classList.add('is-failed');
        if (step.status === 'skipped') item.classList.add('is-skipped');

        if (statusNode) {
            statusNode.textContent = mapDataSyncStepStatusText(step);
        }
        if (metaNode) {
            metaNode.textContent = buildDataSyncStepMeta(step);
        }
    });
}

function renderDataSyncSummary() {
    const summary = document.getElementById('dataSyncSummary');
    if (!summary) return;

    if (dataSyncState.running) {
        const lines = [
            `当前阶段：${dataSyncState.stepName || '等待阶段开始'}`,
            dataSyncState.subProgress ? `子进度：${dataSyncState.subProgress}` : null,
            dataSyncState.detail ? `阶段详情：${dataSyncState.detail}` : null,
            `已用时：${formatElapsedSeconds(dataSyncState.elapsedSeconds)}`,
        ].filter(Boolean);
        appendTextLines(summary, lines);
        return;
    }

    if (!dataSyncState.lastResult) {
        summary.textContent = '尚未触发数据更新。';
        return;
    }

    const result = dataSyncState.lastResult;
    const collectionSummary = result.summary?.collection_result || {};
    const refreshSummary = result.summary?.asset_refresh_summary || {};
    const marketSuccessCount = (collectionSummary.market_success_codes || []).length;
    const fundSuccessCount = (collectionSummary.fund_success_codes || []).length;
    const failedCount = (collectionSummary.market_failed_codes || []).length + (collectionSummary.fund_failed_codes || []).length;
    const emptyCount = (collectionSummary.market_empty_codes || []).length + (collectionSummary.fund_empty_codes || []).length;

    const lines = [
        `状态：${mapResultStatusLabel(result.status)}`,
        `总耗时：${formatElapsedSeconds(result.elapsed_seconds)}`,
        `目标日期：${result.summary?.target_date || '--'}`,
        `采集成功：${marketSuccessCount + fundSuccessCount}`,
        `采集失败：${failedCount}`,
        `空数据：${emptyCount}`,
        `影响账户：${refreshSummary.affected_account_count ?? '--'}`,
    ];

    if (result.error?.message) {
        lines.push(`异常：${result.error.message}`);
    }

    appendTextLines(summary, lines);
}

function renderDataSyncLogs() {
    const toggleButton = document.getElementById('dataSyncToggleLogsButton');
    const logSection = document.getElementById('dataSyncLogSection');
    const logList = document.getElementById('dataSyncLogList');
    const scrollButton = document.getElementById('dataSyncScrollToBottom');
    if (!toggleButton || !logSection || !logList) return;

    toggleButton.textContent = dataSyncState.logsExpanded ? '收起日志' : '展开日志';
    toggleButton.setAttribute('aria-expanded', dataSyncState.logsExpanded ? 'true' : 'false');
    logSection.classList.toggle('is-expanded', dataSyncState.logsExpanded);

    if (!dataSyncState.logsExpanded) {
        scrollButton?.classList.add('hidden');
        return;
    }

    if (!dataSyncState.logEntries.length) {
        clearElement(logList);
        const emptyState = document.createElement('div');
        emptyState.className = 'data-sync-empty';
        emptyState.textContent = '等待日志输出...';
        logList.appendChild(emptyState);
        scrollButton?.classList.add('hidden');
        return;
    }

    const entries = dataSyncState.logEntries.slice(-120);
    clearElement(logList);
    entries.forEach((entry, index) => {
        const item = document.createElement('div');
        item.className = `data-sync-log-item level-${sanitizeCssToken(entry.level, 'info')}`;
        if (index === entries.length - 1) {
            item.classList.add('is-current');
        }

        const meta = document.createElement('div');
        meta.className = 'data-sync-log-meta';
        [entry.time, entry.level, entry.source].forEach((value) => {
            const span = document.createElement('span');
            span.textContent = value || '--';
            meta.appendChild(span);
        });

        const message = document.createElement('div');
        message.className = 'data-sync-log-message';
        message.textContent = entry.message || '';

        item.appendChild(meta);
        item.appendChild(message);
        logList.appendChild(item);
    });
    if (dataSyncState.autoScrollPinned) {
        scrollDataSyncLogsToBottom();
        scrollButton?.classList.add('hidden');
    } else {
        scrollButton?.classList.remove('hidden');
    }
}

function renderDataSyncErrorDetail() {
    const refs = getDataSyncDomRefs();
    if (!refs.errorSection || !refs.errorDetail) return;

    const errorMessage = getDataSyncErrorMessage();
    refs.errorSection.classList.toggle('hidden', !errorMessage);
    refs.errorDetail.textContent = errorMessage || '当前无错误详情。';
}

function renderDataSyncFooterActions() {
    const retryButton = document.getElementById('dataSyncRetryButton');
    const refreshButton = document.getElementById('dataSyncRefreshPageButton');
    if (!retryButton || !refreshButton) return;

    const canRetry = !dataSyncState.running && (dataSyncState.statusKind === 'partial' || dataSyncState.statusKind === 'failed');
    const canRefreshPage = !dataSyncState.running && (dataSyncState.statusKind === 'success' || dataSyncState.statusKind === 'partial');

    retryButton.hidden = !canRetry;
    refreshButton.hidden = !canRefreshPage;
}

function buildDataSyncStepText() {
    if (dataSyncState.running && dataSyncState.currentStep > 0) {
        const suffix = dataSyncState.subProgress ? ` · ${dataSyncState.subProgress}` : '';
        return `第 ${dataSyncState.currentStep}/${dataSyncState.totalSteps} 步：${dataSyncState.stepName || '处理中'}${suffix}`;
    }
    if (dataSyncState.lastResult?.status) {
        return `最近结果：${mapResultStatusLabel(dataSyncState.lastResult.status)}`;
    }
    return '等待触发';
}

function formatElapsedSeconds(seconds) {
    if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return '--';
    const total = Math.max(0, Math.round(Number(seconds)));
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    if (mins <= 0) return `${secs}s`;
    return `${mins}m ${String(secs).padStart(2, '0')}s`;
}

function mapResultStatusLabel(status) {
    if (status === 'success') return '成功';
    if (status === 'partial_success') return '部分完成';
    if (status === 'failed') return '失败';
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
    const status = dataSyncState.lastResult?.status;
    if (status === 'success' || status === 'partial_success') return 100;
    if (status === 'failed') {
        const failedStep = Number(dataSyncState.lastResult?.failed_step || dataSyncState.currentStep || 1);
        return Math.max(10, Math.min(95, (failedStep / dataSyncState.totalSteps) * 100));
    }
    return 0;
}

function handleDataSyncLogScroll() {
    const logList = document.getElementById('dataSyncLogList');
    if (!logList || !dataSyncState.logsExpanded) return;
    const threshold = 32;
    const distanceToBottom = logList.scrollHeight - logList.scrollTop - logList.clientHeight;
    dataSyncState.autoScrollPinned = distanceToBottom <= threshold;
    document.getElementById('dataSyncScrollToBottom')?.classList.toggle('hidden', dataSyncState.autoScrollPinned);
}

function scrollDataSyncLogsToBottom() {
    const logList = document.getElementById('dataSyncLogList');
    if (!logList) return;
    logList.scrollTop = logList.scrollHeight;
    dataSyncState.autoScrollPinned = true;
    document.getElementById('dataSyncScrollToBottom')?.classList.add('hidden');
}

function scheduleDataSyncButtonReset() {
    resetDataSyncResetTimer();
    dataSyncState.resetTimer = setTimeout(() => {
        if (!dataSyncState.running && dataSyncState.statusKind === 'success') {
            dataSyncState.statusKind = 'idle';
            dataSyncState.statusLabel = '空闲';
            renderDataSyncState();
        }
        dataSyncState.resetTimer = null;
    }, 5000);
}

function resetDataSyncResetTimer() {
    if (dataSyncState.resetTimer) {
        clearTimeout(dataSyncState.resetTimer);
        dataSyncState.resetTimer = null;
    }
}

function createDataSyncStepsState() {
    return DATA_SYNC_STEP_DEFINITIONS.map((step) => ({
        number: step.number,
        name: step.name,
        status: 'pending',
        subProgress: null,
        detail: null,
        startedAtMs: null,
        durationMs: null,
    }));
}

function getDataSyncStepRecord(stepNumber) {
    return dataSyncState.steps.find((step) => step.number === Number(stepNumber)) || null;
}

function updateDataSyncStepStatus(stepNumber, status, { subProgress = null, detail = null } = {}) {
    const step = getDataSyncStepRecord(stepNumber);
    if (!step) return;

    const nowMs = Date.now();
    if (status === 'running') {
        if (!step.startedAtMs) {
            step.startedAtMs = nowMs;
        }
    }

    if (status === 'completed' || status === 'failed') {
        if (!step.startedAtMs) {
            step.startedAtMs = nowMs;
        }
        step.durationMs = Math.max(0, nowMs - step.startedAtMs);
    }

    step.status = status;
    if (subProgress !== null) {
        step.subProgress = subProgress;
    }
    if (detail !== null) {
        step.detail = detail;
    }

    dataSyncState.steps.forEach((record) => {
        if (record.number < step.number && record.status === 'pending') {
            record.status = 'completed';
        }
    });
}

function syncDataSyncStepsFromStatus(status) {
    if (!dataSyncState.steps.length) {
        dataSyncState.steps = createDataSyncStepsState();
    }

    if (!status.running) {
        if (status.last_result) {
            markDataSyncStepsFromResult(status.last_result);
        } else {
            dataSyncState.steps = createDataSyncStepsState();
        }
        return;
    }

    const currentStep = Number(status.current_step || 0);
    dataSyncState.steps.forEach((step) => {
        if (step.number < currentStep && step.status === 'pending') {
            step.status = 'completed';
        }
        if (step.number > currentStep && step.status === 'skipped') {
            step.status = 'pending';
        }
    });

    if (currentStep > 0) {
        updateDataSyncStepStatus(currentStep, status.step_status || 'running', {
            subProgress: status.sub_progress ?? null,
            detail: status.detail ?? null,
        });
    }
}

function markDataSyncStepsFromResult(result) {
    const failedStep = Number(result?.failed_step || 0);
    dataSyncState.steps.forEach((step) => {
        if (result?.status === 'success') {
            step.status = 'completed';
            return;
        }
        if (result?.status === 'partial_success') {
            step.status = step.number < 4 ? 'completed' : 'failed';
            return;
        }
        if (result?.status === 'failed') {
            if (failedStep && step.number < failedStep) step.status = 'completed';
            else if (failedStep && step.number === failedStep) step.status = 'failed';
            else if (failedStep && step.number > failedStep) step.status = 'skipped';
            else step.status = 'pending';
            return;
        }
        step.status = 'pending';
    });
}

function mapDataSyncStepStatusText(step) {
    if (step.status === 'running') return step.subProgress || '进行中';
    if (step.status === 'completed') return '已完成';
    if (step.status === 'failed') return dataSyncState.lastResult?.status === 'partial_success' ? '部分完成' : '失败';
    if (step.status === 'skipped') return '跳过';
    return '待开始';
}

function buildDataSyncStepMeta(step) {
    if (step.status === 'running') {
        const parts = [];
        if (step.detail) parts.push(step.detail);
        if (step.startedAtMs) parts.push(`已用时 ${formatElapsedSeconds((Date.now() - step.startedAtMs) / 1000)}`);
        return parts.join(' · ') || '任务执行中';
    }
    if (step.status === 'completed') {
        return step.durationMs !== null ? `${formatElapsedSeconds(step.durationMs / 1000)} · 已完成` : '已完成';
    }
    if (step.status === 'failed') {
        const detail = step.detail || getDataSyncErrorMessage();
        return detail || '执行失败';
    }
    if (step.status === 'skipped') {
        return '本阶段未执行';
    }
    return '等待执行';
}

function getDataSyncStatusKind(status) {
    if (status === 'success') return 'success';
    if (status === 'partial_success') return 'partial';
    if (status === 'failed') return 'failed';
    return 'idle';
}

function mapDataSyncStatusLabel(kind) {
    if (kind === 'success') return '更新完成';
    if (kind === 'partial') return '部分完成';
    if (kind === 'failed') return '更新失败';
    if (kind === 'running') return '运行中';
    return '空闲';
}

function announceDataSyncResultIfNeeded(result) {
    if (!result?.task_id || dataSyncState.announcedResultTaskId === result.task_id) {
        return;
    }

    dataSyncState.announcedResultTaskId = result.task_id;
    if (result.status === 'success') {
        showToast('success', '数据更新完成');
        startAutoRefreshCountdown();
    } else if (result.status === 'partial_success') {
        showToast('warning', '数据更新部分完成');
        startAutoRefreshCountdown();
    } else if (result.status === 'failed') {
        showToast('error', '数据更新失败，请查看错误详情');
    }
}

function getDataSyncErrorMessage() {
    if (dataSyncState.lastResult?.error?.message) {
        return dataSyncState.lastResult.error.message;
    }
    const latestErrorLog = [...dataSyncState.logEntries].reverse().find((entry) => {
        const level = String(entry.level || '').toLowerCase();
        return level === 'error' || level === 'critical';
    });
    return latestErrorLog?.message || '';
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

/* ==================== 数据更新横幅渲染 ==================== */

function renderDataSyncBanner() {
    const refs = getDataSyncDomRefs();
    if (!refs.banner || !refs.bannerText) return;

    const shouldShow = dataSyncState.featureEnabled && (
        dataSyncState.running ||
        dataSyncState.countdownSeconds > 0 ||
        dataSyncState.statusKind === 'failed'
    );

    refs.banner.classList.toggle('is-visible', shouldShow);
    refs.banner.classList.remove('is-success', 'is-failed');
    dataSyncState.bannerVisible = shouldShow;

    if (!shouldShow) return;

    // 运行中
    if (dataSyncState.running) {
        const stepInfo = dataSyncState.currentStep > 0
            ? `${dataSyncState.currentStep}/${dataSyncState.totalSteps} · ${dataSyncState.stepName || '处理中'}`
            : '准备中';
        refs.bannerText.textContent = `数据更新中 · ${stepInfo}`;
        refs.bannerSub.textContent = dataSyncState.subProgress
            ? `${dataSyncState.subProgress} · ${formatElapsedSeconds(dataSyncState.elapsedSeconds)}`
            : formatElapsedSeconds(dataSyncState.elapsedSeconds);
        renderBannerActions('running');
        return;
    }

    // 倒计时阶段（success 或 partial_success）
    if (dataSyncState.countdownSeconds > 0) {
        refs.banner.classList.add('is-success');
        const statusText = dataSyncState.statusKind === 'partial' ? '部分完成' : '更新完成';
        refs.bannerText.textContent = `✓ ${statusText}`;
        refs.bannerSub.textContent = `${dataSyncState.countdownSeconds}秒后自动刷新...`;
        renderBannerActions('countdown');
        return;
    }

    // 失败态
    if (dataSyncState.statusKind === 'failed') {
        refs.banner.classList.add('is-failed');
        refs.bannerText.textContent = '⚠ 更新失败';
        refs.bannerSub.textContent = getDataSyncErrorMessage() || '请查看详情';
        renderBannerActions('failed');
        return;
    }
}

function renderBannerActions(mode) {
    const refs = getDataSyncDomRefs();
    if (!refs.bannerActions) return;
    clearElement(refs.bannerActions);

    if (mode === 'running') {
        refs.bannerActions.appendChild(createBannerActionButton('查看详情 ▼', () => {
            openDataSyncPanel();
            connectDataSyncEventSource();
        }));
        return;
    }

    if (mode === 'countdown') {
        refs.bannerActions.appendChild(createBannerActionButton('立即刷新', () => {
            clearCountdownTimer();
            executeAutoRefresh();
        }));
        refs.bannerActions.appendChild(createBannerActionButton('取消', () => {
            dataSyncState.autoRefreshCancelled = true;
            clearCountdownTimer();
            dataSyncState.countdownSeconds = 0;
            renderDataSyncBanner();
        }, 'btn-dismiss'));
        return;
    }

    if (mode === 'failed') {
        refs.bannerActions.appendChild(createBannerActionButton('查看详情', () => {
            openDataSyncPanel();
            connectDataSyncEventSource();
        }));
        refs.bannerActions.appendChild(createBannerActionButton('✕', () => {
            dataSyncState.statusKind = 'idle';
            dataSyncState.statusLabel = '空闲';
            renderDataSyncState();
        }, 'btn-dismiss'));
    }
}

function createBannerActionButton(label, onClick, extraClass = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `data-sync-banner-btn ${extraClass}`.trim();
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
}

/* ==================== 3秒倒计时自动刷新 ==================== */

function startAutoRefreshCountdown() {
    clearCountdownTimer();
    dataSyncState.autoRefreshCancelled = false;
    dataSyncState.countdownSeconds = 3;
    renderDataSyncBanner();

    dataSyncState.countdownTimer = setInterval(() => {
        dataSyncState.countdownSeconds--;
        if (dataSyncState.countdownSeconds <= 0) {
            clearCountdownTimer();
            if (!dataSyncState.autoRefreshCancelled) {
                executeAutoRefresh();
            }
        } else {
            renderDataSyncBanner();
        }
    }, 1000);
}

function clearCountdownTimer() {
    if (dataSyncState.countdownTimer) {
        clearInterval(dataSyncState.countdownTimer);
        dataSyncState.countdownTimer = null;
    }
}

function executeAutoRefresh() {
    dataSyncState.countdownSeconds = 0;
    dataSyncState.statusKind = 'idle';
    dataSyncState.statusLabel = '空闲';
    closeDataSyncPanel();
    renderDataSyncState();
    loadPageData();
    showToast('success', '页面数据已自动刷新');
}
