// app-transactions.js

function initTradeModal() {
    // 买入/卖出切换
    document.querySelectorAll('.tv-side-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            const side = this.dataset.side;
            switchTradeSide(side);
        });
    });

    // 绑定提交按钮
    const submitBtn = document.getElementById('btn-submit-trade');
    if (submitBtn) {
        submitBtn.addEventListener('click', submitTradeOrder);
    }

    // 绑定 input 计算总计
    const calcInputs = ['tradePrice', 'tradeVolume', 'tradeCommission'];
    calcInputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', calculateTradeTotal);
        }
    });

    // 绑定标的代码 blur 事件，用于反查名称和批次
    const stockCodeInput = document.getElementById('stockCode');
    if (stockCodeInput) {
        stockCodeInput.addEventListener('blur', function () {
            const code = this.value.trim();
            if (code) {
                fetchStockNameAndLots(code);
            } else {
                document.getElementById('stockName').value = '';
                resetLotSelection();
            }
        });
    }

    // 点击遮罩关闭
    const modal = document.getElementById('tradeModal');
    if (modal) {
        modal.addEventListener('click', function (e) {
            if (e.target === this) closeTradeModal();
        });
    }
}

function openTradeModal(type, stockCode = '', stockName = '') {
    const modal = document.getElementById('tradeModal');
    if (!modal) return;

    state.tradeIdempotencyKey = createTradeIdempotencyKey();

    // 清空旧数据
    document.getElementById('tradePrice').value = '';
    document.getElementById('tradeVolume').value = '';
    const dateInput = document.getElementById('tradeDate');
    if (dateInput) dateInput.value = getTodayDateString();
    document.getElementById('tradeCommission').value = '';
    document.getElementById('tradeRemark').value = '';
    document.getElementById('stockName').value = stockName;
    const remarkCount = document.getElementById('remarkCount');
    if (remarkCount) remarkCount.textContent = '0/128';

    // 设置代码
    const codeInput = document.getElementById('stockCode');
    if (codeInput) {
        codeInput.value = stockCode || '';
        codeInput.disabled = !!stockCode;
    }

    switchTradeSide(type);
    calculateTradeTotal();
    modal.classList.add('active');
    ensureCurrentAccountSummaryLoaded().then((data) => {
        if (data && modal.classList.contains('active')) {
            calculateTradeTotal();
        }
    });

    // 如果带了代码进来，主动查一次
    if (stockCode) {
        fetchStockNameAndLots(stockCode, stockName);
    } else {
        resetLotSelection();
    }
}

function closeTradeModal() {
    const modal = document.getElementById('tradeModal');
    if (modal) modal.classList.remove('active');
    state.tradeIdempotencyKey = null;
}

function createTradeIdempotencyKey() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return window.crypto.randomUUID();
    }
    return `trade-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function resetTradeEntryFields() {
    document.getElementById('tradePrice').value = '';
    document.getElementById('tradeVolume').value = '';
    document.getElementById('tradeCommission').value = '';
    document.getElementById('tradeRemark').value = '';
    const remarkCount = document.getElementById('remarkCount');
    if (remarkCount) remarkCount.textContent = '0/128';
    resetLotSelection();
}

function switchTradeSide(type) {
    const sideChanged = state.tradeSide !== type;
    state.tradeSide = type;
    document.querySelectorAll('.tv-side-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.side === type) btn.classList.add('active');
    });

    if (sideChanged) {
        resetTradeEntryFields();
    }

    // 更新提交按钮文字
    const submitBtn = document.getElementById('btn-submit-trade');
    if (submitBtn) {
        submitBtn.textContent = '保存';
    }

    // 控制卖出批次的显示/隐藏
    const lotGroup = document.getElementById('lotSelectionGroup');
    if (lotGroup) {
        lotGroup.style.display = type === 'sell' ? 'block' : 'none';

        // 如果切到卖出，且已有代码，重拉批次
        if (type === 'sell') {
            const code = document.getElementById('stockCode').value.trim();
            if (code) {
                fetchStockNameAndLots(code, document.getElementById('stockName').value);
            }
        }
    }

    calculateTradeTotal();
}

function getCurrentTradeFeeConfig() {
    const summary = state.currentAccountSummary || {};
    const commissionRate = Number(summary.commission_rate);
    const commissionMin = Number(summary.commission_min);
    const stampDutyRate = Number(summary.stamp_duty_rate);
    return {
        commissionRate: Number.isFinite(commissionRate) ? commissionRate : 0.00025,
        commissionMin: Number.isFinite(commissionMin) ? commissionMin : 5.0,
        stampDutyRate: Number.isFinite(stampDutyRate) ? stampDutyRate : 0.001,
    };
}

async function ensureCurrentAccountSummaryLoaded() {
    if (!state.currentAccount) return state.currentAccountSummary;
    if (
        state.currentAccountSummary &&
        Number(state.currentAccountSummary.account_id) === Number(state.currentAccount)
    ) {
        return state.currentAccountSummary;
    }
    const data = await fetchApi(`/account/summary?account_id=${state.currentAccount}`);
    if (data && Number(data.account_id) === Number(state.currentAccount)) {
        state.currentAccountSummary = data;
        state.currentCashBalance = data.cash_balance;
    }
    return data;
}

function getTradeCalculationBreakdown() {
    const price = parseFloat(document.getElementById('tradePrice').value) || 0;
    const volume = parseFloat(document.getElementById('tradeVolume').value) || 0;
    const commissionText = document.getElementById('tradeCommission').value.trim();
    const hasManualCommission = commissionText !== '';
    const manualCommission = hasManualCommission ? parseFloat(commissionText) : NaN;
    const feeConfig = getCurrentTradeFeeConfig();
    const amount = price * volume;
    let commission = 0;

    if (amount > 0) {
        if (hasManualCommission && Number.isFinite(manualCommission) && manualCommission >= 0) {
            commission = manualCommission;
        } else {
            commission = Math.max(amount * feeConfig.commissionRate, feeConfig.commissionMin);
        }
    }

    const tax = state.tradeSide === 'sell' && amount > 0 ? amount * feeConfig.stampDutyRate : 0;
    const total = state.tradeSide === 'sell' ? amount - commission - tax : amount + commission;

    return {
        amount,
        commission,
        tax,
        total,
        hasManualCommission,
        commissionLabel: '手续费',
        totalLabel: '总计金额',
        showTax: state.tradeSide === 'sell' && tax > 0,
    };
}

function calculateTradeTotal() {
    const breakdown = getTradeCalculationBreakdown();
    const amountEl = document.getElementById('tradeAmountValue');
    const commissionLabelEl = document.getElementById('tradeCommissionSummaryLabel');
    const commissionValueEl = document.getElementById('tradeCommissionValue');
    const taxRowEl = document.getElementById('tradeTaxRow');
    const taxValueEl = document.getElementById('tradeTaxValue');
    const totalLabelEl = document.getElementById('tradeTotalLabel');
    const totalEl = document.getElementById('tradeTotal');

    if (amountEl) amountEl.textContent = formatCurrency(breakdown.amount);
    if (commissionLabelEl) commissionLabelEl.textContent = breakdown.commissionLabel;
    if (commissionValueEl) commissionValueEl.textContent = formatCurrency(breakdown.commission);
    if (taxRowEl) {
        taxRowEl.style.display = breakdown.showTax ? 'flex' : 'none';
        taxRowEl.classList.toggle('hidden', !breakdown.showTax);
    }
    if (taxValueEl) taxValueEl.textContent = formatCurrency(breakdown.tax);
    if (totalLabelEl) totalLabelEl.textContent = breakdown.totalLabel;
    if (totalEl) totalEl.textContent = formatCurrency(breakdown.total);
}

async function fetchStockNameAndLots(code, knownName = '') {
    const nameInput = document.getElementById('stockName');

    // 1. 查名称 (如果还没查或外界没有传过来)
    if (!knownName) {
        nameInput.placeholder = '查询中...';
        // 方案A：从当前的持仓或者基础档案缓存中找
        let foundName = '';
        if (window._cachedAssets) {
            const asset = window._cachedAssets.find(a => a.asset_code === code);
            if (asset) foundName = asset.asset_name;
        }

        if (foundName) {
            nameInput.value = foundName;
        } else {
            // 方案B：查实时行情顶替（带短缓存与请求合并）
            const quoteResult = window.quoteService ? await window.quoteService.fetchQuotes([code]) : null;
            const quotes = quoteResult ? quoteResult.quotes : null;
            if (quotes && quotes[code] && quotes[code].name) {
                nameInput.value = quotes[code].name;
            } else {
                nameInput.value = '';
                nameInput.placeholder = '未找到名称(可继续)';
            }
        }
    } else {
        nameInput.value = knownName;
    }

    // 2. 如果当前是卖出，拉取批次
    if (state.tradeSide === 'sell') {
        const lotSelect = document.getElementById('tradeLot');
        setSelectOptions(lotSelect, [], { placeholder: '加载批次中...', disabled: true });

        const accountId = state.currentAccount || 1;
        const lots = await fetchApi(`/trade/positions/${code}/lots?account_id=${accountId}`);

        resetLotSelection(); // 先清一下

        if (!lots || lots.length === 0) {
            setSelectOptions(lotSelect, [], { placeholder: '暂无可卖批次', disabled: true });
            document.getElementById('btn-submit-trade').disabled = true;
            return;
        }

        // 渲染批次
        document.getElementById('btn-submit-trade').disabled = false;
        setSelectOptions(lotSelect, lots.map(l => {
            const dateStr = l.buy_date.split(' ')[0]; // 取日期部分
            const priceStr = formatNumber(l.buy_price, 3);
            return {
                value: l.order_id,
                text: `${dateStr} | ${code} | ${priceStr} | ${l.remain_vol}`,
                dataset: {
                    maxvol: l.remain_vol
                }
            };
        }), { disabled: false });
    }
}

function resetLotSelection() {
    const lotSelect = document.getElementById('tradeLot');
    if (lotSelect) {
        setSelectOptions(lotSelect, [], { placeholder: '请先输入代码', disabled: true });
    }
    // 不一定马上禁掉提交按钮，万一切换到 buy 呢。由 switchTradeType 去兜底
    const submitBtn = document.getElementById('btn-submit-trade');
    if (submitBtn && state.tradeSide === 'sell') {
        submitBtn.disabled = true; // 卖出时无批次不可点
    }
}

async function submitTradeOrder() {
    const code = document.getElementById('stockCode').value.trim();
    if (!code) {
        showToast('error', '请输入商品代码');
        return;
    }

    const price = parseFloat(document.getElementById('tradePrice').value);
    const vol = parseFloat(document.getElementById('tradeVolume').value);

    if (isNaN(price) || price <= 0 || isNaN(vol) || vol <= 0) {
        showToast('error', '请正确填写价格和数量（需大于0）');
        return;
    }

    const commStr = document.getElementById('tradeCommission').value.trim();
    if (commStr !== '') {
        const manualCommission = parseFloat(commStr);
        if (isNaN(manualCommission) || manualCommission < 0) {
            showToast('error', '手续费不能为负数');
            return;
        }
    }

    const remark = document.getElementById('tradeRemark').value.trim();
    const tradeDate = document.getElementById('tradeDate').value;

    if (!tradeDate) {
        showToast('error', '请选择成交日期');
        return;
    }

    const accountId = state.currentAccount || 1;

    const submitBtn = document.getElementById('btn-submit-trade');
    const oldText = submitBtn.textContent;
    submitBtn.textContent = '提交中...';
    submitBtn.disabled = true;
    if (!state.tradeIdempotencyKey) {
        state.tradeIdempotencyKey = createTradeIdempotencyKey();
    }
    const headers = {
        'Content-Type': 'application/json',
        'Idempotency-Key': state.tradeIdempotencyKey
    };

    try {
        if (state.tradeSide === 'sell' || commStr === '') {
            const summary = await ensureCurrentAccountSummaryLoaded();
            if (!summary) {
                showToast('error', '无法加载当前账户费率，请稍后重试');
                return;
            }
            calculateTradeTotal();
        }

        const breakdown = getTradeCalculationBreakdown();

        if (state.tradeSide === 'buy') {
            const payload = {
                code: code,
                trade_date: tradeDate,
                price: price,
                volume: vol,
                target_rate: 0.0, // 默认0
                commission: breakdown.commission,
                remark: remark
            };

            await fetchApiOrThrow(`/trade/order/buy?account_id=${accountId}`, {
                method: 'POST',
                headers,
                body: JSON.stringify(payload)
            });

        } else {
            // Sell
            const lotSelect = document.getElementById('tradeLot');
            const lotId = lotSelect.value;
            if (!lotId) {
                throw new Error('请选择要卖出的批次');
            }

            // 校验数量
            const selectedOption = lotSelect.options[lotSelect.selectedIndex];
            const maxVol = parseFloat(selectedOption.getAttribute('data-maxvol')) || 0;
            if (vol > maxVol) {
                showToast('error', `校验失败：填写数量（${vol}）不应超出所选批次的持仓数量（${maxVol}）`);
                return;
            }

            const payload = {
                link_order_id: parseInt(lotId),
                trade_date: tradeDate,
                price: price,
                volume: vol,
                commission: breakdown.commission,
                tax: breakdown.tax,
                remark: remark
            };

            await fetchApiOrThrow(`/trade/order/sell?account_id=${accountId}`, {
                method: 'POST',
                headers,
                body: JSON.stringify(payload)
            });
        }

        // 成功
        closeTradeModal();
        showToast('success', '交易提交成功');
        loadPageData(); // 刷新全局数据

    } catch (err) {
        showToast('error', `提交失败: ${err.message}`);
    } finally {
        submitBtn.textContent = oldText;
        submitBtn.disabled = false;
    }
}

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
    return status || '--';
}

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
    return `<span class="status-chip status-chip-pending">${escapeHtml(status || '--')}</span>`;
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

    const rows = [
        { label: '参与份额', value: preview.eligible_qty || '--' },
        { label: '影响批次', value: `${preview.affected_lot_count || 0}` }
    ];

    if (actionType === 'SPLIT') {
        rows.push({ label: '调整比例', value: preview.split_ratio_text || '--' });
    } else {
        rows.push({ label: '分红现金', value: preview.dividend_cash || '--' });
    }

    if (actionType === 'DIVIDEND_REINVEST') {
        rows.push(
            { label: '再投份额', value: preview.reinvest_volume || '--' },
            { label: '已用现金', value: preview.dividend_cash_used || '--' },
            { label: '残余现金', value: preview.cash_residual || '--' }
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

function getCorporateActionActionHtml(item) {
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

function switchTransactionTab(tabName, loadContext = null) {
    state.transactionSubTab = tabName;
    document.querySelectorAll('#view-transactions .sub-tab-item').forEach((tab) => {
        const isTarget = (tab.innerText === '交易记录' && tabName === 'trade_orders')
            || (tab.innerText === '企业事件' && tabName === 'corporate_actions');
        tab.classList.toggle('active', isTarget);
    });
    document.getElementById('transactions-orders-panel')?.classList.toggle('hidden', tabName !== 'trade_orders');
    document.getElementById('transactions-corporate-actions-panel')?.classList.toggle('hidden', tabName !== 'corporate_actions');
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
        renderTableStatusRow(tbody, 10, '加载中...');
    } else {
        setPaginationLoading('transaction_orders', true);
    }

    const result = await fetchApi(`/trade-orders?account_id=${state.currentAccount}&page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
    if (isStaleContentLoad(loadContext, 'transactions')) return;
    if (!result) {
        listPaginationState.transaction_orders.loading = false;
        updatePaginationUI('transaction_orders');
        if (!append) {
            renderTableStatusRow(tbody, 10, '暂无记录', { padded: true });
        }
        return;
    }

    const items = applyPaginatedResult('transaction_orders', result, append);
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 10, '暂无记录', { padded: true });
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
        renderTableStatusRow(tbody, 9, '加载中...');
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
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 9, '暂无记录', { padded: true });
        return;
    }

    const rowsHtml = items.map((item) => `
        <tr>
            <td>${escapeHtml(item.biz_date || '--')}</td>
            <td class="stock-code">${escapeHtml(item.asset_code || '--')}</td>
            <td class="stock-name">${escapeHtml(item.asset_name || '--')}</td>
            <td>${escapeHtml(item.display_type || '--')}</td>
            <td>${getCorporateActionSummaryText(item)}</td>
            <td class="center">${getCorporateActionStatusChip(item.status || 'PENDING')}</td>
            <td>${getCorporateActionErrorText(item)}</td>
            <td>${item.remark ? escapeHtml(item.remark) : '--'}</td>
            <td class="center">${getCorporateActionActionHtml(item)}</td>
        </tr>
    `).join('');

    renderTableRows(tbody, rowsHtml, append);

    state.corporateActions = listPaginationState.transaction_actions.items.slice();
}

// 交易记录弹窗逻辑
let currentEditOrderId = null;

function syncTransactionEditAmount() {
    const price = parseFloat(document.getElementById('edit-trade-price').value) || 0;
    const volume = parseFloat(document.getElementById('edit-trade-volume').value) || 0;
    document.getElementById('edit-trade-amount').value = (price * volume).toFixed(2);
}

function openTransactionEditModal(orderId) {
    const normalizedOrderId = Number(orderId);
    const order = state.tradeOrders.find((item) => Number(item.row_id) === normalizedOrderId);
    if (!order) {
        showToast('error', '找不到该交易记录信息');
        return;
    }

    currentEditOrderId = normalizedOrderId;

    document.getElementById('edit-trade-code').value = order.asset_code;
    document.getElementById('edit-trade-name').value = order.asset_name || '';
    document.getElementById('edit-trade-date').value = order.trade_time.split(' ')[0];
    document.getElementById('edit-trade-side').value = order.side;
    document.getElementById('edit-trade-price').value = order.price;
    document.getElementById('edit-trade-volume').value = order.volume;
    document.getElementById('edit-trade-commission').value = order.commission || 0;
    document.getElementById('edit-trade-amount').value = order.amount || 0;

    document.getElementById('edit-trade-price').oninput = syncTransactionEditAmount;
    document.getElementById('edit-trade-volume').oninput = syncTransactionEditAmount;

    document.getElementById('transactionEditModal').classList.add('active');
}

function closeTransactionEditModal() {
    document.getElementById('transactionEditModal').classList.remove('active');
    currentEditOrderId = null;
}

async function saveTransactionEdit() {
    if (!currentEditOrderId) return;

    const tradeDate = document.getElementById('edit-trade-date').value;
    const side = document.getElementById('edit-trade-side').value;
    const price = parseFloat(document.getElementById('edit-trade-price').value);
    const volume = parseFloat(document.getElementById('edit-trade-volume').value);
    const commission = parseFloat(document.getElementById('edit-trade-commission').value);

    if (!tradeDate || !side || isNaN(price) || isNaN(volume)) {
        showToast('error', '请完整填写必填字段，且价格与数量必须为有效数值');
        return;
    }
    if (price <= 0 || volume <= 0) {
        showToast('error', '价格和数量必须大于 0');
        return;
    }

    const payload = {
        trade_time: `${tradeDate} 00:00:00`,
        side,
        price,
        volume,
        commission: isNaN(commission) ? 0 : commission,
        remark: '用户修改单据'
    };

    const submitBtn = document.getElementById('btn-save-transaction');
    const oldText = submitBtn.textContent;
    submitBtn.textContent = '提交中...';
    submitBtn.disabled = true;

    try {
        const accountId = state.currentAccount || 1;
        await fetchApiOrThrow(`/trade/order/${currentEditOrderId}?account_id=${accountId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        closeTransactionEditModal();
        showToast('success', '交易记录已修改');
        loadPageData();
    } catch (err) {
        showToast('error', `修改订单失败: ${err.message}`);
    } finally {
        submitBtn.textContent = oldText;
        submitBtn.disabled = false;
    }
}

// ==================== 页面逻辑: 指数分析 ====================

function openDepositModal() {
    const modal = document.getElementById("depositModal");
    if (!modal) return;
    document.getElementById("form-deposit-amount").value = "";
    document.getElementById("form-deposit-remark").value = "";
    document.getElementById("err-deposit-amount").classList.add("hidden");
    modal.classList.add("active");
    setTimeout(() => {
        const input = document.getElementById("form-deposit-amount");
        if(input) input.focus();
    }, 100);
}

function closeDepositModal() {
    const modal = document.getElementById("depositModal");
    if (modal) modal.classList.remove("active");
}

async function submitDeposit() {
    const amountInput = document.getElementById("form-deposit-amount");
    const remarkInput = document.getElementById("form-deposit-remark");
    const errSpan = document.getElementById("err-deposit-amount");
    const btnSubmit = document.getElementById("btn-save-deposit");

    const amount = parseFloat(amountInput.value);

    if (isNaN(amount) || amount <= 0) {
        errSpan.textContent = "金额必须大于0，请输入合法金额";
        errSpan.classList.remove("hidden");
        return;
    }

    errSpan.classList.add("hidden");
    btnSubmit.disabled = true;
    const oldText = btnSubmit.textContent;
    btnSubmit.textContent = "提交中...";

    try {
        const payload = {
            account_id: state.currentAccount,
            amount: amount,
            remark: remarkInput.value || "入金",
            source_type: "MANUAL"
        };

        await fetchApiOrThrow('/account/deposit', {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        closeDepositModal();
        showToast("success", "入金成功");

        loadPageData();
    } catch (err) {
        showToast("error", `入金失败: ${err.message}`);
    } finally {
        if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.textContent = oldText;
        }
    }
}

/* ==================== 出金弹窗 ==================== */
function openWithdrawModal() {
    const modal = document.getElementById("withdrawModal");
    if (!modal) return;
    document.getElementById("form-withdraw-amount").value = "";
    document.getElementById("form-withdraw-remark").value = "";
    document.getElementById("err-withdraw-amount").classList.add("hidden");
    modal.classList.add("active");
    setTimeout(() => {
        const input = document.getElementById("form-withdraw-amount");
        if(input) input.focus();
    }, 100);
}

function closeWithdrawModal() {
    const modal = document.getElementById("withdrawModal");
    if (modal) modal.classList.remove("active");
}

async function submitWithdraw() {
    const amountInput = document.getElementById("form-withdraw-amount");
    const remarkInput = document.getElementById("form-withdraw-remark");
    const errSpan = document.getElementById("err-withdraw-amount");
    const btnSubmit = document.getElementById("btn-save-withdraw");

    const amount = parseFloat(amountInput.value);

    if (isNaN(amount) || amount <= 0) {
        errSpan.textContent = "金额必须大于0，请输入合法金额";
        errSpan.classList.remove("hidden");
        return;
    }

    errSpan.classList.add("hidden");
    btnSubmit.disabled = true;
    const oldText = btnSubmit.textContent;
    btnSubmit.textContent = "提交中...";

    try {
        const payload = {
            account_id: state.currentAccount,
            amount: amount,
            remark: remarkInput.value || "出金",
            source_type: "MANUAL"
        };

        await fetchApiOrThrow('/account/withdraw', {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        closeWithdrawModal();
        showToast("success", "出金成功");

        loadPageData();
    } catch (err) {
        showToast("error", `出金失败: ${err.message}`);
    } finally {
        if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.textContent = oldText;
        }
    }
}


/* ==================== 调账弹窗 ==================== */
function openCashAdjustModal() {
    const modal = document.getElementById("cashAdjustModal");
    if (!modal) return;

    document.getElementById("form-cash-amount").value = state.currentCashBalance || 0;
    document.getElementById("err-cash-amount").classList.add("hidden");

    modal.classList.add("active");
    setTimeout(() => {
        document.getElementById("form-cash-amount").focus();
    }, 100);
}

function closeCashAdjustModal() {
    const modal = document.getElementById("cashAdjustModal");
    if (modal) modal.classList.remove("active");
}

async function saveCashAdjust() {
    const amountInput = document.getElementById("form-cash-amount");
    const errSpan = document.getElementById("err-cash-amount");
    const btnSubmit = document.getElementById("btn-save-cash");

    const newVal = parseFloat(amountInput.value);

    if (isNaN(newVal) || newVal < 0) {
        errSpan.textContent = "可用现金不能为负数，请输入合法金额";
        errSpan.classList.remove("hidden");
        return;
    }

    const diff = newVal - (state.currentCashBalance || 0);

    if (Math.abs(diff) < 0.01) {
        closeCashAdjustModal();
        showToast("info", "金额无变化");
        return;
    }

    const direction = diff > 0 ? "IN" : "OUT";
    const amount = Math.abs(diff);

    errSpan.classList.add("hidden");
    btnSubmit.disabled = true;
    const oldText = btnSubmit.textContent;
    btnSubmit.textContent = "提交中...";

    try {
        const payload = {
            amount: amount,
            direction: direction,
            remark: "前端手工校准可用现金"
        };

        await fetchApi(`/account/adjust?account_id=${state.currentAccount || 1}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        closeCashAdjustModal();
        showToast("success", "可用现金修正成功");

        loadAccountSummaryData();
    } catch (err) {
        showToast("error", `修正失败: ${err.message}`);
    } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = oldText;
    }
}
