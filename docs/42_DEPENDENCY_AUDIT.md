# 42 · Dependency Audit (T-011)

**Round:** T-011 · 15 November 2026 · auditor tool: `infra/dependency_audit.py`
**Trigger:** environment rebuild after a sandbox recycle exposed that `pip install -e ".[dev]"` could not run the app or the suite — the dependency manifest had drifted from the code.

## Method

`infra/dependency_audit.py` inventories the manifest (`pyproject.toml`) against the
actually installed distributions in the *same* interpreter (same-environment
invariant: CVE scanning always runs under `sys.executable -m pip_audit`, never a
PATH binary that may belong to another venv). It cross-checks imports in
`app/` and `tests/`, flags declared-but-unused and imported-but-unresolved, and
scans for known CVEs via pip-audit (OSV/PyPI advisory feeds).

Usage: `.venv/bin/python infra/dependency_audit.py --repo .`
Exit 0 = clean · 1 = findings · 2 = usage error.

## Findings and resolutions

| # | Finding | Impact | Resolution |
|---|---|---|---|
| 1 | **4 runtime dependencies undeclared**: `argon2-cffi` (app/core/security), `jinja2` (app/main Jinja2Templates), `email-validator` (pydantic EmailStr in api/v1), `python-multipart` (Form() in ui/admin, ui/portal) | fresh `pip install -e .` could not boot the app — 57 test errors (ImportError/RuntimeError); CI pytest step red on any clean runner | added to `[project] dependencies` with pins |
| 2 | **4 test dependencies undeclared**: `pgserver`, `playwright`, `Pillow`, `pip-audit` | suite only worked in a sandbox that happened to have them preinstalled elsewhere | added to `[project.optional-dependencies] dev` |
| 3 | **CI contract bug**: `tests/conftest.py` reads `AKNJA_TEST_DATABASE_URL` (else imports pgserver); CI set only `DATABASE_URL` | CI pytest step raised `ModuleNotFoundError: pgserver` | added `AKNJA_TEST_DATABASE_URL` (service-container URL) to the workflow env |
| 4 | **Editable install broken on current setuptools**: flat-layout auto-discovery rejected multiple top-level dirs (`app`, `alembic`, `infra`, `database`) | `pip install -e ".[dev]"` fails with setuptools ≥ the current release (CI passed earlier only via an older cached setuptools) | explicit `[tool.setuptools.packages.find] include = ["app*"]` |
| 5 | **CVE: pytest 8.4.2** — PYSEC-2026-1845 | dev tooling exposure | upgraded to `pytest>=9.0.3,<10` (9.2.0 installed; suite green) |
| 6 | **CVE: Pillow 11.3.0** — 59 advisories; 12.3.0 still carried 42 (all fixed in 13.0.0) | e2e visual comparison exposure | upgraded to `Pillow>=13,<14` (13.0.0 installed; visual tests green) |
| 7 | **Visual baseline drift** (`admin-providers`): 1.18 % pixel diff, tolerance 0.2 % | suspected regression; analysis showed 37 changed bands of 8–13 px height (text lines only), identical 1280×3152 canvas, no layout change | baseline regenerated (`AKNJA_E2E_UPDATE_BASELINES=1`); cause is date-dependent text plus chromium 159 glyph rendering |

Why the AST import scan could not have caught finding 1: all four packages are
imported *lazily inside starlette/pydantic* at first use, so no `import` of them
exists in our source. The audit tool records this limitation in
`_LAZY_IMPORT_ALLOWLIST` and never flags those as unused.

## Final state (verification evidence)

- `pip install -e ".[dev]"` succeeds on a clean venv and boots the app
- `ruff check app tests` — clean
- `pytest -q` — **160 passed** (incl. Playwright e2e + visual on regenerated baseline)
- audit report: **81 installed · 0 CVE · 0 unused · 0 undeclared · 0 unresolved**, exit 0
- zero-cost invariant (docs/33): every dependency is MIT/Apache/BSD-class open source; no paid-service SDK among them (inventory in the generated report)

## Follow-ups (backlog candidates)

1. **Visual baselines are time-fragile** — screens rendering dates (admin-providers)
   will drift again. Improvement: freeze/mask date regions in `_capture`, or
   re-baseline on a schedule.
   *Update (T-012): root cause revised — the page renders no dates (seed
   timestamps frozen at a constant); the drift was a chromium build change
   affecting table-font rasterization. Baselines are environment-stable
   (two consecutive runs pixel-identical); the drift-vs-regression protocol
   is now tool-supported (`infra/baseline_verify.py`, docs/41 §5).*
2. **e2e is not exercised in CI** — *resolved in T-012: dedicated CI e2e job
   (chromium + `AKNJA_E2E_DATABASE_URL`) runs the 11 functional flows; visual
   baselines deliberately stay local (font-stack-tied).*
3. **No lockfile** — *resolved in T-012: `uv.lock` committed; CI installs via
   `uv sync --frozen --all-extras`.*
