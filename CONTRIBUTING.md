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
| `make test` | Unit tests with coverage (95% minimum) |
| `make format` | Format the code |
| `make pre-push` | Run the pre-push checks by hand (Python 3.14) |

## Conventions

- [Conventional Commits](https://www.conventionalcommits.org/) (`feat(card): …`, `fix(token): …`) and semantic versioning.
- Tests come with the change. Coverage must stay at or above 95%.
- `strings.json` is the source of truth for UI text. Every file in `translations/` must have the same keys (a test checks it).
- `manifest.json` holds the version; `pyproject.toml` mirrors it (a test checks it).
- Any change to network behaviour states how many extra requests to EZVIZ it makes, in the PR and in the CHANGELOG.
- Link issues with `Relates to #N`, not `Fixes #N`.
- Commits must be signed, see below.

## Signed commits

`main` only accepts signed commits, so a pull request whose commits show as *Unverified* on GitHub can't be merged. Set signing up once, following GitHub's guides: [telling Git about your signing key](https://docs.github.com/en/authentication/managing-commit-signature-verification/telling-git-about-your-signing-key) (an SSH key is the quickest) and [signing commits](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits). `git config --global commit.gpgsign true` then signs every commit you make.

To sign commits you have already pushed, where `N` is the number of commits in your pull request:

```bash
git rebase --exec "git commit --amend --no-edit -S" HEAD~N
git push --force-with-lease
```

That recipe is for a branch with a straight line of commits. If yours has merge commits (for example, you merged `main` into it), say so in the pull request and we'll sort it out together.
