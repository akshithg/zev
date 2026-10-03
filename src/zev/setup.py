"""Human-facing setup and diagnostics for zev."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from importlib import metadata, resources
from pathlib import Path
from typing import Any

BRIDGE_ENDPOINT = "http://127.0.0.1:24119/status"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    action: str = ""


@dataclass(frozen=True)
class DoctorResult:
    checks: tuple[CheckResult, ...]
    package_version: str
    bundled_bridge_version: str | None
    installed_bridge_version: str | None

    @property
    def ready(self) -> bool:
        return any(check.name == "zev-bridge" and check.ok for check in self.checks)


def package_version() -> str:
    try:
        return metadata.version("zev")
    except metadata.PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        try:
            for line in pyproject.read_text().splitlines():
                if line.startswith("version = "):
                    return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return "0.0.0+unknown"


def bundled_xpi_path() -> Path | None:
    try:
        path = resources.files("zev.assets").joinpath("zev-bridge.xpi")
    except ModuleNotFoundError:
        return None

    if not path.is_file():
        return None

    with resources.as_file(path) as concrete_path:
        return Path(concrete_path)


def bridge_version_from_xpi(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            with archive.open("manifest.json") as manifest_file:
                manifest = json.load(manifest_file)
    except (FileNotFoundError, KeyError, OSError, json.JSONDecodeError, zipfile.BadZipFile):
        return None

    version = manifest.get("version")
    return str(version) if version else None


def http_json(url: str, timeout: float = 1.0) -> tuple[bool, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return True, json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return False, str(exc)


def run_doctor() -> DoctorResult:
    version = package_version()
    xpi_path = bundled_xpi_path()
    bundled_version = bridge_version_from_xpi(xpi_path) if xpi_path else None
    checks: list[CheckResult] = []

    if xpi_path and bundled_version:
        checks.append(CheckResult("Bundled bridge", True, f"{bundled_version} at {xpi_path}"))
    elif xpi_path:
        checks.append(CheckResult("Bundled bridge", False, f"found at {xpi_path}, but version is unreadable"))
    else:
        checks.append(
            CheckResult(
                "Bundled bridge",
                False,
                "not found in the installed Python package",
                "Reinstall or upgrade zev; the wheel should include zev-bridge.xpi.",
            )
        )

    bridge_ok, bridge_payload = http_json(BRIDGE_ENDPOINT)
    installed_version = _bridge_payload_version(bridge_payload) if bridge_ok else None
    if bridge_ok:
        detail = f"ok, version {installed_version}" if installed_version else "ok"
        # The bundled XPI is the newest build we have; a running bridge older
        # than it means the plugin was rebuilt but never reinstalled, which
        # otherwise fails silently as "my fix didn't take effect".
        if installed_version and bundled_version and compare_versions(installed_version, bundled_version) < 0:
            checks.append(
                CheckResult(
                    "zev-bridge",
                    False,
                    f"{detail}; bundled build is {bundled_version}",
                    "Run `zev setup` to install the newer bridge through Zotero’s Plugins window.",
                )
            )
        else:
            checks.append(CheckResult("zev-bridge", True, detail))
    else:
        checks.append(
            CheckResult(
                "zev-bridge",
                False,
                f"not reachable at {BRIDGE_ENDPOINT}: {bridge_payload}",
                "Run `zev setup` for installation instructions.",
            )
        )

    return DoctorResult(
        checks=tuple(checks),
        package_version=version,
        bundled_bridge_version=bundled_version,
        installed_bridge_version=installed_version,
    )


def format_doctor(result: DoctorResult) -> str:
    lines = [f"zev {result.package_version}"]
    for check in result.checks:
        marker = "ok" if check.ok else "needs attention"
        lines.append(f"{check.name}: {marker} - {check.detail}")
        if check.action:
            lines.append(f"Next: {check.action}")
    lines.append(f"Status: {'ready' if result.ready else 'setup incomplete'}")
    return "\n".join(lines)


def resolve_setup_xpi(xpi: str | None) -> Path:
    if xpi:
        path = Path(xpi).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"XPI not found: {path}")
        return path
    bundled = bundled_xpi_path()
    if bundled is None:
        raise FileNotFoundError("Bundled zev-bridge.xpi was not found in this zev installation.")
    return bundled


def setup_guidance(xpi_path: Path, result: DoctorResult, force: bool = False) -> str:
    if result.ready and not force:
        return format_doctor(result) + "\nzev-bridge is installed and current."

    lines = [
        format_doctor(result),
        "",
        f"Use this XPI: {xpi_path}",
        "Install path:",
        "1. Open Zotero Tools -> Plugins.",
        "2. Drag zev-bridge.xpi into the Plugins window.",
        "3. Restart Zotero.",
        "4. Run `zev doctor` to verify the bridge.",
    ]
    return "\n".join(lines)


def compare_versions(left: str, right: str) -> int:
    left_key = _version_key(left)
    right_key = _version_key(right)
    return (left_key > right_key) - (left_key < right_key)


def _version_key(version: str) -> tuple[tuple[int, int, str], ...]:
    """Return an orderable key for a dotted version string.

    Each part becomes a ``(kind, number, text)`` triple so numeric and
    alphabetic segments compare without mixing ``int`` and ``str`` (numeric
    parts sort before alphabetic ones at the same position).
    """
    parts: list[tuple[int, int, str]] = []
    for part in version.replace("-", ".").split("."):
        if part.isdigit():
            parts.append((0, int(part), ""))
        elif part:
            parts.append((1, 0, part))
    return tuple(parts)


def _bridge_payload_version(payload: Any) -> str | None:
    if isinstance(payload, dict):
        version = payload.get("version")
        return str(version) if version else None
    return None
