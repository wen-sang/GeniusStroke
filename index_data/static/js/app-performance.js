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
