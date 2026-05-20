(function () {
    async function searchAssetCatalog(keyword, page = 1) {
        const normalizedKeyword = String(keyword || '').trim();
        if (!normalizedKeyword) {
            return { items: [], has_more: false };
        }
        const params = new URLSearchParams({
            keyword: normalizedKeyword,
            page: String(page),
            page_size: '10'
        });
        return fetchApiOrThrow(`/v1/catalog/search?${params.toString()}`);
    }

    window.assetCatalog = {
        searchAssetCatalog
    };
    window.searchAssetCatalog = searchAssetCatalog;
})();
