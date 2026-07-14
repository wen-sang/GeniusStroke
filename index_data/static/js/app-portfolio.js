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
        renderTableSkeletonRows(tbody, 13);
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
        <tr data-code="${escapeHtmlAttr(p.asset_code)}" data-asset-type="${escapeHtmlAttr(p.asset_type || '')}" data-vol="${escapeHtmlAttr(p.total_volume)}" data-cost="${escapeHtmlAttr(p.cost_amount || 0)}" data-realized="${escapeHtmlAttr(p.realized_pnl || 0)}">
            <td class="stock-code">${escapeHtml(p.asset_code)}</td>
            <td class="stock-name center">${escapeHtml(p.asset_name)}</td>
            <td class="price number" style="font-weight:bold;">${formatNumber(p.current_price, 3)}</td>
            <td class="change number">--</td>
            <td class="market-value number">${formatCurrency(p.market_value)}</td>
            <td class="holding-quantity number">${formatNumber(p.total_volume, 0)}</td>
            <td class="holding-pnl number">${formatCurrency(p.holding_pnl)}</td>
            <td class="holding-pnl-rate number">${formatPercent(p.holding_pnl_rate)}</td>
            <td class="history-total-pnl number">${formatCurrency(p.history_total_pnl)}</td>
            <td class="volume number">--</td>
            <td class="amount number">--</td>
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
                    ${renderPositionCorporateActionButtons(p)}
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

function renderPositionCorporateActionButtons(position) {
    const assetType = String(position.asset_type || '').toUpperCase();
    const code = escapeHtmlAttr(position.asset_code);
    const name = escapeHtmlAttr(position.asset_name);
    if (assetType === 'STOCK') {
        return `
                    <button type="button" class="row-action-item" data-position-action="stock-corporate-action" data-code="${code}" data-name="${name}">
                        <span class="row-action-symbol">除</span>
                        <span>股票除权除息</span>
                    </button>
        `;
    }
    return `
                    <button type="button" class="row-action-item" data-position-action="corporate-action" data-action-type="SPLIT" data-code="${code}" data-name="${name}">
                        <span class="row-action-symbol">≈</span>
                        <span>份额调整</span>
                    </button>
                    <button type="button" class="row-action-item" data-position-action="corporate-action" data-action-type="CASH_DIVIDEND" data-code="${code}" data-name="${name}">
                        <span class="row-action-symbol">¥</span>
                        <span>现金分红</span>
                    </button>
                    <button type="button" class="row-action-item" data-position-action="corporate-action" data-action-type="DIVIDEND_REINVEST" data-code="${code}" data-name="${name}">
                        <span class="row-action-symbol">↺</span>
                        <span>红利再投</span>
                    </button>
    `;
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

function openPositionStockCorporateAction(event, stockCode, stockName) {
    event.stopPropagation();
    closePositionActionMenus();
    openStockCorporateActionModal(stockCode, stockName);
}

function openStockCorporateActionModal(stockCode, stockName, options = {}) {
    const modal = document.getElementById('stockCorporateActionModal');
    if (!modal) return;
    setupStockCorporateActionForm();

    stockCorporateActionState.mode = options.mode || 'create';
    stockCorporateActionState.bundleRefId = options.bundleRefId || null;
    document.getElementById('stockCorporateActionModalTitle').textContent = stockCorporateActionState.mode === 'edit'
        ? '修改股票除权除息'
        : '股票除权除息';
    document.getElementById('btn-save-stock-corporate-action').textContent = stockCorporateActionState.mode === 'edit'
        ? '确认修改'
        : '确定保存';
    document.getElementById('sca-event-type').disabled = stockCorporateActionState.mode === 'edit';

    if (options.bundleData) {
        fillStockCorporateActionBundle(options.bundleData, stockName);
        modal.classList.add('active');
        setTimeout(() => document.getElementById('sca-record-date')?.focus(), 60);
        return;
    }

    document.getElementById('sca-asset-code').value = stockCode || '';
    document.getElementById('sca-asset-name').value = stockName || '';
    document.getElementById('sca-event-type').value = 'CASH_AND_SHARE_CHANGE';
    document.getElementById('sca-record-date').value = '';
    document.getElementById('sca-ex-date').value = getTodayDateString();
    document.getElementById('sca-cash-pay-date').value = getTodayDateString();
    document.getElementById('sca-cash-base-unit').value = 'PER_10_SHARES';
    document.getElementById('sca-cash-base-qty').value = '10';
    document.getElementById('sca-cash-amount').value = '';
    document.getElementById('sca-ratio-from').value = '10';
    document.getElementById('sca-ratio-to').value = '';
    document.getElementById('sca-share-subtype').value = 'CAPITAL_TRANSFER';
    document.getElementById('sca-remark').value = '';
    resetStockCorporateActionPreview();
    toggleStockCorporateActionFields();
    modal.classList.add('active');
    setTimeout(() => document.getElementById('sca-record-date')?.focus(), 60);
}

function closeStockCorporateActionModal() {
    document.getElementById('stockCorporateActionModal')?.classList.remove('active');
    stockCorporateActionState.mode = 'create';
    stockCorporateActionState.bundleRefId = null;
}

function fillStockCorporateActionBundle(bundleData, preferredName = '') {
    const actions = bundleData.actions || [];
    const cashAction = actions.find((item) => item.action_type === 'CASH_DIVIDEND') || null;
    const shareAction = actions.find((item) => item.action_type === 'SPLIT') || null;
    const primary = cashAction || shareAction || {};

    let eventType = 'CASH_AND_SHARE_CHANGE';
    if (cashAction && !shareAction) eventType = 'CASH_DIVIDEND';
    if (!cashAction && shareAction) eventType = 'SHARE_CHANGE';

    document.getElementById('sca-event-type').value = eventType;
    document.getElementById('sca-asset-code').value = primary.asset_code || '';
    document.getElementById('sca-asset-name').value = preferredName || primary.asset_name || '';
    document.getElementById('sca-record-date').value = primary.record_date || '';
    document.getElementById('sca-ex-date').value = primary.ex_date || primary.effective_date || '';
    document.getElementById('sca-cash-pay-date').value = cashAction?.effective_date || '';
    document.getElementById('sca-cash-base-unit').value = cashAction?.cash_base_unit || 'PER_10_SHARES';
    document.getElementById('sca-cash-base-qty').value = cashAction?.cash_base_qty ?? (cashAction ? '10' : '');
    document.getElementById('sca-cash-amount').value = cashAction?.cash_amount ?? '';
    document.getElementById('sca-ratio-from').value = shareAction?.ratio_from ?? '10';
    document.getElementById('sca-ratio-to').value = shareAction?.ratio_to ?? '';
    document.getElementById('sca-share-subtype').value = shareAction?.share_change_subtype || 'CAPITAL_TRANSFER';
    document.getElementById('sca-remark').value = primary.remark || '';

    resetStockCorporateActionPreview();
    toggleStockCorporateActionFields();
}

function setupStockCorporateActionForm() {
    const eventType = document.getElementById('sca-event-type');
    if (eventType && eventType.dataset.bound !== 'true') {
        eventType.addEventListener('change', () => {
            toggleStockCorporateActionFields();
            resetStockCorporateActionPreview();
        });
        eventType.dataset.bound = 'true';
    }
    const cashBaseUnit = document.getElementById('sca-cash-base-unit');
    if (cashBaseUnit && cashBaseUnit.dataset.bound !== 'true') {
        cashBaseUnit.addEventListener('change', () => {
            const baseQty = document.getElementById('sca-cash-base-qty');
            if (!baseQty) return;
            if (cashBaseUnit.value === 'PER_SHARE') baseQty.value = '1';
            if (cashBaseUnit.value === 'PER_10_SHARES') baseQty.value = '10';
            if (cashBaseUnit.value === 'PER_N_SHARES') baseQty.value = '';
            resetStockCorporateActionPreview();
        });
        cashBaseUnit.dataset.bound = 'true';
    }
}

function toggleStockCorporateActionFields() {
    const eventType = document.getElementById('sca-event-type')?.value || 'CASH_AND_SHARE_CHANGE';
    const showCash = eventType === 'CASH_DIVIDEND' || eventType === 'CASH_AND_SHARE_CHANGE';
    const showShare = eventType === 'SHARE_CHANGE' || eventType === 'CASH_AND_SHARE_CHANGE';
    [
        'sca-cash-pay-date-group',
        'sca-cash-base-unit-group',
        'sca-cash-base-qty-group',
        'sca-cash-amount-group'
    ].forEach(id => document.getElementById(id)?.classList.toggle('hidden', !showCash));
    [
        'sca-ratio-from-group',
        'sca-ratio-to-group',
        'sca-share-subtype-group'
    ].forEach(id => document.getElementById(id)?.classList.toggle('hidden', !showShare));
}

function resetStockCorporateActionPreview() {
    const content = document.getElementById('sca-preview-content');
    if (content) content.textContent = '填写参数后点击“预览结果”查看影响。';
}

function collectStockCorporateActionPayload() {
    if (!state.currentAccount) throw new Error('当前没有可用账户');
    const eventType = document.getElementById('sca-event-type').value;
    const payload = {
        account_id: state.currentAccount,
        asset_code: document.getElementById('sca-asset-code').value.trim(),
        event_type: eventType,
        record_date: document.getElementById('sca-record-date').value,
        ex_date: document.getElementById('sca-ex-date').value,
        remark: document.getElementById('sca-remark').value.trim()
    };
    if (!payload.asset_code) throw new Error('股票代码不能为空');
    if (!payload.record_date) throw new Error('请选择股权登记日');
    if (!payload.ex_date) throw new Error('请选择除权除息日');

    const needsCash = eventType === 'CASH_DIVIDEND' || eventType === 'CASH_AND_SHARE_CHANGE';
    const needsShare = eventType === 'SHARE_CHANGE' || eventType === 'CASH_AND_SHARE_CHANGE';
    if (needsCash) {
        payload.cash_pay_date = document.getElementById('sca-cash-pay-date').value;
        payload.cash_base_unit = document.getElementById('sca-cash-base-unit').value;
        payload.cash_amount = parseFloat(document.getElementById('sca-cash-amount').value);
        if (!payload.cash_pay_date) throw new Error('请选择现金到账日');
        if (isNaN(payload.cash_amount) || payload.cash_amount <= 0) throw new Error('请输入合法的派现金额');
        if (payload.cash_base_unit === 'PER_SHARE') payload.cash_base_qty = 1;
        if (payload.cash_base_unit === 'PER_10_SHARES') payload.cash_base_qty = 10;
        if (payload.cash_base_unit === 'PER_N_SHARES') {
            payload.cash_base_qty = parseFloat(document.getElementById('sca-cash-base-qty').value);
            if (isNaN(payload.cash_base_qty) || payload.cash_base_qty <= 0) throw new Error('请输入合法的基准股数');
        }
    }
    if (needsShare) {
        payload.ratio_from = Number(document.getElementById('sca-ratio-from').value);
        payload.ratio_to = Number(document.getElementById('sca-ratio-to').value);
        payload.share_change_subtype = document.getElementById('sca-share-subtype').value;
        if (!Number.isInteger(payload.ratio_from) || payload.ratio_from <= 0 || !Number.isInteger(payload.ratio_to) || payload.ratio_to <= 0) {
            throw new Error('请输入合法的股份变动比例');
        }
        if (payload.ratio_to <= payload.ratio_from) throw new Error('本期只支持增加股份');
    }
    return payload;
}

async function previewStockCorporateAction() {
    const button = document.getElementById('btn-preview-stock-corporate-action');
    const oldText = button?.textContent || '预览结果';
    try {
        const payload = collectStockCorporateActionPayload();
        if (button) {
            button.textContent = '预览中...';
            button.disabled = true;
        }
        const result = await fetchApiOrThrow('/stock-corporate-actions/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        renderStockCorporateActionPreview(result.data || {});
    } catch (err) {
        showToast('error', `预览失败: ${err.message}`);
    } finally {
        if (button) {
            button.textContent = oldText;
            button.disabled = false;
        }
    }
}

async function submitStockCorporateAction() {
    const button = document.getElementById('btn-save-stock-corporate-action');
    const oldText = button?.textContent || '确定保存';
    try {
        const payload = collectStockCorporateActionPayload();
        const isEdit = stockCorporateActionState.mode === 'edit' && stockCorporateActionState.bundleRefId;
        if (button) {
            button.textContent = isEdit ? '修改中...' : '保存中...';
            button.disabled = true;
        }
        const endpoint = isEdit
            ? `/stock-corporate-actions/bundles/${encodeURIComponent(stockCorporateActionState.bundleRefId)}`
            : '/stock-corporate-actions';
        await fetchApiOrThrow(endpoint, {
            method: isEdit ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        closeStockCorporateActionModal();
        showToast('success', isEdit ? '股票除权除息已修改' : '股票除权除息已创建');
        loadPageData();
    } catch (err) {
        showToast('error', `提交失败: ${err.message}`);
    } finally {
        if (button) {
            button.textContent = oldText;
            button.disabled = false;
        }
    }
}

function renderStockCorporateActionPreview(data) {
    const content = document.getElementById('sca-preview-content');
    if (!content) return;
    const rows = [];
    if (data.cash) {
        rows.push(`<div>登记日参与股数：${escapeHtml(formatCorporateActionQuantity(data.cash.eligible_qty))}</div>`);
        rows.push(`<div>现金分红：${escapeHtml(formatCorporateActionAmount(data.cash.dividend_cash))}</div>`);
    }
    if (data.share) {
        rows.push(`<div>新增股份：${escapeHtml(formatCorporateActionQuantity(data.share.share_delta))}</div>`);
        rows.push(`<div>除权后持股：${escapeHtml(formatCorporateActionQuantity(data.share.adjusted_qty))}</div>`);
        rows.push(`<div>股份比例：${escapeHtml(String(data.share.split_ratio_text || '--'))}</div>`);
    }
    content.innerHTML = rows.length ? rows.join('') : '暂无可预览影响。';
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
            return;
        }
        if (action === 'stock-corporate-action') {
            openPositionStockCorporateAction(event, code, name);
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

    const chunks = window.quoteService.chunkCodes(codes, 5);
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
