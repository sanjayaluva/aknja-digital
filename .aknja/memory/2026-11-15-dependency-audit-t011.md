# Episodic memory — Dependency audit + workspace recovery (T-011, 2026-11-15)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What happened

A sandbox recycle wiped the local clone, venv and push credentials between
rounds. Three blocked turns were spent building audit tooling blind (later
committed as `infra/dependency_audit.py`); the owner then set the repo public
and the workspace was rebuilt at 455054e. The rebuild immediately exposed that
the dependency manifest had drifted from the code — this round became T-011.

## What was found and fixed

1. **Manifest drift (the core finding).** `pip install -e ".[dev]"` could not
   boot the app on a clean venv: `argon2-cffi`, `jinja2`, `email-validator` and
   `python-multipart` were imported (lazily — inside starlette/pydantic, so no
   visible `import` in our source) but never declared. Local runs had been
   masked by a general-purpose sandbox venv that happened to contain them.
   Test deps `pgserver`, `playwright`, `Pillow`, `pip-audit` were equally
   undeclared. All eight are now pinned in pyproject.
2. **CI was latently red.** `tests/conftest.py` reads `AKNJA_TEST_DATABASE_URL`
   (else it imports pgserver); the workflow set only `DATABASE_URL`. Any clean
   CI runner would fail with `ModuleNotFoundError: pgserver`. Fixed by setting
   the contract variable alongside DATABASE_URL.
3. **Editable install broke on current setuptools** (flat-layout discovery
   rejected `app/alembic/infra/database` as multiple top-level packages).
   Fixed with explicit `[tool.setuptools.packages.find] include = ["app*"]`.
4. **CVE upgrades:** pytest 8.4.2 → 9.2.0 (PYSEC-2026-1845), Pillow 11.3.0 →
   13.0.0 (59 advisories on 11.x, 42 still on 12.3.0).
5. **Visual baseline regeneration** (`admin-providers`): 1.18 % pixel diff vs
   0.2 % tolerance was proven non-structural — 37 changed bands, all 8–13 px
   (text-line height), identical 1280×3152 canvas. Cause: date-dependent text
   plus chromium 159 glyph rendering. Baseline regenerated with the built-in
   `AKNJA_E2E_UPDATE_BASELINES=1`.

## Tooling lessons (encoded in the audit tool)

- pip-audit must run under the SAME interpreter as the inventory
  (`sys.executable -m pip_audit`); a PATH-resolved `pip-audit` binary can
  silently audit a different venv and misattribute its CVEs.
- pip-audit 2.10 JSON is `{"dependencies": [{name, version, vulns}], "fixes"}`;
  the vuln list field is `vulns`, and OSV advisories can appear twice via
  aliases — dedupe by (package, id).
- Distribution names need PEP 503 normalization (`pip-audit` vs `pip_audit`).
- AST import scans cannot see lazy imports; maintain an explicit
  `_LAZY_IMPORT_ALLOWLIST` (jinja2, python-multipart, email-validator).

## Verification

Clean-venv editable install + app import OK · ruff clean · pytest 160/160
(incl. e2e + visual on Pillow 13 / chromium 159) · audit 81 installed /
0 CVE / 0 unused / 0 undeclared / 0 unresolved, exit 0.

## Follow-ups surfaced

Visual baselines are time-fragile (date-rendering screens); e2e lacks a CI job
with browsers; no lockfile — reproducibility is range-based. Logged in
docs/42 §Follow-ups as T-012 candidates.
