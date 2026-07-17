// app-asset-manager.js
// 资产管理弹窗：列表/表单双视图、目录检索 Popover、脏检查与离开确认

// 全局弹窗滚动锁定器
const ModalScrollController = {
    lock() {
        document.body.classList.add('modal-open');
    },
    unlock() {
        document.body.classList.remove('modal-open');
    }
};

function handleAssetManagerModalKeydown(event) {
    if (event.key === 'Escape') {
        event.preventDefault();
        if (assetManagerState.mode === 'form') {
            requestLeaveForm('close', document.getElementById('assetManagerCloseX'));
        } else {
            closeAssetManagerModal();
        }
        return;
    }
    
    if (event.key === 'Tab') {
        const modal = document.getElementById('assetManagerModal');
        if (!modal) return;
        
        const focusableElements = Array.from(modal.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )).filter(el => {
            if (el.disabled || el.tabIndex === -1) return false;
            return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
        });
        
        if (!focusableElements.length) return;
        
        const first = focusableElements[0];
        const last = focusableElements[focusableElements.length - 1];
        
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }
}

const assetManagerState = {
    currentTab: 'others',
    mode: 'list',
    formMode: null,
    editingCode: null,
    isDirty: false,
    formSnapshot: {},
    pendingLeaveAction: null,
    pendingLeaveTriggerEl: null,
    lookupSelectedItem: null
};

const lookupState = {
    isOpen: false,
    keyword: '',
    page: 1,
    hasMore: false,
    focusedIndex: -1,
    debounceTimer: null,
    requestSeq: 0,
    items: [],
    loadingMore: false
};

let assetManagerEventsBound = false;
let assetManagerReturnFocusEl = null;
let leaveConfirmKeydownHandler = null;

function initAssetManagerEvents() {
    if (assetManagerEventsBound) return;
    assetManagerEventsBound = true;

    document.getElementById('openAssetManagerBtn')?.addEventListener('click', openAssetManagerModal);

    document.getElementById('marketBrandTabs')?.addEventListener('click', event => {
        const tab = event.target.closest('[data-action="switch-market-brand"]');
        if (tab) switchMarketBrand(tab.dataset.brand);
    });

    document.getElementById('marketViewSwitcher')?.addEventListener('click', event => {
        const btn = event.target.closest('.gs-capsule-item');
        if (!btn || btn.classList.contains('active')) return;
        switchMarketView(btn.dataset.view);
    });

    document.getElementById('market-table-market')?.addEventListener('click', event => {
        const btn = event.target.closest('[data-action="sort-market"]');
        if (btn) sortMarketBy(btn.dataset.sortBy);
    });

    document.getElementById('assetManagerAddBtn')?.addEventListener('click', () => {
        switchToFormView('create');
    });

    document.getElementById('assetManagerCloseX')?.addEventListener('click', event => {
        if (assetManagerState.mode === 'form') requestLeaveForm('close', event.currentTarget);
        else closeAssetManagerModal();
    });

    document.getElementById('assetManagerCloseBtn')?.addEventListener('click', closeAssetManagerModal);

    document.getElementById('assetFormBackBtn')?.addEventListener('click', event => {
        requestLeaveForm('back', event.currentTarget);
    });

    document.getElementById('assetFormCancelBtn')?.addEventListener('click', event => {
        requestLeaveForm('back', event.currentTarget);
    });

    document.getElementById('assetFormSaveBtn')?.addEventListener('click', handleAssetFormSave);

    document.getElementById('leaveConfirmStayBtn')?.addEventListener('click', closeLeaveConfirmModal);
    document.getElementById('leaveConfirmLeaveBtn')?.addEventListener('click', () => {
        executeLeave(assetManagerState.pendingLeaveAction);
    });

    document.querySelector('#assetManagerModal .am-modal-box')?.addEventListener('click', event => {
        const tab = event.target.closest('[data-action="switch-asset-manager-tab"]');
        if (tab) {
            switchAssetManagerTab(tab.dataset.tab);
            return;
        }
        const edit = event.target.closest('[data-action="am-edit-asset"]');
        if (edit) {
            handleAssetEdit(edit.dataset.code);
            return;
        }
        const del = event.target.closest('[data-action="am-delete-asset"]');
        if (del) handleAssetDelete(del.dataset.code);
    });

    const codeInput = document.getElementById('am-form-code');
    codeInput?.addEventListener('click', () => {
        if (assetManagerState.lookupSelectedItem) return;
        if (assetManagerState.formMode === 'edit') return;
        // 点击输入框时不应该立即弹出卡片，而是仅仅开启输入状态，让用户能够键入
        if (codeInput.readOnly) {
            codeInput.readOnly = false;
            codeInput.focus();
        }
    });
    codeInput?.addEventListener('input', onLookupInput);
    codeInput?.addEventListener('keydown', onLookupKeydown);

    document.getElementById('amLookupClear')?.addEventListener('click', event => {
        event.stopPropagation();
        clearLookupSelection();
    });

    document.getElementById('amLookupPopover')?.addEventListener('click', event => {
        const item = event.target.closest('.am-lookup-item');
        if (item) {
            selectLookupItem(lookupState.items[Number(item.dataset.index)]);
            return;
        }
        const more = event.target.closest('.am-lookup-more');
        if (more) loadMoreLookupResults();
    });

    document.querySelectorAll('#assetManagerFormView input, #assetManagerFormView select').forEach(el => {
        el.addEventListener('input', markAssetFormDirty);
        el.addEventListener('change', markAssetFormDirty);
    });

    const scrollContainer = document.querySelector('#assetManagerModal .am-table-scroll');
    scrollContainer?.addEventListener('scroll', () => {
        const key = 'asset_manager';
        const pagination = listPaginationState[key];
        if (!pagination) return;
        if (pagination.loading) return;
        if (pagination.items.length >= pagination.total) return;
        if (assetManagerState.mode !== 'list') return;

        const { scrollTop, scrollHeight, clientHeight } = scrollContainer;
        if (scrollHeight - scrollTop - clientHeight <= 15) {
            loadMoreList(key);
        }
    });
}

function openAssetManagerModal() {
    assetManagerReturnFocusEl = document.activeElement || document.getElementById('openAssetManagerBtn');
    assetManagerState.currentTab = marketState.currentBrand === 'index' ? 'index' : 'others';
    
    // 优雅锁定 body 背景滚动
    ModalScrollController.lock();
    
    const modal = document.getElementById('assetManagerModal');
    modal?.classList.add('active');
    
    // 注册 keydown 监听器
    modal?.addEventListener('keydown', handleAssetManagerModalKeydown);
    
    document.addEventListener('click', onDocumentClickForLookup);
    switchToListView();
    updateAssetManagerTabs();
    
    // 让弹窗内 Tab 立刻拥有漂移滑块
    setTimeout(() => {
        syncCapsuleSlider(document.getElementById('assetManagerSubTabs'));
    }, 0);
    
    loadAssetManagerList();
    setTimeout(() => document.getElementById('assetManagerCloseX')?.focus(), 0);
}

function closeAssetManagerModal() {
    closeLookupPopover();
    document.removeEventListener('click', onDocumentClickForLookup);
    
    const modal = document.getElementById('assetManagerModal');
    if (modal) {
        // 显式注销键盘监听器，以防内存泄漏
        modal.removeEventListener('keydown', handleAssetManagerModalKeydown);
        modal.classList.remove('active');
    }
    
    // 恢复背景滚动
    ModalScrollController.unlock();
    
    assetManagerState.pendingLeaveAction = null;
    assetManagerState.pendingLeaveTriggerEl = null;
    assetManagerState.lookupSelectedItem = null;
    if (assetManagerReturnFocusEl && typeof assetManagerReturnFocusEl.focus === 'function') {
        assetManagerReturnFocusEl.focus();
    } else {
        document.getElementById('openAssetManagerBtn')?.focus();
    }
}

function switchAssetManagerTab(tab) {
    if (!['others', 'index'].includes(tab)) return;
    if (tab === assetManagerState.currentTab) return;
    assetManagerState.currentTab = tab;
    updateAssetManagerTabs();
    
    // 切换 Tab 时强制重置表格滚动高度，瞬间回到最顶部，提供完美的视觉重置体验
    const scrollContainer = document.querySelector('#assetManagerModal .am-table-scroll');
    if (scrollContainer) {
        scrollContainer.scrollTop = 0;
    }

    // 同步弹窗内单轨滑块
    syncCapsuleSlider(document.getElementById('assetManagerSubTabs'));
    
    loadAssetManagerList();
}

function updateAssetManagerTabs() {
    document.querySelectorAll('#assetManagerSubTabs [data-tab]').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === assetManagerState.currentTab);
    });
}

async function loadAssetManagerList(loadContext = null, append = false) {
    const tbody = document.querySelector('#assetManagerTable tbody');
    if (!tbody) return;
    const key = 'asset_manager';
    const category = assetManagerState.currentTab;
    const page = append ? (listPaginationState[key].page + 1) : 1;
    
    const overlay = document.getElementById('amTableLoadingOverlay');

    if (!append) {
        resetPaginationState(key);
        // Tab切换或首次加载，开启毛玻璃遮罩层，且不清空已有数据，防止闪烁抖动
        overlay?.classList.add('active');
    } else {
        setPaginationLoading(key, true);
    }

    try {
        const res = await fetchApi(`/v1/assets/list?category=${category}&page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
        
        // API 返回后立即关闭遮罩层
        overlay?.classList.remove('active');

        if (category !== assetManagerState.currentTab) return;
        if (!document.getElementById('assetManagerModal')?.classList.contains('active')) return;
        if (!res) {
            listPaginationState[key].loading = false;
            updatePaginationUI(key);
            return;
        }

        const items = applyPaginatedResult(key, res, append);
        if (!append && items.length === 0) {
            renderTableStatusRow(tbody, 5, '暂无档案记录', { padded: true });
            return;
        }

        renderAssetManagerRows(items, append);
        window._assetManagerCachedAssets = listPaginationState[key].items.slice();
    } catch (err) {
        overlay?.classList.remove('active');
        listPaginationState[key].loading = false;
        updatePaginationUI(key);
        console.error('loadAssetManagerList error:', err);
    }
}

function renderAssetManagerRows(items, append = false) {
    const tbody = document.querySelector('#assetManagerTable tbody');
    const rowsHtml = items.map(item => {
        const sourceName = getSourceDisplayName(item.source_id);
        return `
        <tr>
            <td><span class="stock-code">${escapeHtml(item.asset_code)}</span></td>
            <td><span class="stock-name">${escapeHtml(item.asset_name)}</span></td>
            <td>${escapeHtml(item.asset_type)}</td>
            <td>${escapeHtml(sourceName)}</td>
            <td class="am-action-cell">
                <button class="am-action-btn am-action-edit" type="button" data-action="am-edit-asset" data-code="${escapeHtmlAttr(item.asset_code)}">修改</button>
                <button class="am-action-btn am-action-delete" type="button" data-action="am-delete-asset" data-code="${escapeHtmlAttr(item.asset_code)}">删除</button>
            </td>
        </tr>
    `}).join('');
    renderTableRows(tbody, rowsHtml, append);
}

function getSourceDisplayName(sourceId) {
    if (isLixinrenSource(sourceId)) return '理杏仁';
    if (sourceId === SOURCE_TICKFLOW) return 'TickFlow';
    if (sourceId === SOURCE_AKSHARE) return 'Akshare';
    return sourceId || '--';
}

function handleAssetEdit(code) {
    const target = (window._assetManagerCachedAssets || []).find(item => item.asset_code === code);
    if (target) switchToFormView('edit', target);
}

function handleAssetDelete(code) {
    const target = (window._assetManagerCachedAssets || []).find(item => item.asset_code === code);
    const assetName = target ? `${code}（${target.asset_name}）` : code;
    openConfirmModal(assetName, async () => {
        await fetchApiOrThrow(`/v1/assets/${encodeURIComponent(code)}`, { method: 'DELETE' });
        await loadAssetManagerList();
    }, '档案已删除');
}

function switchToFormView(mode, assetData = null) {
    assetManagerState.mode = 'form';
    assetManagerState.formMode = mode;
    assetManagerState.editingCode = assetData ? assetData.asset_code : null;
    assetManagerState.lookupSelectedItem = null;

    document.getElementById('assetFormBackBtn')?.classList.remove('hidden');
    document.getElementById('assetManagerTitle').textContent = mode === 'create' ? '新增档案' : '修改档案';
    document.getElementById('assetManagerListView')?.classList.add('hidden');
    document.getElementById('assetManagerFormView')?.classList.remove('hidden');
    document.getElementById('assetManagerFooterList')?.classList.add('hidden');
    document.getElementById('assetManagerFooterForm')?.classList.remove('hidden');

    resetAssetForm();
    if (mode === 'edit' && assetData) {
        populateAssetForm(assetData);
        setCodeFieldEditMode(assetData.asset_code);
    } else {
        initLookupField();
        document.getElementById('am-form-type').value =
            assetManagerState.currentTab === 'index' ? 'INDEX' : 'ETF';
    }

    takeFormSnapshot();
    assetManagerState.isDirty = false;
    setTimeout(() => {
        const focusTarget = mode === 'edit'
            ? document.getElementById('am-form-name')
            : document.getElementById('am-form-code');
        focusTarget?.focus();
    }, 0);
}

function switchToListView() {
    assetManagerState.mode = 'list';
    assetManagerState.isDirty = false;
    assetManagerState.formSnapshot = {};
    assetManagerState.formMode = null;
    assetManagerState.editingCode = null;
    assetManagerState.pendingLeaveAction = null;
    assetManagerState.pendingLeaveTriggerEl = null;
    assetManagerState.lookupSelectedItem = null;
    closeLookupPopover();

    document.getElementById('assetFormBackBtn')?.classList.add('hidden');
    document.getElementById('assetManagerTitle').textContent = '基础档案';
    document.getElementById('assetManagerFormView')?.classList.add('hidden');
    document.getElementById('assetManagerListView')?.classList.remove('hidden');
    document.getElementById('assetManagerFooterForm')?.classList.add('hidden');
    document.getElementById('assetManagerFooterList')?.classList.remove('hidden');

    // 每次切换回列表视图时，也自动回到最顶部，保持清爽重置状态
    const scrollContainer = document.querySelector('#assetManagerModal .am-table-scroll');
    if (scrollContainer) {
        scrollContainer.scrollTop = 0;
    }
}

function resetAssetForm() {
    clearFormErrors('assetManagerModal');
    setValue('am-form-code', '');
    setValue('am-form-name', '');
    setValue('am-form-source', SOURCE_LIXINREN);
    setValue('am-form-date', '');
    setValue('am-form-type', 'ETF');
    setValue('am-form-exchange', 'SH');
    setValue('am-form-category', 'EXCHANGE');
    setValue('am-form-source-raw', '');
    const codeInput = document.getElementById('am-form-code');
    if (codeInput) {
        codeInput.disabled = false;
        codeInput.readOnly = true;
    }
}

function populateAssetForm(assetData) {
    setValue('am-form-code', assetData.asset_code);
    setValue('am-form-name', assetData.asset_name);
    setValue('am-form-source', assetData.source_id || SOURCE_LIXINREN);
    setValue('am-form-date', assetData.listing_date || '');
    setValue('am-form-type', assetData.asset_type || 'ETF');
    setValue('am-form-exchange', assetData.exchange || 'SH');
    setValue('am-form-category', assetData.market_category || 'EXCHANGE');
    setValue('am-form-source-raw', assetData.source_code || '');
}

function setCodeFieldEditMode(code) {
    const input = document.getElementById('am-form-code');
    if (input) {
        input.value = code || '';
        input.disabled = true;
        input.readOnly = false;
        input.placeholder = '';
        input.setAttribute('aria-expanded', 'false');
    }
    document.getElementById('amLookupWrap')?.classList.remove('is-open', 'is-selected');
    document.getElementById('amLookupLock')?.classList.add('hidden');
    document.getElementById('amLookupClear')?.classList.add('hidden');
    document.getElementById('amLookupPopover')?.classList.add('hidden');
}

function getAssetFormValues() {
    return {
        code: document.getElementById('am-form-code')?.value.trim() || '',
        name: document.getElementById('am-form-name')?.value.trim() || '',
        source: document.getElementById('am-form-source')?.value || '',
        date: document.getElementById('am-form-date')?.value || '',
        type: document.getElementById('am-form-type')?.value || '',
        exchange: document.getElementById('am-form-exchange')?.value || '',
        category: document.getElementById('am-form-category')?.value || ''
    };
}

function takeFormSnapshot() {
    assetManagerState.formSnapshot = getAssetFormValues();
}

function isFormDirty() {
    const current = getAssetFormValues();
    return Object.keys(current).some(key => current[key] !== assetManagerState.formSnapshot[key]);
}

function markAssetFormDirty() {
    if (assetManagerState.mode !== 'form') return;
    assetManagerState.isDirty = isFormDirty();
}

function requestLeaveForm(action, triggerEl) {
    if (!isFormDirty()) {
        executeLeave(action);
        return;
    }
    assetManagerState.pendingLeaveAction = action;
    assetManagerState.pendingLeaveTriggerEl = triggerEl;
    openLeaveConfirmModal(triggerEl);
}

function executeLeave(action) {
    closeLeaveConfirmModal({ restoreFocus: false });
    if (action === 'back') {
        switchToListView();
    } else if (action === 'close') {
        switchToListView();
        closeAssetManagerModal();
    }
}

async function handleAssetFormSave() {
    clearFormErrors('assetManagerModal');
    const values = getAssetFormValues();
    let hasError = false;
    if (!values.code) {
        showFieldError('am-form-code', 'am-err-code', '请输入代码');
        hasError = true;
    }
    if (!values.name) {
        showFieldError('am-form-name', 'am-err-name', '请输入名称');
        hasError = true;
    }
    if (!values.source || !values.type) {
        showToast('error', '错误: 数据源和标的类型不能为空');
        hasError = true;
    }
    if (hasError) return;

    const isEditing = assetManagerState.formMode === 'edit';
    const payload = {
        asset_code: values.code,
        asset_name: values.name,
        source_id: values.source,
        asset_type: values.type,
        listing_date: values.date || null,
        exchange: values.exchange,
        market_category: values.category
    };
    if (!isEditing) {
        payload.source_code = assetManagerState.lookupSelectedItem?.source_code
            || document.getElementById('am-form-source-raw')?.value
            || null;
    }

    const button = document.getElementById('assetFormSaveBtn');
    button?.classList.add('is-loading');
    if (button) button.disabled = true;
    try {
        const endpoint = isEditing
            ? `/v1/assets/${encodeURIComponent(assetManagerState.editingCode)}`
            : '/v1/assets';
        await fetchApiOrThrow(endpoint, {
            method: isEditing ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        showToast('success', isEditing ? '档案修改成功' : '档案添加成功');
        switchToListView();
        loadAssetManagerList();
    } catch (err) {
        showToast('error', `错误: ${err.message}`);
    } finally {
        button?.classList.remove('is-loading');
        if (button) button.disabled = false;
    }
}

function initLookupField() {
    lookupState.isOpen = false;
    lookupState.keyword = '';
    lookupState.page = 1;
    lookupState.hasMore = false;
    lookupState.focusedIndex = -1;
    lookupState.items = [];
    clearTimeout(lookupState.debounceTimer);

    const input = document.getElementById('am-form-code');
    if (input) {
        input.value = '';
        input.readOnly = true;
        input.disabled = false;
        input.placeholder = '点击搜索标的代码或名称...';
        input.setAttribute('aria-expanded', 'false');
    }
    document.getElementById('amLookupWrap')?.classList.remove('is-open', 'is-selected');
    document.getElementById('amLookupLock')?.classList.add('hidden');
    document.getElementById('amLookupClear')?.classList.add('hidden');
    const popover = document.getElementById('amLookupPopover');
    if (popover) {
        popover.classList.add('hidden');
        popover.innerHTML = '';
    }
}

function openLookupPopover() {
    const input = document.getElementById('am-form-code');
    if (!input || assetManagerState.lookupSelectedItem || assetManagerState.formMode === 'edit') return;
    input.readOnly = false;
    input.setAttribute('aria-expanded', 'true');
    document.getElementById('amLookupWrap')?.classList.add('is-open');
    const popover = document.getElementById('amLookupPopover');
    popover?.classList.remove('hidden');
    lookupState.isOpen = true;
    lookupState.focusedIndex = -1;
}

function closeLookupPopover() {
    const input = document.getElementById('am-form-code');
    if (input) input.setAttribute('aria-expanded', 'false');
    document.getElementById('amLookupWrap')?.classList.remove('is-open');
    document.getElementById('amLookupPopover')?.classList.add('hidden');
    lookupState.isOpen = false;
    lookupState.focusedIndex = -1;

    if (!assetManagerState.lookupSelectedItem && input && assetManagerState.formMode !== 'edit') {
        input.readOnly = true;
        input.value = '';
        lookupState.keyword = '';
    }
}

function onLookupInput(event) {
    const keyword = event.target.value.trim();
    lookupState.keyword = keyword;
    lookupState.focusedIndex = -1;
    lookupState.items = [];

    const popover = document.getElementById('amLookupPopover');
    if (!keyword) {
        // 如果输入为空，立即彻底隐藏并关闭推荐卡片
        closeLookupPopover();
        return;
    }

    // 只有在输入非空内容时，才显示 Popover 并初始化检索
    if (!lookupState.isOpen) {
        openLookupPopover();
    }

    clearTimeout(lookupState.debounceTimer);
    if (popover) popover.innerHTML = '<div class="am-lookup-status">搜索中...</div>';
    const seq = ++lookupState.requestSeq;
    lookupState.debounceTimer = setTimeout(async () => {
        try {
            lookupState.page = 1;
            const data = await searchAssetCatalog(keyword, 1);
            if (seq !== lookupState.requestSeq) return;
            lookupState.hasMore = !!data.has_more;
            renderLookupResults(data.items || [], false);
        } catch {
            if (popover) popover.innerHTML = '<div class="am-lookup-status is-error">搜索失败，请稍后重试</div>';
        }
    }, 300);
}

function onLookupKeydown(event) {
    if (!lookupState.isOpen) {
        if (event.key === 'Enter' || event.key === 'ArrowDown') {
            event.preventDefault();
            const keyword = event.target.value.trim();
            // 只有当输入非空内容时，回车或者按向下键才允许展开卡片并检索
            if (keyword) {
                openLookupPopover();
            }
        }
        return;
    }

    const resultItems = Array.from(document.querySelectorAll('#amLookupPopover .am-lookup-item'));
    const moreBtn = document.querySelector('#amLookupPopover .am-lookup-more');
    const focusable = moreBtn ? [...resultItems, moreBtn] : resultItems;

    if (event.key === 'Escape') {
        event.preventDefault();
        closeLookupPopover();
        return;
    }

    if (event.key === 'Tab') {
        closeLookupPopover();
        return;
    }

    if (!focusable.length) return;

    if (event.key === 'ArrowDown') {
        event.preventDefault();
        lookupState.focusedIndex = (lookupState.focusedIndex + 1) % focusable.length;
        updateLookupFocus(focusable);
        return;
    }

    if (event.key === 'ArrowUp') {
        event.preventDefault();
        lookupState.focusedIndex =
            (lookupState.focusedIndex - 1 + focusable.length) % focusable.length;
        updateLookupFocus(focusable);
        return;
    }

    if (event.key === 'Enter' && lookupState.focusedIndex >= 0) {
        event.preventDefault();
        focusable[lookupState.focusedIndex].click();
    }
}

function updateLookupFocus(focusable) {
    document.querySelectorAll('#amLookupPopover .is-focused').forEach(el => {
        el.classList.remove('is-focused');
    });
    const current = focusable[lookupState.focusedIndex];
    if (current) {
        current.classList.add('is-focused');
        current.scrollIntoView({ block: 'nearest' });
    }
}

function renderLookupResults(items, append = false) {
    const popover = document.getElementById('amLookupPopover');
    if (!popover) return;
    lookupState.items = append ? lookupState.items.concat(items) : items.slice();
    if (lookupState.items.length === 0) {
        popover.innerHTML = '<div class="am-lookup-status">未找到匹配的标的，请检查代码或名称是否正确</div>';
        return;
    }

    const rows = [];
    lookupState.items.forEach((item, index) => {
        const prev = lookupState.items[index - 1];
        if (index > 0 && prev && prev.code !== item.code) {
            rows.push('<div class="am-lookup-separator"></div>');
        }
        const disabled = item.already_added ? ' disabled aria-disabled="true"' : '';
        const addedLabel = item.already_added
            ? '<span class="am-lookup-item__status">已添加</span>'
            : '';
        rows.push(`
            <button class="am-lookup-item${item.already_added ? ' is-disabled' : ''}" type="button" data-index="${index}"${disabled}>
                <span class="am-lookup-item__code">${escapeHtml(item.code)}</span>
                <span class="am-lookup-item__name">${escapeHtml(item.name)}</span>
                <span class="am-lookup-item__source">来自 ${escapeHtml(getSourceDisplayName(item.source))}</span>
                <span class="am-lookup-item__type">${escapeHtml(item.type || '')}</span>
                ${addedLabel}
            </button>
        `);
    });
    if (lookupState.hasMore) {
        rows.push('<button class="am-lookup-more" type="button">显示更多</button>');
    }
    popover.innerHTML = rows.join('');
}

async function loadMoreLookupResults() {
    if (lookupState.loadingMore || !lookupState.hasMore || !lookupState.keyword) return;
    lookupState.loadingMore = true;
    const moreBtn = document.querySelector('#amLookupPopover .am-lookup-more');
    if (moreBtn) moreBtn.textContent = '加载中...';
    try {
        const nextPage = lookupState.page + 1;
        const data = await searchAssetCatalog(lookupState.keyword, nextPage);
        lookupState.page = nextPage;
        lookupState.hasMore = !!data.has_more;
        renderLookupResults(data.items || [], true);
    } catch {
        const popover = document.getElementById('amLookupPopover');
        if (popover) popover.innerHTML = '<div class="am-lookup-status is-error">搜索失败，请稍后重试</div>';
    } finally {
        lookupState.loadingMore = false;
    }
}

function onDocumentClickForLookup(event) {
    const wrap = document.getElementById('amLookupWrap');
    if (wrap && !wrap.contains(event.target)) {
        closeLookupPopover();
    }
}

function selectLookupItem(item) {
    if (!item) return;
    if (item.already_added) return;
    const input = document.getElementById('am-form-code');
    if (input) {
        input.value = item.code || '';
        input.readOnly = true;
        input.setAttribute('aria-expanded', 'false');
    }
    setValue('am-form-name', item.name || '');
    setValue('am-form-source', item.source || SOURCE_LIXINREN);
    setValue('am-form-date', item.list_date || '');
    setValue('am-form-type', item.type || 'ETF');
    setValue('am-form-exchange', item.exchange || 'SH');
    setValue('am-form-source-raw', item.source_code || '');

    document.getElementById('amLookupWrap')?.classList.remove('is-open');
    document.getElementById('amLookupWrap')?.classList.add('is-selected');
    document.getElementById('amLookupLock')?.classList.remove('hidden');
    document.getElementById('amLookupClear')?.classList.remove('hidden');
    document.getElementById('amLookupPopover')?.classList.add('hidden');

    lookupState.isOpen = false;
    assetManagerState.lookupSelectedItem = item;
    assetManagerState.isDirty = true;
}

function clearLookupSelection() {
    assetManagerState.lookupSelectedItem = null;
    lookupState.items = [];
    lookupState.keyword = '';
    lookupState.focusedIndex = -1;
    clearTimeout(lookupState.debounceTimer);

    setValue('am-form-code', '');
    setValue('am-form-name', '');
    setValue('am-form-source', SOURCE_LIXINREN);
    setValue('am-form-date', '');
    setValue('am-form-type', assetManagerState.currentTab === 'index' ? 'INDEX' : 'ETF');
    setValue('am-form-exchange', 'SH');
    setValue('am-form-category', 'EXCHANGE');
    setValue('am-form-source-raw', '');

    const input = document.getElementById('am-form-code');
    if (input) {
        input.readOnly = true;
        input.disabled = false;
        input.placeholder = '点击搜索标的代码或名称...';
        input.setAttribute('aria-expanded', 'false');
        input.focus();
    }
    document.getElementById('amLookupWrap')?.classList.remove('is-open', 'is-selected');
    document.getElementById('amLookupLock')?.classList.add('hidden');
    document.getElementById('amLookupClear')?.classList.add('hidden');
    const popover = document.getElementById('amLookupPopover');
    if (popover) {
        popover.classList.add('hidden');
        popover.innerHTML = '';
    }
    lookupState.isOpen = false;
    assetManagerState.isDirty = isFormDirty();
}

function openLeaveConfirmModal(triggerEl) {
    assetManagerState.pendingLeaveTriggerEl = triggerEl || document.activeElement;
    const modal = document.getElementById('leaveConfirmModal');
    modal?.classList.add('active');
    leaveConfirmKeydownHandler = trapFocusInLeaveConfirm;
    modal?.addEventListener('keydown', leaveConfirmKeydownHandler);
    setTimeout(() => document.getElementById('leaveConfirmStayBtn')?.focus(), 0);
}

function closeLeaveConfirmModal(options = {}) {
    const { restoreFocus = true } = options;
    const modal = document.getElementById('leaveConfirmModal');
    if (modal && leaveConfirmKeydownHandler) {
        modal.removeEventListener('keydown', leaveConfirmKeydownHandler);
    }
    leaveConfirmKeydownHandler = null;
    modal?.classList.remove('active');
    if (restoreFocus && assetManagerState.pendingLeaveTriggerEl) {
        assetManagerState.pendingLeaveTriggerEl.focus();
    }
}

function trapFocusInLeaveConfirm(event) {
    if (event.key !== 'Tab') return;
    const buttons = [
        document.getElementById('leaveConfirmStayBtn'),
        document.getElementById('leaveConfirmLeaveBtn')
    ].filter(Boolean);
    if (!buttons.length) return;

    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}

function setValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value || '';
}
