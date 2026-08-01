# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(PEP 440 takes precedence for pre-releases).

## [Unreleased]

### Added
- Initial release: consolidates the previously standalone `~/bin` history
  builders into one installable package with a shared JSONL store.
- `svb24-history`, `decathlon-history`, `aliexpress-history` (capture-API
  ingester) and `lidl-history` (ingests `shopping-analyzer`'s `lidl_receipts.json`).
- Optional TOML config (`~/.config/order-scrapers/config.toml`).
- AliExpress order-API capture userscript under `userscripts/`.
- `lidl-history --fetch` runs shopping-analyzer to refresh `lidl_receipts.json`
  before ingesting it, so a Lidl update is one command like the other shops'
  instead of a `cd ~/regnskap && python ~/shopping-analyzer/get_data.py update
  --browser chromium --country bg` nobody had written down. The downloader is
  spawned, never imported, and runs in a scratch directory on a *copy* — its
  output path is relative to the working directory, so a crashed run would
  otherwise overwrite the stored receipts. A result holding fewer receipts than
  it was given is refused; a receipt already stored is reported rather than
  rewritten (`--update-all` takes the fetched copy); and `--country` is required,
  because shopping-analyzer defaults to Germany and the wrong country's API
  answers "no receipts" exactly like a good fetch with nothing new.
