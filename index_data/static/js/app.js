// app.js

function setupGlobalActionBindings() {
    document.body.addEventListener('click', (e) => {
        const preventCloseEl = e.target.closest('[data-prevent-close="true"]');
        if (preventCloseEl) {
            e.stopPropagation();
        }

        const actionEl = e.target.closest('[data-action]');
        if (!actionEl) return;

        const action = actionEl.getAttribute('data-action');
        
        switch(action) {
            case 'toggle-account-menu':
                e.preventDefault();
                e.stopPropagation();
                if (typeof toggleAccountMenu === 'function') toggleAccountMenu(e);
                break;
            case 'open-trade-modal':
                e.preventDefault();
                if (typeof closeTransactionMenu === 'function') closeTransactionMenu();
                if (typeof openTradeModal === 'function') openTradeModal(actionEl.getAttribute('data-side'));
                break;
            case 'toggle-transaction-menu':
                e.preventDefault();
                e.stopPropagation();
                if (typeof toggleTransactionMenu === 'function') toggleTransactionMenu(e);
                break;
            case 'open-modal':
                e.preventDefault();
                if (typeof closeTransactionMenu === 'function') closeTransactionMenu();
                const modalId = actionEl.getAttribute('data-modal');
                if (modalId === 'depositModal' && typeof openDepositModal === 'function') openDepositModal();
                if (modalId === 'withdrawModal' && typeof openWithdrawModal === 'function') openWithdrawModal();
                if (modalId === 'cashAdjustModal' && typeof openCashAdjustModal === 'function') openCashAdjustModal();
                if (modalId === 'dividendTaxModal' && typeof openDividendTaxModal === 'function') openDividendTaxModal();
                break;
            case 'open-create-account-modal':
                e.preventDefault();
                if (typeof openCreateAccountModal === 'function') openCreateAccountModal();
                break;
            case 'refresh-quotes':
                e.preventDefault();
                if (typeof refreshPositionsQuotes === 'function') refreshPositionsQuotes();
                break;
            case 'load-more':
                e.preventDefault();
                if (typeof loadMoreList === 'function') loadMoreList(actionEl.getAttribute('data-target'));
                break;
            case 'switch-tab':
                e.preventDefault();
                const group = actionEl.getAttribute('data-group');
                const tabName = actionEl.getAttribute('data-tab');
                if (group === 'transaction' && typeof switchTransactionTab === 'function') switchTransactionTab(tabName);
                break;
            case 'close-modal':
                e.preventDefault();
                const mClose = actionEl.getAttribute('data-modal');
                if (mClose === 'transactionEditModal' && typeof closeTransactionEditModal === 'function') closeTransactionEditModal();
                if (mClose === 'accountModal' && typeof closeAccountModal === 'function') closeAccountModal();
                if (mClose === 'accountDeleteModal' && typeof closeAccountDeleteModal === 'function') closeAccountDeleteModal();
                if (mClose === 'tradeModal' && typeof closeTradeModal === 'function') closeTradeModal();
                if (mClose === 'depositModal' && typeof closeDepositModal === 'function') closeDepositModal();
                if (mClose === 'withdrawModal' && typeof closeWithdrawModal === 'function') closeWithdrawModal();
                if (mClose === 'cashAdjustModal' && typeof closeCashAdjustModal === 'function') closeCashAdjustModal();
                if (mClose === 'dividendTaxModal' && typeof closeDividendTaxModal === 'function') closeDividendTaxModal();
                if (mClose === 'corporateActionModal' && typeof closeCorporateActionModal === 'function') closeCorporateActionModal();
                if (mClose === 'stockCorporateActionModal' && typeof closeStockCorporateActionModal === 'function') closeStockCorporateActionModal();
                break;
            case 'save-transaction-edit':
                e.preventDefault();
                if (typeof saveTransactionEdit === 'function') saveTransactionEdit();
                break;
            case 'save-account':
                e.preventDefault();
                if (typeof saveAccountModal === 'function') saveAccountModal();
                break;
            case 'confirm-delete-account':
                e.preventDefault();
                if (typeof confirmDeleteAccount === 'function') confirmDeleteAccount();
                break;
            case 'submit-deposit':
                e.preventDefault();
                if (typeof submitDeposit === 'function') submitDeposit();
                break;
            case 'submit-withdraw':
                e.preventDefault();
                if (typeof submitWithdraw === 'function') submitWithdraw();
                break;
            case 'submit-cash-adjust':
                e.preventDefault();
                if (typeof saveCashAdjust === 'function') saveCashAdjust();
                break;
            case 'submit-dividend-tax':
                e.preventDefault();
                if (typeof submitDividendTax === 'function') submitDividendTax();
                break;
            case 'edit-transaction':
                e.preventDefault();
                if (typeof openTransactionEditModal === 'function') openTransactionEditModal(actionEl.getAttribute('data-id'));
                break;
            case 'edit-ca':
                e.preventDefault();
                if (typeof openCorporateActionEditModal === 'function') openCorporateActionEditModal(actionEl.getAttribute('data-id'));
                break;
            case 'cancel-ca':
                e.preventDefault();
                const cancelId = actionEl.getAttribute('data-id');
                if (cancelId) {
                    if (typeof cancelCorporateAction === 'function') cancelCorporateAction(cancelId);
                } else {
                    if (typeof cancelCurrentCorporateAction === 'function') cancelCurrentCorporateAction();
                }
                break;
            case 'confirm-stock-ca-bundle':
                e.preventDefault();
                if (typeof confirmStockCorporateActionBundle === 'function') confirmStockCorporateActionBundle(actionEl.getAttribute('data-bundle'));
                break;
            case 'edit-stock-ca-bundle':
                e.preventDefault();
                if (typeof openStockCorporateActionBundleEditModal === 'function') openStockCorporateActionBundleEditModal(actionEl.getAttribute('data-bundle'));
                break;
            case 'cancel-stock-ca-bundle':
                e.preventDefault();
                if (typeof cancelStockCorporateActionBundle === 'function') cancelStockCorporateActionBundle(actionEl.getAttribute('data-bundle'));
                break;
            case 'preview-ca':
                e.preventDefault();
                if (typeof previewCorporateAction === 'function') previewCorporateAction();
                break;
            case 'submit-ca':
                e.preventDefault();
                if (typeof submitCorporateAction === 'function') submitCorporateAction();
                break;
            case 'preview-stock-ca':
                e.preventDefault();
                if (typeof previewStockCorporateAction === 'function') previewStockCorporateAction();
                break;
            case 'submit-stock-ca':
                e.preventDefault();
                if (typeof submitStockCorporateAction === 'function') submitStockCorporateAction();
                break;
        }
    });
}

document.addEventListener('DOMContentLoaded', async () => {
    setupGlobalActionBindings();
    initializeTradeDateDefault();
    initTabs();
    initTradeModal();
    initCorporateActionModal();
    if (typeof initAssetManagerEvents === 'function') initAssetManagerEvents();
    await initDataSyncUI();
    Object.keys(listPaginationState).forEach((key) => updatePaginationUI(key));

    // v2.5: 绑定表格行的排他选中高亮事件 (事件委托)
    document.querySelectorAll('.data-table, .fixed-layout').forEach(table => {
        table.addEventListener('click', function(e) {
            const tr = e.target.closest('tr');
            if (!tr || !tr.parentElement || tr.parentElement.tagName !== 'TBODY') return;
            
            // 排除对操作按钮、链接、菜单面板的点击
            if (e.target.closest('button') || e.target.closest('a') || e.target.closest('.row-action-menu')) {
                return;
            }

            // 移除同表下的所有其他高亮行
            const tbody = tr.parentElement;
            tbody.querySelectorAll('tr.active-row').forEach(row => row.classList.remove('active-row'));
            
            // 激活当前点击行
            tr.classList.add('active-row');
        });
    });

    await initAccountContext();
});
