// utils.js

/**
 * 格式化数字为千分位字符串
 * @param {number} num - 要格式化的数字
 * @param {number} decimals - 保留的小数位数
 * @returns {string} - 格式化后的字符串
 */
function formatNumber(num, decimals = 2) {
    if (num === null || num === undefined || isNaN(num)) {
        return '--';
    }
    return Number(num).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

/**
 * 格式化货币值（带货币符号）
 * @param {number} value - 货币数值
 * @param {string} currency - 货币符号，默认为 ''
 * @returns {string}
 */
function formatCurrency(value, currency = '') {
    if (value === null || value === undefined) return '--';
    const formatted = formatNumber(value, 2);
    return currency ? `${currency} ${formatted}` : formatted;
}

/**
 * 根据数值正负返回颜色类名
 * @param {number} value 
 * @returns {string} 'positive' (红色), 'negative' (绿色) or ''
 */
function getColorClass(value) {
    if (value > 0) return 'positive';
    if (value < 0) return 'negative';
    return '';
}

/**
 * 格式化百分比
 * @param {number} value - 小数 (e.g., 0.1 for 10%)
 * @param {boolean} includeSign - 是否强制显示正号
 * @returns {string}
 */
function formatPercent(value, includeSign = true) {
    if (value === null || value === undefined || isNaN(value)) return '--%';
    const pct = value * 100;
    const formatted = pct.toFixed(2) + '%';
    if (includeSign && pct > 0) {
        return '+' + formatted;
    }
    return formatted;
}

/**
 * 格式化日期
 * @param {string} dateStr 
 * @returns {string} YYYY-MM-DD
 */
function formatDate(dateStr) {
    if (!dateStr) return '--';
    const d = new Date(dateStr);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function formatTime(dateStr) {
    if (!dateStr) return '--';
    const d = new Date(dateStr);
    if (Number.isNaN(d.getTime())) {
        const parts = String(dateStr).split(' ');
        return parts[1] || '--';
    }
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    const seconds = String(d.getSeconds()).padStart(2, '0');
    return `${hours}:${minutes}:${seconds}`;
}

function formatTimestampCell(dateStr) {
    if (!dateStr) return '--';
    return `
        <span class="timestamp-date">${formatDate(dateStr)}</span>
        <span class="timestamp-time">${formatTime(dateStr)}</span>
    `;
}

function escapeHtmlAttr(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function clearElement(element) {
    if (!element) return;
    element.replaceChildren();
}

function appendTextLines(container, lines, itemTag = 'div') {
    if (!container) return;
    clearElement(container);
    lines.forEach((line) => {
        const item = document.createElement(itemTag);
        item.textContent = line;
        container.appendChild(item);
    });
}

function sanitizeCssToken(value, fallback = '') {
    const normalized = String(value ?? '')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '');
    return normalized || fallback;
}

function setSelectOptions(selectElement, options = [], { placeholder = null, disabled = null } = {}) {
    if (!selectElement) return;

    clearElement(selectElement);

    if (placeholder !== null) {
        const placeholderOption = document.createElement('option');
        placeholderOption.value = '';
        placeholderOption.textContent = placeholder;
        selectElement.appendChild(placeholderOption);
    }

    options.forEach((option) => {
        const optionElement = document.createElement('option');
        optionElement.value = String(option.value ?? '');
        optionElement.textContent = option.text ?? '';

        Object.entries(option.dataset || {}).forEach(([key, datasetValue]) => {
            if (datasetValue === null || datasetValue === undefined) return;
            optionElement.dataset[key] = String(datasetValue);
        });

        selectElement.appendChild(optionElement);
    });

    if (typeof disabled === 'boolean') {
        selectElement.disabled = disabled;
    }
}

/**
 * >= 1万手, < 1亿手: X万手
 * >= 1亿手: X亿手
 * @param {number|string} value - 原始数量(股/份)
 * @returns {string} 格式化后的字符串
 */
function formatVolume(value) {
    if (value === null || value === undefined || isNaN(value)) {
        return '--';
    }
    const num = Number(value);
    if (num === 0) return '0.00手';

    const hand = num / 100;
    const absHand = Math.abs(hand);

    if (absHand < 10000) {
        return hand.toFixed(2) + '手';
    } else if (absHand < 100000000) { // 1亿手 = 1,0000,0000
        return (hand / 10000).toFixed(2) + '万手';
    } else {
        return (hand / 100000000).toFixed(2) + '亿手';
    }
}

/**
 * 格式化成交额（按万/亿/万亿进位）
 * 规则：
 * < 1万元: X元
 * >= 1万元, < 1亿元: X万元
 * >= 1亿元, < 1万亿元: X亿元
 * >= 1万亿元: X万亿元
 * @param {number|string} value - 原始金额(元)
 * @returns {string} 格式化后的字符串
 */
function formatAmount(value) {
    if (value === null || value === undefined || isNaN(value)) {
        return '--';
    }
    const num = Number(value);
    if (num === 0) return '0.00元';

    const absNum = Math.abs(num);

    if (absNum < 10000) {
        return num.toFixed(2) + '元';
    } else if (absNum < 100000000) { // 1亿元 = 1,0000,0000
        return (num / 10000).toFixed(2) + '万元';
    } else if (absNum < 1000000000000) { // 1万亿元
        return (num / 100000000).toFixed(2) + '亿元';
    } else {
        return (num / 1000000000000).toFixed(2) + '万亿元';
    }
}

