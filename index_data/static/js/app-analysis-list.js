// app-analysis-list.js
// 行情 Tab 三视图（行情/技术/基本面）列表加载、品牌切换与排序

function syncCapsuleSlider(switcherEl) {
    if (!switcherEl) return;
    let slider = switcherEl.querySelector('.gs-capsule-slider');
    if (!slider) {
        slider = document.createElement('div');
        slider.className = 'gs-capsule-slider';
        switcherEl.prepend(slider);
    }
    
    // 支持全站一致性 components.css .sub-tabs 或 pages.css .gs-capsule-switcher
    const activeItem = switcherEl.querySelector('.gs-capsule-item.active, .sub-tab-item.active');
    if (!activeItem) {
        slider.style.width = '0px';
        return;
    }
    
    const isSubTab = switcherEl.classList.contains('sub-tabs');
    const x = isSubTab ? activeItem.offsetLeft : (activeItem.offsetLeft - 4); // 二级 Tab 呼吸下划线不偏置 4px
    const w = activeItem.offsetWidth;
    
    slider.style.transform = `translate3d(${x}px, 0, 0)`;
    slider.style.width = `${w}px`;
}

// 窗口尺寸变化自适应
window.addEventListener('resize', () => {
    document.querySelectorAll('.gs-capsule-switcher, .sub-tabs').forEach(syncCapsuleSlider);
});

const marketState = {
    currentBrand: 'trading',
    currentView: 'market',
    marketSortBy: 'amount',
    marketSortOrder: 'desc'
};

function loadAnalysis(loadContext = null) {
    switchMarketView(marketState.currentView, loadContext, false);
}

function getCurrentMarketGroup() {
    return marketState.currentBrand === 'index' ? 'index' : 'non_index';
}

function clearTableLoadingState() {
    const wrapper = document.querySelector('.market-table-wrapper');
    if (wrapper) {
        wrapper.style.minHeight = '';
    }
    document.querySelectorAll('.data-table').forEach(table => {
        table.classList.remove('table-fade-loading');
    });
}

function switchMarketBrand(brand) {
    if (!['trading', 'index'].includes(brand)) return;
    if (brand === marketState.currentBrand) return;

    marketState.currentBrand = brand;

    document.querySelectorAll('#marketBrandTabs [data-brand]').forEach(tab => {
        const isTarget = tab.dataset.brand === brand;
        tab.classList.toggle('active', isTarget);
        tab.setAttribute('aria-selected', isTarget ? 'true' : 'false');
    });
    
    // 同步左轨胶囊滑块
    syncCapsuleSlider(document.getElementById('marketBrandTabs'));

    const fundamentalButton = document.getElementById('mvsButtonFundamental');
    if (fundamentalButton) {
        fundamentalButton.classList.toggle('hidden', brand !== 'index');
    }

    if (brand === 'trading' && marketState.currentView === 'fundamental') {
        marketState.currentView = 'market';
    }

    // 基本面按钮隐藏状态变化会导致右轨宽度变化，因此在此也同步一次右轨胶囊
    setTimeout(() => {
        syncCapsuleSlider(document.getElementById('marketViewSwitcher'));
    }, 50);

    switchMarketView(marketState.currentView, createCurrentContentLoadContext('analysis'), false);
}

function switchMarketView(view, loadContext = null, append = false) {
    if (!['market', 'technical', 'fundamental'].includes(view)) return;
    if (view === 'fundamental' && marketState.currentBrand !== 'index') {
        view = 'market';
    }
    
    // 锁定高度防抖动 (CLS Control)
    let previousHeight = 0;
    if (!append) {
        const currentPanel = document.getElementById(`market-panel-${marketState.currentView}`);
        if (currentPanel && !currentPanel.classList.contains('hidden')) {
            previousHeight = currentPanel.offsetHeight;
        }
    }

    marketState.currentView = view;

    document.querySelectorAll('#marketViewSwitcher .gs-capsule-item').forEach(btn => {
        const isTarget = btn.dataset.view === view;
        btn.classList.toggle('active', isTarget);
        btn.setAttribute('aria-selected', isTarget ? 'true' : 'false');
    });
    
    // 同步右轨胶囊滑块
    syncCapsuleSlider(document.getElementById('marketViewSwitcher'));

    const panels = {
        market: document.getElementById('market-panel-market'),
        technical: document.getElementById('market-panel-technical'),
        fundamental: document.getElementById('market-panel-fundamental')
    };
    Object.entries(panels).forEach(([key, panel]) => {
        if (panel) panel.classList.toggle('hidden', key !== view);
    });

    const wrapper = document.querySelector('.market-table-wrapper');
    if (wrapper && previousHeight > 0) {
        wrapper.style.minHeight = `${previousHeight}px`;
    }

    // 给表格添加 Loading 磨砂过渡
    const activeTable = document.getElementById(`market-table-${view}`);
    if (activeTable) {
        activeTable.classList.add('table-fade-loading');
    }

    const context = loadContext || createCurrentContentLoadContext('analysis');
    if (view === 'market') return loadMarketRows(context, append);
    if (view === 'technical') return loadTechnicalRows(context, append);
    return loadFundamentalRows(context, append);
}

async function loadMarketRows(loadContext = null, append = false) {
    const tbody = document.querySelector('#market-table-market tbody');
    if (!tbody) return;
    const key = 'market_trading';
    const brand = marketState.currentBrand;
    const page = append ? (listPaginationState[key].page + 1) : 1;
    updateMarketSortHeaders();
    if (!append) {
        resetPaginationState(key);
        const hasDataRows = tbody.children.length > 0 && !tbody.querySelector('td[colspan]') && !tbody.querySelector('.skeleton-row');
        if (hasDataRows) {
            document.getElementById('market-table-market')?.classList.add('table-fade-loading');
        } else {
            renderTableSkeletonRows(tbody, 10);
        }
    } else {
        setPaginationLoading(key, true);
    }

    const group = getCurrentMarketGroup();
    const params = new URLSearchParams({
        page,
        page_size: DEFAULT_PAGE_SIZE,
        group,
        sort_by: marketState.marketSortBy,
        sort_order: marketState.marketSortOrder
    });
    const res = await fetchApi(`/market?${params.toString()}`);
    if (isStaleContentLoad(loadContext, 'analysis')) return;
    if (brand !== marketState.currentBrand || marketState.currentView !== 'market') return;
    if (!res) {
        listPaginationState[key].loading = false;
        updatePaginationUI(key);
        clearTableLoadingState();
        return;
    }

    const items = applyPaginatedResult(key, res, append);
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 10, '暂无数据');
        clearTableLoadingState();
        return;
    }

    const rowsHtml = items.map(item => `
        <tr>
            <td>${escapeHtml(item.trade_date)}</td>
            <td class="stock-code center">${escapeHtml(item.code)}</td>
            <td class="stock-name center">${escapeHtml(item.name)}</td>
            <td class="number">${formatNumber(item.close)}</td>
            <td class="number ${getColorClass(item.return_22d)}">${formatPercent(item.return_22d)}</td>
            <td class="number ${getColorClass(item.return_60d)}">${formatPercent(item.return_60d)}</td>
            <td class="number ${getColorClass(item.return_6m)}">${formatPercent(item.return_6m)}</td>
            <td class="number ${getColorClass(item.return_1y)}">${formatPercent(item.return_1y)}</td>
            <td class="number">${formatVolume(item.volume)}</td>
            <td class="number">${formatAmount(item.amount)}</td>
        </tr>
    `).join('');
    renderTableRows(tbody, rowsHtml, append);
    clearTableLoadingState();
}

function sortMarketBy(sortBy) {
    if (marketState.marketSortBy === sortBy) {
        marketState.marketSortOrder = marketState.marketSortOrder === 'desc' ? 'asc' : 'desc';
    } else {
        marketState.marketSortBy = sortBy;
        marketState.marketSortOrder = 'desc';
    }
    updateMarketSortHeaders();
    loadMarketRows(createCurrentContentLoadContext('analysis'), false);
}

function updateMarketSortHeaders() {
    document.querySelectorAll('[data-action="sort-market"]').forEach(btn => {
        const active = btn.dataset.sortBy === marketState.marketSortBy;
        btn.classList.toggle('is-active', active);
        btn.dataset.sortOrder = active ? marketState.marketSortOrder : '';
        btn.setAttribute(
            'aria-sort',
            active ? (marketState.marketSortOrder === 'desc' ? 'descending' : 'ascending') : 'none'
        );
    });
}

async function loadTechnicalRows(loadContext = null, append = false) {
    const tbody = document.querySelector('#market-table-technical tbody');
    if (!tbody) return;
    const key = 'market_technical';
    const brand = marketState.currentBrand;
    const page = append ? (listPaginationState[key].page + 1) : 1;
    if (!append) {
        resetPaginationState(key);
        const hasDataRows = tbody.children.length > 0 && !tbody.querySelector('td[colspan]') && !tbody.querySelector('.skeleton-row');
        if (hasDataRows) {
            document.getElementById('market-table-technical')?.classList.add('table-fade-loading');
        } else {
            renderTableSkeletonRows(tbody, 14);
        }
    } else {
        setPaginationLoading(key, true);
    }

    const group = getCurrentMarketGroup();
    const res = await fetchApi(`/indicator?page=${page}&page_size=${DEFAULT_PAGE_SIZE}&group=${group}`);
    if (isStaleContentLoad(loadContext, 'analysis')) return;
    if (brand !== marketState.currentBrand || marketState.currentView !== 'technical') return;
    if (!res) {
        listPaginationState[key].loading = false;
        updatePaginationUI(key);
        clearTableLoadingState();
        return;
    }

    const items = applyPaginatedResult(key, res, append);
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 14, '暂无数据');
        clearTableLoadingState();
        return;
    }

    const rowsHtml = items.map(item => `
        <tr>
            <td>${escapeHtml(item.trade_date)}</td>
            <td class="stock-code center">${escapeHtml(item.code)}</td>
            <td class="stock-name center">${escapeHtml(item.name)}</td>
            <td class="number">${formatNumber(item.close)}</td>
            <td class="number">${formatNumber(item.ma5)}</td>
            <td class="number">${formatNumber(item.ma10)}</td>
            <td class="number">${formatNumber(item.ma20)}</td>
            <td class="number">${formatNumber(item.rsi_6)}</td>
            <td class="number">${formatNumber(item.rsi_14)}</td>
            <td class="number">${formatNumber(item.dif)}</td>
            <td class="number">${formatNumber(item.dea)}</td>
            <td class="number ${getColorClass(item.macd)}">${formatNumber(item.macd)}</td>
            <td class="number">${formatNumber(item.atr14)}</td>
            <td class="number">${formatNumber(item.atr_stop_loss)}</td>
        </tr>
    `).join('');
    renderTableRows(tbody, rowsHtml, append);
    clearTableLoadingState();
}

async function loadFundamentalRows(loadContext = null, append = false) {
    if (marketState.currentBrand !== 'index') return;
    const tbody = document.querySelector('#market-table-fundamental tbody');
    if (!tbody) return;
    const key = 'market_fundamental';
    const page = append ? (listPaginationState[key].page + 1) : 1;
    if (!append) {
        resetPaginationState(key);
        const hasDataRows = tbody.children.length > 0 && !tbody.querySelector('td[colspan]') && !tbody.querySelector('.skeleton-row');
        if (hasDataRows) {
            document.getElementById('market-table-fundamental')?.classList.add('table-fade-loading');
        } else {
            renderTableSkeletonRows(tbody, 9);
        }
    } else {
        setPaginationLoading(key, true);
    }

    const res = await fetchApi(`/fundamental?page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
    if (isStaleContentLoad(loadContext, 'analysis')) return;
    if (marketState.currentBrand !== 'index' || marketState.currentView !== 'fundamental') return;
    if (!res) {
        listPaginationState[key].loading = false;
        updatePaginationUI(key);
        clearTableLoadingState();
        return;
    }

    const items = applyPaginatedResult(key, res, append);
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 9, '暂无数据');
        clearTableLoadingState();
        return;
    }

    const rowsHtml = items.map(item => {
        let peClass = '';
        if (item.pe_low_20 !== null && item.pe_ttm < item.pe_low_20) {
            peClass = 'val-low';
        } else if (item.pe_high_80 !== null && item.pe_ttm > item.pe_high_80) {
            peClass = 'val-high';
        }

        let posClass = '';
        if (item.pe_pos_5y !== null) {
            if (item.pe_pos_5y < 0.2) posClass = 'badge-success';
            else if (item.pe_pos_5y > 0.8) posClass = 'badge-error';
        }

        return `
        <tr>
            <td>${escapeHtml(item.trade_date)}</td>
            <td class="stock-code center">${escapeHtml(item.code)}</td>
            <td class="stock-name center">${escapeHtml(item.name)}</td>
            <td class="number ${peClass}">${formatNumber(item.pe_ttm)}</td>
            <td class="number">${formatNumber(item.pb)}</td>
            <td class="number ${posClass}">${formatPercent(item.pe_pos_5y)}</td>
            <td class="number">${formatNumber(item.pe_low_20)}</td>
            <td class="number">${formatNumber(item.pe_mid_50)}</td>
            <td class="number">${formatNumber(item.pe_high_80)}</td>
        </tr>
    `}).join('');
    renderTableRows(tbody, rowsHtml, append);
    clearTableLoadingState();
}
