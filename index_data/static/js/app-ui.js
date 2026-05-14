// app-ui.js

function showGlobalOverlay(onCloseCallback) {
    const overlay = document.getElementById('globalOverlay');
    if (!overlay) return;

    overlay.classList.remove('hidden');
    // 强制回流以确保动画生效
    void overlay.offsetWidth;
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';

    overlay.onclick = function (e) {
        if (e.target === overlay) {
            // 点击外部同样隐藏，不过如果有传入外部回调，先调回调
            if (onCloseCallback) onCloseCallback();
        }
    };
}

function hideGlobalOverlay() {
    const overlay = document.getElementById('globalOverlay');
    if (!overlay) return;

    overlay.classList.remove('active');
    document.body.style.overflow = '';

    // 对应 CSS 中 0.3s 的 transition 动画
    setTimeout(() => {
        if (!overlay.classList.contains('active')) {
            overlay.classList.add('hidden');
        }
    }, 300);

    overlay.onclick = null;
}

function showToast(type, message) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ'
    };
    const durations = {
        success: 3000,
        error: 5000,
        warning: 4000,
        info: 3000
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.textContent = icons[type] || 'ℹ';

    const messageNode = document.createElement('span');
    messageNode.className = 'toast-message';
    messageNode.textContent = message;

    const closeButton = document.createElement('button');
    closeButton.className = 'toast-close';
    closeButton.setAttribute('aria-label', '关闭');
    closeButton.textContent = '×';

    toast.appendChild(icon);
    toast.appendChild(messageNode);
    toast.appendChild(closeButton);

    // 关闭按钮
    closeButton.addEventListener('click', () => {
        toast.remove();
    });

    container.appendChild(toast);

    // 最多同时显示 3 条
    while (container.children.length > 3) {
        container.firstChild.remove();
    }

    // 自动消失
    setTimeout(() => {
        if (toast.parentNode) toast.remove();
    }, durations[type] || 3000);
}

// 确认弹窗
function openConfirmModal(targetText, onConfirm) {
    const modal = document.getElementById('confirmModal');
    const target = document.getElementById('confirmTarget');

    // 注入被删除的对象信息
    target.textContent = targetText;

    // 绑定确认/取消事件（每次打开重新绑定，避免事件堆积）
    const okBtn = document.getElementById('confirmOkBtn');
    const cancelBtn = document.getElementById('confirmCancelBtn');

    const handleConfirm = async () => {
        okBtn.classList.add('is-loading');
        okBtn.disabled = true;
        try {
            await onConfirm();
            closeConfirmModal();
            showToast('success', `已删除`);
        } catch (err) {
            okBtn.classList.remove('is-loading');
            okBtn.disabled = false;
            showToast('error', `删除失败：${err.message}`);
        }
    };

    // 每次重新绑定（先克隆节点移除旧监听）
    const newOkBtn = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newOkBtn, okBtn);
    newOkBtn.addEventListener('click', handleConfirm);
    cancelBtn.onclick = closeConfirmModal;

    // 显示
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
    // 焦点移到取消按钮（更安全，防止 Enter 键误确认）
    setTimeout(() => cancelBtn.focus(), 50);
}

function closeConfirmModal() {
    const modal = document.getElementById('confirmModal');
    modal.classList.remove('active');
    document.body.style.overflow = '';
}

// 加载弹窗
let loadingTimer = null;

function showLoadingModal(text = '处理中，请稍候...') {
    const modal = document.getElementById('loadingModal');
    document.getElementById('loadingText').textContent = text;
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';

    // 超时保护：15s 自动关闭
    loadingTimer = setTimeout(() => {
        hideLoadingModal();
        showToast('error', '操作超时，请重试');
    }, 15000);
}

function hideLoadingModal() {
    if (loadingTimer) { clearTimeout(loadingTimer); loadingTimer = null; }
    const modal = document.getElementById('loadingModal');
    modal.classList.remove('active');
    document.body.style.overflow = '';
}

// 表单校验辅助
function showFieldError(inputId, errorId, message) {
    const input = document.getElementById(inputId);
    const error = document.getElementById(errorId);
    if (input) input.classList.add('has-error');
    if (error) { error.textContent = message; error.classList.remove('hidden'); }
}

function clearFormErrors(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    modal.querySelectorAll('.form-input, .form-select').forEach(el => el.classList.remove('has-error'));
    modal.querySelectorAll('.form-error').forEach(el => el.classList.add('hidden'));
}

// 全局 Escape 键关闭弹窗/侧边栏
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        closeAccountMenu();
        closePositionActionMenus();
        closeTransactionMenu();
        // 按优先级关闭
        const accountDeleteModal = document.getElementById('accountDeleteModal');
        if (accountDeleteModal && accountDeleteModal.classList.contains('active')) {
            closeAccountDeleteModal();
            return;
        }
        const accountModal = document.getElementById('accountModal');
        if (accountModal && accountModal.classList.contains('active')) {
            closeAccountModal();
            return;
        }
        const confirmModal = document.getElementById('confirmModal');
        if (confirmModal && confirmModal.classList.contains('active')) {
            closeConfirmModal();
            return;
        }
        const assetModal = document.getElementById('assetModal');
        if (assetModal && assetModal.classList.contains('active')) {
            closeAssetModal();
            return;
        }
        const corporateActionModal = document.getElementById('corporateActionModal');
        if (corporateActionModal && corporateActionModal.classList.contains('active')) {
            closeCorporateActionModal();
            return;
        }
        const txModal = document.getElementById('transactionEditModal');
        if (txModal && txModal.classList.contains('active')) {
            closeTransactionEditModal();
            return;
        }
        const tradeModal = document.getElementById('tradeModal');
        if (tradeModal && tradeModal.classList.contains('active')) {
            closeTradeModal();
            return;
        }
    }
});

document.addEventListener('click', () => {
    closeAccountMenu();
    closePositionActionMenus();
    closeTransactionMenu();
});


function toggleTransactionMenu(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('transactionMenu');
    if (!menu) return;
    menu.classList.toggle('hidden');
}

function closeTransactionMenu() {
    const menu = document.getElementById('transactionMenu');
    if (menu) menu.classList.add('hidden');
}
