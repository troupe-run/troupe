# Source: troupe-run/infrastructure. Change it there; copies in other repositories are delivered.
"""The quality gates' dependency audit and weekly advisory report (spec: quality-gates; its design
D7 and D8). Split from quality_gates.py to keep each file short enough to review in one read
(#271; gate-files design D8): quality_gates.py's `audit` and `report` commands run these, so
every repository calls them as before.

Standard library only, like the guard. pip-audit, uv and npm run as processes, and OSV is read
over HTTPS.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from quality_gates import (
    CONFIG_NAME,
    SEVERITIES,
    AuditConfig,
    Config,
    GateError,
    _git,
    _process,
    _tool,
    resolve_base,
)

# --- Audit (design D7) ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Advisory:
    package: str
    version: str
    id: str
    severity: str
    """One of SEVERITIES, or `unknown`."""
    fixed_in: str | None
    """The version that fixes it, or None when there's no fix."""

    def text(self) -> str:
        fix = f"fixed in {self.fixed_in}" if self.fixed_in else "no fix yet"
        return f"{self.package} {self.version}: {self.id} ({self.severity}, {fix})"


def changed_lock_files(root: Path, base: str, lock_files: Sequence[str]) -> list[str]:
    """The configured lock files that differ between `base` and the work."""
    changed = []
    for lock in lock_files:
        diff = _git(root, "diff", "--quiet", base, "--", lock)
        if diff.returncode == 1:
            changed.append(lock)
        elif diff.returncode != 0:
            raise GateError(f"git diff of {lock} from {base} failed: {diff.stderr.strip()}")
        elif not (root / lock).exists():
            raise GateError(f"{CONFIG_NAME} names {lock}, which doesn't exist.")
    return changed


OSV_VULNS = "https://api.osv.dev/v1/vulns/"


def osv_record(advisory_id: str, timeout: float = 30) -> dict[str, object] | None:
    """An advisory's OSV record, or None when OSV doesn't have it. Unreachable is an error."""
    url = OSV_VULNS + urllib.parse.quote(advisory_id)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 (fixed https URL)
            record = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise GateError(f"OSV answered {error.code} for {advisory_id}.") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise GateError(f"couldn't read {advisory_id} from OSV ({url}): {error}.") from error
    return record if isinstance(record, dict) else None


def osv_severity(advisory_id: str, timeout: float = 30) -> str | None:
    """The severity GitHub's advisory database gives an advisory, through OSV, or None."""
    record = osv_record(advisory_id, timeout)
    specific = record.get("database_specific") if record else None
    severity = specific.get("severity") if isinstance(specific, dict) else None
    return severity.lower() if isinstance(severity, str) else None


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def osv_fixed_version(record: Mapping[str, object], package: str) -> str | None:
    """The lowest version of `package` that OSV's record says fixes the advisory, or None.

    Only the vulnerable package's own patched releases count: npm's `fixAvailable` can name a
    downgrade of a package that depends on it, which isn't a fix (spec: quality-gates; #330)."""
    fixed = []
    affected = record.get("affected")
    for entry in affected if isinstance(affected, list) else []:
        if entry.get("package", {}).get("name") != package:
            continue
        for found in entry.get("ranges", []):
            fixed += [event["fixed"] for event in found.get("events", []) if "fixed" in event]
    return min(fixed, key=_version_key) if fixed else None


SeverityLookup = Callable[[str], str | None]
RecordLookup = Callable[[str], Mapping[str, object] | None]


def pip_audit_advisories(report: Mapping[str, object], severity: SeverityLookup) -> list[Advisory]:
    """Each advisory in pip-audit's JSON, once, with its severity read through its GitHub alias."""
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        raise GateError("pip-audit's report has no `dependencies`: is it `-f json` output?")
    advisories: dict[tuple[str, str], Advisory] = {}
    for dependency in dependencies:
        for vuln in dependency.get("vulns", []):
            key = (dependency["name"], vuln["id"])
            if key in advisories:
                continue  # pip-audit lists some advisories twice
            ids = [vuln["id"], *vuln.get("aliases", [])]
            github = next((i for i in ids if i.startswith("GHSA-")), None)
            found = severity(github) if github else None
            fixes = vuln.get("fix_versions") or []
            advisories[key] = Advisory(
                dependency["name"],
                dependency["version"],
                github or vuln["id"],
                found if found in SEVERITIES else "unknown",
                fixes[0] if fixes else None,
            )
    return list(advisories.values())


def _npm_own_fix(entry: object, package: str) -> str | None:
    """npm's fix for an advisory OSV has no record of, only when it names the vulnerable package
    itself: a dependent's move, such as a downgrade, isn't a fix (owner, 2026-11-18; #330)."""
    fix = entry.get("fixAvailable") if isinstance(entry, dict) else None
    if isinstance(fix, dict) and fix.get("name") == package and isinstance(fix.get("version"), str):
        return str(fix["version"])
    return None


def npm_audit_advisories(
    report: Mapping[str, object], record: RecordLookup = osv_record
) -> list[Advisory]:
    """Each root advisory in `npm audit --json`, once, with npm's severity and OSV's fixed version.

    npm lists every package that depends on a vulnerable one too; the advisories themselves are
    the objects in each entry's `via`. Each one's fix is OSV's; npm's `fixAvailable` is read only
    when OSV has no record, and only when it names the vulnerable package itself, since it can be a
    downgrade of a dependent (#330)."""
    if "error" in report:
        raise GateError(f"npm audit failed: {report['error']}")
    vulnerabilities = report.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        raise GateError("npm audit's report has no `vulnerabilities`: is it `--json` output?")
    roots: dict[object, Mapping[str, object]] = {}
    for entry in vulnerabilities.values():
        for via in entry.get("via", []):
            if isinstance(via, dict):
                roots.setdefault(via.get("source", via.get("url")), via)
    advisories = []
    for via in sorted(roots.values(), key=lambda v: (str(v.get("name")), str(v.get("url")))):
        package = str(via.get("name"))
        advisory_id = str(via.get("url", "")).rstrip("/").rsplit("/", 1)[-1] or "npm advisory"
        found = record(advisory_id) if advisory_id.startswith("GHSA-") else None
        if found is not None:
            fixed_in = osv_fixed_version(found, package)
        else:
            fixed_in = _npm_own_fix(vulnerabilities.get(package), package)
        severity = via.get("severity")
        advisories.append(
            Advisory(
                package,
                str(via.get("range", "?")),
                advisory_id,
                severity if isinstance(severity, str) and severity in SEVERITIES else "unknown",
                fixed_in,
            )
        )
    return advisories


def blocking(advisories: Iterable[Advisory], config: AuditConfig) -> list[Advisory]:
    """The advisories that fail the gate: a blocked or unknown severity, with a fix."""
    return [
        advisory
        for advisory in advisories
        if advisory.fixed_in is not None
        and (advisory.severity in config.block or advisory.severity == "unknown")
    ]


def _run_json(command: Sequence[str], root: Path, what: str) -> dict[str, object]:
    """Run a tool that prints JSON (exit 1 can mean "found something"), and parse it."""
    result = _process(command, root)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise GateError(
            f"{what} failed (exit {result.returncode}): {result.stderr.strip()[-2000:]}"
        ) from None
    if not isinstance(data, dict):
        raise GateError(f"{what} printed JSON that isn't an object.")
    return data


def audit_uv_lock(
    root: Path, uv: str, pip_audit: str, severity: SeverityLookup = osv_severity
) -> list[Advisory]:
    """Every advisory for what uv.lock pins, every group and workspace member included."""
    with tempfile.TemporaryDirectory() as scratch:
        requirements = Path(scratch) / "requirements.txt"
        exported = _process(
            [uv, "export", "--frozen", "--all-groups", "--all-packages", "--no-emit-workspace",
             "--no-hashes", "--no-header", "--quiet", "--output-file", str(requirements)],
            root,
        )  # fmt: skip
        if exported.returncode != 0:
            raise GateError(f"uv export failed: {exported.stderr.strip()}")
        report = _run_json(
            [pip_audit, "-r", str(requirements), "--no-deps", "--disable-pip", "-s", "osv",
             "-f", "json", "--progress-spinner", "off"],
            root, "pip-audit",
        )  # fmt: skip
    return pip_audit_advisories(report, severity)


def audit_package_lock(root: Path, npm: str) -> list[Advisory]:
    return npm_audit_advisories(
        _run_json([npm, "audit", "--package-lock-only", "--json"], root, "npm audit")
    )


# --- Weekly report (design D8) --------------------------------------------------------------------

REPORT_TITLE = "Dependency advisories"
REPORT_LABEL = "dependencies"


class IssueTracker(Protocol):
    """The one report issue: found among open issues by title and label."""

    def find_open(self) -> int | None: ...
    def create(self, body: str) -> str: ...
    def edit(self, number: int, body: str) -> None: ...
    def close(self, number: int, comment: str) -> None: ...


def report_body(
    advisories: Sequence[Advisory], config: AuditConfig, lock_files: Sequence[str]
) -> str:
    """The issue's body: every advisory, marking those that would block a pull request."""
    failing = blocking(advisories, config)
    rows = [
        f"| {a.package} | {a.version} | {a.id} | {a.severity} | {a.fixed_in or 'no fix yet'} | "
        f"{'yes' if a in failing else ''} |"
        for a in sorted(advisories, key=lambda a: (a.package, a.id))
    ]
    return "\n".join(
        [
            f"The weekly dependency audit found {len(advisories)} advisories in "
            f"{', '.join(f'`{lock}`' for lock in lock_files)} on `main` "
            "(spec: quality-gates). This issue is kept up to date by "
            "`.github/workflows/dependency-report.yml`: its list is replaced each week, and it's "
            "closed when the audit finds none.",
            "",
            "A pull request that changes a lock file fails on the advisories marked *blocks*.",
            "",
            "| Package | Version | Advisory | Severity | Fixed in | Blocks |",
            "|---|---|---|---|---|---|",
            *rows,
        ]
    )


def upkeep(
    advisories: Sequence[Advisory],
    config: AuditConfig,
    issues: IssueTracker,
    lock_files: Sequence[str],
) -> str | None:
    """Open, update or close the one report issue. Returns its URL when it was opened."""
    number = issues.find_open()
    if not advisories:
        if number is not None:
            issues.close(number, "The weekly dependency audit found no advisories.")
        return None
    body = report_body(advisories, config, lock_files)
    if number is None:
        return issues.create(body)
    issues.edit(number, body)
    return None


class GhIssues:
    """The report issue through the gh CLI, with the token the workflow gives it."""

    def __init__(self, gh: str, repository: str) -> None:
        self.gh = gh
        self.repository = repository

    def _run(self, *args: str, body: str | None = None) -> str:
        result = _process([self.gh, *args, "-R", self.repository], Path.cwd(), body)
        if result.returncode != 0:
            raise GateError(f"gh {args[0]} {args[1]} failed: {result.stderr.strip()}")
        return result.stdout

    def find_open(self) -> int | None:
        listed = json.loads(
            self._run(
                "issue", "list", "--state", "open", "--label", REPORT_LABEL,
                "--search", f'in:title "{REPORT_TITLE}"', "--json", "number,title",
            )
        )  # fmt: skip
        matches = sorted(i["number"] for i in listed if i["title"] == REPORT_TITLE)
        return matches[0] if matches else None

    def create(self, body: str) -> str:
        return self._run(
            "issue", "create", "--title", REPORT_TITLE, "--label", REPORT_LABEL,
            "--body-file", "-", body=body,
        ).strip()  # fmt: skip

    def edit(self, number: int, body: str) -> None:
        self._run("issue", "edit", str(number), "--body-file", "-", body=body)

    def close(self, number: int, comment: str) -> None:
        self._run("issue", "close", str(number), "--comment", comment)


# --- Commands -----------------------------------------------------------------------------------


def _audit_locks(args: argparse.Namespace, root: Path, locks: Sequence[str]) -> list[Advisory]:
    found: list[Advisory] = []
    for lock in locks:
        if Path(lock).name == "uv.lock":
            where = root / Path(lock).parent
            found += audit_uv_lock(where, _tool("uv", args.uv), _tool("pip-audit", args.pip_audit))
        else:
            found += audit_package_lock(root / Path(lock).parent, _tool("npm", args.npm))
    return found


def audit_command(args: argparse.Namespace, root: Path, config: Config) -> int:
    base = resolve_base(root, args.base)
    changed = changed_lock_files(root, base, config.audit.lock_files)
    if not changed:
        print("audit: no lock file changed, so nothing to audit")
        return 0
    found = _audit_locks(args, root, changed)
    failing = blocking(found, config.audit)
    for advisory in found:
        mark = "FAIL" if advisory in failing else "note"
        print(f"audit: {mark} {advisory.text()}")
    if failing:
        print("audit: update each package above to its fixed version, or pin a fixed version.")
        return 1
    print(f"audit: {', '.join(changed)}: no {'/'.join(config.audit.block)} advisory with a fix")
    return 0


def report_command(args: argparse.Namespace, root: Path, config: Config) -> int:
    for lock in config.audit.lock_files:
        if not (root / lock).exists():
            raise GateError(f"{CONFIG_NAME} names {lock}, which doesn't exist.")
    found = _audit_locks(args, root, config.audit.lock_files)
    issues = GhIssues(_tool("gh", args.gh), args.repository)
    opened = upkeep(found, config.audit, issues, config.audit.lock_files)
    print(f"report: {len(found)} advisories in {', '.join(config.audit.lock_files)}")
    if opened is not None and args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as output:
            output.write(f"issue-url={opened}\n")
    return 0
