# HROS deployment and demo-credential cleanup

## Required repository layout

The repository root (the Vercel Root Directory) must directly contain:

- `manage.py` and `requirements.txt`
- `vercel.json` and `api/index.py` (Vercel WSGI entrypoint)
- `payroll_project/` (settings, URLs and WSGI config)
- `core/` (models, views, templates, static assets and migrations)
- `requirements/` (shared/base, development and production dependency lists)

Do not set Vercel's Root Directory to `core/` or `payroll_project/`.

## What this correction changes

- Removes the public landing-page section that displayed `admin / admin123` and `aarav.sharma / emp123`.
- Changes the public call-to-action to account creation instead of demo credentials.
- Adds the explicit `api/index.py` WSGI entrypoint and catch-all rewrite for Vercel.
- Consolidates dependency declarations so `django-allauth` and `requests` are installed through the production requirements.
- Pins the Vercel Python version to 3.12 and removes generated `__pycache__`/`.pyc` files from the source archive.
- Removes published demo passwords from the README and makes clear that `seed_demo` is local-development-only.

## Deploy these changes

1. Extract this archive and open the inner `zesthr-django-main/` directory. That directory is the repository root.
2. Review the changed files, then copy them into the root of the existing GitHub repository. Do not nest the whole project under another directory.
3. Commit and push the changes to the exact branch configured in Vercel.
4. In Vercel Project Settings → Build and Deployment, verify Root Directory points to the folder containing `manage.py` and `vercel.json` (normally `.`).
5. Open Deployments and verify the new deployment shows the new commit SHA. Redeploy without build cache if needed.
6. In Project Settings → Environment Variables, confirm the production variables exist for the Production environment: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and `DATABASE_URL` (or all required `DB_*` variables). Keep `DJANGO_DEBUG=False`. Google OAuth credentials are separate.

## Important database warning

Removing the demo panel only removes public disclosure of the credentials. It does not delete demo users already stored in Supabase. Before production use, check the production database securely and rotate passwords or deactivate/delete known demo accounts as appropriate. Do not run `seed_demo` against production.

## Verify after deployment

- The home page no longer contains a Demo Access navigation link or demo credential section.
- `/login/` shows no demo usernames/passwords.
- `/signup/` is reachable.
- The Vercel deployment page shows the intended commit SHA.
- Sign-in and authorization checks are tested with a new unlinked account, a linked employee, and an authorized HR account.
