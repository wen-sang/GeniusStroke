// app-analysis-assets.js

const analysisState = {
    currentSubTab: 'market' // market, fundamental, technical
};

function loadAnalysis(loadContext = null) {
    switchAnalysisTab(analysisState.currentSubTab, loadContext);
}

function switchAnalysisTab(tabName, loadContext = null) {
    analysisState.currentSubTab = tabName;

    // Update Tab UI - Only within analysis view
    document.querySelectorAll('#view-analysis .sub-tab-item').forEach(tab => {
        // Check by text content or adding data attributes would be better, but text works for now
        if (tab.innerText === '行情概览' && tabName === 'market') tab.classList.add('active');
        else if (tab.innerText === '基本面分析' && tabName === 'fundamental') tab.classList.add('active');
        else if (tab.innerText === '技术分析' && tabName === 'technical') tab.classList.add('active');
        else tab.classList.remove('active');
    });

    const tabs = {
        'market': document.getElementById('analysis-market'),
        'fundamental': document.getElementById('analysis-fundamental'),
        'technical': document.getElementById('analysis-technical')
    };

    for (const [key, el] of Object.entries(tabs)) {
        if (key === tabName) {
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    }

    // Load Data
    if (tabName === 'market') loadAnalysisMarket(loadContext);
    if (tabName === 'fundamental') loadAnalysisFundamental(loadContext);
    if (tabName === 'technical') loadAnalysisTechnical(loadContext);
}

async function loadAnalysisMarket(loadContext = null, append = false) {
    const tbody = document.querySelector('#analysis-market tbody');
    if (!tbody) return;
    const page = append ? (listPaginationState.analysis_market.page + 1) : 1;
    if (!append) {
        resetPaginationState('analysis_market');
        renderTableStatusRow(tbody, 7, '加载中...');
    } else {
        setPaginationLoading('analysis_market', true);
    }

    const res = await fetchApi(`/market?page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
    if (isStaleContentLoad(loadContext, 'analysis')) return;
    if (analysisState.currentSubTab !== 'market') return;
    if (!res) {
        listPaginationState.analysis_market.loading = false;
        updatePaginationUI('analysis_market');
        return;
    }

    const items = applyPaginatedResult('analysis_market', res, append);
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 7, '暂无数据');
        return;
    }

    const rowsHtml = items.map(item => `
        <tr>
            <td>${item.trade_date}</td>
            <td class="stock-code center">${item.code}</td>
            <td class="stock-name center">${item.name}</td>
            <td class="number center">${formatNumber(item.close)}</td>
            <td class="number center">${formatVolume(item.volume)}</td>
            <td class="number center">${formatAmount(item.amount)}</td>
        </tr>
    `).join('');

    renderTableRows(tbody, rowsHtml, append);
}

async function loadAnalysisFundamental(loadContext = null, append = false) {
    const tbody = document.querySelector('#analysis-fundamental tbody');
    if (!tbody) return;
    const page = append ? (listPaginationState.analysis_fundamental.page + 1) : 1;
    if (!append) {
        resetPaginationState('analysis_fundamental');
        renderTableStatusRow(tbody, 9, '加载中...');
    } else {
        setPaginationLoading('analysis_fundamental', true);
    }

    const res = await fetchApi(`/fundamental?page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
    if (isStaleContentLoad(loadContext, 'analysis')) return;
    if (analysisState.currentSubTab !== 'fundamental') return;
    if (!res) {
        listPaginationState.analysis_fundamental.loading = false;
        updatePaginationUI('analysis_fundamental');
        return;
    }

    const items = applyPaginatedResult('analysis_fundamental', res, append);
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 9, '暂无数据');
        return;
    }

    const rowsHtml = items.map(item => {
        // PE-TTM Color Logic
        let peClass = '';
        if (item.pe_low_20 !== null && item.pe_ttm < item.pe_low_20) {
            peClass = 'val-low';
        } else if (item.pe_high_80 !== null && item.pe_ttm > item.pe_high_80) {
            peClass = 'val-high';
        }

        // PE 5-Year Position Color Logic
        let posClass = '';
        if (item.pe_pos_5y !== null) {
            if (item.pe_pos_5y < 0.2) posClass = 'badge-success';
            else if (item.pe_pos_5y > 0.8) posClass = 'badge-error';
        }

        return `
        <tr>
            <td style="text-align: left !important;">${item.trade_date}</td>
            <td class="stock-code center">${item.code}</td>
            <td class="stock-name center">${item.name}</td>
            <td class="number center ${peClass}">${formatNumber(item.pe_ttm)}</td>
            <td class="number center">${formatNumber(item.pb)}</td>
            <td class="number center ${posClass}">${formatPercent(item.pe_pos_5y)}</td>
            <td class="number center">${formatNumber(item.pe_low_20)}</td>
            <td class="number center">${formatNumber(item.pe_mid_50)}</td>
            <td class="number center">${formatNumber(item.pe_high_80)}</td>
        </tr>
    `}).join('');

    renderTableRows(tbody, rowsHtml, append);
}

async function loadAnalysisTechnical(loadContext = null, append = false) {
    const tbody = document.querySelector('#analysis-technical tbody');
    if (!tbody) return;
    const page = append ? (listPaginationState.analysis_technical.page + 1) : 1;
    if (!append) {
        resetPaginationState('analysis_technical');
        renderTableStatusRow(tbody, 14, '加载中...');
    } else {
        setPaginationLoading('analysis_technical', true);
    }

    const res = await fetchApi(`/indicator?page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
    if (isStaleContentLoad(loadContext, 'analysis')) return;
    if (analysisState.currentSubTab !== 'technical') return;
    if (!res) {
        listPaginationState.analysis_technical.loading = false;
        updatePaginationUI('analysis_technical');
        return;
    }

    const items = applyPaginatedResult('analysis_technical', res, append);
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 14, '暂无数据');
        return;
    }

    const rowsHtml = items.map(item => `
        <tr>
            <td>${item.trade_date}</td>
            <td class="stock-code center">${item.code}</td>
            <td class="stock-name center">${item.name}</td>
            <td class="number center">${formatNumber(item.close)}</td>
            <td class="number center">${formatNumber(item.ma5)}</td>
            <td class="number center">${formatNumber(item.ma10)}</td>
            <td class="number center">${formatNumber(item.ma20)}</td>
            <td class="number center">${formatNumber(item.rsi_6)}</td>
            <td class="number center">${formatNumber(item.rsi_14)}</td>
            <td class="number center">${formatNumber(item.dif)}</td>
            <td class="number center">${formatNumber(item.dea)}</td>
            <td class="number center ${getColorClass(item.macd)}">${formatNumber(item.macd)}</td>
            <td class="number center">${formatNumber(item.atr14)}</td>
            <td class="number center">${formatNumber(item.atr_stop_loss)}</td>
        </tr>
    `).join('');

    renderTableRows(tbody, rowsHtml, append);
}

// ==================== 页面逻辑: 基础档案 (原自选) ====================

const assetState = {
    currentTab: 'others', // others (交易品种), index (指数信息)
    editingCode: null // null=新增, 否则为正在编辑的 asset_code
};

function switchAssetTab(tabId) {
    assetState.currentTab = tabId;

    // 更新 Tab 样式
    document.querySelectorAll('#view-watchlist .sub-tab-item').forEach(el => {
        el.classList.remove('active');
    });
    // 基于 onclick 的文本或直接绑定的 onClick
    const tabs = document.querySelectorAll('#view-watchlist .sub-tab-item');
    if (tabId === 'others') tabs[0].classList.add('active');
    else tabs[1].classList.add('active');

    loadWatchlist();
}

async function loadWatchlist(loadContext = null, append = false) {
    if (isStaleContentLoad(loadContext, 'watchlist')) return;
    const tbody = document.querySelector('#view-watchlist .data-table tbody');
    if (!tbody) return;
    const page = append ? (listPaginationState.watchlist.page + 1) : 1;
    if (!append) {
        resetPaginationState('watchlist');
        renderTableStatusRow(tbody, 5, '加载中...');
    } else {
        setPaginationLoading('watchlist', true);
    }

    const category = assetState.currentTab;
    const res = await fetchApi(`/v1/assets/list?category=${category}&page=${page}&page_size=${DEFAULT_PAGE_SIZE}`);
    if (isStaleContentLoad(loadContext, 'watchlist')) return;
    if (category !== assetState.currentTab) return;
    if (!res) {
        listPaginationState.watchlist.loading = false;
        updatePaginationUI('watchlist');
        return;
    }

    const items = applyPaginatedResult('watchlist', res, append);
    if (!append && items.length === 0) {
        renderTableStatusRow(tbody, 6, '暂无档案记录', { padded: true });
        return;
    }

    const rowsHtml = items.map(item => {
        const sourceName = isLixinrenSource(item.source_id) ? '理杏仁' :
            item.source_id === SOURCE_AKSHARE ? 'Akshare' :
                item.source_id === SOURCE_TICKFLOW ? 'TickFlow' :
                (item.source_id || '--');
        return `
        <tr>
            <td><span class="stock-code">${item.asset_code}</span></td>
            <td><span class="stock-name" style="font-size: 14px;">${item.asset_name}</span></td>
            <td>${item.asset_type}</td>
            <td><span class="number">${item.listing_date || '--'}</span></td>
            <td>${sourceName}</td>
            <td>
                <a href="javascript:void(0)" data-action="edit-asset" data-code="${item.asset_code}" style="color: var(--primary); margin-right: 12px; text-decoration: none; font-size: 13px;">修改</a>
                <a href="javascript:void(0)" data-action="delete-asset" data-code="${item.asset_code}" style="color: var(--up-red); text-decoration: none; font-size: 13px;">删除</a>
            </td>
        </tr>
    `}).join('');

    renderTableRows(tbody, rowsHtml, append);

    // 为了避免 JSON 注入，暴露全局方法使用缓存数据
    window._cachedAssets = listPaginationState.watchlist.items.slice();
    window.openAssetModalByCode = function (code) {
        const target = window._cachedAssets.find(x => x.asset_code === code);
        if (target) openAssetModal(target);
    };
}

function openAssetModal(assetData = null) {
    const modal = document.getElementById('assetModal');
    const title = document.getElementById('assetModalTitle');
    const codeInput = document.getElementById('form-asset-code');

    // 清空重置
    document.getElementById('form-asset-code').value = '';
    document.getElementById('form-asset-name').value = '';
    document.getElementById('form-asset-source').value = SOURCE_LIXINREN;
    const sourceCodeInput = document.getElementById('form-asset-source-code');
    if (sourceCodeInput) sourceCodeInput.value = '';
    document.getElementById('form-asset-date').value = '';
    document.getElementById('form-asset-type').value = 'ETF';
    document.getElementById('form-asset-exchange').value = 'SH';
    document.getElementById('form-asset-category').value = 'EXCHANGE';

    if (assetData && assetData.asset_code) {
        // 修改模式
        assetState.editingCode = assetData.asset_code;
        title.textContent = '修改档案';
        codeInput.value = assetData.asset_code;
        codeInput.disabled = true; // 主键不可改

        document.getElementById('form-asset-name').value = assetData.asset_name;
        document.getElementById('form-asset-source').value = assetData.source_id || SOURCE_LIXINREN;
        if (sourceCodeInput) sourceCodeInput.value = assetData.source_code || '';
        document.getElementById('form-asset-date').value = assetData.listing_date || '';
        document.getElementById('form-asset-type').value = assetData.asset_type || 'ETF';
        document.getElementById('form-asset-exchange').value = assetData.exchange || 'SH';
        document.getElementById('form-asset-category').value = assetData.market_category || 'EXCHANGE';
        if (window.assetCatalog) {
            window.assetCatalog.bindAssetModalCatalogSearch({ visible: false });
        }
    } else {
        // 新增模式
        assetState.editingCode = null;
        title.textContent = '新增档案';
        codeInput.disabled = false;

        // 如果当前是指数信息 tab 下点的新增，默认给 INDEX
        if (assetState.currentTab === 'index') {
            document.getElementById('form-asset-type').value = 'INDEX';
        }
        if (window.assetCatalog) {
            window.assetCatalog.bindAssetModalCatalogSearch({ visible: true });
        }
    }

    // 使用 modal-overlay .active 机制
    modal.classList.add('active');
}

function closeAssetModal() {
    const modal = document.getElementById('assetModal');
    if (modal) modal.classList.remove('active');
    if (window.assetCatalog) {
        window.assetCatalog.resetAssetCatalogSelection();
    }
    // 清除表单错误状态
    clearFormErrors('assetModal');
}

async function saveAssetInfo() {
    // 1. 清除旧错误状态
    clearFormErrors('assetModal');

    const code = document.getElementById('form-asset-code').value.trim();
    const name = document.getElementById('form-asset-name').value.trim();
    const type = document.getElementById('form-asset-type').value;
    const source = document.getElementById('form-asset-source').value;
    const sourceCodeInput = document.getElementById('form-asset-source-code');
    const sourceCode = sourceCodeInput ? sourceCodeInput.value || null : null;

    // 2. 行内校验（取代 alert）
    let hasError = false;
    if (!code) {
        showFieldError('form-asset-code', 'err-asset-code', '请输入代码');
        hasError = true;
    }
    if (!name) {
        showFieldError('form-asset-name', 'err-asset-name', '请输入名称');
        hasError = true;
    }
    if (hasError) return;

    const isEditing = !!assetState.editingCode;
    const payload = {
        asset_code: code,
        asset_name: name,
        source_id: source,
        asset_type: type,
        listing_date: document.getElementById('form-asset-date').value || null,
        exchange: document.getElementById('form-asset-exchange').value,
        market_category: document.getElementById('form-asset-category').value
    };
    if (!isEditing) {
        payload.source_code = sourceCode;
    }

    const method = isEditing ? 'PUT' : 'POST';
    const url = isEditing ? `/v1/assets/${assetState.editingCode}` : '/v1/assets';

    // 3. 加载中状态
    const renderBtn = document.getElementById('btn-save-asset');
    const oldText = renderBtn.textContent;
    renderBtn.classList.add('is-loading');
    renderBtn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}${url}`, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail || '保存失败');
        }

        // 保存成功
        closeAssetModal();
        loadWatchlist();
        showToast('success', '保存成功');
    } catch (err) {
        showToast('error', `错误: ${err.message}`);
    } finally {
        renderBtn.textContent = oldText;
        renderBtn.classList.remove('is-loading');
        renderBtn.disabled = false;
    }
}

async function deleteAsset(code) {
    // 从缓存中获取名称
    let assetName = code;
    if (window._cachedAssets) {
        const found = window._cachedAssets.find(a => a.asset_code === code);
        if (found) assetName = `${code}（${found.asset_name}）`;
    }

    openConfirmModal(assetName, async () => {
        const response = await fetch(`${API_BASE}/v1/assets/${code}`, {
            method: 'DELETE'
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail || '删除失败');
        }

        loadWatchlist(); // 刷新列表
    });
}

// ==================== UI 工具函数 ====================
