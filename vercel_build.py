"""Vercel build step: apply database migrations before the new deployment goes live.

Runs on production deployments by default. Preview deployments usually share the
production database, so they only migrate when DJANGO_MIGRATE_ON_BUILD=true
(e.g. when previews point at a separate database branch).
"""
import os
import subprocess
import sys


def should_migrate() -> bool:
    override = os.environ.get("DJANGO_MIGRATE_ON_BUILD", "").strip().lower()
    if override in ("1", "true", "yes"):
        return True
    if override in ("0", "false", "no"):
        return False
    return os.environ.get("VERCEL_ENV") == "production"


def main() -> int:
    if not should_migrate():
        print(f"Skipping migrations (VERCEL_ENV={os.environ.get('VERCEL_ENV')!r}).")
        return 0
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "payroll_project.settings.production")
    print("Applying database migrations...")
    return subprocess.call([sys.executable, "manage.py", "migrate", "--noinput"])


if __name__ == "__main__":
    sys.exit(main())
