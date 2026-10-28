"""Prepare schema once before starting the production server."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(*, prepare_only=False):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "payroll_project.settings.production")
    import django
    django.setup()
    from django.core.management import call_command
    call_command("prepare_deployment")
    if prepare_only:
        return
    os.environ["HROS_SCHEMA_PREPARED"] = "1"
    try:
        os.execvp("gunicorn", ["gunicorn", "--config", "gunicorn.conf.py", "payroll_project.wsgi:application"])
    finally:
        os.environ.pop("HROS_SCHEMA_PREPARED", None)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    main(prepare_only=parser.parse_args().prepare_only)
