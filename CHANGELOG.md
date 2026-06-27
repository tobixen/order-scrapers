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
