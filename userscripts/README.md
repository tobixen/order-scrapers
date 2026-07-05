# Userscripts

## `order-api-capture.user.js` — AliExpress order-API capture

AliExpress can't be fetched headless: the order list is loaded from Alibaba's
signed `mtop` gateway and guarded by an anti-bot captcha. So the capture runs
**inside the logged-in browser**. This Tampermonkey/Violentmonkey userscript
hooks `fetch`/`XHR` on `https://www.aliexpress.com/p/order/*`, auto-collects the
`mtop.aliexpress.trade.buyer.order.list` JSON responses as you scroll, and gives
you a floating button to download them as one JSON file.

Page 1 of the order list is rendered **server-side** and never passes through
`fetch`/`XHR`, so hooking alone silently misses the newest orders (the captured
responses start at `pageIndex` 2). Since 0.2 the script also harvests the
embedded page-1 state and records it in the same envelope as the API responses.
If you are stuck on 0.1 (or the embedded-state harvest fails on a page
redesign), force page 1 through the API instead: switch the status tab (e.g. to
*Awaiting delivery* and back to *View all*) before downloading. The ingester
prints a warning when a capture is missing page 1.

### Use

1. Install in Tampermonkey (Firefox or Chromium): *Utilities → Install from
   URL*, pointing at this file's raw URL (or paste its contents into a new
   script).
2. **Reload** `https://www.aliexpress.com/p/order/index.html` (the hook only
   takes effect on a fresh page load).
3. Scroll / "View More Orders" until your whole history is rendered; the red
   button bottom-right shows the capture count.
4. Click **"⬇ Download captured API"** → saves
   `aliexpress-order-api-capture.json`.
5. Feed it to the ingester:
   ```
   aliexpress-history ~/Downloads/aliexpress-order-api-capture.json
   ```

The list API already includes per-line prices and a real `currencyCode`, so no
order-detail page visits are needed — even multi-item orders come through fully.

## Related: the DOM-scraping alternative

Before the API-capture approach, a forked DOM-scraping userscript was used
(tab-separated clipboard export). It lives separately at
[tobixen/aliexpress-order-downloader](https://github.com/tobixen/aliexpress-order-downloader)
(a fork of [chriskomus/aliexpress-order-downloader](https://github.com/chriskomus/aliexpress-order-downloader);
currency/bug fixes offered upstream as PR #4). The API-capture script here
supersedes it for building the JSONL history.
