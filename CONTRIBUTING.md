# Contributing to order-scrapers

Contributions are mostly welcome (but do tell me if you've used AI or other
tools). If the length of this text scares you, skip reading it and just open a
pull request on GitHub. If you find it too difficult to write test code etc.,
skip it and hope the maintainer will fix it.

Web shops change their markup and APIs constantly, so the most valuable
contributions are usually **bug reports with a captured fixture** (a sanitized
sample of the response that broke) and a failing test.

## What to include

Every submission should ideally include:

- **Test code** covering the new behaviour or bug fix, with a **sanitized**
  fixture — remove names, addresses and anything else personal. Order ids and
  product titles in small samples are acceptable; never commit a full history.
- **Documentation** updates where relevant.
- **A changelog entry** in `CHANGELOG.md` under `[Unreleased]`.

## Scope and licensing

This repo collects *history builders*: each shop module turns a logged-in
session (or an exported capture) into an append-only JSONL history. It does not
embed credentials — cookies are read from your browser at runtime.

The project is licensed **AGPL-3.0-or-later**. The Lidl support here only
*ingests* the JSON produced by the separate AGPL project
[shopping-analyzer](https://github.com/tobixen/shopping-analyzer); it does not
copy that code.

## Commit messages

Please follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
in the imperative mood:

- `fix: handle multi-item AliExpress orders`
- `feat: add lidl ingester`
- `docs: update README`
