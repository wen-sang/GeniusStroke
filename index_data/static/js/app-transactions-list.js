// app-transactions-list.js
// 交易 Tab 列表渲染：交易记录与企业事件两个子列表的行构建与分页加载

function getCorporateActionStatusChip(status) {
    if (status === 'PENDING') {
        return '<span class="status-chip status-chip-pending">待确认</span>';
    }
    if (status === 'ACTIVE') {
        return '<span class="status-chip status-chip-active">有效</span>';
    }
    if (status === 'CONFIRMED') {
        return '<span class="status-chip status-chip-active">已确认</span>';
    }
    if (status === 'CANCELLED') {
        return '<span class="status-chip status-chip-cancelled">已作废</span>';
    }
    if (status === 'PARTIAL') {
        return '<span class="status-chip status-chip-pending">部分确认</span>';
    }
    return `<span class="status-chip status-chip-pending">${escapeHtml(status || '--')}</span>`;
}

function getTradeOrderTypeClass(item) {
    if (item.side === 'BUY') return 'positive';
    if (item.side === 'SELL') return 'negative';
    return '';
}

function getTradeOrderPriceText(item) {
    if (item.order_type === 'SPLIT_ADJUST') return '--';
    return formatNumber(item.price, 3);
}

function getTradeOrderQuantityText(item) {
    return formatNumber(item.volume, 0);
}

function getTradeOrderAmountText(item) {
    if (item.order_type === 'SPLIT_ADJUST') return '--';
    return formatCurrency(item.amount);
}

function hasTradeOrderRealizedResult(item) {
    return item.side === 'SELL'
        && item.status === 'ACTIVE'
        && item.realized_return_rate !== null
        && item.realized_return_rate !== undefined
        && Number.isFinite(Number(item.realized_return_rate));
}

function getTradeOrderRealizedPnlText(item) {
    if (!hasTradeOrderRealizedResult(item)) return '--';
    return formatCurrency(item.realized_pnl);
}

function getTradeOrderRealizedReturnRateText(item) {
    if (!hasTradeOrderRealizedResult(item)) return '--';
    return formatPercent(item.realized_return_rate);
}

function getTradeOrderActionHtml(item) {
    if (item.editable_via === 'trade') {
        return `<a href="javascript:void(0)" data-action="edit-transaction" data-id="${item.row_id}" style="color: var(--primary); text-decoration: none; font-size: 13px;">修改</a>`;
    }
    return '--';
}

function getCorporateActionSummaryText(item) {
    if (item.derived_summary && item.derived_summary.summary_text) {
        return escapeHtml(item.derived_summary.summary_text);
    }
    if (item.action_type === 'SPLIT' && item.ratio_from && item.ratio_to) {
        return `${item.ratio_from}:${item.ratio_to}`;
    }
    if (item.cash_amount !== null && item.cash_amount !== undefined) {
        const unitText = item.cash_base_unit === 'PER_10_SHARES' ? '每10份' : '每份';
        return `${unitText} ${formatNumber(item.cash_amount, 4)}`;
    }
    return '--';
}

function getCorporateActionErrorText(item) {
    return item.last_error_message ? escapeHtml(item.last_error_message) : '--';
}

function aggregateCorporateActionStatus(actions) {
    const statuses = actions.map((item) => item.status || 'PENDING');
    if (statuses.every((status) => status === 'PENDING')) return 'PENDING';
    if (statuses.every((status) => status === 'CONFIRMED')) return 'CONFIRMED';
    if (statuses.every((status) => status === 'CANCELLED')) return 'CANCELLED';
    return 'PARTIAL';
}

function getStockBundleDisplayType(actions) {
    const types = new Set(actions.map((item) => item.action_type));
    if (types.has('CASH_DIVIDEND') && types.has('SPLIT')) return '股票除权除息';
    if (types.has('CASH_DIVIDEND')) return '股票现金派息';
    if (types.has('SPLIT')) return '股票股份变动';
    return '股票企业事件';
}

function buildStockCorporateActionBundleRows(items) {
    const rows = [];
    const groups = new Map();

    items.forEach((item) => {
        if (!item.bundle_ref_id) {
            rows.push(item);
            return;
        }

        let group = groups.get(item.bundle_ref_id);
        if (!group) {
            group = {
                row_kind: 'stock_corporate_action_bundle',
                row_id: item.bundle_ref_id,
                account_id: item.account_id,
                bundle_ref_id: item.bundle_ref_id,
                biz_date: item.ex_date || item.effective_date || item.biz_date,
                effective_date: item.effective_date,
                record_date: item.record_date,
                ex_date: item.ex_date,
                asset_code: item.asset_code,
                asset_name: item.asset_name,
                action_type: 'STOCK_BUNDLE',
                display_type: '股票除权除息',
                remark: item.remark || '',
                children: [],
            };
            groups.set(item.bundle_ref_id, group);
            rows.push(group);
        }
        group.children.push(item);
    });

    rows.forEach((item) => {
        if (item.row_kind !== 'stock_corporate_action_bundle') return;
        item.display_type = getStockBundleDisplayType(item.children);
        item.status = aggregateCorporateActionStatus(item.children);
        item.last_error_message = item.children
            .map((child) => child.last_error_message)
            .filter(Boolean)
            .join('；');
        item.remark = item.children.map((child) => child.remark).find(Boolean) || '';
    });

    return rows;
}

function getStockBundleSummaryText(item) {
    const children = item.children || [];
    const parts = children.map((child) => {
        if (child.action_type === 'SPLIT' && child.ratio_from && child.ratio_to) {
            return `比例 ${child.ratio_from}:${child.ratio_to}`;
        }
        if (child.action_type === 'CASH_DIVIDEND' && child.cash_amount !== null && child.cash_amount !== undefined) {
            const unitText = child.cash_base_unit === 'PER_SHARE' ? '每股' : `每${formatNumber(child.cash_base_qty || 10, 0)}股`;
            return `${unitText} ${formatNumber(child.cash_amount, 4)}`;
        }
        return getCorporateActionSummaryText(child);
    }).filter((text) => text && text !== '--');
    return parts.length ? parts.map(escapeHtml).join(' + ') : '--';
}

function getCorporateActionActionHtml(item) {
    if (item.row_kind === 'stock_corporate_action_bundle') {
        const children = item.children || [];
        const canConfirm = children.some((child) => child.status === 'PENDING');
        const canEdit = canConfirm;
        const canCancel = children.some((child) => child.status === 'PENDING' || child.status === 'CONFIRMED');
        const actions = [];
        const bundle = escapeHtmlAttr(item.bundle_ref_id || '');
        if (canConfirm) {
            const label = item.status === 'PARTIAL' ? '重试确认' : '确认';
            actions.push(`<a href="javascript:void(0)" data-action="confirm-stock-ca-bundle" data-bundle="${bundle}" style="color: var(--primary); text-decoration: none; font-size: 13px;">${label}</a>`);
        }
        if (canEdit) {
            actions.push(`<a href="javascript:void(0)" data-action="edit-stock-ca-bundle" data-bundle="${bundle}" style="color: var(--primary); text-decoration: none; font-size: 13px;">修改</a>`);
        }
        if (canCancel) {
            actions.push(`<a href="javascript:void(0)" data-action="cancel-stock-ca-bundle" data-bundle="${bundle}" style="color: #b91c1c; text-decoration: none; font-size: 13px;">作废</a>`);
        }
        return actions.length ? actions.join('<span style="margin: 0 6px; color: var(--border-color);">/</span>') : '--';
    }

    const canEdit = item.status === 'PENDING';
    const canCancel = item.status === 'PENDING' || item.status === 'CONFIRMED';
    if (!canEdit && !canCancel) return '--';

    const actions = [];
    if (canEdit) {
        actions.push(`<a href="javascript:void(0)" data-action="edit-ca" data-id="${item.row_id}" style="color: var(--primary); text-decoration: none; font-size: 13px;">修改</a>`);
    }
    if (canCancel) {
        actions.push(`<a href="javascript:void(0)" data-action="cancel-ca" data-id="${item.row_id}" style="color: #b91c1c; text-decoration: none; font-size: 13px;">作废</a>`);
    }
    return actions.join('<span style="margin: 0 6px; color: var(--border-color);">/</span>');
}

function loadTransactions(loadContext = null) {
    if (state.transactionSubTab === 'corporate_actions') {
        return loadCorporateActionRows(loadContext, false);
    }
    return loadTradeOrders(loadContext, false);
}

function switchTransactionTab(tabName, loadContext = null, { reload = true } = {}) {
    state.transactionSubTab = tabName;
    if (typeof syncTabHash === 'function') syncTabHash();
    document.querySelectorAll('#view-transactions .sub-tab-item').forEach((tab) => {
        const isTarget = (tab.innerText === '交易记录' && tabName === 'trade_orders')
            || (tab.innerText === '企业事件' && tabName === 'corporate_actions');
        tab.classList.toggle('active', isTarget);
        if (tab.hasAttribute('role')) tab.setAttribute('aria-selected', isTarget ? 'true' : 'false');
    });
    document.getElementById('transactions-orders-panel')?.classList.toggle('hidden', tabName !== 'trade_orders');
    document.getElementById('transactions-corporate-actions-panel')?.classList.toggle('hidden', tabName !== 'corporate_actions');
    if (!reload) return;
    if (!state.currentAccount) return;
    if (tabName === 'corporate_actions') {
        loadCorporateActionRows(loadContext, false);
    } else {
        loadTradeOrders(loadContext, false);
    }
}

window.switchTransactionTab = switchTransactionTab;

async function loadTradeOrders(loadContext = null, append = false) {
    if (!state.currentAccount) return;
    if (isStaleContentLoad(loadContext, 'transactions')) return;

    const tbody = document.querySelector('#transactions-orders-panel tbody');
    if (!tbody) return;
    const page = append ? (listPaginationState.transaction_orders.page + 1) : 1;
    if (!append) {
        resetPaginationState('transaction_orders');
        state.tradeOrders = [];
        renderTableSkeletonRows(tbody, 13);
    } else {
        setPaginationLoading('transaction_orders', true);
    }

    const result = await fetchApi(`/trade-orders?account_id=${state.currentAccount}&page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
    if (isStaleContentLoad(loadContext, 'transactions')) return;
    if (!result) {
        listPaginationState.transaction_orders.loading = false;
        updatePaginationUI('transaction_orders');
        if (!append) {
            renderTableStatusRow(tbody, 13, '暂无记录', { padded: true });
        }
        return;
    }

    const items = applyPaginatedResult('transaction_orders', result, append);
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 13, '暂无记录', { padded: true });
        return;
    }

    const rowsHtml = items.map((item) => `
        <tr>
            <td>${escapeHtml(item.biz_date || '--')}</td>
            <td class="stock-code">${escapeHtml(item.asset_code || '--')}</td>
            <td class="stock-name">${escapeHtml(item.asset_name || '--')}</td>
            <td class="${getTradeOrderTypeClass(item)}">${escapeHtml(item.display_type || '--')}</td>
            <td class="number">${escapeHtml(String(getTradeOrderPriceText(item)))}</td>
            <td class="number">${escapeHtml(String(getTradeOrderQuantityText(item)))}</td>
            <td class="number">${escapeHtml(String(getTradeOrderAmountText(item)))}</td>
            <td class="number">${escapeHtml(String(formatCurrency(item.transfer_fee || 0)))}</td>
            <td class="number">${escapeHtml(String(getTradeOrderRealizedPnlText(item)))}</td>
            <td class="number">${escapeHtml(String(getTradeOrderRealizedReturnRateText(item)))}</td>
            <td class="center">${getCorporateActionStatusChip(item.status || 'ACTIVE')}</td>
            <td class="transaction-remark-cell" title="${escapeHtmlAttr(item.remark || '')}">${item.remark ? escapeHtml(item.remark) : '--'}</td>
            <td class="center">${getTradeOrderActionHtml(item)}</td>
        </tr>
    `).join('');

    renderTableRows(tbody, rowsHtml, append);

    state.tradeOrders = listPaginationState.transaction_orders.items.slice();
}

async function loadCorporateActionRows(loadContext = null, append = false) {
    if (!state.currentAccount) return;
    if (isStaleContentLoad(loadContext, 'transactions')) return;

    const tbody = document.querySelector('#transactions-corporate-actions-panel tbody');
    if (!tbody) return;
    const page = append ? (listPaginationState.transaction_actions.page + 1) : 1;
    if (!append) {
        resetPaginationState('transaction_actions');
        state.corporateActions = [];
        renderTableSkeletonRows(tbody, 9);
    } else {
        setPaginationLoading('transaction_actions', true);
    }

    const result = await fetchApi(`/corporate-actions?account_id=${state.currentAccount}&page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
    if (isStaleContentLoad(loadContext, 'transactions')) return;
    if (!result) {
        listPaginationState.transaction_actions.loading = false;
        updatePaginationUI('transaction_actions');
        if (!append) {
            renderTableStatusRow(tbody, 9, '暂无记录', { padded: true });
        }
        return;
    }

    const items = applyPaginatedResult('transaction_actions', result, append);
    const displayItems = buildStockCorporateActionBundleRows(items);
    if (!append && displayItems.length === 0) {
        renderTableStatusRow(tbody, 9, '暂无记录', { padded: true });
        return;
    }

    const rowsHtml = displayItems.map((item) => `
        <tr>
            <td>${escapeHtml(item.biz_date || '--')}</td>
            <td class="stock-code">${escapeHtml(item.asset_code || '--')}</td>
            <td class="stock-name">${escapeHtml(item.asset_name || '--')}</td>
            <td>${escapeHtml(item.display_type || '--')}</td>
            <td>${item.row_kind === 'stock_corporate_action_bundle' ? getStockBundleSummaryText(item) : getCorporateActionSummaryText(item)}</td>
            <td class="center">${getCorporateActionStatusChip(item.status || 'PENDING')}</td>
            <td>${getCorporateActionErrorText(item)}</td>
            <td>${item.remark ? escapeHtml(item.remark) : '--'}</td>
            <td class="center">${getCorporateActionActionHtml(item)}</td>
        </tr>
    `).join('');

    renderTableRows(tbody, rowsHtml, append);

    state.corporateActions = displayItems.slice();
}
