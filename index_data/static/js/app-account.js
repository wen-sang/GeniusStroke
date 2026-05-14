// app-account.js

async function initAccountContext() {
    await refreshAccountList({ keepCurrent: true, reload: false });
    if (state.currentAccount && !state.isEmptyAccountState) {
        loadPageData();
    }
}

function updateAccountPageState() {
    const switcherBar = document.getElementById('accountSwitcherBar');
    const metricsSection = document.getElementById('metricsSection');
    const emptyState = document.getElementById('accountEmptyState');
    const targetViewId = `view-${state.currentTab}`;

    if (switcherBar) switcherBar.classList.toggle('hidden', state.isEmptyAccountState);
    if (metricsSection) metricsSection.classList.toggle('hidden', state.isEmptyAccountState);
    if (emptyState) emptyState.classList.toggle('hidden', !state.isEmptyAccountState);

    document.querySelectorAll('[id^="view-"]').forEach((el) => {
        el.classList.toggle('hidden', state.isEmptyAccountState || el.id !== targetViewId);
    });
}

function renderAccountSwitcher() {
    const bar = document.getElementById('accountSwitcherBar');
    const nameEl = document.getElementById('accountSwitcherCurrentName');
    const trigger = document.getElementById('accountSwitcherTrigger');
    const menu = document.getElementById('accountSwitcherMenu');
    if (!bar || !nameEl || !trigger || !menu) return;

    if (state.isEmptyAccountState || !state.currentAccount || state.accountList.length === 0) {
        bar.classList.add('hidden');
        menu.classList.add('hidden');
        trigger.setAttribute('aria-expanded', 'false');
        return;
    }

    bar.classList.remove('hidden');
    nameEl.textContent = state.currentAccountName || '--';
    trigger.setAttribute('aria-expanded', state.isAccountMenuOpen ? 'true' : 'false');
    clearElement(menu);
    menu.appendChild(buildAccountSwitcherActions());

    const sectionTitle = document.createElement('div');
    sectionTitle.className = 'account-section-title';
    sectionTitle.textContent = '账户列表';
    menu.appendChild(sectionTitle);

    const list = document.createElement('div');
    list.className = 'account-switcher-list';
    state.accountList.forEach((acc) => {
        list.appendChild(buildAccountSwitcherItem(acc));
    });
    menu.appendChild(list);
    menu.classList.toggle('hidden', !state.isAccountMenuOpen);
}

function buildAccountSwitcherActions() {
    const actions = document.createElement('div');
    actions.className = 'account-switcher-actions';

    actions.appendChild(createAccountSwitcherActionButton({
        label: '编辑...',
        iconMarkup: '<svg class="action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>',
        onClick: openEditAccountModal
    }));
    actions.appendChild(createAccountSwitcherActionButton({
        label: '删除',
        iconMarkup: '<svg class="action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
        onClick: openAccountDeleteModal
    }));

    const divider = document.createElement('div');
    divider.className = 'account-switcher-divider';
    actions.appendChild(divider);

    actions.appendChild(createAccountSwitcherActionButton({
        label: '创建新的账户',
        iconMarkup: '<svg class="action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>',
        onClick: openCreateAccountModal,
        className: 'action-create',
        wrapInActionLeft: true
    }));

    return actions;
}

function createAccountSwitcherActionButton({ label, iconMarkup, onClick, className = '', wrapInActionLeft = false }) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `account-switcher-action ${className}`.trim();

    const contentRoot = wrapInActionLeft ? document.createElement('div') : button;
    if (wrapInActionLeft) {
        contentRoot.className = 'action-left';
        button.appendChild(contentRoot);
    }

    const iconHost = document.createElement('span');
    iconHost.className = 'account-switcher-icon';
    iconHost.innerHTML = iconMarkup;
    contentRoot.appendChild(iconHost);

    const labelSpan = document.createElement('span');
    labelSpan.textContent = label;
    contentRoot.appendChild(labelSpan);

    button.addEventListener('click', (event) => {
        event.stopPropagation();
        onClick();
    });

    return button;
}

function buildAccountSwitcherItem(account) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'account-switcher-item';
    if (account.account_id === state.currentAccount) {
        button.classList.add('active');
    }

    const nameSpan = document.createElement('span');
    nameSpan.style.flexGrow = '1';
    nameSpan.style.textAlign = 'left';
    nameSpan.textContent = account.account_name || '--';
    button.appendChild(nameSpan);

    if (account.account_id === state.currentAccount) {
        const checkIcon = document.createElement('span');
        checkIcon.className = 'account-switcher-check';
        checkIcon.innerHTML = '<svg class="action-icon" viewBox="0 0 24 24" fill="none" stroke="#2962FF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px; opacity: 1;"><polyline points="20 6 9 17 4 12"></polyline></svg>';
        button.appendChild(checkIcon);
    }

    button.addEventListener('click', (event) => {
        event.stopPropagation();
        switchAccount(account.account_id);
    });

    return button;
}

function toggleAccountMenu(event, force = null) {
    if (event) event.stopPropagation();
    if (state.isEmptyAccountState || !state.currentAccount) return;
    state.isAccountMenuOpen = force === null ? !state.isAccountMenuOpen : !!force;
    renderAccountSwitcher();
}

function closeAccountMenu() {
    if (!state.isAccountMenuOpen) return;
    state.isAccountMenuOpen = false;
    renderAccountSwitcher();
}

function enterAccountEmptyState() {
    state.isEmptyAccountState = true;
    state.currentAccount = null;
    state.currentAccountName = '';
    state.currentAccountSummary = null;
    state.currentCashBalance = 0;
    state.isAccountMenuOpen = false;
    updateAccountPageState();
    renderAccountSwitcher();
}

function exitAccountEmptyState() {
    state.isEmptyAccountState = false;
    updateAccountPageState();
    renderAccountSwitcher();
}

async function refreshAccountList({ keepCurrent = true, preferredAccountId = null, reload = true } = {}) {
    const accounts = await fetchApi('/account/list');
    if (accounts === null) {
        showToast('error', '账户列表加载失败，请稍后重试');
        return null;
    }
    state.accountList = Array.isArray(accounts) ? accounts : [];

    if (state.accountList.length === 0) {
        enterAccountEmptyState();
        return null;
    }

    const desiredId = preferredAccountId ?? (keepCurrent ? state.currentAccount : null);
    let selected = state.accountList.find((acc) => acc.account_id === desiredId);
    if (!selected) selected = state.accountList[0];

    state.currentAccount = selected.account_id;
    state.currentAccountName = selected.account_name || 'Default';
    state.currentAccountSummary = null;
    exitAccountEmptyState();

    if (reload) {
        loadPageData();
    } else {
        updateAccountPageState();
        renderAccountSwitcher();
    }
    return selected;
}

function switchAccount(accountId) {
    const selected = state.accountList.find((acc) => acc.account_id === Number(accountId));
    if (!selected) return;
    state.currentAccount = selected.account_id;
    state.currentAccountName = selected.account_name || 'Default';
    state.currentAccountSummary = null;
    closeAccountMenu();
    loadPageData();
}

function openCreateAccountModal() {
    state.accountModalMode = 'create';
    const modal = document.getElementById('accountModal');
    const title = document.getElementById('accountModalTitle');
    const input = document.getElementById('form-account-name');
    const button = document.getElementById('btn-save-account');
    clearFormErrors('accountModal');
    if (title) title.textContent = '新增账户';
    if (button) button.textContent = '确定保存';
    if (input) input.value = '';
    if (modal) modal.classList.add('active');
    closeAccountMenu();
    setTimeout(() => input && input.focus(), 80);
}

function openEditAccountModal() {
    if (!state.currentAccount) return;
    state.accountModalMode = 'edit';
    const modal = document.getElementById('accountModal');
    const title = document.getElementById('accountModalTitle');
    const input = document.getElementById('form-account-name');
    const button = document.getElementById('btn-save-account');
    clearFormErrors('accountModal');
    if (title) title.textContent = '编辑账户';
    if (button) button.textContent = '确定保存';
    if (input) input.value = state.currentAccountName || '';
    if (modal) modal.classList.add('active');
    closeAccountMenu();
    setTimeout(() => input && input.focus(), 80);
}

function closeAccountModal() {
    const modal = document.getElementById('accountModal');
    if (modal) modal.classList.remove('active');
    clearFormErrors('accountModal');
}

function validateAccountNameInput() {
    const input = document.getElementById('form-account-name');
    const raw = input ? input.value : '';
    const value = String(raw || '').trim();

    if (!value) {
        showFieldError('form-account-name', 'err-account-name', '请输入账户名称');
        return null;
    }
    if (value.length > 50) {
        showFieldError('form-account-name', 'err-account-name', '账户名称长度不能超过50个字符');
        return null;
    }
    return value;
}

async function saveAccountModal() {
    clearFormErrors('accountModal');
    const accountName = validateAccountNameInput();
    if (!accountName) return;

    const isEditing = state.accountModalMode === 'edit';
    const button = document.getElementById('btn-save-account');
    const oldText = button ? button.textContent : '确定保存';
    if (button) {
        button.disabled = true;
        button.classList.add('is-loading');
    }

    try {
        const result = await fetchApiOrThrow(isEditing ? `/account/${state.currentAccount}` : '/account', {
            method: isEditing ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_name: accountName })
        });
        closeAccountModal();
        await refreshAccountList({
            preferredAccountId: result.account?.account_id || state.currentAccount,
            keepCurrent: !isEditing,
            reload: true
        });
        showToast('success', isEditing ? '账户更新成功' : '账户创建成功');
    } catch (error) {
        showFieldError('form-account-name', 'err-account-name', error.message || '保存失败');
    } finally {
        if (button) {
            button.disabled = false;
            button.classList.remove('is-loading');
            button.textContent = oldText;
        }
    }
}

function openAccountDeleteModal() {
    if (!state.currentAccount) return;
    const modal = document.getElementById('accountDeleteModal');
    const target = document.getElementById('accountDeleteTarget');
    if (target) target.textContent = state.currentAccountName || '--';
    if (modal) modal.classList.add('active');
    closeAccountMenu();
}

function closeAccountDeleteModal() {
    const modal = document.getElementById('accountDeleteModal');
    if (modal) modal.classList.remove('active');
}

async function confirmDeleteAccount() {
    if (!state.currentAccount) return;
    const button = document.getElementById('accountDeleteConfirmBtn');
    if (button) {
        button.disabled = true;
        button.classList.add('is-loading');
    }

    try {
        const result = await fetchApiOrThrow(`/account/${state.currentAccount}`, {
            method: 'DELETE'
        });
        closeAccountDeleteModal();
        if ((result.remaining_account_count || 0) === 0) {
            state.accountList = [];
            enterAccountEmptyState();
        } else {
            await refreshAccountList({
                preferredAccountId: result.next_account_id,
                keepCurrent: false,
                reload: true
            });
        }
        showToast('success', '账户删除成功');
    } catch (error) {
        showToast('error', error.message || '删除失败');
    } finally {
        if (button) {
            button.disabled = false;
            button.classList.remove('is-loading');
        }
    }
}

// ==================== 页面逻辑: Tab 切换 ====================

function initTabs() {
    document.querySelectorAll('.main-tab-item').forEach(tab => {
        tab.addEventListener('click', function () {
            // Update Active State
            document.querySelectorAll('.main-tab-item').forEach(t => t.classList.remove('active'));
            this.classList.add('active');

            const tabName = this.dataset.tab;
            switchMainTab(tabName);
        });
    });
}

function switchMainTab(tabName) {
    state.currentTab = tabName;

    updateAccountPageState();

    if (state.isEmptyAccountState) return;
    loadCurrentTabData();
}

// ==================== 页面逻辑: 账户概览 ====================

async function loadAccountSummary(loadContext = null) {
    if (!state.currentAccount) return;
    if (isStaleSummaryLoad(loadContext)) return;

    // Reset to loading state
    setText('summary-total-asset', '--');
    setText('summary-cash', '--');
    setText('summary-market-value', '--');
    setText('summary-daily-return', '--');
    setText('summary-daily-return-rate', '--');
    setText('summary-holding-pnl', '--');
    setText('summary-holding-pnl-rate', '--');
    setText('summary-total-return', '--');
    setText('summary-history-total-pnl', '--');
    setText('summary-history-total-pnl-rate', '--');
    setText('summary-account-xirr', '--');
    setText('summary-data-updated-to', '数据更新至 --');

    const data = await fetchApi(`/account/summary?account_id=${state.currentAccount}`);
    if (isStaleSummaryLoad(loadContext)) return;
    if (data) {
        state.currentAccountSummary = data;
        state.currentAccountName = data.account_name || state.currentAccountName;
        renderAccountSwitcher();
        setText('summary-total-asset', formatCurrency(data.total_asset));
        setText('summary-cash', formatCurrency(data.cash_balance));
        setText('summary-market-value', formatCurrency(data.total_market_value));
        setText('summary-daily-return', formatCurrency(data.daily_return));
        setText('summary-daily-return-rate', formatPercent(data.daily_return_rate));
        setText('summary-holding-pnl', formatCurrency(data.floating_pnl));
        const holdingCost = data.total_market_value - data.floating_pnl;
        const holdingPnlRate = holdingCost > 0 ? data.floating_pnl / holdingCost : null;
        setText('summary-holding-pnl-rate', formatPercent(holdingPnlRate));
        setText('summary-total-return', formatCurrency(data.history_total_pnl));
        setText('summary-history-total-pnl', formatCurrency(data.history_total_pnl));
        setText('summary-history-total-pnl-rate', formatPercent(data.history_total_pnl_rate));
        setText('summary-account-xirr', formatPercent(data.account_xirr));
        const displayDate = data.data_updated_to ? String(data.data_updated_to).replace(/-/g, '') : '--';
        setText('summary-data-updated-to', `数据更新至 ${displayDate}`);

        state.currentCashBalance = data.cash_balance;
        const editBtn = document.getElementById('edit-cash-btn');
        if (editBtn) editBtn.classList.remove('hidden');

        setColor('summary-daily-return', data.daily_return);
        setColor('summary-daily-return-rate', data.daily_return);
        setColor('summary-holding-pnl', data.floating_pnl);
        setColor('summary-holding-pnl-rate', data.floating_pnl);
        setColor('summary-total-return', data.history_total_pnl);
        setColor('summary-history-total-pnl', data.history_total_pnl);
        setColor('summary-history-total-pnl-rate', data.history_total_pnl);
        setColor('summary-account-xirr', data.account_xirr);
        if (document.getElementById('tradeModal')?.classList.contains('active')) {
            calculateTradeTotal();
        }
    }
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function setColor(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.style.color = value > 0 ? 'var(--up-red)' : (value < 0 ? 'var(--down-green)' : '');
    }
}
