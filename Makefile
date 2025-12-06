.PHONY: help install test lint format clean run stop all

.DEFAULT_GOAL := help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } ' $(MAKEFILE_LIST)

run: ## Start all services (builds if needed)
	docker compose up -d --build

stop: ## Stop all services
	docker compose down

install: ## Install all dependencies
	pip install -r master-node/requirements.txt
	pip install -r remote-node/requirements.txt
	pip install -r gateway/requirements.txt
	pip install -r requirements.txt
	pip install black pytest

test: ## Run tests
	python -m pytest tests/ --ignore=tests/integration -v

lint: ## Check code formatting
	black --check --exclude '/(\.git|\.venv|venv|\.pytest_cache|__pycache__|\.egg-info)/' .

format: ## Format code with black
	black --exclude '/(\.git|\.venv|venv|\.pytest_cache|__pycache__|\.egg-info)/' .

clean: ## Clean temporary files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage

all: clean lint test ## Clean, lint, and test everything
	@echo "\n✓ All checks passed"
