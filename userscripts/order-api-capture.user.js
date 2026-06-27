// ==UserScript==
// @name         AliExpress Order API Capture
// @namespace    http://tobixen.no/
// @version      0.1
// @description  Auto-capture the mtop order-API JSON responses on the AliExpress order pages (no DevTools needed). Adds a floating button to download everything captured, so we can see the real response shape and build a JSONL exporter from it.
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

    if (document.body) addButton();
    else document.addEventListener('DOMContentLoaded', addButton);
})();
