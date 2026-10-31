# HROS

HROS manages employee records, attendance, leave, reviewed payroll, private employee documents, notifications, and audit reporting. It runs as a Django modular monolith with PostgreSQL in production and SQLite for development.

The current release has automated authorization, tenant-isolation, attendance, leave, payroll, migration, and storage tests. Production readiness still depends on verified deployment settings, private storage provisioning, recovery operations, and approved business policies. See [progress and remaining work](docs/PROGRESS.md).

## Local setup

Use Python 3.12. Create and activate a virtual environment, then run:

```sh
python -m pip install -r requirements/development.txt
```

Copy `.env.example` to `.env`, select development settings, and supply a local secret. Keep secrets out of Git. The development database is SQLite; production settings require PostgreSQL, explicit hosts, a strong secret, and email configuration.

```sh
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/. On Windows, activate with `.venv\Scripts\Activate.ps1`; on Unix, use `source .venv/bin/activate` after creating the environment with `python -m venv .venv`. Do not generate new migrations merely to initialize an existing checkout.

`seed_demo` is optional and restricted to debug development environments. Its known-password accounts belong only in disposable local databases. Existing production records must never be replaced by demo data.

## Core workflows

- Provision login accounts in the restricted administration interface, link employees, and assign employment dates, departments, managers, and schedules. Provisioned accounts must change their initial password. Deactivation revokes the linked login and retains history.
- Employees check in/out, request attendance corrections, apply for leave, read notifications, and access their own available payslips and documents.
- Authorized managers review direct-report leave and correction requests. HR access is limited by explicit permissions and organization membership.
- Payroll operators calculate and review snapshots. Independent approval precedes finalization. Finalized payroll is immutable; reversals and subsequent adjustments preserve history.
- Attendance anomalies are reviewable exceptions. They do not establish misconduct or automatically impose penalties.
- PDF documents use private storage, validated uploads, authorized downloads, audit events, and retention controls. Production uploads stay disabled until durable storage is configured.

## Verification

```sh
python manage.py test
python manage.py makemigrations --check --dry-run
python -m pip_audit
```

The default test command uses isolated test settings. GitHub Actions runs the full suite on SQLite and PostgreSQL, checks migration drift and selected lint errors, enforces coverage of at least 75%, audits dependencies, and builds/verifies the non-root container. PostgreSQL concurrency tests intentionally skip on SQLite. Use the isolated Compose service and settings described in [operations](docs/OPERATIONS.md) for local PostgreSQL verification.

## Documentation

- [Architecture and current module boundaries](docs/ARCHITECTURE.md)
- [Accounts and roles](docs/ACCOUNTS.md)
- [Attendance policies](docs/ATTENDANCE_POLICY.md)
- [Leave, payroll, and data ownership policies](docs/BUSINESS_POLICIES.md)
- [Read-only versioned API](docs/API.md)
- [Database migration](docs/DATABASE.md)
- [Deployment, backup, recovery, rollback, and document storage](docs/OPERATIONS.md)
- [Implementation evidence and limitations](docs/PROGRESS.md)

The deployment target is Render using `render.yaml` and `scripts/start_server.py`. The older Vercel material is historical guidance and is not the verified production deployment path. Store production environment values in the hosting secret manager; `.env.example` documents their names without credentials.

Native mobile applications, automatic statutory taxation, and comprehensive country/branch-specific policies are outside the verified release. Existing location and calendar reference models do not establish a complete multi-branch business implementation.

## Neon, organization isolation and messaging

See [Neon Auth and messaging setup](docs/NEON_AND_MESSAGING.md) for Neon PostgreSQL
and managed Neon Auth, organization invitations, tenant isolation, HR announcements,
the website help assistant, and verified WhatsApp attendance and notification commands.
Neon and Meta account configuration is required before their live integrations work.
