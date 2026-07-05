// ==UserScript==
// @name         AliExpress Order API Capture
// @namespace    http://tobixen.no/
// @version      0.2
// @description  Auto-capture the mtop order-API JSON responses on the AliExpress order pages (no DevTools needed). Also harvests the server-rendered first page from the page's embedded state — it never passes through fetch/XHR, so hooking alone silently misses the newest orders. Adds a floating button to download everything captured.
// @match        https://www.aliexpress.com/p/order/*
// @grant        GM_setClipboard
// @run-at       document-start
// ==/UserScript==

// Why document-start: we must replace window.fetch / XMLHttpRequest BEFORE the
// page's own scripts grab references to them, otherwise the order API calls
// fly past uncaptured.

(function () {
    'use strict';

    var captured = [];          // { url, status, body }
    var seen = new Set();       // de-dupe identical bodies

    // Keep this loose on purpose for the first capture pass: anything that
    // smells like the order API. We'd rather over-capture and filter later.
    function looksRelevant(url, body) {
        var u = (url || '').toLowerCase();
        if (/mtop|\/order|acs\.aliexpress|buyer|tradeorder/.test(u)) return true;
        if (typeof body === 'string' &&
            /"orderId"|orderList|"orderStatus"|"subOrders"|"productList"|"itemList"/.test(body)) {
            return true;
        }
        return false;
    }

    function record(url, status, body) {
        try {
            if (typeof body !== 'string' || !body) return;
            if (!looksRelevant(url, body)) return;
            var key = (url || '') + '|' + body.length + '|' + body.slice(0, 64);
            if (seen.has(key)) return;
            seen.add(key);
            captured.push({ url: String(url || ''), status: status, body: body });
            updateButton();
        } catch (e) { /* never break the page */ }
    }

    // --- hook fetch -------------------------------------------------------
    var origFetch = window.fetch;
    if (origFetch) {
        window.fetch = function () {
            var args = arguments;
            var url = (args[0] && args[0].url) ? args[0].url : args[0];
            return origFetch.apply(this, args).then(function (resp) {
                try {
                    resp.clone().text().then(function (body) {
                        record(url, resp.status, body);
                    }).catch(function () {});
                } catch (e) {}
                return resp;
            });
        };
    }

    // --- hook XMLHttpRequest ----------------------------------------------
    var origOpen = XMLHttpRequest.prototype.open;
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
        this.__capUrl = url;
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function () {
        var xhr = this;
        xhr.addEventListener('load', function () {
            var body;
            try { body = xhr.responseText; } catch (e) { body = null; }
            record(xhr.__capUrl, xhr.status, body);
        });
        return origSend.apply(this, arguments);
    };

    // --- server-rendered page 1 ---------------------------------------------
    // Page 1 of the order list is rendered server-side and embedded in the
    // page's initial state, so it never passes through fetch/XHR — hooking
    // alone silently misses the newest orders (the captured responses start at
    // pageIndex 2). Search the page globals for the component map that holds
    // the pc_om_list_order entries and record it wrapped in the same
    // {data:{data:components}} envelope as the real API responses, so the
    // Python parser needs no changes.
    var ssrDone = false;

    function findOrderComponents(root) {
        var visited = new Set();
        var stack = [{ obj: root, depth: 0 }];
        while (stack.length) {
            var cur = stack.pop();
            var obj = cur.obj;
            if (!obj || typeof obj !== 'object' || visited.has(obj)) continue;
            if (obj.nodeType) continue; // skip DOM nodes
            visited.add(obj);
            var keys;
            try { keys = Object.keys(obj); } catch (e) { continue; }
            for (var i = 0; i < keys.length; i++) {
                var v;
                try { v = obj[keys[i]]; } catch (e) { continue; }
                if (v && typeof v === 'object' &&
                    v.tag === 'pc_om_list_order' && v.fields) {
                    return obj; // obj is the component map
                }
            }
            if (cur.depth >= 8) continue;
            for (var j = 0; j < keys.length; j++) {
                var w;
                try { w = obj[keys[j]]; } catch (e) { continue; }
                if (w && typeof w === 'object') stack.push({ obj: w, depth: cur.depth + 1 });
            }
        }
        return null;
    }

    function harvestSSR() {
        if (ssrDone) return;
        try {
            var W = (typeof unsafeWindow !== 'undefined') ? unsafeWindow : window;
            // likely init-data globals first, then a full sweep of page globals
            var names = ['runParams', '__INIT_DATA__', '_init_data_', '__INITIAL_STATE__', '__AER_DATA__'];
            try { names = names.concat(Object.keys(W)); } catch (e) {}
            for (var i = 0; i < names.length && !ssrDone; i++) {
                var root;
                try { root = W[names[i]]; } catch (e) { continue; }
                if (!root || typeof root !== 'object') continue;
                var comps = findOrderComponents(root);
                if (!comps) continue;
                try {
                    record('ssr://mtop.aliexpress.trade.buyer.order.list/embedded-page-1',
                           200, JSON.stringify({ data: { data: comps } }));
                    ssrDone = true;
                } catch (e) { /* cyclic state; fall through to raw scripts */ }
            }
            if (!ssrDone) {
                // fallback: keep the raw inline scripts so the data at least
                // lands in the capture for later shape analysis
                var scripts = document.querySelectorAll('script:not([src])');
                for (var k = 0; k < scripts.length; k++) {
                    var text = scripts[k].textContent || '';
                    if (text.indexOf('pc_om_list_order') !== -1) {
                        record('ssr://inline-script', 200, text);
                        ssrDone = true;
                    }
                }
            }
        } catch (e) { /* never break the page */ }
    }

    // the init-data global may only appear once the app has booted, so retry
    function scheduleHarvest() {
        harvestSSR();
        [1000, 3000, 8000].forEach(function (ms) { setTimeout(harvestSSR, ms); });
    }

    // --- UI ----------------------------------------------------------------
    var btn;
    function updateButton() {
        if (btn) btn.textContent = '⬇ Download captured API (' + captured.length + ')';
    }

    function download() {
        var blob = new Blob([JSON.stringify(captured, null, 2)], { type: 'application/json' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'aliexpress-order-api-capture.json';
        document.body.appendChild(a);
        a.click();
        a.remove();
    }

    function addButton() {
        if (btn || !document.body) return;
        btn = document.createElement('button');
        btn.type = 'button';
        btn.style.cssText =
            'position:fixed;z-index:999999;right:16px;bottom:16px;padding:10px 14px;' +
            'background:#e62e04;color:#fff;border:0;border-radius:8px;font-size:14px;' +
            'cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3);';
        btn.addEventListener('click', download);
        document.body.appendChild(btn);
        updateButton();
    }

    function boot() {
        addButton();
        scheduleHarvest();
    }

    if (document.body) boot();
    else document.addEventListener('DOMContentLoaded', boot);
})();
