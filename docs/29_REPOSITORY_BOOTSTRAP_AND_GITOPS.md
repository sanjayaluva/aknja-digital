# Repository Bootstrap and GitOps Rules

Branch model: protected `main`; short-lived `feat/*`, `fix/*`, `docs/*`; PR review and CI required. Commit messages reference issue/requirement IDs. Pin dependency versions and base image digests. Generate SBOM and artifact provenance. Use migrations in version control. No secrets or production data. Every release tags source commit and immutable image digest. Root `AGENTS.md` points to `.aknja/README.md` and defines coding conventions only; no duplicate memory stores.
