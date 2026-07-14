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
    const calcInputs = ['tradePrice', 'tradeVolume', 'tradeCommission', 'tradeTransferFee', 'tradeTax'];
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
    document.getElementById('tradeTransferFee').value = '0';
    document.getElementById('tradeTax').value = '';
    document.getElementById('tradeRemark').value = '';
    document.getElementById('stockName').value = stockName;
    state.tradeAssetType = null;
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
    state.tradeAssetType = null;
}

function createTradeIdempotencyKey() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return window.crypto.randomUUID();
    }
    return `trade-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function fetchAssetMetaByCode(code) {
    const normalizedCode = String(code || '').trim();
    if (!normalizedCode) return null;

    const response = await fetch(`${API_BASE}/v1/assets/${encodeURIComponent(normalizedCode)}`);
    const result = await response.json().catch(() => ({}));
    if (response.status === 404) return null;
    if (!response.ok) {
        throw new Error(result.detail || '资产档案查询失败');
    }
    return result;
}

function resetTradeEntryFields() {
    document.getElementById('tradePrice').value = '';
    document.getElementById('tradeVolume').value = '';
    document.getElementById('tradeCommission').value = '';
    document.getElementById('tradeTransferFee').value = '0';
    document.getElementById('tradeTax').value = '';
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

    updateTradeFeeFieldVisibility();
    calculateTradeTotal();
}

function isTradeAssetStock(assetType = state.tradeAssetType) {
    return String(assetType || '').toUpperCase() === 'STOCK';
}

function updateTradeFeeFieldVisibility() {
    const isStock = isTradeAssetStock();
    const showTransferFee = isStock;
    const showTax = isStock && state.tradeSide === 'sell';
    const transferGroup = document.getElementById('tradeTransferFeeGroup');
    const taxGroup = document.getElementById('tradeTaxInputGroup');
    const transferInput = document.getElementById('tradeTransferFee');
    const taxInput = document.getElementById('tradeTax');

    if (transferGroup) transferGroup.classList.toggle('hidden', !showTransferFee);
    if (taxGroup) taxGroup.classList.toggle('hidden', !showTax);
    if (!showTransferFee && transferInput) transferInput.value = '0';
    if (!showTax && taxInput) taxInput.value = '';
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
    const transferFeeText = document.getElementById('tradeTransferFee').value.trim();
    const taxText = document.getElementById('tradeTax').value.trim();
    const hasManualCommission = commissionText !== '';
    const hasManualTransferFee = transferFeeText !== '';
    const hasManualTax = taxText !== '';
    const manualCommission = hasManualCommission ? parseFloat(commissionText) : NaN;
    const manualTransferFee = hasManualTransferFee ? parseFloat(transferFeeText) : NaN;
    const manualTax = hasManualTax ? parseFloat(taxText) : NaN;
    const feeConfig = getCurrentTradeFeeConfig();
    const amount = price * volume;
    let commission = 0;
    let transferFee = 0;
    let tax = 0;

    if (amount > 0) {
        if (hasManualCommission && Number.isFinite(manualCommission) && manualCommission >= 0) {
            commission = manualCommission;
        } else {
            commission = Math.max(amount * feeConfig.commissionRate, feeConfig.commissionMin);
        }
    }

    if (isTradeAssetStock()) {
        if (hasManualTransferFee && Number.isFinite(manualTransferFee) && manualTransferFee >= 0) {
            transferFee = manualTransferFee;
        }
        if (state.tradeSide === 'sell' && amount > 0) {
            if (hasManualTax && Number.isFinite(manualTax) && manualTax >= 0) {
                tax = manualTax;
            } else {
                tax = amount * feeConfig.stampDutyRate;
            }
        }
    }

    const total = state.tradeSide === 'sell'
        ? amount - commission - transferFee - tax
        : amount + commission + transferFee;

    return {
        amount,
        commission,
        transferFee,
        tax,
        total,
        hasManualCommission,
        hasManualTransferFee,
        hasManualTax,
        commissionLabel: '手续费',
        totalLabel: '总计金额',
        showTransferFee: isTradeAssetStock(),
        showTax: isTradeAssetStock() && state.tradeSide === 'sell',
    };
}

function calculateTradeTotal() {
    const breakdown = getTradeCalculationBreakdown();
    const amountEl = document.getElementById('tradeAmountValue');
    const commissionLabelEl = document.getElementById('tradeCommissionSummaryLabel');
    const commissionValueEl = document.getElementById('tradeCommissionValue');
    const transferFeeRowEl = document.getElementById('tradeTransferFeeRow');
    const transferFeeValueEl = document.getElementById('tradeTransferFeeValue');
    const taxRowEl = document.getElementById('tradeTaxRow');
    const taxValueEl = document.getElementById('tradeTaxValue');
    const totalLabelEl = document.getElementById('tradeTotalLabel');
    const totalEl = document.getElementById('tradeTotal');

    if (amountEl) amountEl.textContent = formatCurrency(breakdown.amount);
    if (commissionLabelEl) commissionLabelEl.textContent = breakdown.commissionLabel;
    if (commissionValueEl) commissionValueEl.textContent = formatCurrency(breakdown.commission);
    if (transferFeeRowEl) {
        transferFeeRowEl.style.display = breakdown.showTransferFee ? 'flex' : 'none';
        transferFeeRowEl.classList.toggle('hidden', !breakdown.showTransferFee);
    }
    if (transferFeeValueEl) transferFeeValueEl.textContent = formatCurrency(breakdown.transferFee);
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

    nameInput.placeholder = '查询中...';
    try {
        const asset = await fetchAssetMetaByCode(code);
        if (asset && asset.asset_name) {
            nameInput.value = asset.asset_name;
            state.tradeAssetType = asset.asset_type || null;
        } else {
            nameInput.value = knownName || '';
            nameInput.placeholder = '未找到标的档案';
            state.tradeAssetType = null;
        }
    } catch (error) {
        console.error('资产档案查询失败', error);
        nameInput.value = knownName || '';
        nameInput.placeholder = '档案查询失败';
        state.tradeAssetType = null;
    }
    updateTradeFeeFieldVisibility();
    calculateTradeTotal();

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

    let asset = null;
    try {
        asset = await fetchAssetMetaByCode(code);
    } catch (error) {
        showToast('error', `资产档案查询失败: ${error.message}`);
        return;
    }
    if (!asset && state.tradeSide === 'buy') {
        showToast('error', '未找到标的档案，请先新增基础档案');
        return;
    }
    state.tradeAssetType = asset?.asset_type || null;
    const nameInput = document.getElementById('stockName');
    if (nameInput && asset?.asset_name) {
        nameInput.value = asset.asset_name;
    }
    updateTradeFeeFieldVisibility();

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
    const transferFeeStr = document.getElementById('tradeTransferFee').value.trim();
    if (transferFeeStr !== '') {
        const manualTransferFee = parseFloat(transferFeeStr);
        if (isNaN(manualTransferFee) || manualTransferFee < 0) {
            showToast('error', '过户费不能为负数');
            return;
        }
    }
    const taxStr = document.getElementById('tradeTax').value.trim();
    if (taxStr !== '') {
        const manualTax = parseFloat(taxStr);
        if (isNaN(manualTax) || manualTax < 0) {
            showToast('error', '印花税不能为负数');
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
                transfer_fee: breakdown.transferFee,
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
                transfer_fee: breakdown.transferFee,
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
    if (status === 'PARTIAL') return '部分确认';
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
    if (status === 'PARTIAL') {
        return '<span class="status-chip status-chip-pending">部分确认</span>';
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

// 交易记录弹窗逻辑
let currentEditOrderId = null;

function syncTransactionEditAmount() {
    const price = parseFloat(document.getElementById('edit-trade-price').value) || 0;
    const volume = parseFloat(document.getElementById('edit-trade-volume').value) || 0;
    document.getElementById('edit-trade-amount').value = (price * volume).toFixed(2);
}

function updateTransactionEditFeeVisibility() {
    const isStock = isTradeAssetStock(state.editTradeAssetType);
    const side = document.getElementById('edit-trade-side').value;
    const transferGroup = document.getElementById('edit-trade-transfer-fee-group');
    const taxGroup = document.getElementById('edit-trade-tax-group');
    const transferInput = document.getElementById('edit-trade-transfer-fee');
    const taxInput = document.getElementById('edit-trade-tax');
    const showTax = isStock && side === 'SELL';

    if (transferGroup) transferGroup.classList.toggle('hidden', !isStock);
    if (taxGroup) taxGroup.classList.toggle('hidden', !showTax);
    if (!isStock && transferInput) transferInput.value = '0';
    if (!showTax && taxInput) taxInput.value = '0';
}

function openTransactionEditModal(orderId) {
    const normalizedOrderId = Number(orderId);
    const order = state.tradeOrders.find((item) => Number(item.row_id) === normalizedOrderId);
    if (!order) {
        showToast('error', '找不到该交易记录信息');
        return;
    }

    currentEditOrderId = normalizedOrderId;
    state.editTradeAssetType = order.asset_type || null;

    document.getElementById('edit-trade-code').value = order.asset_code;
    document.getElementById('edit-trade-name').value = order.asset_name || '';
    document.getElementById('edit-trade-date').value = order.trade_time.split(' ')[0];
    document.getElementById('edit-trade-side').value = order.side;
    document.getElementById('edit-trade-price').value = order.price;
    document.getElementById('edit-trade-volume').value = order.volume;
    document.getElementById('edit-trade-commission').value = order.commission || 0;
    document.getElementById('edit-trade-transfer-fee').value = order.transfer_fee || 0;
    document.getElementById('edit-trade-tax').value = order.tax || 0;
    document.getElementById('edit-trade-amount').value = order.amount || 0;

    document.getElementById('edit-trade-price').oninput = syncTransactionEditAmount;
    document.getElementById('edit-trade-volume').oninput = syncTransactionEditAmount;
    document.getElementById('edit-trade-side').onchange = updateTransactionEditFeeVisibility;
    updateTransactionEditFeeVisibility();

    document.getElementById('transactionEditModal').classList.add('active');
}

function closeTransactionEditModal() {
    document.getElementById('transactionEditModal').classList.remove('active');
    currentEditOrderId = null;
    state.editTradeAssetType = null;
}

async function saveTransactionEdit() {
    if (!currentEditOrderId) return;

    const tradeDate = document.getElementById('edit-trade-date').value;
    const side = document.getElementById('edit-trade-side').value;
    const price = parseFloat(document.getElementById('edit-trade-price').value);
    const volume = parseFloat(document.getElementById('edit-trade-volume').value);
    const commission = parseFloat(document.getElementById('edit-trade-commission').value);
    const transferFee = parseFloat(document.getElementById('edit-trade-transfer-fee').value);
    const tax = parseFloat(document.getElementById('edit-trade-tax').value);

    if (!tradeDate || !side || isNaN(price) || isNaN(volume)) {
        showToast('error', '请完整填写必填字段，且价格与数量必须为有效数值');
        return;
    }
    if (price <= 0 || volume <= 0) {
        showToast('error', '价格和数量必须大于 0');
        return;
    }
    if (!isNaN(commission) && commission < 0) {
        showToast('error', '佣金不能为负数');
        return;
    }
    if (!isNaN(transferFee) && transferFee < 0) {
        showToast('error', '过户费不能为负数');
        return;
    }
    if (!isNaN(tax) && tax < 0) {
        showToast('error', '印花税不能为负数');
        return;
    }

    const payload = {
        trade_time: `${tradeDate} 00:00:00`,
        side,
        price,
        volume,
        commission: isNaN(commission) ? 0 : commission,
        transfer_fee: isTradeAssetStock(state.editTradeAssetType) && !isNaN(transferFee) ? transferFee : 0,
        tax: side === 'SELL' && isTradeAssetStock(state.editTradeAssetType) && !isNaN(tax) ? tax : 0,
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

function getRequiredCurrentAccountId() {
    const accountId = Number(state.currentAccount);
    if (!Number.isInteger(accountId) || accountId <= 0) {
        throw new Error("请先选择账户");
    }
    return accountId;
}

function openDepositModal() {
    const modal = document.getElementById("depositModal");
    if (!modal) return;
    document.getElementById("form-deposit-date").value = getTodayDateString();
    document.getElementById("form-deposit-amount").value = "";
    document.getElementById("form-deposit-remark").value = "";
    document.getElementById("err-deposit-date").classList.add("hidden");
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
    const dateInput = document.getElementById("form-deposit-date");
    const amountInput = document.getElementById("form-deposit-amount");
    const remarkInput = document.getElementById("form-deposit-remark");
    const errDateSpan = document.getElementById("err-deposit-date");
    const errSpan = document.getElementById("err-deposit-amount");
    const btnSubmit = document.getElementById("btn-save-deposit");

    const amount = parseFloat(amountInput.value);

    errDateSpan.classList.add("hidden");
    errSpan.classList.add("hidden");

    if (!dateInput.value) {
        errDateSpan.textContent = "请选择入金时间";
        errDateSpan.classList.remove("hidden");
        return;
    }
    if (isNaN(amount) || amount <= 0) {
        errSpan.textContent = "金额必须大于0，请输入合法金额";
        errSpan.classList.remove("hidden");
        return;
    }

    btnSubmit.disabled = true;
    const oldText = btnSubmit.textContent;
    btnSubmit.textContent = "提交中...";

    try {
        const accountId = getRequiredCurrentAccountId();
        const payload = {
            amount: amount,
            biz_date: dateInput.value,
            remark: remarkInput.value || "入金"
        };

        await fetchApiOrThrow(`/account/deposit?account_id=${accountId}`, {
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
    document.getElementById("form-withdraw-date").value = getTodayDateString();
    document.getElementById("form-withdraw-amount").value = "";
    document.getElementById("form-withdraw-remark").value = "";
    document.getElementById("err-withdraw-date").classList.add("hidden");
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
    const dateInput = document.getElementById("form-withdraw-date");
    const amountInput = document.getElementById("form-withdraw-amount");
    const remarkInput = document.getElementById("form-withdraw-remark");
    const errDateSpan = document.getElementById("err-withdraw-date");
    const errSpan = document.getElementById("err-withdraw-amount");
    const btnSubmit = document.getElementById("btn-save-withdraw");

    const amount = parseFloat(amountInput.value);

    errDateSpan.classList.add("hidden");
    errSpan.classList.add("hidden");

    if (!dateInput.value) {
        errDateSpan.textContent = "请选择出金时间";
        errDateSpan.classList.remove("hidden");
        return;
    }
    if (isNaN(amount) || amount <= 0) {
        errSpan.textContent = "金额必须大于0，请输入合法金额";
        errSpan.classList.remove("hidden");
        return;
    }

    btnSubmit.disabled = true;
    const oldText = btnSubmit.textContent;
    btnSubmit.textContent = "提交中...";

    try {
        const accountId = getRequiredCurrentAccountId();
        const payload = {
            amount: amount,
            biz_date: dateInput.value,
            remark: remarkInput.value || "出金"
        };

        await fetchApiOrThrow(`/account/withdraw?account_id=${accountId}`, {
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

/* ==================== 红利税弹窗 ==================== */
function openDividendTaxModal() {
    const modal = document.getElementById("dividendTaxModal");
    if (!modal) return;
    document.getElementById("form-dividend-tax-date").value = getTodayDateString();
    document.getElementById("form-dividend-tax-amount").value = "";
    document.getElementById("form-dividend-tax-related-action-id").value = "";
    document.getElementById("form-dividend-tax-remark").value = "";
    document.getElementById("err-dividend-tax-amount").classList.add("hidden");
    modal.classList.add("active");
    setTimeout(() => {
        const input = document.getElementById("form-dividend-tax-amount");
        if (input) input.focus();
    }, 100);
}

function closeDividendTaxModal() {
    const modal = document.getElementById("dividendTaxModal");
    if (modal) modal.classList.remove("active");
}

async function submitDividendTax() {
    const dateInput = document.getElementById("form-dividend-tax-date");
    const amountInput = document.getElementById("form-dividend-tax-amount");
    const relatedActionInput = document.getElementById("form-dividend-tax-related-action-id");
    const remarkInput = document.getElementById("form-dividend-tax-remark");
    const errSpan = document.getElementById("err-dividend-tax-amount");
    const btnSubmit = document.getElementById("btn-save-dividend-tax");

    const amount = parseFloat(amountInput.value);
    if (!dateInput.value) {
        errSpan.textContent = "请选择扣税日期";
        errSpan.classList.remove("hidden");
        return;
    }
    if (isNaN(amount) || amount <= 0) {
        errSpan.textContent = "金额必须大于0，请输入合法金额";
        errSpan.classList.remove("hidden");
        return;
    }

    const afterCash = (state.currentCashBalance || 0) - amount;
    if (afterCash < 0 && !window.confirm(`扣税后可用现金将为 ${formatCurrency(afterCash)}，确认继续吗？`)) {
        return;
    }

    errSpan.classList.add("hidden");
    btnSubmit.disabled = true;
    const oldText = btnSubmit.textContent;
    btnSubmit.textContent = "提交中...";

    try {
        const accountId = getRequiredCurrentAccountId();
        const payload = {
            flow_type: "DIVIDEND_TAX",
            amount,
            biz_date: dateInput.value,
            remark: remarkInput.value || "红利税"
        };
        const relatedActionId = Number(relatedActionInput.value);
        if (Number.isInteger(relatedActionId) && relatedActionId > 0) {
            payload.related_action_id = relatedActionId;
        }

        await fetchApiOrThrow(`/account/cash-flows?account_id=${accountId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        closeDividendTaxModal();
        showToast("success", "红利税已记录");
        loadPageData();
    } catch (err) {
        showToast("error", `红利税记录失败: ${err.message}`);
    } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = oldText;
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
        const accountId = getRequiredCurrentAccountId();
        const payload = {
            amount: amount,
            direction: direction,
            remark: "前端手工校准可用现金"
        };

        await fetchApi(`/account/adjust?account_id=${accountId}`, {
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
