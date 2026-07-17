// app-trade-modal.js
// 交易弹窗（开/关/切换/费用计算/提交）与交易记录编辑弹窗

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
