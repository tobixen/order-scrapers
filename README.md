# order-scrapers

Append-only **order/purchase history builders** for various web shops. Each
shop command turns a logged-in browser session (or an exported capture) into a
de-duplicated JSONL history you can feed into bookkeeping/analysis.

| Command | Shop | How it gets data |
|---------|------|------------------|
| `svb24-history` | svb24.com | replays the logged-in session (browser cookies, `curl_cffi` past Cloudflare); parses order HTML + invoice PDFs |
| `decathlon-history` | decathlon.* | replays the `web-engage` JSON API with browser cookies |
| `aliexpress-history` | aliexpress.com | ingests a JSON capture of the `mtop` order-list API (see [`userscripts/`](userscripts/)) |
| `lidl-history` | lidl.* | ingests the `lidl_receipts.json` produced by [shopping-analyzer](https://github.com/tobixen/shopping-analyzer) |

All four share one tested JSONL store with the same `--update-all` / `--dry-run`
semantics. **No credentials are embedded**: cookies are read from your browser
at runtime, and the actual history files stay wherever you point `-o` (they are
*not* part of this repo).

## Installation

```
make install
```

This auto-detects `uv`, `pipx`, or `pip --user` and installs the four commands
into `~/.local/bin`. (For development: `make dev` for an editable install with
test deps.)

## Usage

Each command appends to a JSONL file (default under `~/regnskap/`) and
de-duplicates on the shop's order id. Run any command with `--help` for the full
option list; the common ones are `-o/--output`, `--update-all` (re-fetch and
rewrite changed records) and `-n/--dry-run`.

```
svb24-history --browser firefox
decathlon-history --update-all
aliexpress-history ~/Downloads/aliexpress-order-api-capture.json
lidl-history --input ~/shopping-analyzer/lidl_receipts.json
```

### AliExpress capture

AliExpress can't be fetched headless (signed `mtop` gateway + anti-bot). Install
the userscript in [`userscripts/`](userscripts/), load your order page, scroll
to load all orders, click the download button, then run `aliexpress-history` on
the downloaded JSON. See [`userscripts/README.md`](userscripts/README.md).

## Configuration

Optional TOML at `~/.config/order-scrapers/config.toml` sets per-shop defaults
(output path, browser, country, input/capture file); command-line flags always
win. Example:

```toml
[aliexpress]
output = "~/regnskap/aliexpress-history.jsonl"

[decathlon]
browser = "firefox"
country = "bg"
```

## License

AGPL-3.0-or-later. The Lidl support only ingests output from the separate AGPL
[shopping-analyzer](https://github.com/tobixen/shopping-analyzer) project; no
code is copied from it.
