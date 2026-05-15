(function () {
    const API_BASE = '/api';
    const state = {
        sources: [],
        sourceId: null,
        selectedItem: null,
        page: 1,
        pageSize: 20,
        total: 0,
        loadingMore: false,
        debounceTimer: null,
        requestSeq: 0,
        bound: false
    };

    function refs() {
        return {
            section: document.getElementById('assetCatalogSearchSection'),
            divider: document.getElementById('assetCatalogFormDivider'),
            toggle: document.getElementById('assetCatalogSourceToggle'),
            keyword: document.getElementById('assetCatalogKeyword'),
            results: document.getElementById('assetCatalogResults'),
            list: document.getElementById('assetCatalogResultsList'),
            footer: document.getElementById('assetCatalogResultsFooter'),
            more: document.getElementById('assetCatalogLoadMore'),
            count: document.querySelector('#assetCatalogResultsFooter .catalog-results-count'),
            banner: document.getElementById('assetCatalogInfoBanner'),
            sourceCode: document.getElementById('form-asset-source-code')
        };
    }

    async function loadSources() {
        const r = refs();
        if (!r.toggle) return;
        const response = await fetch(`${API_BASE}/v1/asset-catalog/sources`);
        if (!response.ok) throw new Error('目录来源加载失败');
        const data = await response.json();
        state.sources = (data.items || []).filter(item => item.catalog_enabled);
        if (!state.sourceId && state.sources.length > 0) {
            state.sourceId = state.sources[0].source_id;
        }
        renderSources();
    }

    function renderSources() {
        const r = refs();
        if (!r.toggle) return;
        r.toggle.innerHTML = state.sources.map(source => `
            <button type="button"
                    class="catalog-source-option${source.source_id === state.sourceId ? ' active' : ''}"
                    data-catalog-source="${escapeHtml(source.source_id)}">${escapeHtml(source.display_name)}</button>
        `).join('');
    }

    function bindAssetModalCatalogSearch(options) {
        const r = refs();
        const visible = !!(options && options.visible);
        if (r.section) r.section.style.display = visible ? '' : 'none';
        if (r.divider) r.divider.style.display = visible ? '' : 'none';
        resetAssetCatalogSelection();
        if (!visible) return;
        bindEventsOnce();
        loadSources().catch(() => renderError('目录来源加载失败'));
    }

    function bindEventsOnce() {
        if (state.bound) return;
        state.bound = true;
        const r = refs();
        if (r.toggle) {
            r.toggle.addEventListener('click', event => {
                const button = event.target.closest('[data-catalog-source]');
                if (!button || button.dataset.catalogSource === state.sourceId) return;
                state.sourceId = button.dataset.catalogSource;
                renderSources();
                resetSearchOnly({ clearSourceCode: true });
            });
        }
        if (r.keyword) {
            r.keyword.addEventListener('input', () => {
                const keyword = r.keyword.value.trim();
                clearTimeout(state.debounceTimer);
                if (keyword.length < 2) {
                    hideResults();
                    return;
                }
                state.debounceTimer = setTimeout(() => search({ page: 1 }), 300);
            });
        }
        if (r.more) {
            r.more.addEventListener('click', () => {
                if (!state.loadingMore) search({ page: state.page + 1, append: true });
            });
        }
    }

    async function search(options) {
        const r = refs();
        if (!state.sourceId || !r.keyword) return;
        const page = options && options.page ? options.page : 1;
        const append = !!(options && options.append);
        const keyword = r.keyword.value.trim();
        if (keyword.length < 2) {
            hideResults();
            return;
        }

        const seq = ++state.requestSeq;
        if (append) {
            state.loadingMore = true;
            updateFooter(true);
        } else {
            state.page = 1;
            renderLoading();
        }

        try {
            const params = new URLSearchParams({
                source_id: state.sourceId,
                keyword,
                page: String(page),
                page_size: String(state.pageSize)
            });
            const response = await fetch(`${API_BASE}/v1/asset-catalog/search?${params.toString()}`);
            if (!response.ok) throw new Error('搜索失败，请稍后重试');
            const data = await response.json();
            if (seq !== state.requestSeq) return;
            state.page = data.page;
            state.total = data.total;
            renderResults(data.items || [], append);
        } catch (err) {
            if (seq === state.requestSeq) renderError(err.message || '搜索失败，请稍后重试');
        } finally {
            state.loadingMore = false;
            updateFooter(false);
        }
    }

    function renderLoading() {
        const r = refs();
        if (!r.results || !r.list || !r.footer) return;
        r.results.classList.remove('hidden');
        r.footer.classList.add('hidden');
        r.list.innerHTML = '<div class="catalog-search-state"><div class="loading-spinner"></div><div>正在搜索...</div></div>';
    }

    function renderResults(items, append) {
        const r = refs();
        if (!r.results || !r.list) return;
        r.results.classList.remove('hidden');
        if (!append && items.length === 0) {
            r.list.innerHTML = '<div class="catalog-search-state">未找到匹配的标的</div>';
            return;
        }
        const html = items.map(renderResultItem).join('');
        if (append) {
            r.list.insertAdjacentHTML('beforeend', html);
        } else {
            r.list.innerHTML = html;
        }
        Array.from(r.list.querySelectorAll('.catalog-result-item:not(.is-added)')).forEach(item => {
            item.addEventListener('click', () => selectItem(JSON.parse(item.dataset.catalogItem)));
        });
        updateFooter(false);
    }

    function renderResultItem(item) {
        const payload = escapeHtml(JSON.stringify(item));
        const main = `${item.external_symbol || item.asset_code}  ${item.asset_name || ''}`;
        const sub = [item.asset_type, item.exchange, item.listing_date].filter(Boolean).join(' · ');
        if (item.already_added) {
            return `
                <div class="catalog-result-item is-added">
                    <div class="catalog-result-content">
                        <div class="catalog-result-main">${escapeHtml(main)}</div>
                        <div class="catalog-result-sub">${escapeHtml(sub)}</div>
                    </div>
                    <span class="catalog-result-badge">已在档案中</span>
                </div>
            `;
        }
        return `
            <div class="catalog-result-item" data-catalog-id="${escapeHtml(String(item.catalog_id))}" data-catalog-item="${payload}">
                <div class="catalog-result-main">${escapeHtml(main)}</div>
                <div class="catalog-result-sub">${escapeHtml(sub)}</div>
            </div>
        `;
    }

    function updateFooter(isLoading) {
        const r = refs();
        if (!r.footer || !r.more || !r.count) return;
        if (state.total <= state.pageSize) {
            r.footer.classList.add('hidden');
            return;
        }
        r.footer.classList.remove('hidden');
        r.count.innerHTML = `共 <strong>${state.total}</strong> 条结果`;
        const loaded = state.page * state.pageSize;
        r.more.hidden = loaded >= state.total;
        r.more.textContent = isLoading ? '加载中...' : '显示更多';
        r.more.style.pointerEvents = isLoading ? 'none' : '';
    }

    function renderError(message) {
        const r = refs();
        if (!r.results || !r.list || !r.footer) return;
        r.results.classList.remove('hidden');
        r.footer.classList.add('hidden');
        r.list.innerHTML = `<div class="catalog-search-state catalog-search-state-error">${escapeHtml(message)}</div>`;
    }

    function selectItem(item) {
        state.selectedItem = item;
        setValue('form-asset-code', item.asset_code);
        setValue('form-asset-name', item.asset_name);
        setValue('form-asset-type', item.asset_type || 'ETF');
        setValue('form-asset-exchange', item.exchange || 'SH');
        setValue('form-asset-date', item.listing_date || '');
        setValue('form-asset-category', item.market_category || 'EXCHANGE');
        setValue('form-asset-source-code', item.external_symbol || '');

        const source = state.sources.find(x => x.source_id === item.source_id);
        const sourceSelect = document.getElementById('form-asset-source');
        const banner = refs().banner;
        if (source && source.collection_enabled && sourceSelect) {
            sourceSelect.value = source.source_id;
            if (banner) banner.classList.add('hidden');
        } else if (banner) {
            banner.classList.remove('hidden');
        }
        hideResults();
    }

    function resetAssetCatalogSelection() {
        state.selectedItem = null;
        resetSearchOnly({ clearSourceCode: true });
    }

    function resetSearchOnly(options) {
        const r = refs();
        if (r.keyword) r.keyword.value = '';
        if (r.banner) r.banner.classList.add('hidden');
        if (options && options.clearSourceCode && r.sourceCode) r.sourceCode.value = '';
        hideResults();
    }

    function hideResults() {
        const r = refs();
        if (r.results) r.results.classList.add('hidden');
        if (r.list) r.list.innerHTML = '';
        if (r.footer) r.footer.classList.add('hidden');
    }

    function getSelectedCatalogItem() {
        return state.selectedItem;
    }

    function getSelectedSourceCode() {
        const r = refs();
        return r.sourceCode ? r.sourceCode.value : '';
    }

    function setValue(id, value) {
        const el = document.getElementById(id);
        if (el) el.value = value || '';
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    window.assetCatalog = {
        loadSources,
        search,
        bindAssetModalCatalogSearch,
        resetAssetCatalogSelection,
        getSelectedCatalogItem,
        getSelectedSourceCode
    };
})();
