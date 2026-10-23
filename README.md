# HROS: Human Resources Operating System (Django)

Track daily attendance and generate monthly salary slips with automated loss-of-pay deductions.
Stack: Python, Django, PostgreSQL in production (Supabase), SQLite for local development, HTML, CSS.

## Run it
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations core
python manage.py migrate
python manage.py runserver
```
Open http://127.0.0.1:8000/ to explore the **HROS Home Page** and sign in.

### Sample data (local development only)

The optional `seed_demo` command creates test accounts with known passwords. It is guarded by `DEBUG=True`; use it only in a disposable local development database, never in production. The command is not run automatically. Do not expose demo credentials or seed demo users into the production Supabase database.

## Modules & Features
- **Home**: Product landing page with HROS brand logo, feature highlights, live architecture preview, interactive payroll calculator, and credentials sandbox.
- **Role-Based Portals**:
  - **Employee Portal**: Dedicated self-service dashboard with real-time punch card (Check-In & Check-Out), 1-per-month sick leave quota balance meter, upcoming Indian holiday reminder, personal attendance history, and salary slips.
  - **HR Admin Portal**: Company-wide stats, employee management, manual attendance marking, leave approval queue, and monthly payroll generation.
- **Daily Attendance**: Self check-in / check-out with automatic timestamps; admin bulk management for Present (P), Absent (A), Half-Day (H), and Leave (L).
- **Indian Government Holidays 🇮🇳**: Complete 2026 official calendar categorized into Gazetted (mandatory off) and Restricted / Optional holidays with contextual significance badges.
- **Leave Management & 1 Sick Leave / Month Rule**:
  - Apply Leave interface with form validation enforcing **strictly 1 Sick Leave per calendar month** (maximum 1 day duration per application, strictly non-cumulative).
  - Also supports Casual Leave (CL) and Paid Leave (PL).
  - Admin approval/rejection pipeline: Approved leaves automatically record Paid Leave (`L`) in daily attendance without salary penalty.
- **Payroll & Deductions**: Loss-of-pay calculations, salary register generation, and printable individual salary slips.
- Light/dark theme toggle, responsive mobile navigation, and print-ready stylesheet.

## Salary formula
`per_day_pay = basic / days in month`  
`absent_days = absent + half-days / 2` (approved leave `L` is fully exempt from deduction)  
`net = basic - (absent_days x per_day_pay)`  

## Deployment layout

The repository root must contain `manage.py`, `requirements.txt`, `vercel.json`, `api/index.py`, and the `payroll_project/` and `core/` packages. In Vercel, set the project Root Directory to the directory containing `vercel.json` and `manage.py` (normally `.`). Push changes to the configured Git branch, then redeploy the new commit. If the deployment still serves old templates, inspect the deployment commit SHA and use **Redeploy without Build Cache**.

## Files
- `core/models.py`: Employee, Attendance, Salary, Holiday, LeaveApplication
- `core/forms.py`: Employee, Attendance, and LeaveApplicationForm with sick leave quota validation
- `core/views.py`: Role-scoped dashboards, attendance check-in/out, holiday calendar, and leave approvals
- `core/templates/`: `employee_dashboard.html`, `dashboard.html`, `holidays.html`, `leaves_list.html`, `leave_apply.html`, `home.html`, etc.
- `core/static/css/style.css`: HROS design system, color tokens, and responsive layout

