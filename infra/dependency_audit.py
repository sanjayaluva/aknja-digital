#!/usr/bin/env python
"""Dependency audit runner — T-011 tooling (aknja-digital).

Runs against a repository checkout and produces a dependency audit:

  1. manifest inventory   — direct dependencies from pyproject.toml
                            ([project] dependencies) or requirements*.txt
  2. installed inventory  — every installed distribution with version,
                            license and direct/transitive classification
  3. import cross-check   — scans app/tests source for imports, flags
                            declared-but-unused and used-but-undeclared
  4. CVE scan             — via pip-audit (if importable), JSON parsed;
                            skipped with an explicit note when offline

Output: <out>/dependency_audit.json + dependency_audit.md
Exit 0 = no blocking findings; 1 = findings needing attention; 2 = usage/env error.

Written while the aknja-digital checkout was unavailable (sandbox recycle,
private remote). Smoke-tested against a synthetic manifest; point it at the
restored checkout with:

    python scripts/dependency_audit.py --repo /home/z/my-project/aknja-digital

Zero-cost invariant (docs/33): the report lists every dependency so a human
can confirm none of them is a paid-service SDK.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

# Build/test tooling that is allowed to never appear in source imports
# (invoked as CLI commands, or audit-only).
_TOOL_ALLOWLIST = {
    "pip-audit", "pytest", "pytest-cov", "coverage", "ruff", "black",
    "mypy", "uv", "pip", "setuptools", "wheel", "hatchling", "build",
    "alembic",
}
# Runtime dependencies whose import is LAZY and happens inside another
# library, so the AST import scan can never see it — never flag as unused.
#   jinja2            — starlette.templating.Jinja2Templates (app/main.py)
#   python-multipart  — starlette form parsing (app/ui Form() endpoints)
#   email-validator   — pydantic EmailStr (app/api/v1 auth/crm)
_LAZY_IMPORT_ALLOWLIST = {"jinja2", "python-multipart", "email-validator"}
# Modules imported only for side effects / typing; ignore in the import scan.
_IMPORT_IGNORE = {"__future__"}


def _norm(name: str) -> str:
    """PEP 503 normalization so pip-audit == pip_audit == pip.audit."""
    return re.sub(r"[-_.]+", "-", name).lower()


def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


# ------------------------------------------------------------- manifest


def parse_manifest(repo: Path) -> tuple[list[str], str]:
    """Return (direct dependency specs, manifest kind)."""
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
        deps = list(data.get("project", {}).get("dependencies", []))
        groups = data.get("project", {}).get("optional-dependencies", {})
        for extra in groups.values():
            deps.extend(extra)
        return deps, "pyproject.toml"

    req = repo / "requirements.txt"
    if not req.is_file():
        candidates = sorted(repo.glob("requirements*.txt"))
        if not candidates:
            die(f"no pyproject.toml or requirements*.txt under {repo}")
        req = candidates[0]
    specs: list[str] = []
    for line in req.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            specs.append(line)
    return specs, req.name


def spec_name(spec: str) -> str:
    """Distribution name from a requirement spec (PEP 508 name part)."""
    m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    return m.group(1).lower() if m else spec.lower()


# --------------------------------------------------------- installed set


def installed_dists() -> dict[str, metadata.Distribution]:
    out: dict[str, metadata.Distribution] = {}
    for dist in metadata.distributions():
        name = (dist.metadata["Name"] or "").lower()
        if name:
            out[name] = dist
    return out


def module_to_dist_map() -> dict[str, list[str]]:
    try:
        return metadata.packages_distributions()
    except Exception:  # noqa: BLE001 — older importlib metadata raises several types
        return {}


# ----------------------------------------------------------- import scan


def scan_imports(repo: Path) -> set[str]:
    """Top-level modules imported anywhere under app/ tests/ (skip venv)."""
    modules: set[str] = set()
    for base in ("app", "tests"):
        root = repo / base
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        modules.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    modules.add(node.module.split(".")[0])
    return modules - _IMPORT_IGNORE


# --------------------------------------------------------------- pip-audit


def run_pip_audit() -> tuple[list[dict], str]:
    """CVE scan via pip-audit JSON. Returns (findings, note).

    pip_audit MUST run under the same interpreter as the inventory above,
    so prefer `sys.executable -m pip_audit`; the PATH binary is only a
    fallback (it may belong to a different venv and audit the wrong env).
    """
    import shutil

    if importlib.util.find_spec("pip_audit") is not None:
        cmd = [sys.executable, "-m", "pip_audit"]
    elif shutil.which("pip-audit"):
        cmd = ["pip-audit"]
    else:
        return [], "skipped: pip-audit not installed (pip install pip-audit for CVE scan)"
    try:
        proc = subprocess.run(
            cmd + ["--format", "json", "--skip-editable"],
            capture_output=True, text=True, timeout=600, check=False,
        )
    except subprocess.TimeoutExpired:
        return [], "skipped: pip-audit timed out (offline?)"
    if proc.returncode not in (0, 1):
        return [], f"skipped: pip-audit exited {proc.returncode}: {proc.stderr[-300:]}"
    try:
        findings = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], "skipped: pip-audit produced no parsable JSON"
    return findings, ""


# ------------------------------------------------------------------ main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="repository checkout to audit")
    parser.add_argument("--out", default=None, help="output dir (default: <repo>)")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        die(f"repository path not found: {repo}")
    out = Path(args.out).resolve() if args.out else repo
    out.mkdir(parents=True, exist_ok=True)

    specs, manifest_kind = parse_manifest(repo)
    direct_names = {_norm(spec_name(s)) for s in specs}
    installed = {_norm(k): v for k, v in installed_dists().items()}
    mod2dist = module_to_dist_map()
    imported = scan_imports(repo)

    # which distributions are actually imported by source code
    imported_dists: set[str] = set()
    for module in imported:
        imported_dists.update(_norm(d) for d in mod2dist.get(module, []))

    unused_declared, undeclared_used, inventory = [], [], {}
    for name, dist in sorted(installed.items()):
        version = dist.version
        license_field = (dist.metadata.get("License") or "").strip()
        # classifier fallback for the common License-File-only packages
        if not license_field:
            for classifier in dist.metadata.get_all("Classifier") or []:
                if classifier.startswith("License ::"):
                    license_field = classifier.split("::")[-1].strip()
                    break
        is_direct = name in direct_names
        inventory[name] = {
            "version": version,
            "license": license_field or "UNKNOWN",
            "direct": is_direct,
            "imported_by_source": name in imported_dists,
        }
        if (
            is_direct
            and name not in imported_dists
            and name not in _TOOL_ALLOWLIST
            and name not in _LAZY_IMPORT_ALLOWLIST
        ):
            unused_declared.append(name)
    for dist_name in sorted(imported_dists):
        if dist_name not in inventory:
            undeclared_used.append(dist_name)  # imported but not installed here
    for name in direct_names:
        if name not in inventory:
            undeclared_used.append(f"{name} (declared, not installed)")

    # Imported top-level modules that map to NO installed distribution and are
    # neither stdlib nor repo-local packages — the signature of an undeclared
    # dependency that pip install -e . would NOT provide (CI-fresh-runner red).
    stdlib = set(sys.stdlib_module_names)
    unresolved = sorted(
        mod for mod in imported
        if mod not in stdlib
        and mod not in mod2dist
        and not (repo / mod).is_dir()
    )

    findings, note = run_pip_audit()
    # pip-audit 2.10 JSON schema: {"dependencies": [{name, version, vulns: [...]}],
    # "fixes": [...]}; each vuln has id / fix_versions / aliases / description.
    dep_list = findings.get("dependencies", []) if isinstance(findings, dict) else findings
    vulns: list[dict] = []
    seen_vulns: set[tuple[str, str]] = set()
    for dep in dep_list:
        for v in (dep.get("vulns") or []):
            key = (dep.get("name", "?"), v.get("id", "?"))
            if key in seen_vulns:  # OSV advisories can surface twice via aliases
                continue
            seen_vulns.add(key)
            vulns.append({
                "package": dep.get("name", "?"),
                "version": dep.get("version", "?"),
                "id": v.get("id", "?"),
                "aliases": v.get("aliases") or [],
                "fix_versions": v.get("fix_versions", []),
            })

    blocking = bool(vulns) or bool(undeclared_used) or bool(unresolved)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "repository": str(repo),
        "manifest": {"kind": manifest_kind, "direct_dependencies": specs},
        "inventory": inventory,
        "unused_declared": sorted(set(unused_declared)),
        "undeclared_or_missing": sorted(set(undeclared_used)),
        "unresolved_imports": unresolved,
        "vulnerabilities": vulns,
        "cve_scan_note": note,
        "counts": {
            "installed": len(inventory),
            "direct": len(direct_names),
            "transitive": len(inventory) - sum(1 for i in inventory.values() if i["direct"]),
            "vulnerabilities": len(vulns),
        },
        "blocking": blocking,
    }
    (out / "dependency_audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    md = [
        "# Dependency audit report",
        "",
        f"- generated: {report['generated_at']}",
        f"- repository: `{repo}`",
        f"- manifest: `{manifest_kind}` ({len(direct_names)} direct dependencies)",
        (f"- installed: {report['counts']['installed']}"
         f" ({report['counts']['direct']} direct, {report['counts']['transitive']} transitive)"),
        "",
        "## Vulnerabilities (pip-audit)",
        "",
        note or (f"{len(vulns)} finding(s)." if vulns else "No known CVEs in installed versions."),
    ]
    for v in vulns:
        md.append(f"- **{v['package']}** {v['version']} — {v['id']} "
                  f"(aliases: {', '.join(v['aliases']) or '—'}; "
                  f"fix: {', '.join(v['fix_versions']) or 'none'})")
    md += ["", "## Declared but never imported (candidates for removal)", ""]
    md += [f"- {n}" for n in report["unused_declared"]] or ["- none"]
    md += ["", "## Imported but not declared/installed", ""]
    md += [f"- {n}" for n in report["undeclared_or_missing"]] or ["- none"]
    md += ["", "## Unresolved imports (module installed nowhere — undeclared dependency, breaks fresh installs)", ""]
    md += [f"- {n}" for n in report["unresolved_imports"]] or ["- none"]
    md += ["", "## Inventory", "", "| package | version | license | direct | imported |",
           "| --- | --- | --- | --- | --- |"]
    for name, item in inventory.items():
        md.append(f"| {name} | {item['version']} | {item['license']} | "
                  f"{'yes' if item['direct'] else 'no'} | "
                  f"{'yes' if item['imported_by_source'] else 'no'} |")
    (out / "dependency_audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"audit complete: {report['counts']['installed']} installed, "
          f"{len(vulns)} CVE finding(s), {len(report['unused_declared'])} unused, "
          f"{len(report['undeclared_or_missing'])} undeclared/missing, "
          f"{len(report['unresolved_imports'])} unresolved")
    if note:
        print(f"  CVE scan: {note}")
    for n in report["unused_declared"]:
        print(f"  unused:      {n}")
    for n in report["undeclared_or_missing"]:
        print(f"  undeclared:  {n}")
    for n in report["unresolved_imports"]:
        print(f"  UNRESOLVED:  {n}  <-- not installed, not stdlib, undeclared")
    print(f"  report: {out / 'dependency_audit.md'}")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
