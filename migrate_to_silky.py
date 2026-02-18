#!/usr/bin/env python3
"""
migrate_to_silky.py
-------------------
Automated zero-data-loss migration from django-silk to django-silky.

Supports PostgreSQL, MySQL / MariaDB, and SQLite.

Usage
-----
  # From your Django project root (where manage.py lives):
  python migrate_to_silky.py

  # Specify manage.py location explicitly:
  python migrate_to_silky.py --manage-py /path/to/manage.py

  # Custom backup directory:
  python migrate_to_silky.py --backup-dir /var/backups/silk

  # Install a specific version:
  python migrate_to_silky.py --silky-version 1.0.0

  # See what would happen without touching anything:
  python migrate_to_silky.py --dry-run

  # Skip backup (not recommended, but useful in CI with external backups):
  python migrate_to_silky.py --skip-backup
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

OLD_PACKAGE = "django-silk"
NEW_PACKAGE = "django-silky"

# All tables owned by the 'silk' Django app
SILK_TABLES = [
    "silk_request",
    "silk_response",
    "silk_sqlquery",
    "silk_profile",
]

# Expected migration names (0001–0008) — same in both packages
EXPECTED_MIGRATIONS = [
    "0001_initial",
    "0002_auto_update_uuid4_id_field",
    "0003_request_prof_file",
    "0004_request_prof_file_storage",
    "0005_increase_request_prof_file_length",
    "0006_fix_request_poc_file_blank",
    "0007_sqlquery_identifier",
    "0008_sqlquery_analysis",
]

# ── Terminal colours ──────────────────────────────────────────────────────────

_USE_COLOUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

def _c(code: str) -> str:
    return code if _USE_COLOUR else ""

RESET  = _c("\033[0m")
BOLD   = _c("\033[1m")
GREEN  = _c("\033[32m")
YELLOW = _c("\033[33m")
RED    = _c("\033[31m")
CYAN   = _c("\033[36m")
DIM    = _c("\033[2m")


def info(msg: str)    -> None: print(f"{CYAN}  ▶  {RESET}{msg}")
def ok(msg: str)      -> None: print(f"{GREEN}  ✔  {RESET}{msg}")
def warn(msg: str)    -> None: print(f"{YELLOW}  ⚠  {RESET}{msg}")
def err(msg: str)     -> None: print(f"{RED}  ✖  {RESET}{msg}", file=sys.stderr)
def heading(msg: str) -> None: print(f"\n{BOLD}{msg}{RESET}")
def dim(msg: str)     -> None: print(f"{DIM}      {msg}{RESET}")


def die(msg: str, code: int = 1) -> None:
    err(msg)
    sys.exit(code)


# ── Subprocess helpers ────────────────────────────────────────────────────────

def run(
    cmd: list[str],
    capture: bool = False,
    check: bool = True,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    kwargs: dict = {"check": check, "env": env or os.environ.copy()}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)


def pip_run(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    return run([sys.executable, "-m", "pip", *args], capture=capture)


def manage_run(
    manage_py: Path,
    *args: str,
    capture: bool = False,
    check: bool = True,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    return run([sys.executable, str(manage_py), *args], capture=capture, check=check, env=env)


# ── Locate manage.py ─────────────────────────────────────────────────────────

def find_manage_py(hint: str | None) -> Path:
    if hint:
        p = Path(hint)
        if not p.is_file():
            die(f"manage.py not found at: {hint}")
        return p.resolve()

    for candidate in [Path("manage.py"), *sorted(Path(".").glob("*/manage.py"))]:
        if candidate.is_file():
            return candidate.resolve()

    die(
        "Could not find manage.py.\n"
        "  Run this script from your Django project root, or pass "
        "--manage-py /path/to/manage.py"
    )


# ── Read Django DB config ─────────────────────────────────────────────────────

def get_db_config(manage_py: Path) -> dict:
    """Ask Django to serialise DATABASES['default'] as JSON."""
    snippet = (
        "import json; from django.conf import settings; "
        "db = dict(settings.DATABASES.get('default', {})); "
        "print('__SILKY_DB__' + json.dumps(db))"
    )
    result = manage_run(
        manage_py, "shell", "-c", snippet,
        capture=True, check=False,
    )
    if result.returncode != 0:
        die(
            "Could not read Django settings.\n"
            f"  stderr: {result.stderr.strip()}\n\n"
            "  Make sure:\n"
            "  • DJANGO_SETTINGS_MODULE is set (or use --settings)\n"
            "  • All dependencies are installed in the current Python environment"
        )
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("__SILKY_DB__"):
            try:
                return json.loads(line[len("__SILKY_DB__"):])
            except json.JSONDecodeError:
                break
    die(
        "Unexpected output from Django shell.\n"
        f"  stdout: {result.stdout[:500]}"
    )


def detect_engine(db: dict) -> str:
    engine = db.get("ENGINE", "")
    if "postgresql" in engine or "psycopg" in engine:
        return "postgresql"
    if "mysql" in engine:
        return "mysql"
    if "sqlite" in engine:
        return "sqlite"
    die(
        f"Unsupported database engine: {engine!r}\n"
        "  Supported: django.db.backends.postgresql, .mysql, .sqlite3"
    )


# ── Backup helpers ────────────────────────────────────────────────────────────

def _pg_conn_args(db: dict) -> list[str]:
    """pg_dump / pg_restore connection flags (no db name)."""
    args: list[str] = []
    if db.get("HOST"):  args += ["--host",     db["HOST"]]
    if db.get("PORT"):  args += ["--port",     str(db["PORT"])]
    if db.get("USER"):  args += ["--username", db["USER"]]
    return args


def _pg_env(db: dict) -> dict:
    env = os.environ.copy()
    if db.get("PASSWORD"):
        env["PGPASSWORD"] = db["PASSWORD"]
    return env


def backup_postgresql(db: dict, backup_file: Path) -> None:
    table_flags: list[str] = []
    for t in SILK_TABLES:
        table_flags += ["--table", t]

    cmd = [
        "pg_dump",
        *_pg_conn_args(db),
        db["NAME"],
        "--format=custom",
        "--no-owner",
        "--no-acl",
        *table_flags,
        f"--file={backup_file}",
    ]
    dim("$ " + " ".join(cmd))
    run(cmd, env=_pg_env(db))
    ok(f"PostgreSQL backup → {backup_file}")


def restore_postgresql(db: dict, backup_file: Path) -> None:
    cmd = [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-acl",
        *_pg_conn_args(db),
        f"--dbname={db['NAME']}",
        str(backup_file),
    ]
    dim("$ " + " ".join(cmd))
    run(cmd, env=_pg_env(db))
    ok("PostgreSQL tables restored.")


def _mysql_conn_args(db: dict) -> list[str]:
    """mysql / mysqldump connection flags (password via env)."""
    args: list[str] = []
    if db.get("HOST"):  args += ["--host",  db["HOST"]]
    if db.get("PORT"):  args += ["--port",  str(db["PORT"])]
    if db.get("USER"):  args += ["--user",  db["USER"]]
    return args


def _mysql_env(db: dict) -> dict:
    env = os.environ.copy()
    if db.get("PASSWORD"):
        env["MYSQL_PWD"] = db["PASSWORD"]  # avoids password in ps output
    return env


def backup_mysql(db: dict, backup_file: Path) -> None:
    cmd = [
        "mysqldump",
        *_mysql_conn_args(db),
        "--single-transaction",
        "--add-drop-table",
        db["NAME"],
        *SILK_TABLES,
    ]
    dim("$ mysqldump [conn-args] " + db["NAME"] + " " + " ".join(SILK_TABLES))
    with open(backup_file, "w") as f:
        subprocess.run(cmd, stdout=f, check=True, env=_mysql_env(db))
    ok(f"MySQL backup → {backup_file}")


def restore_mysql(db: dict, backup_file: Path) -> None:
    cmd = ["mysql", *_mysql_conn_args(db), db["NAME"]]
    dim("$ mysql [conn-args] " + db["NAME"] + " < " + str(backup_file))
    with open(backup_file) as f:
        subprocess.run(cmd, stdin=f, check=True, env=_mysql_env(db))
    ok("MySQL tables restored.")


def backup_sqlite(db: dict, backup_file: Path) -> None:
    src = Path(db.get("NAME", ""))
    if not src.is_file():
        die(f"SQLite database not found: {src}")
    shutil.copy2(src, backup_file)
    ok(f"SQLite database copied → {backup_file}")


def restore_sqlite(db: dict, backup_file: Path) -> None:
    dest = Path(db.get("NAME", ""))
    shutil.copy2(backup_file, dest)
    ok(f"SQLite database restored → {dest}")


_BACKUP_FNS = {
    "postgresql": (backup_postgresql, restore_postgresql),
    "mysql":      (backup_mysql,      restore_mysql),
    "sqlite":     (backup_sqlite,     restore_sqlite),
}

_BACKUP_EXT = {
    "postgresql": ".dump",
    "mysql":      ".sql",
    "sqlite":     ".sqlite3",
}

_BACKUP_TOOL = {
    "postgresql": "pg_dump",
    "mysql":      "mysqldump",
    "sqlite":     None,  # no external tool needed
}


def do_backup(engine: str, db: dict, backup_dir: Path, dry_run: bool) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"silk_backup_{ts}{_BACKUP_EXT[engine]}"

    if dry_run:
        info(f"[dry-run] Would write backup → {backup_file}")
        return backup_file

    backup_dir.mkdir(parents=True, exist_ok=True)
    _BACKUP_FNS[engine][0](db, backup_file)
    return backup_file


def do_restore(engine: str, db: dict, backup_file: Path) -> None:
    warn(f"Restoring from backup: {backup_file}")
    _BACKUP_FNS[engine][1](db, backup_file)


# ── Package helpers ───────────────────────────────────────────────────────────

def get_version(package: str) -> str | None:
    """Return installed version of *package*, or None if not installed."""
    result = run(
        [
            sys.executable, "-c",
            f"import importlib.metadata; print(importlib.metadata.version({package!r}))",
        ],
        capture=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


# ── Migration helpers ─────────────────────────────────────────────────────────

def get_migration_status(manage_py: Path) -> dict[str, bool]:
    """Return {migration_label: applied} for the silk app."""
    result = manage_run(
        manage_py, "showmigrations", "silk", "--list",
        capture=True, check=False,
    )
    if result.returncode != 0:
        return {}

    status: dict[str, bool] = {}
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("[X]"):
            status[stripped[4:].strip()] = True
        elif stripped.startswith("[ ]"):
            status[stripped[4:].strip()] = False
    return status


# ── Data verification ─────────────────────────────────────────────────────────

def verify_data(manage_py: Path) -> None:
    snippet = (
        "from silk.models import Request, SQLQuery, Profile; "
        "print(f'  requests : {Request.objects.count():,}'); "
        "print(f'  queries  : {SQLQuery.objects.count():,}'); "
        "print(f'  profiles : {Profile.objects.count():,}')"
    )
    result = manage_run(
        manage_py, "shell", "-c", snippet,
        capture=True, check=False,
    )
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if any(k in line for k in ("requests", "queries", "profiles")):
                ok(line.strip())
    else:
        warn("Could not query row counts — check /silk/ in the browser manually.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="migrate_to_silky.py",
        description="Migrate from django-silk to django-silky with zero data loss.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Full docs: https://github.com/VaishnavGhenge/django-silky/blob/master/MIGRATING.md",
    )
    parser.add_argument(
        "--manage-py", metavar="PATH",
        help="Path to manage.py (default: auto-detect)",
    )
    parser.add_argument(
        "--backup-dir", metavar="DIR", default="./silk_backups",
        help="Directory for backup files (default: ./silk_backups)",
    )
    parser.add_argument(
        "--silky-version", metavar="VER", default=None,
        help="django-silky version to install, e.g. 1.0.0 (default: latest)",
    )
    parser.add_argument(
        "--skip-backup", action="store_true",
        help="Skip the backup step (not recommended)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without making any changes",
    )
    return parser.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    manage_py = find_manage_py(args.manage_py)
    backup_dir = Path(args.backup_dir)
    dry_run = args.dry_run
    install_spec = f"{NEW_PACKAGE}=={args.silky_version}" if args.silky_version else NEW_PACKAGE

    print(f"""
{BOLD}┌──────────────────────────────────────────────────┐
│  django-silk  →  django-silky  migration script  │
└──────────────────────────────────────────────────┘{RESET}""")

    if dry_run:
        warn("DRY-RUN mode — no changes will be made.\n")

    # ── Step 1: Pre-flight ───────────────────────────────────────────────────
    heading("Step 1 / 5 — Pre-flight checks")

    silk_ver = get_version(OLD_PACKAGE)
    silky_ver = get_version(NEW_PACKAGE)

    if silk_ver:
        ok(f"{OLD_PACKAGE} {silk_ver} installed")
    else:
        warn(f"{OLD_PACKAGE} not found — continuing anyway")

    if silky_ver:
        warn(f"{NEW_PACKAGE} {silky_ver} already installed — you may be re-running after a partial migration")

    info(f"manage.py: {manage_py}")

    db = get_db_config(manage_py)
    engine = detect_engine(db)
    ok(f"Database engine : {engine}  ({db.get('ENGINE', '')})")
    ok(f"Database name   : {db.get('NAME', '(unknown)')}")
    if db.get("HOST"):
        ok(f"Database host   : {db['HOST']}:{db.get('PORT', 'default')}")

    # Check backup tool is available
    if not args.skip_backup:
        tool = _BACKUP_TOOL[engine]
        if tool and not shutil.which(tool):
            die(
                f"Backup tool '{tool}' not found in PATH.\n\n"
                "  Install it and retry, or use --skip-backup to proceed without a backup.\n\n"
                "  PostgreSQL: apt install postgresql-client  |  brew install libpq\n"
                "  MySQL:      apt install default-mysql-client  |  brew install mysql-client"
            )
        if tool:
            ok(f"Backup tool     : {shutil.which(tool)}")
        else:
            ok("Backup tool     : built-in (shutil.copy2)")

    # ── Step 2: Backup ───────────────────────────────────────────────────────
    heading("Step 2 / 5 — Backup silk tables")

    backup_file: Path | None = None
    if args.skip_backup:
        warn("Skipping backup (--skip-backup passed).")
    else:
        backup_file = do_backup(engine, db, backup_dir, dry_run)

    # ── Step 3: Swap packages ────────────────────────────────────────────────
    heading("Step 3 / 5 — Swap packages")

    if dry_run:
        if silk_ver:
            info(f"[dry-run] pip uninstall {OLD_PACKAGE} -y")
        info(f"[dry-run] pip install {install_spec}")
    else:
        if silk_ver:
            info(f"Uninstalling {OLD_PACKAGE} {silk_ver} …")
            pip_run("uninstall", OLD_PACKAGE, "-y")
            ok(f"{OLD_PACKAGE} removed")
        else:
            info(f"{OLD_PACKAGE} not installed — skipping uninstall")

        info(f"Installing {install_spec} …")
        pip_run("install", install_spec)
        new_ver = get_version(NEW_PACKAGE) or "unknown"
        ok(f"{NEW_PACKAGE} {new_ver} installed")

    # ── Step 4: Migrations ───────────────────────────────────────────────────
    heading("Step 4 / 5 — Migrations")

    if dry_run:
        info("[dry-run] manage.py showmigrations silk")
        info("[dry-run] manage.py migrate silk  (only if pending)")
    else:
        migrations = get_migration_status(manage_py)

        if not migrations:
            warn(
                "Could not read migration status.\n"
                "  Run manually: python manage.py migrate silk"
            )
        else:
            applied = [m for m, done in migrations.items() if done]
            pending = [m for m, done in migrations.items() if not done]

            for m in applied:
                ok(f"[X] {m}")
            for m in pending:
                warn(f"[ ] {m}")

            if pending:
                info(f"Running: manage.py migrate silk  ({len(pending)} pending) …")
                result = manage_run(manage_py, "migrate", "silk", check=False)
                if result.returncode != 0:
                    err("manage.py migrate silk failed!")
                    if backup_file and backup_file.exists():
                        do_restore(engine, db, backup_file)
                        warn(f"Data restored. Re-install {OLD_PACKAGE} to get back to your previous state:")
                        warn(f"  pip install {OLD_PACKAGE}=={silk_ver or 'latest'}")
                    sys.exit(1)
                ok("All migrations applied.")
            else:
                ok(f"All {len(applied)} silk migrations already applied — no migrate needed.")

    # ── Step 5: Verify ───────────────────────────────────────────────────────
    heading("Step 5 / 5 — Verify data")

    if dry_run:
        info("[dry-run] Would query silk model row counts via manage.py shell")
    else:
        verify_data(manage_py)

    # ── Done ─────────────────────────────────────────────────────────────────
    rollback_cmd = f"pip install {OLD_PACKAGE}=={silk_ver}" if silk_ver else f"pip install {OLD_PACKAGE}"
    backup_note = str(backup_file) if backup_file else "(skipped)"

    print(f"""
{GREEN}{BOLD}  All done!{RESET}

  {BOLD}Next steps:{RESET}
  1. Restart your application server
  2. Visit /silk/ and confirm the UI loads with your historical data

  {BOLD}Backup location:{RESET}
  {backup_note}

  {BOLD}To roll back:{RESET}
  pip uninstall {NEW_PACKAGE} && {rollback_cmd}
  (no manage.py migrate needed — schema is shared)

  {DIM}Full migration docs: https://github.com/VaishnavGhenge/django-silky/blob/master/MIGRATING.md{RESET}
""")


if __name__ == "__main__":
    main()
