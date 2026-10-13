"""
mock-azure/test_environment.py
============================================================
Environment / dependency-compatibility tests.

These run outside the harness (no monkeypatching, no shim) so the results
reflect what a user actually gets from a fresh install.
"""

import subprocess
import sys
from pathlib import Path

import pytest

import offline_harness as H

REPO = H.REPO


def test_guard_sdk_import_works_on_a_fresh_install():
    """
    FIXED (was P0 / blocker): the tool used to fail to start on a current
    install.

    providers/azure/resources.py asked for

        from azure.mgmt.resource import ResourceManagementClient

    but on azure-mgmt-resource 26.x the class is no longer re-exported at the
    package root — it lives at azure.mgmt.resource.resources. The ImportError
    was swallowed by main.py's provider registry, which set registry["azure"]
    to None and refused to run.

    Verified here in a clean subprocess with no shim, so this fails again if the
    import path or the version floor regresses.
    """
    r = subprocess.run(
        [sys.executable, "-c",
         "from providers.azure import resources; "
         "print(resources.ResourceManagementClient.__module__)"],
        cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"import still broken:\n{r.stderr}"
    assert "ResourceManagementClient" in r.stdout or "azure" in r.stdout


def test_guard_cli_starts_and_completes_a_run(tmp_path):
    """
    FIXED (was P0, user-visible): the CLI no longer refuses to run with
    "Provider 'azure' is not available", and a full extraction→export run now
    completes offline.
    """
    out = tmp_path / "ran.csv"
    r = subprocess.run(
        [sys.executable, "main.py", "--provider", "azure",
         "--input", str(H.NORMALIZED_CSV), "--output", str(out), "--no-pricing"],
        cwd=str(REPO), capture_output=True, text=True, timeout=300)

    combined = r.stdout + r.stderr
    assert "is not available" not in combined, combined[-2000:]
    assert r.returncode == 0, f"exit {r.returncode}\n{combined[-2000:]}"
    assert out.exists(), "no output written"
    assert len(H.read_rows(out)) == len(H.normalized_rows())


def test_guard_azure_sdk_pin_matches_the_import_path():
    """
    GUARD: the dependency declaration must stay consistent with the import the
    code performs. requirements.txt pins azure-mgmt-resource exactly, so the
    SDK layout cannot drift under the import without the change being visible.
    """
    import importlib.metadata as md

    req = (REPO / "requirements.txt").read_text(encoding="utf-8")
    spec = [l.strip() for l in req.splitlines()
            if l.strip().startswith("azure-mgmt-resource")][0]
    assert spec.startswith("azure-mgmt-resource=="), f"not pinned exactly: {spec}"

    pinned = spec.split("==", 1)[1].strip()
    assert int(pinned.split(".")[0]) >= 26, f"predates the 26.x layout: {pinned}"

    installed = md.version("azure-mgmt-resource")
    assert installed == pinned, f"declared {pinned}, installed {installed}"

    # and the pinned version really does expose the name the code imports
    from azure.mgmt.resource.resources import (        # noqa: F401
        ResourceManagementClient,
    )
    assert ResourceManagementClient.__module__.startswith("azure.mgmt.resource")


def test_guard_lockfile_present_and_referenced():
    """
    GUARD: requirements.lock is the freeze CI installs. It must exist and the
    install path must actually point at it, or the pinning is decorative.
    """
    lock = REPO / "requirements.lock"
    req = (REPO / "requirements.txt").read_text(encoding="utf-8")

    assert lock.exists(), "requirements.lock missing"
    assert "requirements.lock" in req, "lock exists but nothing references it"

    locked = lock.read_text(encoding="utf-8")
    assert "azure-mgmt-resource==" in locked
    assert "azure-identity==" in locked


def test_confirmed_no_pyproject_or_entrypoint():
    """
    CONTEXT: there is no pyproject.toml and no console entry point, so the tool
    is invoked as `python main.py` and cannot be installed, versioned, or
    distributed. No __version__ exists anywhere either.
    """
    assert not (REPO / "pyproject.toml").exists()
    assert not (REPO / "setup.py").exists()
    skip = (".venv-312", ".venv-test", ".venv", ".worktrees", ".git", "mock-azure")
    src = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                    for p in REPO.rglob("*.py")
                    if not any(x in p.parts for x in skip))
    assert "__version__" not in src
