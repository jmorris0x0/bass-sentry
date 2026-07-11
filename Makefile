.PHONY: help install test lint format clean run stop all fleet-update fleet-status fleet-logs

.DEFAULT_GOAL := help

NODES ?= sound-pi-1 sound-pi-2 sound-pi-3
SSH_USER ?= sound
SERVICE = bass_sentry_remote_node

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } ' $(MAKEFILE_LIST)

run: ## Start all services (builds if needed)
	docker compose up -d --build
	@pkill -f advertise-service.sh 2>/dev/null || true
	@sleep 1
	@nohup ./advertise-service.sh >/tmp/bass-advertise.log 2>&1 &
	@echo "\n✓ Bass Sentry running and advertised on network"

stop: ## Stop all services
	docker compose down
	pkill -f advertise-service.sh || true

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

fleet-update: ## git pull + restart service on every node in $(NODES)
	@for h in $(NODES); do echo "== $$h =="; \
	  ssh $(SSH_USER)@$$h.local 'cd bass-sentry && git pull --ff-only && sudo systemctl restart $(SERVICE)' ; \
	done

fleet-status: ## Show service state on every node
	@for h in $(NODES); do printf "%-15s " $$h; \
	  ssh $(SSH_USER)@$$h.local "systemctl is-active $(SERVICE)" ; \
	done

fleet-logs: ## Tail last 20 lines of service logs on every node
	@for h in $(NODES); do echo "== $$h =="; \
	  ssh $(SSH_USER)@$$h.local "sudo journalctl -u $(SERVICE) -n 20 --no-pager" ; \
	done
