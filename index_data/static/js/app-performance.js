// app-performance.js

function formatPerformancePercent(value, includeSign = true) {
    if (value === null || value === undefined || isNaN(value)) return '--';
    return formatPercent(value, includeSign);
}

function formatPerformanceNumber(value, decimals = 2) {
    if (value === null || value === undefined || isNaN(value)) return '--';
    return formatNumber(value, decimals);
}

function formatPerformanceCurrency(value) {
    if (value === null || value === undefined || isNaN(value)) return '--';
    return formatCurrency(value);
}

function formatPerformanceDateCompact(value) {
    if (!value) return '--';
    return String(value).replace(/-/g, '');
}

function setPerformanceValue(id, text, colorValue = null) {
    setText(id, text);
    if (colorValue !== null && colorValue !== undefined) {
        setColor(id, colorValue);
    }
}

function resetPerformanceView() {
    [
        'performance-net-value',
        'performance-cumulative-pnl-existing',
        'performance-cumulative-pnl-performance',
        'performance-cumulative-twr',
        'performance-cumulative-mwr',
        'performance-annualized-twr',
        'performance-annualized-xirr',
        'performance-max-drawdown',
        'performance-annualized-volatility',
        'performance-win-rate',
        'performance-profit-loss-ratio',
        'performance-average-win-amount',
        'performance-average-loss-amount',
        'performance-total-trade-count',
        'performance-average-holding-days',
        'performance-expectancy'
    ].forEach((id) => setText(id, '--'));
    setText('performance-data-updated-to', '数据更新至 --');
    setText('performance-drawdown-period', '--');
}

async function loadPerformance(loadContext = null) {
    if (!state.currentAccount || state.isEmptyAccountState) return;
    if (isStaleContentLoad(loadContext, 'performance')) return;

    resetPerformanceView();
    const data = await fetchApi(`/account/performance?account_id=${state.currentAccount}`);
    if (isStaleContentLoad(loadContext, 'performance')) return;
    if (!data) return;

    renderPerformance(data);
}

function renderPerformance(data) {
    const displayDate = data.data_updated_to ? formatPerformanceDateCompact(data.data_updated_to) : '--';
    setText('performance-data-updated-to', `数据更新至 ${displayDate}`);
    setPerformanceValue('performance-net-value', formatPerformanceNumber(data.net_value, 4));
    setPerformanceValue(
        'performance-cumulative-pnl-existing',
        formatPerformanceCurrency(data.cumulative_pnl_existing),
        data.cumulative_pnl_existing
    );
    setPerformanceValue(
        'performance-cumulative-pnl-performance',
        formatPerformanceCurrency(data.cumulative_pnl_performance),
        data.cumulative_pnl_performance
    );
    setPerformanceValue('performance-cumulative-twr', formatPerformancePercent(data.cumulative_twr), data.cumulative_twr);
    setPerformanceValue('performance-cumulative-mwr', formatPerformancePercent(data.cumulative_mwr), data.cumulative_mwr);
    setPerformanceValue('performance-annualized-twr', formatPerformancePercent(data.annualized_twr), data.annualized_twr);
    setPerformanceValue('performance-annualized-xirr', formatPerformancePercent(data.annualized_xirr), data.annualized_xirr);
    setPerformanceValue('performance-max-drawdown', formatPerformancePercent(data.max_drawdown, false), data.max_drawdown ? -data.max_drawdown : null);
    setPerformanceValue('performance-annualized-volatility', formatPerformancePercent(data.annualized_volatility, false));
    setPerformanceValue('performance-win-rate', formatPerformancePercent(data.win_rate, false));
    setText(
        'performance-profit-loss-ratio',
        data.profit_loss_ratio_is_infinite ? '∞' : formatPerformanceNumber(data.profit_loss_ratio, 2)
    );
    setPerformanceValue('performance-average-win-amount', formatPerformanceCurrency(data.average_win_amount));
    setPerformanceValue('performance-average-loss-amount', formatPerformanceCurrency(data.average_loss_amount));
    setText('performance-total-trade-count', Number.isFinite(Number(data.total_trade_count)) ? String(data.total_trade_count) : '0');
    setText('performance-average-holding-days', formatHoldingDays(data.average_holding_days));
    setPerformanceValue('performance-expectancy', formatPerformanceCurrency(data.expectancy), data.expectancy);
    setText('performance-drawdown-period', buildDrawdownPeriodText(data));
}

function buildDrawdownPeriodText(data) {
    if (!data.max_drawdown_start_date || !data.max_drawdown_end_date) return '--';
    const start = formatPerformanceDateCompact(data.max_drawdown_start_date);
    const end = formatPerformanceDateCompact(data.max_drawdown_end_date);
    const recovery = data.max_drawdown_recovery_date
        ? formatPerformanceDateCompact(data.max_drawdown_recovery_date)
        : '--';
    return `${start} - ${end} / 修复 ${recovery}`;
}

function formatHoldingDays(value) {
    if (value === null || value === undefined || isNaN(value)) return '--';
    return `${formatPerformanceNumber(value, 1)} 天`;
}


// ==================== 周期视图 ====================

let performanceSubTab = 'overview';

function switchPerformanceTab(tabName, loadContext = null) {
    performanceSubTab = tabName;
    document.querySelectorAll('#view-performance .performance-sub-tabs .sub-tab-item').forEach((tab) => {
        const isTarget = tab.getAttribute('data-tab') === tabName;
        tab.classList.toggle('active', isTarget);
        tab.setAttribute('aria-selected', isTarget ? 'true' : 'false');
    });
    document.getElementById('performance-overview-panel')?.classList.toggle('hidden', tabName !== 'overview');
    document.getElementById('performance-periods-panel')?.classList.toggle('hidden', tabName !== 'periods');
    if (!state.currentAccount) return;
    if (tabName === 'periods') {
        loadPerformancePeriods(loadContext);
    } else {
        loadPerformance(loadContext);
    }
}

function loadPerformanceTabData(loadContext = null) {
    if (performanceSubTab === 'periods') {
        loadPerformancePeriods(loadContext);
    } else {
        loadPerformance(loadContext);
    }
}

const performancePeriodState = {
    period: 'month',
    startDate: '',
    endDate: ''
};

function initPerformancePeriodView() {
    const switcher = document.getElementById('performance-period-switcher');
    if (switcher) {
        switcher.addEventListener('click', (event) => {
            const btn = event.target.closest('[data-period]');
            if (!btn || btn.dataset.period === performancePeriodState.period) return;
            performancePeriodState.period = btn.dataset.period;
            switcher.querySelectorAll('[data-period]').forEach((item) => {
                const active = item === btn;
                item.classList.toggle('active', active);
                item.setAttribute('aria-selected', active ? 'true' : 'false');
            });
            if (typeof syncCapsuleSlider === 'function') syncCapsuleSlider(switcher);
            togglePerformancePeriodRange();
            loadPerformancePeriods(null);
        });
    }

    const applyBtn = document.getElementById('performance-period-apply');
    if (applyBtn) {
        applyBtn.addEventListener('click', () => {
            const start = document.getElementById('performance-period-start').value;
            const end = document.getElementById('performance-period-end').value;
            if (!start || !end) {
                if (typeof showToast === 'function') showToast('error', '请选择开始和结束日期');
                return;
            }
            if (start > end) {
                if (typeof showToast === 'function') showToast('error', '开始日期不能晚于结束日期');
                return;
            }
            performancePeriodState.startDate = start;
            performancePeriodState.endDate = end;
            loadPerformancePeriods(null);
        });
    }

    const resetBtn = document.getElementById('performance-period-reset');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            performancePeriodState.startDate = '';
            performancePeriodState.endDate = '';
            const startInput = document.getElementById('performance-period-start');
            const endInput = document.getElementById('performance-period-end');
            if (startInput) startInput.value = '';
            if (endInput) endInput.value = '';
            loadPerformancePeriods(null);
        });
    }
}

function togglePerformancePeriodRange() {
    const range = document.querySelector('.performance-period-range');
    if (range) range.classList.toggle('hidden', performancePeriodState.period !== 'custom');
}

async function loadPerformancePeriods(loadContext = null) {
    if (!state.currentAccount || state.isEmptyAccountState) return;
    if (isStaleContentLoad(loadContext, 'performance')) return;

    if (performancePeriodState.period === 'custom'
        && (!performancePeriodState.startDate || !performancePeriodState.endDate)) {
        renderPerformancePeriodHint('请选择起止日期后点击查询');
        return;
    }

    const params = new URLSearchParams({
        account_id: state.currentAccount,
        granularity: performancePeriodState.period
    });
    if (performancePeriodState.period === 'custom') {
        params.set('start_date', performancePeriodState.startDate);
        params.set('end_date', performancePeriodState.endDate);
    }

    const data = await fetchApi(`/account/performance/periods?${params.toString()}`);
    if (isStaleContentLoad(loadContext, 'performance')) return;
    if (!data) return;

    renderPerformancePeriods(data.items || []);
}

function renderPerformancePeriodHint(text) {
    const tbody = document.getElementById('performance-period-tbody');
    if (!tbody) return;
    tbody.textContent = '';
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 12;
    cell.className = 'performance-period-empty';
    cell.textContent = text;
    row.appendChild(cell);
    tbody.appendChild(row);
}

function renderPerformancePeriods(items) {
    const tbody = document.getElementById('performance-period-tbody');
    if (!tbody) return;
    tbody.textContent = '';

    if (!items.length) {
        renderPerformancePeriodHint('暂无周期数据');
        return;
    }

    items.slice().reverse().forEach((item) => {
        const row = document.createElement('tr');
        appendPeriodCell(row, item.period_label);
        appendPeriodCell(row, `${formatPerformanceDateCompact(item.period_start)}~${formatPerformanceDateCompact(item.period_end)}`);
        appendPeriodCell(row, formatPerformancePercent(item.cumulative_twr), item.cumulative_twr);
        appendPeriodCell(row, formatPerformanceCurrency(item.period_pnl), item.period_pnl);
        appendPeriodCell(row, formatPerformancePercent(item.annualized_twr), item.annualized_twr);
        appendPeriodCell(row, formatPerformancePercent(item.annualized_xirr), item.annualized_xirr);
        appendPeriodCell(
            row,
            formatPerformancePercent(item.max_drawdown, false),
            item.max_drawdown ? -item.max_drawdown : null
        );
        appendPeriodCell(row, formatPerformancePercent(item.annualized_volatility, false));
        appendPeriodCell(row, formatPerformancePercent(item.win_rate, false));
        appendPeriodCell(
            row,
            item.profit_loss_ratio_is_infinite ? '∞' : formatPerformanceNumber(item.profit_loss_ratio, 2)
        );
        appendPeriodCell(row, String(item.total_trade_count || 0));
        appendPeriodCell(row, formatHoldingDays(item.average_holding_days));
        tbody.appendChild(row);
    });
}

function appendPeriodCell(row, text, colorValue = null) {
    const cell = document.createElement('td');
    cell.textContent = text;
    if (colorValue !== null && colorValue !== undefined && !isNaN(colorValue)) {
        cell.style.color = colorValue > 0 ? 'var(--up-red)' : (colorValue < 0 ? 'var(--down-green)' : '');
    }
    row.appendChild(cell);
}

document.addEventListener('DOMContentLoaded', initPerformancePeriodView);
