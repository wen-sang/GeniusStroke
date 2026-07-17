// app-corporate-action-modal.js
// 企业事件弹窗（预览/提交/编辑/取消）与股票企业事件束（确认/编辑/取消）

// ==================== 页面逻辑: 企业事件 / 交易混排 ====================

function initCorporateActionModal() {
    const assetCodeInput = document.getElementById('ca-asset-code');
    if (assetCodeInput) {
        assetCodeInput.addEventListener('blur', async function () {
            const code = this.value.trim();
            if (!code) {
                document.getElementById('ca-asset-name').value = '';
                return;
            }
            await populateCorporateActionAssetName(code);
        });
    }

    [
        'ca-asset-code',
        'ca-effective-date',
        'ca-record-date',
        'ca-ratio-from',
        'ca-ratio-to',
        'ca-cash-base-unit',
        'ca-cash-amount',
        'ca-reinvest-price',
        'ca-rounding-policy',
        'ca-remark'
    ].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        const eventName = el.tagName === 'SELECT' ? 'change' : 'input';
        el.addEventListener(eventName, resetCorporateActionPreview);
    });
}

function getCorporateActionTypeLabel(actionType) {
    const mapping = {
        SPLIT: '份额调整',
        CASH_DIVIDEND: '现金分红',
        DIVIDEND_REINVEST: '红利再投'
    };
    return mapping[actionType] || actionType || '--';
}

function getCorporateActionStatusLabel(status) {
    if (status === 'PENDING') return '待确认';
    if (status === 'ACTIVE') return '有效';
    if (status === 'CONFIRMED') return '已确认';
    if (status === 'CANCELLED') return '已作废';
    if (status === 'PARTIAL') return '部分确认';
    return status || '--';
}

function resetCorporateActionPreview() {
    corporateActionState.preview = null;
    const preview = document.getElementById('ca-preview-content');
    if (preview) {
        preview.textContent = '填写参数后点击“预览结果”查看影响。';
    }
}

function renderCorporateActionPreview(preview, actionType = corporateActionState.actionType) {
    const previewContainer = document.getElementById('ca-preview-content');
    if (!previewContainer || !preview) return;

    const formatQuantity = preview.exchange_traded
        ? formatCorporateActionQuantity
        : (value) => String(value ?? '--');
    const formatAmount = preview.exchange_traded
        ? formatCorporateActionAmount
        : (value) => String(value ?? '--');
    const rows = [
        { label: '参与份额', value: formatQuantity(preview.eligible_qty) },
        { label: '影响批次', value: `${preview.affected_lot_count || 0}` }
    ];

    if (actionType === 'SPLIT') {
        rows.push({ label: '调整比例', value: preview.split_ratio_text || '--' });
    } else {
        rows.push({ label: '分红现金', value: formatAmount(preview.dividend_cash) });
    }

    if (actionType === 'DIVIDEND_REINVEST') {
        rows.push(
            { label: '再投份额', value: formatQuantity(preview.reinvest_volume) },
            { label: '已用现金', value: formatAmount(preview.dividend_cash_used) },
            { label: '残余现金', value: formatAmount(preview.cash_residual) }
        );
    }

    clearElement(previewContainer);

    const grid = document.createElement('div');
    grid.className = 'preview-grid';
    rows.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'preview-kv';

        const label = document.createElement('span');
        label.className = 'preview-kv-label';
        label.textContent = item.label;

        const value = document.createElement('span');
        value.className = 'preview-kv-value';
        value.textContent = String(item.value);

        row.appendChild(label);
        row.appendChild(value);
        grid.appendChild(row);
    });
    previewContainer.appendChild(grid);

    if (Array.isArray(preview.warnings) && preview.warnings.length > 0) {
        const warningList = document.createElement('ul');
        warningList.className = 'preview-warnings';
        preview.warnings.forEach((warning) => {
            const item = document.createElement('li');
            item.textContent = warning;
            warningList.appendChild(item);
        });
        previewContainer.appendChild(warningList);
    }
}

function toggleCorporateActionFields(actionType) {
    const isSplit = actionType === 'SPLIT';
    const isDividend = actionType === 'CASH_DIVIDEND' || actionType === 'DIVIDEND_REINVEST';
    const isReinvest = actionType === 'DIVIDEND_REINVEST';

    [
        'ca-ratio-from-group',
        'ca-ratio-to-group'
    ].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('hidden', !isSplit);
    });

    [
        'ca-cash-base-unit-group',
        'ca-cash-amount-group'
    ].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('hidden', !isDividend);
    });

    [
        'ca-reinvest-price-group',
        'ca-rounding-policy-group'
    ].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('hidden', !isReinvest);
    });
}

async function lookupAssetName(code, preferredName = '') {
    if (preferredName) return preferredName;

    if (window._cachedAssets) {
        const asset = window._cachedAssets.find((item) => item.asset_code === code);
        if (asset && asset.asset_name) return asset.asset_name;
    }

    if (window.quoteService) {
        const quoteResult = await window.quoteService.fetchQuotes([code]);
        const quoteName = quoteResult?.quotes?.[code]?.name;
        if (quoteName) return quoteName;
    }

    return '';
}

async function populateCorporateActionAssetName(code, preferredName = '') {
    const nameInput = document.getElementById('ca-asset-name');
    if (!nameInput) return;
    if (!code) {
        nameInput.value = '';
        return;
    }

    nameInput.placeholder = '查询中...';
    try {
        const name = await lookupAssetName(code, preferredName);
        nameInput.value = name;
        nameInput.placeholder = name ? '自动带出' : '未找到名称';
    } catch (error) {
        console.error('资产名称查询失败', error);
        nameInput.value = '';
        nameInput.placeholder = '未找到名称';
    }
}

function openCorporateActionModal(actionType, stockCode = '', stockName = '') {
    const modal = document.getElementById('corporateActionModal');
    if (!modal) return;
    closeTransactionMenu();

    corporateActionState.mode = 'create';
    corporateActionState.actionId = null;
    corporateActionState.actionType = actionType;
    corporateActionState.status = 'PENDING';
    corporateActionState.assetCodeLocked = !!stockCode;

    document.getElementById('corporateActionModalTitle').textContent = `新增${getCorporateActionTypeLabel(actionType)}`;
    document.getElementById('ca-action-type').value = actionType;
    document.getElementById('ca-status').value = getCorporateActionStatusLabel('PENDING');
    document.getElementById('ca-asset-code').value = stockCode || '';
    document.getElementById('ca-asset-code').disabled = !!stockCode;
    document.getElementById('ca-asset-name').value = stockName || '';
    document.getElementById('ca-effective-date').value = getTodayDateString();
    document.getElementById('ca-record-date').value = '';
    document.getElementById('ca-ratio-from').value = '';
    document.getElementById('ca-ratio-to').value = '';
    document.getElementById('ca-cash-base-unit').value = 'PER_SHARE';
    document.getElementById('ca-cash-amount').value = '';
    document.getElementById('ca-reinvest-price').value = '';
    document.getElementById('ca-rounding-policy').value = 'KEEP_DECIMAL';
    document.getElementById('ca-remark').value = '';
    document.getElementById('btn-save-corporate-action').textContent = '确定保存';
    document.getElementById('btn-cancel-corporate-action').classList.add('hidden');

    toggleCorporateActionFields(actionType);
    resetCorporateActionPreview();
    clearFormErrors('corporateActionModal');
    modal.classList.add('active');

    if (stockCode) {
        populateCorporateActionAssetName(stockCode, stockName);
    }

    setTimeout(() => {
        const focusTarget = stockCode ? document.getElementById('ca-effective-date') : document.getElementById('ca-asset-code');
        if (focusTarget) focusTarget.focus();
    }, 60);
}

function closeCorporateActionModal() {
    const modal = document.getElementById('corporateActionModal');
    if (modal) modal.classList.remove('active');
    corporateActionState.mode = 'create';
    corporateActionState.actionId = null;
    corporateActionState.preview = null;
}

function collectCorporateActionPayload(includeImmutableFields = true) {
    if (!state.currentAccount) {
        throw new Error('当前没有可用账户');
    }

    const assetCode = document.getElementById('ca-asset-code').value.trim();
    const effectiveDate = document.getElementById('ca-effective-date').value;
    const recordDate = document.getElementById('ca-record-date').value || null;
    const remark = document.getElementById('ca-remark').value.trim();
    const actionType = corporateActionState.actionType;

    if (!assetCode && includeImmutableFields) {
        throw new Error('请输入资产代码');
    }
    if (!effectiveDate) {
        throw new Error('请选择生效日');
    }

    const payload = {
        account_id: state.currentAccount,
        effective_date: effectiveDate,
        record_date: recordDate,
        remark
    };

    if (includeImmutableFields) {
        payload.asset_code = assetCode;
        payload.action_type = actionType;
    }

    if (actionType === 'SPLIT') {
        const ratioFrom = Number(document.getElementById('ca-ratio-from').value);
        const ratioTo = Number(document.getElementById('ca-ratio-to').value);
        if (!Number.isInteger(ratioFrom) || ratioFrom <= 0 || !Number.isInteger(ratioTo) || ratioTo <= 0) {
            throw new Error('请输入合法的拆分前后比例');
        }
        payload.ratio_from = ratioFrom;
        payload.ratio_to = ratioTo;
        return payload;
    }

    const cashAmount = parseFloat(document.getElementById('ca-cash-amount').value);
    if (isNaN(cashAmount) || cashAmount <= 0) {
        throw new Error('请输入合法的分红金额');
    }

    payload.cash_base_unit = document.getElementById('ca-cash-base-unit').value;
    payload.cash_amount = cashAmount;

    if (actionType === 'DIVIDEND_REINVEST') {
        const reinvestPrice = parseFloat(document.getElementById('ca-reinvest-price').value);
        if (isNaN(reinvestPrice) || reinvestPrice <= 0) {
            throw new Error('请输入合法的再投价格');
        }
        payload.reinvest_price = reinvestPrice;
        payload.rounding_policy = document.getElementById('ca-rounding-policy').value;
    }

    return payload;
}

async function previewCorporateAction() {
    const previewBtn = document.getElementById('btn-preview-corporate-action');
    const oldText = previewBtn.textContent;

    try {
        const payload = collectCorporateActionPayload(true);
        previewBtn.textContent = '预览中...';
        previewBtn.disabled = true;

        const result = await fetchApiOrThrow('/corporate-actions/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        corporateActionState.preview = result.data || null;
        renderCorporateActionPreview(result.data || {}, corporateActionState.actionType);
    } catch (err) {
        showToast('error', `预览失败: ${err.message}`);
    } finally {
        previewBtn.textContent = oldText;
        previewBtn.disabled = false;
    }
}

async function submitCorporateAction() {
    const submitBtn = document.getElementById('btn-save-corporate-action');
    const oldText = submitBtn.textContent;

    try {
        const isEdit = corporateActionState.mode === 'edit' && !!corporateActionState.actionId;
        const payload = collectCorporateActionPayload(!isEdit);

        submitBtn.textContent = isEdit ? '修改中...' : '保存中...';
        submitBtn.disabled = true;

        const endpoint = isEdit
            ? `/corporate-actions/${corporateActionState.actionId}`
            : '/corporate-actions';
        const method = isEdit ? 'PUT' : 'POST';

        await fetchApiOrThrow(endpoint, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        closeCorporateActionModal();
        showToast('success', isEdit ? '企业事件已修改' : '企业事件已创建');
        loadPageData();
    } catch (err) {
        showToast('error', `提交失败: ${err.message}`);
    } finally {
        submitBtn.textContent = oldText;
        submitBtn.disabled = false;
    }
}

async function openCorporateActionEditModal(actionId) {
    showLoadingModal('加载企业事件详情...');

    try {
        clearFormErrors('corporateActionModal');
        const result = await fetchApiOrThrow(`/corporate-actions/${actionId}`);
        const detail = result.data;
        if (!detail) {
            throw new Error('企业事件详情不存在');
        }
        if (detail.status !== 'PENDING') {
            showToast('warning', '仅待确认的企业事件允许修改');
            return;
        }

        corporateActionState.mode = 'edit';
        corporateActionState.actionId = actionId;
        corporateActionState.actionType = detail.action_type;
        corporateActionState.status = detail.status;
        corporateActionState.assetCodeLocked = true;

        document.getElementById('corporateActionModalTitle').textContent = `修改${getCorporateActionTypeLabel(detail.action_type)}`;
        document.getElementById('ca-action-type').value = detail.action_type;
        document.getElementById('ca-status').value = getCorporateActionStatusLabel(detail.status);
        document.getElementById('ca-asset-code').value = detail.asset_code || '';
        document.getElementById('ca-asset-code').disabled = true;
        document.getElementById('ca-effective-date').value = detail.effective_date || '';
        document.getElementById('ca-record-date').value = detail.record_date || '';
        document.getElementById('ca-ratio-from').value = detail.ratio_from ?? '';
        document.getElementById('ca-ratio-to').value = detail.ratio_to ?? '';
        document.getElementById('ca-cash-base-unit').value = detail.cash_base_unit || 'PER_SHARE';
        document.getElementById('ca-cash-amount').value = detail.cash_amount ?? '';
        document.getElementById('ca-reinvest-price').value = detail.reinvest_price ?? '';
        document.getElementById('ca-rounding-policy').value = detail.rounding_policy || 'KEEP_DECIMAL';
        document.getElementById('ca-remark').value = detail.remark || '';
        document.getElementById('btn-save-corporate-action').textContent = '确认修改';
        document.getElementById('btn-cancel-corporate-action').classList.remove('hidden');

        await populateCorporateActionAssetName(detail.asset_code || '');
        toggleCorporateActionFields(detail.action_type);
        if (detail.derived_summary) {
            corporateActionState.preview = detail.derived_summary;
            renderCorporateActionPreview(detail.derived_summary, detail.action_type);
        } else {
            resetCorporateActionPreview();
        }

        document.getElementById('corporateActionModal').classList.add('active');
    } catch (err) {
        showToast('error', `加载企业事件失败: ${err.message}`);
    } finally {
        hideLoadingModal();
    }
}

async function cancelCorporateAction(actionId) {
    const target = state.corporateActions.find((item) => item.row_id === actionId);
    const targetLabel = target
        ? `${target.asset_code} ${target.display_type} ${target.biz_date}`
        : `企业事件 #${actionId}`;

    if (!window.confirm(`确认作废 ${targetLabel} 吗？此操作会同步重建账户状态。`)) {
        return;
    }

    try {
        await fetchApiOrThrow(`/corporate-actions/${actionId}/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                account_id: state.currentAccount,
                remark: '前端作废企业事件'
            })
        });

        if (corporateActionState.actionId === actionId) {
            closeCorporateActionModal();
        }
        showToast('success', '企业事件已作废');
        loadPageData();
    } catch (err) {
        showToast('error', `作废失败: ${err.message}`);
    }
}

function cancelCurrentCorporateAction() {
    if (!corporateActionState.actionId) return;
    cancelCorporateAction(corporateActionState.actionId);
}

async function confirmStockCorporateActionBundle(bundleRefId) {
    if (!bundleRefId || !state.currentAccount) return;
    const target = state.corporateActions.find((item) => item.bundle_ref_id === bundleRefId);
    const targetLabel = target
        ? `${target.asset_code} ${target.display_type} ${target.biz_date}`
        : `股票组合事件 ${bundleRefId}`;

    if (!window.confirm(`确认执行 ${targetLabel} 吗？`)) {
        return;
    }

    try {
        await fetchApiOrThrow(`/stock-corporate-actions/bundles/${encodeURIComponent(bundleRefId)}/confirm`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_id: state.currentAccount })
        });
        showToast('success', '股票除权除息已确认');
        loadPageData();
    } catch (err) {
        showToast('error', `确认失败: ${err.message}`);
    }
}

async function openStockCorporateActionBundleEditModal(bundleRefId) {
    if (!bundleRefId || !state.currentAccount) return;
    const target = state.corporateActions.find((item) => item.bundle_ref_id === bundleRefId);
    showLoadingModal('加载股票除权除息详情...');

    try {
        const result = await fetchApiOrThrow(
            `/stock-corporate-actions/bundles/${encodeURIComponent(bundleRefId)}?account_id=${state.currentAccount}`
        );
        openStockCorporateActionModal('', target?.asset_name || '', {
            mode: 'edit',
            bundleRefId,
            bundleData: result
        });
    } catch (err) {
        showToast('error', `加载股票除权除息失败: ${err.message}`);
    } finally {
        hideLoadingModal();
    }
}

async function cancelStockCorporateActionBundle(bundleRefId) {
    if (!bundleRefId || !state.currentAccount) return;
    const target = state.corporateActions.find((item) => item.bundle_ref_id === bundleRefId);
    const targetLabel = target
        ? `${target.asset_code} ${target.display_type} ${target.biz_date}`
        : `股票组合事件 ${bundleRefId}`;

    if (!window.confirm(`确认作废 ${targetLabel} 吗？此操作会同步重建账户状态。`)) {
        return;
    }

    try {
        await fetchApiOrThrow(`/stock-corporate-actions/bundles/${encodeURIComponent(bundleRefId)}/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                account_id: state.currentAccount,
                remark: '前端作废股票除权除息'
            })
        });
        showToast('success', '股票除权除息已作废');
        loadPageData();
    } catch (err) {
        showToast('error', `作废失败: ${err.message}`);
    }
}
