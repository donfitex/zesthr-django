-- PayTrack database (SQLite syntax; works in MySQL/PostgreSQL with small type changes).
-- Django creates these same tables via `python manage.py migrate`; this file is the standalone SQL deliverable.

CREATE TABLE IF NOT EXISTS employee (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          VARCHAR(100)  NOT NULL,
    designation   VARCHAR(100)  NOT NULL,
    basic_salary  DECIMAL(10,2) NOT NULL,
    email         VARCHAR(254)  NOT NULL DEFAULT '',
    phone         VARCHAR(20)   NOT NULL DEFAULT '',
    joined_on     DATE          NOT NULL,
    is_active     BOOLEAN       NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_id     INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    date       DATE    NOT NULL,
    check_in   TIME,
    check_out  TIME,
    status     CHAR(1) NOT NULL DEFAULT 'P' CHECK (status IN ('P','A','H','L')),  -- Present/Absent/Half/Leave
    UNIQUE (emp_id, date)
);

CREATE TABLE IF NOT EXISTS salary (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_id        INTEGER NOT NULL REFERENCES employee(id) ON DELETE CASCADE,
    month         SMALLINT      NOT NULL,
    year          SMALLINT      NOT NULL,
    absent_days   DECIMAL(5,2)  NOT NULL DEFAULT 0,
    per_day_pay   DECIMAL(10,2) NOT NULL DEFAULT 0,
    gross         DECIMAL(10,2) NOT NULL,
    deduction     DECIMAL(10,2) NOT NULL DEFAULT 0,
    net           DECIMAL(10,2) NOT NULL,
    generated_on  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (emp_id, month, year)
);

-- Sample data
INSERT INTO employee (name, designation, basic_salary, joined_on) VALUES
 ('Asha Verma','Accountant',32000,'2025-01-10'),
 ('Ravi Kumar','Developer',55000,'2025-02-01'),
 ('Meena Rao','HR Executive',38000,'2025-03-15');

INSERT INTO attendance (emp_id, date, check_in, check_out, status) VALUES
 (1,'2026-10-01','09:05','17:30','P'), (1,'2026-10-02',NULL,NULL,'A'), (1,'2026-10-03','09:10','13:00','H'),
 (2,'2026-10-01','09:00','17:45','P'), (2,'2026-10-02','09:12','17:40','P'), (2,'2026-10-03',NULL,NULL,'L'),
 (3,'2026-10-01','09:20','17:35','P'), (3,'2026-10-02',NULL,NULL,'A'), (3,'2026-10-03',NULL,NULL,'A');

-- Monthly attendance report (GROUP BY)
SELECT e.name,
       SUM(a.status = 'P') AS present_days,
       SUM(a.status = 'H') AS half_days,
       SUM(a.status = 'L') AS leave_days,
       SUM(a.status = 'A') AS absent_days
FROM employee e LEFT JOIN attendance a
  ON a.emp_id = e.id AND strftime('%m', a.date) = '10' AND strftime('%Y', a.date) = '2026'
GROUP BY e.id, e.name;

-- Salary: net = basic - (absent_days x per_day_pay), 31 days in October
INSERT INTO salary (emp_id, month, year, absent_days, per_day_pay, gross, deduction, net)
SELECT e.id, 10, 2026,
       SUM(a.status = 'A') + SUM(a.status = 'H') / 2.0,
       ROUND(e.basic_salary / 31.0, 2),
       e.basic_salary,
       ROUND((SUM(a.status = 'A') + SUM(a.status = 'H') / 2.0) * ROUND(e.basic_salary / 31.0, 2), 2),
       e.basic_salary - ROUND((SUM(a.status = 'A') + SUM(a.status = 'H') / 2.0) * ROUND(e.basic_salary / 31.0, 2), 2)
FROM employee e LEFT JOIN attendance a
  ON a.emp_id = e.id AND strftime('%m', a.date) = '10' AND strftime('%Y', a.date) = '2026'
GROUP BY e.id;
