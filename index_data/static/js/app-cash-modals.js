// app-cash-modals.js
// 资金弹窗：入金 / 出金 / 红利税 / 现金调整

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
