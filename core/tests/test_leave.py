from datetime import date
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import Attendance, Employee, LeaveApplication
from core.services import leave as svc


class LeaveServiceTests(TestCase):
    def setUp(self):
        self.emp = Employee.objects.create(name="Ann", designation="Dev", basic_salary=Decimal("1000"))

    def req(self, **kw):
        base = dict(leave_type="CL", start_date=date(2026, 3, 2), end_date=date(2026, 3, 4), reason="r")
        base.update(kw)
        return base

    # --- validation ---
    def test_end_before_start_is_invalid(self):
        with self.assertRaisesMessage(ValidationError, "End date cannot be earlier"):
            svc.validate_leave_request(self.emp, "CL", date(2026, 3, 5), date(2026, 3, 4))

    def test_sick_leave_is_limited_to_one_day(self):
        with self.assertRaisesMessage(ValidationError, "strictly 1 day"):
            svc.validate_leave_request(self.emp, "SL", date(2026, 3, 2), date(2026, 3, 3))
        svc.validate_leave_request(self.emp, "SL", date(2026, 3, 2), date(2026, 3, 2))

    def test_sick_leave_monthly_quota_counts_only_approved_leave_in_that_month(self):
        LeaveApplication.objects.create(emp=self.emp, leave_type="SL", status="APPROVED",
                                        start_date=date(2026, 3, 10), end_date=date(2026, 3, 10), reason="x")
        with self.assertRaisesMessage(ValidationError, "March 2026"):
            svc.validate_leave_request(self.emp, "SL", date(2026, 3, 20), date(2026, 3, 20))
        svc.validate_leave_request(self.emp, "SL", date(2026, 4, 1), date(2026, 4, 1))  # next month is fine

    def test_multi_day_casual_leave_is_valid(self):
        svc.validate_leave_request(self.emp, "CL", date(2026, 3, 2), date(2026, 3, 20))

    # --- submit ---
    def test_submit_creates_pending_application_for_given_employee(self):
        leave = svc.submit_leave(self.emp, **self.req())
        self.assertEqual((leave.emp, leave.status), (self.emp, "PENDING"))

    def test_submit_revalidates(self):
        with self.assertRaises(ValidationError):
            svc.submit_leave(self.emp, **self.req(leave_type="SL"))
        self.assertFalse(LeaveApplication.objects.exists())

    # --- approve / reject ---
    def test_approve_marks_every_day_as_leave_and_overwrites_existing_punches(self):
        Attendance.objects.create(emp=self.emp, date=date(2026, 3, 3), status="P", check_in="09:00")
        leave = svc.submit_leave(self.emp, **self.req())
        svc.approve_leave(leave, "ok")
        days = Attendance.objects.filter(emp=self.emp).order_by("date")
        self.assertEqual([(a.date.day, a.status, a.check_in) for a in days],
                         [(2, "L", None), (3, "L", None), (4, "L", None)])
        leave.refresh_from_db()
        self.assertEqual((leave.status, leave.admin_note), ("APPROVED", "ok"))

    def test_reject_creates_no_attendance(self):
        leave = svc.submit_leave(self.emp, **self.req())
        svc.reject_leave(leave, "no")
        leave.refresh_from_db()
        self.assertEqual((leave.status, leave.admin_note), ("REJECTED", "no"))
        self.assertFalse(Attendance.objects.exists())

    def test_approval_is_all_or_nothing(self):
        leave = svc.submit_leave(self.emp, **self.req())
        real = Attendance.objects.update_or_create
        calls = {"n": 0}

        def flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("database went away")
            return real(*a, **kw)

        with mock.patch.object(Attendance.objects, "update_or_create", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                svc.approve_leave(leave)
        leave.refresh_from_db()
        self.assertEqual(leave.status, "PENDING")
        self.assertFalse(Attendance.objects.exists())
