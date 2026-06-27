.PHONY: help install dev lint format test clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install the four *-history commands (auto-detects root, uv, pipx, or pip --user)
	@if [ "$$(id -u)" = "0" ]; then \
		echo "Running as root, installing system-wide..."; \
		pip install .; \
	elif command -v uv >/dev/null 2>&1; then \
		echo "Installing with uv (-> ~/.local/bin)..."; \
		uv tool install .; \
	elif command -v pipx >/dev/null 2>&1; then \
		echo "Installing with pipx (-> ~/.local/bin)..."; \
		pipx install .; \
	else \
		echo "Tip: install uv or pipx for isolated installs (pacman -S uv, apt install pipx)"; \
		echo "Falling back to pip install --user ..."; \
		PIP_BREAK_SYSTEM_PACKAGES=1 pip install --user .; \
	fi

dev:  ## Install with dev dependencies (editable)
	PIP_BREAK_SYSTEM_PACKAGES=1 pip install -e ".[dev]"

lint:  ## Run ruff linter and formatter check
	python -m ruff check src/ tests/
	python -m ruff format --check src/ tests/

format:  ## Auto-format code
	python -m ruff check --fix src/ tests/
	python -m ruff format src/ tests/

test:  ## Run tests
	python -m pytest

clean:  ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info src/*.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
