# Benchmark workflow — MAX vs SGLang on Modal.
# Prereqs: .venv with `pip install -r requirements.txt`, `modal token new` once.

MODAL := .venv/bin/modal
export PYTHONPATH := src

.PHONY: deploy-sglang deploy-max stop-sglang stop-max urls check

deploy-sglang: ## Deploy the SGLang baseline app
	$(MODAL) deploy src/apps/sglang_server.py

deploy-max: ## Deploy the OSS MAX app
	$(MODAL) deploy src/apps/max_server.py

stop-sglang: ## Stop the SGLang app (kills GPU spend)
	$(MODAL) app stop bench-sglang

stop-max: ## Stop the MAX app (kills GPU spend)
	$(MODAL) app stop bench-max

urls: ## Print deployed endpoint URLs
	@$(MODAL) app list 2>/dev/null | grep -E "bench-(sglang|max)" || true

check: ## Validate that both app modules import cleanly locally
	python -c "import apps.sglang_server, apps.max_server; print('imports OK')"

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
