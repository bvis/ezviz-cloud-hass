# Contributing

The most useful contribution is testing with a camera model that isn't in the README table yet and reporting the result.

## Development setup

Everything runs in the dev image built from `Dockerfile.dev`, the same one CI uses:

```bash
git clone https://github.com/bvis/ezviz-cloud-hass.git
cd ezviz-cloud-hass
make setup          # one-time: pre-push hook runs every CI check in Docker
make build-docker
docker run --rm -v "$PWD":/app -w /app ezviz-cloud-dev make check
```

## Commands

| Command | Description |
|---|---|
| `make setup` | Configure git hooks (`core.hooksPath = .githooks`) |
| `make build-docker` | Build the `ezviz-cloud-dev` image |
| `make check` | Lint, format check, type check, tests and dead code |
| `make test` | Unit tests with coverage (90% minimum) |
| `make format` | Format the code |
| `make pre-push` | Run the pre-push checks by hand (Python 3.14) |

## Conventions

- [Conventional Commits](https://www.conventionalcommits.org/) (`feat(card): …`, `fix(token): …`) and semantic versioning.
- Tests come with the change. Coverage must stay at or above 90%.
- `strings.json` is the source of truth for UI text. Every file in `translations/` must have the same keys (a test checks it).
- `manifest.json` holds the version; `pyproject.toml` mirrors it (a test checks it).
- Any change to network behaviour states how many extra requests to EZVIZ it makes, in the PR and in the CHANGELOG.
- Link issues with `Relates to #N`, not `Fixes #N`.
