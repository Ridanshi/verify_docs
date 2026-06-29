"""
kaggle_setup.py — one-shot Kaggle environment setup for verify_docs.

Run this ONCE per Kaggle session before launching app.py.
Handles everything: PostgreSQL install + start, DB creation, .env, seeding.

Usage:
    python kaggle_setup.py
"""

import subprocess
import sys
import os
import time


def run(cmd, check=True, capture=False):
    print(f"  $ {cmd}")
    result = subprocess.run(
        cmd, shell=True,
        capture_output=capture,
        text=True
    )
    if check and result.returncode != 0:
        if capture:
            print(result.stderr)
        raise RuntimeError(f"Command failed (exit {result.returncode}): {cmd}")
    return result


def step(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


# ── 1. Install PostgreSQL if missing ─────────────────────────────────────────
step("1/5  Install PostgreSQL")
result = subprocess.run("which psql", shell=True, capture_output=True)
if result.returncode == 0:
    print("  psql already installed, skipping.")
else:
    print("  Installing...")
    run("apt-get install -y postgresql postgresql-contrib")
    print("  Installed.")

# ── 2. Start PostgreSQL ───────────────────────────────────────────────────────
step("2/5  Start PostgreSQL")
run("service postgresql start")
time.sleep(2)

# Create DB + set password (idempotent — IF NOT EXISTS)
run("""sudo -u postgres psql -c "SELECT 1 FROM pg_database WHERE datname='verify_docs_staging';" | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE verify_docs_staging;" """, check=False)
run("""sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';" """)
print("  PostgreSQL ready.")

# ── 3. Install Python deps ────────────────────────────────────────────────────
step("3/5  Install Python dependencies")
repo = "/kaggle/working/verify_docs"
run(f"pip install -r {repo}/requirements.txt -q")
print("  Done.")

# ── 4. Write .env ─────────────────────────────────────────────────────────────
step("4/5  Write .env")
env_path = f"{repo}/.env"
with open(env_path, "w") as f:
    f.write("DB_HOST=localhost\n")
    f.write("DB_PORT=5432\n")
    f.write("DB_NAME=verify_docs_staging\n")
    f.write("DB_USER=postgres\n")
    f.write("DB_PASSWORD=postgres\n")
print(f"  Written to {env_path}")

# ── 5. Seed DB ────────────────────────────────────────────────────────────────
step("5/5  Seed database")
result = subprocess.run(
    [sys.executable, f"{repo}/seed_db.py"],
    cwd=repo,
    text=True
)
if result.returncode != 0:
    print("  seed_db.py failed — check output above")
    sys.exit(1)

# ── Done ──────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("  SETUP COMPLETE")
print("  Now run:  python /kaggle/working/verify_docs/app.py")
print("="*60 + "\n")
