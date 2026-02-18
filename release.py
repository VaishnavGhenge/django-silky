#!/usr/bin/env python3
"""
release.py
----------
Automated release script for django-silky.

Usage
-----
  python release.py 1.0.1                  # full release
  python release.py 1.0.1 --test-pypi      # upload to TestPyPI first, then PyPI
  python release.py 1.0.1 --test-pypi-only # upload to TestPyPI only (dry run)
  python release.py 1.0.1 --skip-tests     # skip pytest
  python release.py 1.0.1 --skip-push      # build & upload without pushing tag to remote
  python release.py 1.0.1 --dry-run        # print every step, execute nothing
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ── Colours ───────────────────────────────────────────────────────────────────

_COLOUR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

def _c(code): return code if _COLOUR else ""

RESET  = _c("\033[0m");  BOLD  = _c("\033[1m")
GREEN  = _c("\033[32m"); YELLOW = _c("\033[33m")
RED    = _c("\033[31m"); CYAN  = _c("\033[36m")
DIM    = _c("\033[2m")

def info(msg):    print(f"{CYAN}  ▶  {RESET}{msg}")
def ok(msg):      print(f"{GREEN}  ✔  {RESET}{msg}")
def warn(msg):    print(f"{YELLOW}  ⚠  {RESET}{msg}")
def err(msg):     print(f"{RED}  ✖  {RESET}{msg}", file=sys.stderr)
def heading(msg): print(f"\n{BOLD}{msg}{RESET}")
def dim(msg):     print(f"{DIM}      {msg}{RESET}")
def die(msg, code=1): err(msg); sys.exit(code)

# ── Subprocess helpers ────────────────────────────────────────────────────────

def run(cmd, capture=False, check=True, env=None):
    kwargs = {"check": check, "env": env or os.environ.copy()}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    dim("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kwargs)

def py(*args, **kwargs):
    return run([sys.executable, *args], **kwargs)

# ── Validation ────────────────────────────────────────────────────────────────

# Matches PEP 440: 1.0.0 / 1.0.0a1 / 1.0.0b2 / 1.0.0rc1 / 1.0.0.post1 / 1.0.0.dev1
_VERSION_RE = re.compile(
    r"^\d+\.\d+\.\d+"
    r"(a\d+|b\d+|rc\d+)?"
    r"(\.post\d+)?"
    r"(\.dev\d+)?$"
)

def validate_version(version: str) -> str:
    if not _VERSION_RE.match(version):
        die(
            f"Invalid version: {version!r}\n"
            "  Expected PEP 440 format, e.g.: 1.0.0 / 1.0.1 / 2.0.0a1 / 1.1.0rc1"
        )
    return version

def tag_exists(version: str) -> bool:
    result = run(["git", "tag", "--list", f"v{version}"], capture=True, check=False)
    return bool(result.stdout.strip())

def working_tree_clean() -> bool:
    result = run(["git", "status", "--porcelain"], capture=True)
    return not result.stdout.strip()

def current_branch() -> str:
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    return result.stdout.strip()

# ── Steps ─────────────────────────────────────────────────────────────────────

def step_preflight(version: str, args) -> None:
    heading("Step 1 / 6 — Pre-flight checks")

    # Git state
    branch = current_branch()
    ok(f"Branch: {branch}")
    if branch not in ("master", "main"):
        warn(f"Not on master/main (on '{branch}') — are you sure?")

    if not working_tree_clean():
        die(
            "Working tree has uncommitted changes.\n"
            "  Commit or stash them before releasing."
        )
    ok("Working tree is clean")

    # Tag collision
    if tag_exists(version):
        die(
            f"Tag v{version} already exists.\n"
            "  Choose a different version or delete the tag:\n"
            f"    git tag -d v{version} && git push origin :refs/tags/v{version}"
        )
    ok(f"Tag v{version} is available")

    # Required tools
    for tool in ("git", "twine"):
        if not shutil.which(tool):
            die(f"'{tool}' not found in PATH — install it and retry.")
        ok(f"Found: {tool}")

    # build module
    result = py("-c", "import build", capture=True, check=False)
    if result.returncode != 0:
        die("'build' package not installed.\n  Run: pip install build")
    ok("Found: build")


def step_tests(args) -> None:
    heading("Step 2 / 6 — Run tests")

    if args.skip_tests:
        warn("Skipping tests (--skip-tests).")
        return

    env = os.environ.copy()
    env.setdefault("DB_ENGINE", "sqlite3")

    result = run(
        [sys.executable, "-m", "pytest", "project/tests/", "-q", "--tb=short"],
        check=False, env=env,
    )
    if result.returncode != 0:
        die("Tests failed — aborting release.")
    ok("All tests passed")


def step_tag(version: str, args) -> None:
    heading("Step 3 / 6 — Tag release")

    if args.dry_run:
        info(f"[dry-run] git tag -a v{version} -m 'Release v{version}'")
        return

    run(["git", "tag", "-a", f"v{version}", "-m", f"Release v{version}"])
    ok(f"Created tag: v{version}")

    if args.skip_push:
        warn("Skipping git push (--skip-push).")
    else:
        remote = _get_remote()
        run(["git", "push", remote, "master", "--tags"])
        ok(f"Pushed tag v{version} → {remote}")


def _get_remote() -> str:
    result = run(["git", "remote"], capture=True)
    remotes = result.stdout.strip().splitlines()
    if "origin" in remotes:
        return "origin"
    if remotes:
        return remotes[0]
    die("No git remote configured.")


def step_build(version: str, args) -> Path:
    heading("Step 4 / 6 — Build distributions")

    dist_dir = Path("dist")

    if args.dry_run:
        info("[dry-run] rm -rf dist/ build/ *.egg-info/")
        info("[dry-run] python -m build")
        return dist_dir

    # Clean previous builds
    for d in [dist_dir, Path("build")]:
        if d.exists():
            shutil.rmtree(d)
            info(f"Removed {d}/")
    for egg in Path(".").glob("*.egg-info"):
        shutil.rmtree(egg)
        info(f"Removed {egg}/")

    py("-m", "build")

    # Verify expected files exist
    whl  = list(dist_dir.glob(f"django_silky-{version}-*.whl"))
    sdist = list(dist_dir.glob(f"django_silky-{version}.tar.gz"))

    if not whl or not sdist:
        # setuptools_scm may format version slightly differently; show what's there
        built = list(dist_dir.iterdir())
        ok(f"Built: {[f.name for f in built]}")
    else:
        ok(f"Built: {whl[0].name}")
        ok(f"Built: {sdist[0].name}")

    return dist_dir


def step_check(dist_dir: Path, args) -> None:
    heading("Step 5 / 6 — Check distributions")

    if args.dry_run:
        info("[dry-run] twine check dist/*")
        return

    result = run(
        ["twine", "check", *dist_dir.glob("*")],
        check=False,
    )
    if result.returncode != 0:
        die("twine check failed — fix the issues above before uploading.")
    ok("twine check passed")


def step_upload(version: str, dist_dir: Path, args) -> None:
    heading("Step 6 / 6 — Upload to PyPI")

    if args.dry_run:
        if args.test_pypi or args.test_pypi_only:
            info("[dry-run] twine upload --repository testpypi dist/*")
        if not args.test_pypi_only:
            info("[dry-run] twine upload dist/*")
        return

    files = list(dist_dir.glob("*"))

    # TestPyPI first
    if args.test_pypi or args.test_pypi_only:
        info("Uploading to TestPyPI …")
        run(["twine", "upload", "--repository", "testpypi", *files])
        ok(f"https://test.pypi.org/project/django-silky/{version}/")

        if args.test_pypi_only:
            warn("--test-pypi-only: stopping here. Run without that flag to publish to PyPI.")
            return

        info("Verify the TestPyPI upload looks correct, then production upload will proceed.")

    # Production PyPI
    info("Uploading to PyPI …")
    run(["twine", "upload", *files])
    ok(f"https://pypi.org/project/django-silky/{version}/")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        prog="release.py",
        description="Build and publish a django-silky release to PyPI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "version",
        help="Version to release, e.g. 1.0.1 (must be PEP 440)",
    )
    parser.add_argument(
        "--test-pypi",
        action="store_true",
        help="Upload to TestPyPI first, then PyPI",
    )
    parser.add_argument(
        "--test-pypi-only",
        action="store_true",
        help="Upload to TestPyPI only (useful for verifying before the real release)",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running the test suite",
    )
    parser.add_argument(
        "--skip-push",
        action="store_true",
        help="Create the tag locally but do not push to remote",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print every step without executing anything",
    )
    return parser.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    version = validate_version(args.version)

    print(f"""
{BOLD}┌────────────────────────────────────────┐
│  django-silky release script  v{version:<8} │
└────────────────────────────────────────┘{RESET}""")

    if args.dry_run:
        warn("DRY-RUN mode — no changes will be made.\n")

    step_preflight(version, args)
    step_tests(args)
    step_tag(version, args)
    dist_dir = step_build(version, args)
    step_check(dist_dir, args)
    step_upload(version, dist_dir, args)

    print(f"""
{GREEN}{BOLD}  Released django-silky {version}!{RESET}

  PyPI:    https://pypi.org/project/django-silky/{version}/
  GitHub:  https://github.com/VaishnavGhenge/django-silky/releases/tag/v{version}

  Install: pip install django-silky=={version}
""")


if __name__ == "__main__":
    main()
