# Database guide

HROS uses **PostgreSQL in production** and **SQLite for local development**. The same
migrations run on both, and the whole test suite is run against both.

## Which settings use which database

| Settings module | Database |
|---|---|
| `payroll_project.settings.development` | SQLite file (`db.sqlite3`, or `DJANGO_SQLITE_PATH`) |
| `payroll_project.settings.test` | SQLite in memory |
| `payroll_project.settings.test_postgres` | PostgreSQL (integration tests) |
| `payroll_project.settings.production` | PostgreSQL (required) |

## Connecting production to PostgreSQL

Set **either** one URL (what Neon, Supabase, Render and Railway give you):

    DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require

**or** the separate values `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`.

| Variable | Default | Meaning |
|---|---|---|
| `DB_SSLMODE` | `require` | Encrypted connection. Use `disable` only for a database on the same private network. Overrides `?sslmode=` in the URL. |
| `DB_CONN_MAX_AGE` | `60` | Seconds a connection is reused. |
| `DB_CONNECT_TIMEOUT` | `10` | Seconds before giving up connecting. |
| `DB_DISABLE_SERVER_SIDE_CURSORS` | `False` | Set `True` behind a transaction pooler (pgbouncer, Neon's pooled endpoint). |

The password may contain special characters; URL-encode them in `DATABASE_URL` (`@` becomes `%40`).

## Running the tests against PostgreSQL

    # local PostgreSQL in Docker (any PostgreSQL 14+ works)
    docker run -d --name hros-pg -e POSTGRES_USER=hros -e POSTGRES_PASSWORD=hros \
        -e POSTGRES_DB=hros -p 5432:5432 postgres:16

    # Windows PowerShell:  $env:TEST_DB_PASSWORD="hros"
    TEST_DB_PASSWORD=hros python manage.py test --settings=payroll_project.settings.test_postgres

Django creates and drops its own `test_hros` database, so the role needs `CREATEDB`
(the Docker user above is a superuser, so it has it).

## Moving existing SQLite data to PostgreSQL

Do this once, with the site stopped, and **keep the original `db.sqlite3` untouched**.

1. Work on a copy and bring it to the latest schema:

       cp db.sqlite3 legacy.sqlite3
       DJANGO_SETTINGS_MODULE=payroll_project.settings.development \
       DJANGO_SQLITE_PATH=legacy.sqlite3 python manage.py migrate

2. Point the production environment at an **empty** PostgreSQL database and create the schema:

       python manage.py migrate

3. Rehearse. This copies, verifies, then rolls everything back:

       python manage.py migrate_legacy_data --source-sqlite legacy.sqlite3 --dry-run

4. Copy for real (all-or-nothing, in one transaction):

       python manage.py migrate_legacy_data --source-sqlite legacy.sqlite3

The command refuses to run if the source has unapplied migrations, if the target already
holds data, or if source and target are the same file. It verifies row counts, primary
keys, which login belongs to which employee, manager links, group memberships and money
totals; any difference cancels the whole copy. Passwords keep working (hashes are copied).
Sessions, content types and permissions are not copied; they are rebuilt, so users sign in
again once.

After the copy, check the site, then archive `legacy.sqlite3` and `db.sqlite3`.
**They contain real employee data: keep them out of Git and delete when no longer needed.**

## Backup and restore

Back up (custom format, compressed, no owner/privilege info so it restores anywhere):

    pg_dump "$DATABASE_URL" -Fc --no-owner --no-privileges -f hros_$(date +%F).dump

Restore into an **empty** database (create it first). `--exit-on-error` stops at the first
problem instead of leaving a half-restored database:

    createdb hros_restore
    pg_restore -d hros_restore --no-owner --no-privileges --exit-on-error hros_2026-10-18.dump

Then point `DATABASE_URL` at it and run `python manage.py check`. Verify a restore by
comparing row counts of `employee`, `attendance` and `auth_user` with the live database.

Backups contain salaries and personal data: store them encrypted, with restricted access,
and delete old ones according to your retention policy. Automated scheduling, retention
and restore drills are set up in the operations phase (Commit 13.3).

## What the database enforces by itself

Rules the database refuses to break even if application code is bypassed:

* one attendance row per employee per day; one salary row per employee per month
* unique employee numbers, department names/codes, schedule names
* salary, deductions and net pay cannot be negative
* a leave cannot end before it starts
* an employee cannot be their own manager
* the `is_active` flag always agrees with the employment status
* resigned/terminated/retired employees must have a separation date that is not before joining
* employees with attendance, leave or payroll history cannot be deleted (deactivate instead)
