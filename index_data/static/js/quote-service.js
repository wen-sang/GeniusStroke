(function () {
    const CLIENT_CACHE_TTL_MS = 10000;
    const quoteCache = new Map();
    const inFlightBatch = new Map();

    function normalizeCodes(codes) {
        const unique = new Set();
        (codes || []).forEach((code) => {
            const normalized = String(code || '').trim();
            if (normalized) unique.add(normalized);
        });
        return Array.from(unique).slice(0, 50);
    }

    function chunkCodes(codes, chunkSize = 5) {
        const normalized = normalizeCodes(codes);
        const chunks = [];
        for (let i = 0; i < normalized.length; i += chunkSize) {
            chunks.push(normalized.slice(i, i + chunkSize));
        }
        return chunks;
    }

    function getFreshCachedQuotes(codes) {
        const now = Date.now();
        const result = {};
        for (const code of codes) {
            const cached = quoteCache.get(code);
            if (cached && (now - cached.ts) < CLIENT_CACHE_TTL_MS) {
                result[code] = cached.data;
            }
        }
        return result;
    }

    function setCache(quotes) {
        if (!quotes) return;
        const now = Date.now();
        Object.entries(quotes).forEach(([code, quote]) => {
            quoteCache.set(code, { data: quote, ts: now });
        });
    }

    function summarizeQuotes(quotes) {
        const summary = {
            total: 0,
            cache: 0,
            realtime: 0,
            staleCache: 0,
            fallback: 0,
        };

        Object.values(quotes || {}).forEach((quote) => {
            summary.total += 1;
            if (quote.source === 'cache') summary.cache += 1;
            if (quote.source === 'stale_cache') summary.staleCache += 1;
            if (quote.origin_source === 'market_db_fallback' || quote.source === 'market_db_fallback') summary.fallback += 1;
            if ((quote.origin_source === 'efinance' || quote.origin_source === 'tickflow' || quote.source === 'tickflow') && quote.source !== 'cache' && quote.source !== 'stale_cache') summary.realtime += 1;
        });

        return summary;
    }

    function buildStatusMessage(summary, meta) {
        if (meta && meta.message) {
            return meta.message;
        }
        if (!summary || summary.total === 0) {
            return '未获取到行情数据';
        }
        if (summary.cache > 0 && summary.fallback === 0 && summary.staleCache === 0) {
            return '行情已是 10 分钟内最新数据';
        }
        if (summary.fallback > 0 && summary.realtime === 0) {
            return '当前显示最近一个交易日收盘数据';
        }
        if (summary.staleCache > 0) {
            return '刷新未成功，当前先显示最近一次缓存数据';
        }
        return '当前数据已更新';
    }

    async function fetchQuotes(codes, options = {}) {
        const { forceRefresh = false } = options;
        const normalizedCodes = normalizeCodes(codes);
        if (normalizedCodes.length === 0) {
            return { quotes: {}, summary: summarizeQuotes({}), meta: { message: '未提供有效代码' } };
        }

        const cachedQuotes = forceRefresh ? {} : getFreshCachedQuotes(normalizedCodes);
        const missingCodes = forceRefresh
            ? normalizedCodes
            : normalizedCodes.filter((code) => !cachedQuotes[code]);

        if (missingCodes.length === 0) {
            const summary = summarizeQuotes(cachedQuotes);
            return { quotes: cachedQuotes, summary, meta: { message: buildStatusMessage(summary) } };
        }

        const batchKey = `${forceRefresh ? 'force:' : ''}${missingCodes.slice().sort().join(',')}`;
        let batchPromise = inFlightBatch.get(batchKey);
        if (!batchPromise) {
            batchPromise = (async () => {
                const query = `/market/realtime?codes=${missingCodes.join(',')}${forceRefresh ? '&force_refresh=true' : ''}`;
                const payload = await window.fetchApi(query);
                const fetchedQuotes = payload && payload.quotes ? payload.quotes : null;
                if (fetchedQuotes) setCache(fetchedQuotes);
                return payload;
            })();
            inFlightBatch.set(batchKey, batchPromise);
            batchPromise.finally(() => {
                inFlightBatch.delete(batchKey);
            });
        }

        const payload = await batchPromise;
        const fetchedQuotes = payload && payload.quotes ? payload.quotes : null;
        const meta = payload && payload.meta ? payload.meta : null;
        if (!fetchedQuotes) {
            const summary = summarizeQuotes(cachedQuotes);
            return {
                quotes: Object.keys(cachedQuotes).length > 0 ? cachedQuotes : null,
                summary,
                meta,
            };
        }

        const mergedQuotes = { ...cachedQuotes, ...fetchedQuotes };
        return {
            quotes: mergedQuotes,
            summary: summarizeQuotes(mergedQuotes),
            meta,
        };
    }

    window.quoteService = {
        buildStatusMessage,
        chunkCodes,
        fetchQuotes,
        normalizeCodes,
        summarizeQuotes,
    };
})();
