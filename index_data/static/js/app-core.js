// app-core.js

const API_BASE = '/api';
const API_TIMEOUT_MS = 12000;
const SOURCE_AKSHARE = 'akshare';
const SOURCE_LIXINREN = 'lixinren';
const SOURCE_TICKFLOW = 'tickflow';
const DEFAULT_PAGE_SIZE = 60;

function isLixinrenSource(sourceId) {
    return sourceId === SOURCE_LIXINREN;
}

function getTodayDateString() {
    const today = new Date();
    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function initializeTradeDateDefault() {
    const tradeDateInput = document.getElementById('tradeDate');
    if (!tradeDateInput) return;
    tradeDateInput.value = getTodayDateString();
}

// 状态管理
const state = {
    currentTab: 'positions', // positions, transactions, analysis, performance
    currentAccount: null,
    currentAccountName: '',
    currentAccountSummary: null,
    accountList: [],
    isAccountMenuOpen: false,
    isEmptyAccountState: false,
    accountModalMode: null,
    tradeSide: 'buy', // buy, sell
    tradeAssetType: null,
    editTradeAssetType: null,
    currentStock: null,
    summaryLoadSeq: 0,
    contentLoadSeq: 0,
    currentCashBalance: 0,
    currentPositionCodes: [],
    positionsQuoteLoading: false,
    tradeIdempotencyKey: null,
    tradeOrders: [],
    corporateActions: [],
    transactionSubTab: 'trade_orders',
};

const corporateActionState = {
    mode: 'create', // create, edit
    actionId: null,
    actionType: 'SPLIT',
    status: 'PENDING',
    preview: null,
    assetCodeLocked: false,
};


function createPaginationState() {
    return {
        page: 0,
        pageSize: DEFAULT_PAGE_SIZE,
        total: 0,
        totalPages: 0,
        items: [],
        loading: false
    };
}
const listPaginationState = {
    positions: createPaginationState(),
    transaction_orders: createPaginationState(),
    transaction_actions: createPaginationState(),
    market_trading: createPaginationState(),
    market_technical: createPaginationState(),
    market_fundamental: createPaginationState(),
    asset_manager: createPaginationState()
};

function loadPageData({ summary = true, content = true } = {}) {
    if (!state.currentAccount || state.isEmptyAccountState) return;
    if (summary) loadAccountSummaryData();
    if (content) loadCurrentTabData();
}

function loadAccountSummaryData() {
    if (!state.currentAccount || state.isEmptyAccountState) return;
    const loadContext = {
        seq: ++state.summaryLoadSeq,
        accountId: state.currentAccount
    };
    loadAccountSummary(loadContext);
}

function loadCurrentTabData() {
    if (!state.currentAccount || state.isEmptyAccountState) return;
    const loadContext = {
        seq: ++state.contentLoadSeq,
        accountId: state.currentAccount,
        tab: state.currentTab
    };

    const tab = state.currentTab;
    if (tab === 'positions') loadPositions(loadContext);
    if (tab === 'transactions') loadTransactions(loadContext);
    if (tab === 'analysis') loadAnalysis(loadContext);
    if (tab === 'performance') loadPerformance(loadContext);
}

function isStaleSummaryLoad(loadContext) {
    if (!loadContext) return false;
    if (loadContext.seq !== state.summaryLoadSeq) return true;
    if (loadContext.accountId !== state.currentAccount) return true;
    return false;
}

function isStaleContentLoad(loadContext, expectedTab = null) {
    if (!loadContext) return false;
    if (loadContext.seq !== state.contentLoadSeq) return true;
    if (loadContext.accountId !== state.currentAccount) return true;
    if (expectedTab && state.currentTab !== expectedTab) return true;
    return false;
}

function createCurrentContentLoadContext(tab = state.currentTab) {
    return {
        seq: state.contentLoadSeq,
        accountId: state.currentAccount,
        tab
    };
}

function getPaginationElements(key) {
    const container = document.querySelector(`[data-list-pagination="${key}"]`);
    if (!container) return {};
    return {
        container,
        loading: container.querySelector('.list-pagination-loading'),
        button: container.querySelector('.list-pagination-button'),
        end: container.querySelector('.list-pagination-end')
    };
}

function resetPaginationState(key) {
    listPaginationState[key] = createPaginationState();
    updatePaginationUI(key);
}

function updatePaginationUI(key) {
    const pagination = listPaginationState[key];
    const { container, loading, button, end } = getPaginationElements(key);
    if (!container) return;

    const loadedCount = pagination.items.length;
    const hasItems = loadedCount > 0;
    const hasMore = pagination.total > loadedCount;

    container.classList.toggle('hidden', !hasItems && !pagination.loading);

    if (loading) {
        loading.textContent = pagination.loading ? '加载中...' : '';
        loading.classList.toggle('hidden', !pagination.loading);
    }

    if (button) {
        button.disabled = pagination.loading;
        button.classList.toggle('hidden', !hasItems || pagination.loading || !hasMore);
    }

    if (end) {
        end.classList.toggle('hidden', !hasItems || hasMore || pagination.loading);
    }
}

function applyPaginatedResult(key, result, append) {
    const pagination = listPaginationState[key];
    const items = Array.isArray(result?.items) ? result.items : [];
    pagination.page = Number(result?.page || (append ? pagination.page + 1 : 1));
    pagination.pageSize = Number(result?.page_size || DEFAULT_PAGE_SIZE);
    pagination.total = Number(result?.total || items.length);
    pagination.totalPages = Number(result?.total_pages || (pagination.total ? Math.ceil(pagination.total / pagination.pageSize) : 0));
    pagination.items = append ? pagination.items.concat(items) : items.slice();
    pagination.loading = false;
    updatePaginationUI(key);
    return items;
}

function setPaginationLoading(key, loading) {
    listPaginationState[key].loading = loading;
    updatePaginationUI(key);
}

async function loadMoreList(key) {
    const loadContext = createCurrentContentLoadContext(key.startsWith('market_') ? 'analysis' : state.currentTab);
    if (key === 'positions') return loadPositions(loadContext, true);
    if (key === 'transaction_orders') return loadTradeOrders(loadContext, true);
    if (key === 'transaction_actions') return loadCorporateActionRows(loadContext, true);
    if (key === 'market_trading') return loadMarketRows(loadContext, true);
    if (key === 'market_technical') return loadTechnicalRows(loadContext, true);
    if (key === 'market_fundamental') return loadFundamentalRows(loadContext, true);
    if (key === 'asset_manager') return loadAssetManagerList(null, true);
}

window.loadMoreList = loadMoreList;

// ==================== API 交互 ====================

function createRequestSignal(externalSignal, timeoutMs = API_TIMEOUT_MS) {
    const controller = new AbortController();
    let timeoutId = null;

    const abortWithReason = (reason) => {
        if (!controller.signal.aborted) {
            controller.abort(reason);
        }
    };

    if (externalSignal) {
        if (externalSignal.aborted) {
            abortWithReason(externalSignal.reason || 'external_abort');
        } else {
            externalSignal.addEventListener(
                'abort',
                () => abortWithReason(externalSignal.reason || 'external_abort'),
                { once: true }
            );
        }
    }

    if (timeoutMs > 0) {
        timeoutId = setTimeout(() => {
            abortWithReason('timeout');
        }, timeoutMs);
    }

    return {
        signal: controller.signal,
        cleanup: () => {
            if (timeoutId) clearTimeout(timeoutId);
        }
    };
}

async function fetchApi(endpoint, options = {}) {
    const { timeoutMs = API_TIMEOUT_MS, signal: externalSignal, ...fetchOptions } = options;
    const { signal, cleanup } = createRequestSignal(externalSignal, timeoutMs);

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...fetchOptions,
            signal
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'API request failed');
        }
        return await response.json();
    } catch (error) {
        if (error && error.name === 'AbortError') {
            console.error('API Error: request aborted', endpoint);
            return null;
        }
        console.error('API Error:', error);
        // 这里可以添加 Toast 提示
        // alert(`操作失败: ${error.message}`);
        return null;
    } finally {
        cleanup();
    }
}
window.fetchApi = fetchApi;

async function fetchApiOrThrow(endpoint, options = {}) {
    const { timeoutMs = API_TIMEOUT_MS, signal: externalSignal, ...fetchOptions } = options;
    const { signal, cleanup } = createRequestSignal(externalSignal, timeoutMs);

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...fetchOptions,
            signal
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.detail || 'API request failed');
        }
        return result;
    } finally {
        cleanup();
    }
}

// ==================== 页面逻辑: 账户上下文 ====================

function renderTableStatusRow(tbody, colspan, message, { padded = false } = {}) {
    if (!tbody) return;
    const style = padded
        ? 'text-align:center; padding: 20px;'
        : 'text-align:center;';
    tbody.innerHTML = `<tr><td colspan="${colspan}" style="${style}">${message}</td></tr>`;
}

function renderTableRows(tbody, rowsHtml, append = false) {
    if (!tbody) return;
    if (append) {
        tbody.insertAdjacentHTML('beforeend', rowsHtml);
        return;
    }
    tbody.innerHTML = rowsHtml;
}

// ==================== 页面逻辑: 持仓列表 ====================
