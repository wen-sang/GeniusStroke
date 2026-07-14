// app-ui.js

// 全站共享内联 SVG 图标（stroke: currentColor，颜色由外层 CSS 控制）
const GS_ICONS = {
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    crossCircle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    cross: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
};

// Tooltip 点击切换（兼顾触屏），点击他处关闭
document.addEventListener('click', (e) => {
    const trigger = e.target.closest('.tooltip-trigger');
    document.querySelectorAll('.tooltip-trigger.is-open').forEach((el) => {
        if (el !== trigger) el.classList.remove('is-open');
    });
    if (trigger) trigger.classList.toggle('is-open');
});

// ==================== 弹窗焦点圈定与归还 ====================
// 通过 MutationObserver 监听 .modal-overlay 的 active 类变化统一挂接，
// 避免逐个改动分散的 openXxxModal/closeXxxModal 开关函数。
const modalFocusState = {
    activeModal: null,
    returnFocusEl: null
};

function getModalFocusables(overlay) {
    const selector = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    return Array.from(overlay.querySelectorAll(selector)).filter((el) => {
        if (el.disabled || el.getAttribute('aria-hidden') === 'true') return false;
        return el.offsetParent !== null; // 过滤 display:none 的元素
    });
}

function handleModalFocusTrapKeydown(e) {
    if (e.key !== 'Tab' || !modalFocusState.activeModal) return;
    const focusables = getModalFocusables(modalFocusState.activeModal);
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const current = document.activeElement;
    if (e.shiftKey) {
        if (current === first || !modalFocusState.activeModal.contains(current)) {
            e.preventDefault();
            last.focus();
        }
    } else if (current === last || !modalFocusState.activeModal.contains(current)) {
        e.preventDefault();
        first.focus();
    }
}

function trapModalFocus(overlay) {
    modalFocusState.activeModal = overlay;
    modalFocusState.returnFocusEl = document.activeElement;
    const focusables = getModalFocusables(overlay);
    if (focusables.length > 0) focusables[0].focus();
}

function releaseModalFocus() {
    modalFocusState.activeModal = null;
    const target = modalFocusState.returnFocusEl;
    modalFocusState.returnFocusEl = null;
    if (target && document.contains(target) && typeof target.focus === 'function') {
        target.focus();
    }
}

function initModalFocusManagement() {
    document.addEventListener('keydown', handleModalFocusTrapKeydown);
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            const overlay = mutation.target;
            const isActive = overlay.classList.contains('active');
            if (isActive && modalFocusState.activeModal !== overlay) {
                trapModalFocus(overlay);
            } else if (!isActive && modalFocusState.activeModal === overlay) {
                releaseModalFocus();
            }
        });
    });
    document.querySelectorAll('.modal-overlay').forEach((overlay) => {
        observer.observe(overlay, { attributes: true, attributeFilter: ['class'] });
    });
}

document.addEventListener('DOMContentLoaded', initModalFocusManagement);

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
        success: GS_ICONS.check,
        error: GS_ICONS.cross,
        warning: GS_ICONS.warning,
        info: GS_ICONS.info
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
    // 固定图标集用 innerHTML 注入 SVG；消息文本仍走 textContent 保证安全
    icon.innerHTML = icons[type] || GS_ICONS.info;

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

    // 退场动画：加 is-leaving 播放滑出过渡后再移除（transitionend + 定时器兜底）
    const dismissToast = (target) => {
        if (!target || !target.parentNode || target.classList.contains('is-leaving')) return;
        target.classList.add('is-leaving');
        const removeNow = () => target.remove();
        target.addEventListener('transitionend', removeNow, { once: true });
        setTimeout(removeNow, 300);
    };

    // 关闭按钮
    closeButton.addEventListener('click', () => {
        dismissToast(toast);
    });

    container.appendChild(toast);

    // 最多同时显示 3 条（超量的同样走退场）
    const activeToasts = Array.from(container.children).filter((el) => !el.classList.contains('is-leaving'));
    while (activeToasts.length > 3) {
        dismissToast(activeToasts.shift());
    }

    // 自动消失
    setTimeout(() => {
        dismissToast(toast);
    }, durations[type] || 3000);
}

// 确认弹窗
function openConfirmModal(targetText, onConfirm, successMessage = '已删除') {
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
            showToast('success', successMessage);
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
        const leaveConfirmModal = document.getElementById('leaveConfirmModal');
        if (leaveConfirmModal && leaveConfirmModal.classList.contains('active')) {
            closeLeaveConfirmModal();
            return;
        }
        const assetManagerModal = document.getElementById('assetManagerModal');
        if (assetManagerModal && assetManagerModal.classList.contains('active')) {
            if (typeof assetManagerState !== 'undefined' && assetManagerState.mode === 'form') {
                requestLeaveForm('close', document.getElementById('assetManagerCloseX'));
            } else {
                closeAssetManagerModal();
            }
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
