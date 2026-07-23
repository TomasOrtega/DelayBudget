# Releasing

## Before tagging

1. Update `src/delaybudget/_version.py`, `CHANGELOG.md`, and `CITATION.cff` to
   the same version and release date.
2. Run the full local checks from [CONTRIBUTING.md](CONTRIBUTING.md).
3. Confirm the `main` branch is green in GitHub Actions.
4. Commit the release and create an annotated `vX.Y.Z` tag. Sign the tag when a
   maintainer signing key is available.

## Publishing

Push the commit and tag:

```bash
git push origin main
git push origin vX.Y.Z
```

The tag-triggered `Release` workflow:

- verifies that the tag matches the package version;
- reruns tests, coverage, linting, formatting, and type checking;
- builds and checks the wheel and source distribution;
- installs and smoke-tests the wheel in a clean environment;
- generates SHA-256 checksums and build-provenance attestations; and
- creates the GitHub release and attaches the artifacts.

The workflow is idempotent: rerunning it replaces artifacts on an existing
release for the same tag.

## PyPI

PyPI publishing is intentionally disabled until the project owner creates the
PyPI project and configures a trusted publisher. When enabled, use a protected
`pypi` environment and OpenID Connect rather than a long-lived API token.
