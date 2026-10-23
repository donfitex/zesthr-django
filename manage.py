#!/usr/bin/env python
import os, sys

if __name__ == "__main__":
    # Locally: development (SQLite). On Vercel: production (Supabase Postgres).
    default_settings = (
        "payroll_project.settings.production"
        if os.environ.get("VERCEL")
        else "payroll_project.settings.development"
    )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)