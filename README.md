# order-scrapers

Append-only **order/purchase history builders** for various shops.  Orders are downloaded from the web and stored locally in jsonl-files.

* No credentials stored.
  * For most shops, user should log into the web shop through the browser, the import script will then catch the browser session cookie and use it.
  * Aliexpress was non-trivial.  It's necessary to run a browser-side script to capture the data from the API-calls, and then run the python script to convert this data to jsonl.
  * Lidl depends on my fork of the [shopping-analyzer](https://github.com/tobixen/shopping-analyzer) (I didn't want to copy the code into this project - though I particularly opted for the AGPL license, making this an option)

## Shops supported as of 2026-06

* svb24.com
* decathlon
* aliexpress.com
* lidl

More to come.  Pull requests adding more shops are welcome.

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
