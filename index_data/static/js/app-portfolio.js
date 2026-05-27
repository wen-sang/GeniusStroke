// app-portfolio.js

async function loadPositions(loadContext = null, append = false) {
    if (!state.currentAccount) return;
    if (isStaleContentLoad(loadContext, 'positions')) return;

    const tbody = document.querySelector('#view-positions .data-table tbody');
    if (!tbody) return;
    const page = append ? (listPaginationState.positions.page + 1) : 1;
    if (!append) {
        resetPaginationState('positions');
        state.currentPositionCodes = [];
        setPositionsRefreshButtonState({ disabled: true, loading: false });
        renderTableStatusRow(tbody, 13, '加载中...');
    } else {
        setPaginationLoading('positions', true);
    }

    const result = await fetchApi(`/trade/positions?account_id=${state.currentAccount}&page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
    if (isStaleContentLoad(loadContext, 'positions')) return;

    if (result === null) {
        listPaginationState.positions.loading = false;
        updatePaginationUI('positions');
        if (!append) {
            renderTableStatusRow(tbody, 13, '加载失败，请稍后重试', { padded: true });
        }
        return;
    }

    const positions = applyPaginatedResult('positions', result, append);

    if (!append && positions.length === 0) {
        renderTableStatusRow(tbody, 13, '暂无持仓', { padded: true });
        return;
    }

    closePositionActionMenus();
    ensurePositionActionMenuBinding(tbody);

    const rowsHtml = positions.map(p => `
        <tr data-code="${escapeHtmlAttr(p.asset_code)}" data-vol="${escapeHtmlAttr(p.total_volume)}" data-cost="${escapeHtmlAttr(p.cost_amount || 0)}" data-realized="${escapeHtmlAttr(p.realized_pnl || 0)}">
            <td class="stock-code">${escapeHtml(p.asset_code)}</td>
            <td class="stock-name center">${escapeHtml(p.asset_name)}</td>
            <td class="price number center" style="font-weight:bold;">${formatNumber(p.current_price, 3)}</td>
            <td class="change number center">--</td>
            <td class="market-value number center">${formatCurrency(p.market_value)}</td>
            <td class="holding-quantity number center">${formatNumber(p.total_volume, 0)}</td>
            <td class="holding-pnl number center">${formatCurrency(p.holding_pnl)}</td>
            <td class="holding-pnl-rate number center">${formatPercent(p.holding_pnl_rate)}</td>
            <td class="history-total-pnl number center">${formatCurrency(p.history_total_pnl)}</td>
            <td class="volume number center">--</td>
            <td class="amount number center">--</td>
            <td class="quote-date center">${formatTimestampCell(p.updated_at)}</td>
            <td class="center row-action-cell">
                <button
                    type="button"
                    class="row-action-trigger"
                    aria-label="打开操作菜单"
                    data-position-action="toggle"
                    data-code="${escapeHtmlAttr(p.asset_code)}"
                >...</button>
                <div class="row-action-menu hidden" data-action-menu="${escapeHtmlAttr(p.asset_code)}">
                    <button type="button" class="row-action-item" data-position-action="trade" data-trade-side="buy" data-code="${escapeHtmlAttr(p.asset_code)}" data-name="${escapeHtmlAttr(p.asset_name)}">
                        <span class="row-action-symbol">+</span>
                        <span>买入</span>
                    </button>
                    <button type="button" class="row-action-item" data-position-action="trade" data-trade-side="sell" data-code="${escapeHtmlAttr(p.asset_code)}" data-name="${escapeHtmlAttr(p.asset_name)}">
                        <span class="row-action-symbol">-</span>
                        <span>卖出</span>
                    </button>
                    <button type="button" class="row-action-item" data-position-action="corporate-action" data-action-type="SPLIT" data-code="${escapeHtmlAttr(p.asset_code)}" data-name="${escapeHtmlAttr(p.asset_name)}">
                        <span class="row-action-symbol">≈</span>
                        <span>份额调整</span>
                    </button>
                    <button type="button" class="row-action-item" data-position-action="corporate-action" data-action-type="CASH_DIVIDEND" data-code="${escapeHtmlAttr(p.asset_code)}" data-name="${escapeHtmlAttr(p.asset_name)}">
                        <span class="row-action-symbol">¥</span>
                        <span>现金分红</span>
                    </button>
                    <button type="button" class="row-action-item" data-position-action="corporate-action" data-action-type="DIVIDEND_REINVEST" data-code="${escapeHtmlAttr(p.asset_code)}" data-name="${escapeHtmlAttr(p.asset_name)}">
                        <span class="row-action-symbol">↺</span>
                        <span>红利再投</span>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');

    renderTableRows(tbody, rowsHtml, append);

    Array.from(tbody.querySelectorAll('tr')).slice(-positions.length).forEach((row, index) => {
        const position = positions[index];
        applyPnLColorToRow(row, position.holding_pnl, position.history_total_pnl);
    });

    state.currentPositionCodes = listPaginationState.positions.items.map(p => p.asset_code);
    setPositionsRefreshButtonState({ disabled: false, loading: false });
    updateRealTimePrices(positions.map(p => p.asset_code), loadContext);
}

function togglePositionActionMenu(event, code) {
    event.stopPropagation();
    const menu = findPositionActionMenu(code);
    if (!menu) return;
    const willOpen = menu.classList.contains('hidden');
    closePositionActionMenus();
    if (willOpen) {
        menu.classList.remove('hidden');
    }
}

function closePositionActionMenus() {
    document.querySelectorAll('.row-action-menu').forEach((menu) => {
        menu.classList.add('hidden');
    });
}

function openPositionTradeAction(event, type, stockCode, stockName) {
    event.stopPropagation();
    closePositionActionMenus();
    openTradeModal(type, stockCode, stockName);
}

function openPositionCorporateAction(event, actionType, stockCode, stockName) {
    event.stopPropagation();
    closePositionActionMenus();
    openCorporateActionModal(actionType, stockCode, stockName);
}

function ensurePositionActionMenuBinding(tbody) {
    if (!tbody || tbody.dataset.positionActionBound === 'true') return;

    tbody.addEventListener('click', (event) => {
        const actionButton = event.target.closest('[data-position-action]');
        if (!actionButton || !tbody.contains(actionButton)) return;

        const code = actionButton.dataset.code || '';
        const name = actionButton.dataset.name || '';
        const action = actionButton.dataset.positionAction;

        if (action === 'toggle') {
            togglePositionActionMenu(event, code);
            return;
        }
        if (action === 'trade') {
            openPositionTradeAction(event, actionButton.dataset.tradeSide, code, name);
            return;
        }
        if (action === 'corporate-action') {
            openPositionCorporateAction(event, actionButton.dataset.actionType, code, name);
        }
    });

    tbody.dataset.positionActionBound = 'true';
}

function findPositionActionMenu(code) {
    return Array.from(document.querySelectorAll('.row-action-menu'))
        .find((menu) => menu.dataset.actionMenu === String(code)) || null;
}



async function updateRealTimePrices(codes, loadContext = null, prefetchedResult = null) {
    if (!codes || codes.length === 0) return null;
    if (isStaleContentLoad(loadContext, 'positions')) return null;
    if (!window.quoteService) return null;

    const hasQuoteValue = (value) => value !== null && value !== undefined && !isNaN(value);
    const applyQuotesToRows = (quotes) => {
        for (const [code, quote] of Object.entries(quotes || {})) {
            const row = document.querySelector(`tr[data-code="${code}"]`);
            if (!row) continue;

            const priceEl = row.querySelector('.price');
            if (priceEl && hasQuoteValue(quote.price)) {
                priceEl.textContent = formatNumber(quote.price, 3);
                if (hasQuoteValue(quote.change_pct)) {
                    priceEl.style.color = getColor(quote.change_pct);
                }
            }

            const changeEl = row.querySelector('.change');
            if (changeEl && hasQuoteValue(quote.change_pct)) {
                changeEl.textContent = formatQuotePercent(quote.change_pct);
                changeEl.style.color = getColor(quote.change_pct);
            }

            const vol = parseFloat(row.dataset.vol || '0');
            const cost = parseFloat(row.dataset.cost || '0');
            const realized = parseFloat(row.dataset.realized || '0');

            const mvEl = row.querySelector('.market-value');
            if (mvEl && vol && hasQuoteValue(quote.price)) {
                const mv = vol * quote.price;
                mvEl.textContent = formatCurrency(mv);

                const holdingPnl = mv - cost;
                const holdingPnlRate = cost > 0 ? holdingPnl / cost : null;
                const historyTotalPnl = realized + holdingPnl;

                const holdingPnlEl = row.querySelector('.holding-pnl');
                const holdingPnlRateEl = row.querySelector('.holding-pnl-rate');
                const historyTotalPnlEl = row.querySelector('.history-total-pnl');
                if (holdingPnlEl) holdingPnlEl.textContent = formatCurrency(holdingPnl);
                if (holdingPnlRateEl) holdingPnlRateEl.textContent = formatPercent(holdingPnlRate);
                if (historyTotalPnlEl) historyTotalPnlEl.textContent = formatCurrency(historyTotalPnl);

                applyPnLColorToRow(row, holdingPnl, historyTotalPnl);
            }

            const volumeEl = row.querySelector('.volume');
            if (volumeEl && hasQuoteValue(quote.volume)) volumeEl.textContent = formatVolume(quote.volume);

            const amountEl = row.querySelector('.amount');
            if (amountEl && hasQuoteValue(quote.amount)) amountEl.textContent = formatAmount(quote.amount);

            const dateEl = row.querySelector('.quote-date');
            if (dateEl && (quote.refreshed_at || quote.date)) {
                dateEl.innerHTML = formatTimestampCell(quote.refreshed_at || quote.date);
            }

            row.dataset.quoteSource = quote.source || '';
            row.title = buildRowQuoteTitle(quote);
        }
    };

    const chunks = window.quoteService.chunkCodes(codes, 3);
    const aggregated = {
        summary: { total: 0, cache: 0, realtime: 0, staleCache: 0, fallback: 0 },
        meta: null,
    };

    for (let index = 0; index < chunks.length; index += 1) {
        if (isStaleContentLoad(loadContext, 'positions')) return aggregated;
        const chunk = chunks[index];
        const result = (prefetchedResult && chunks.length === 1)
            ? prefetchedResult
            : await window.quoteService.fetchQuotes(chunk);
        const quotes = result ? result.quotes : null;
        if (!quotes) continue;

        applyQuotesToRows(quotes);
        if (!aggregated.meta && result.meta) {
            aggregated.meta = result.meta;
        }
        if (result.summary) {
            Object.keys(aggregated.summary).forEach((key) => {
                aggregated.summary[key] += result.summary[key] || 0;
            });
        }

        if (chunks.length > 1 && index < chunks.length - 1) {
            await new Promise((resolve) => setTimeout(resolve, 150));
        }
    }

    return aggregated;
}

function buildRowQuoteTitle(quote) {
    if (!quote) return '';
    const source = quote.source || 'unknown';
    const originSource = quote.origin_source ? `，原始来源: ${quote.origin_source}` : '';
    const refreshedAt = quote.refreshed_at ? `，刷新时间: ${quote.refreshed_at}` : '';
    return `来源: ${source}${originSource}${refreshedAt}`;
}

function setPositionsRefreshButtonState({ disabled = false, loading = false } = {}) {
    const button = document.getElementById('btn-refresh-positions');
    if (!button) return;
    button.disabled = disabled || loading;
    button.classList.toggle('is-loading', loading);
    button.setAttribute('aria-busy', loading ? 'true' : 'false');
}

async function refreshPositionsQuotes() {
    if (!state.currentAccount || state.currentTab !== 'positions') return;
    if (!state.currentPositionCodes || state.currentPositionCodes.length === 0) {
        showToast('info', '当前没有可刷新的持仓行情');
        return;
    }
    if (!window.quoteService || state.positionsQuoteLoading) return;

    state.positionsQuoteLoading = true;
    setPositionsRefreshButtonState({ loading: true });

    try {
        showToast('info', '正在刷新持仓行情...');
        const result = await updateRealTimePrices(
            state.currentPositionCodes,
            createCurrentContentLoadContext('positions')
        );
        if (!result) return;
        showToast('success', window.quoteService.buildStatusMessage(result.summary, result.meta));
    } finally {
        state.positionsQuoteLoading = false;
        setPositionsRefreshButtonState({ disabled: state.currentPositionCodes.length === 0, loading: false });
    }
}

function applyPnLColorToRow(row, holdingPnl, historyTotalPnl) {
    if (!row) return;
    const holdingPnlEl = row.querySelector('.holding-pnl');
    const holdingPnlRateEl = row.querySelector('.holding-pnl-rate');
    const historyTotalPnlEl = row.querySelector('.history-total-pnl');
    if (holdingPnlEl) holdingPnlEl.style.color = getColor(holdingPnl);
    if (holdingPnlRateEl) holdingPnlRateEl.style.color = getColor(holdingPnl);
    if (historyTotalPnlEl) historyTotalPnlEl.style.color = getColor(historyTotalPnl);
}

function formatQuotePercent(value) {
    if (value === null || value === undefined || isNaN(value)) return '--';
    const sign = value > 0 ? '+' : '';
    return `${sign}${Number(value).toFixed(2)}%`;
}

function getColor(val) {
    if (val > 0) return 'var(--up-red)';
    if (val < 0) return 'var(--down-green)';
    return '';
}

// ==================== 页面逻辑: 全局遮罩 ====================
