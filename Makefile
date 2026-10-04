.PHONY: setup build-docker check test lint format format-check typecheck dead-code pre-push

DOCKER_IMAGE = ezviz-cloud-dev

setup:
	git config --local core.hooksPath .githooks
	@echo "Git hooks configured (core.hooksPath = .githooks); pre-push now runs the CI checks in the dev image."

build-docker:
	docker build -f Dockerfile.dev -t $(DOCKER_IMAGE) .

check: lint format-check typecheck test dead-code
	@echo "All checks passed."

test:
	pytest tests/unit/ -v --cov=custom_components/ezviz_cloud --cov-fail-under=90 --cov-report=term-missing

lint:
	ruff check .

format:
	ruff format .

format-check:
	ruff format --check .

typecheck:
	mypy custom_components/ezviz_cloud/ --ignore-missing-imports

dead-code:
	vulture custom_components/ezviz_cloud/ vulture_whitelist.py

pre-push:
	.githooks/pre-push
