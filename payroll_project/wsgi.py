import os
import sys
from django.core.wsgi import get_wsgi_application

# Explicitly use production settings for Vercel
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'payroll_project.settings.production')

# 1. Initialize the Django application layout first
application = get_wsgi_application()

# 2. Automatically execute migrations safely inside the serverless runtime
try:
    from django.core.management import call_command
    print("Running production database migrations...")
    call_command("migrate", interactive=False)
    print("Database migrations applied successfully!")
except Exception as e:
    print(f"Migration fallback error: {e}", file=sys.stderr)
