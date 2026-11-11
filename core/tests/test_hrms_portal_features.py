from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization, OrganizationMembership
from core import roles, selectors
from core.models import Department, Employee, JobPosition, Salary, WorkSchedule


class HRMSPortalFeaturesTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme Corp", code="ACME")
        self.schedule = WorkSchedule.objects.create(
            organization=self.org,
            name="General 9-5",
            start_time="09:00",
            end_time="17:00",
            is_default=True,
        )
        self.dept = Department.objects.create(
            organization=self.org,
            name="Engineering",
            code="ENG",
            work_schedule=self.schedule,
        )
        self.pos = JobPosition.objects.create(
            organization=self.org,
            title="Software Engineer",
            department=self.dept,
        )

        # Admin / HR user
        self.hr_user = User.objects.create_user(
            username="hr_officer",
            email="hr@example.com",
            password="TestPassword123!",
            is_staff=True,
        )
        OrganizationMembership.objects.create(user=self.hr_user, organization=self.org, is_active=True)
        # Give HR user all required permissions
        for perm in [
            roles.VIEW_EMPLOYEE, roles.ADD_EMPLOYEE, roles.CHANGE_EMPLOYEE,
            roles.VIEW_ALL_ATTENDANCE, roles.MARK_ATTENDANCE,
            roles.VIEW_ALL_LEAVES, roles.APPROVE_LEAVE,
            roles.VIEW_PAYROLL_REPORT, roles.VIEW_ALL_PAYSLIPS,
            roles.CHANGE_EMPLOYEE_PAY,
        ]:
            app_label, codename = perm.split(".")
            self.hr_user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))

        # Employee 1: Birthday today
        today = date.today()
        bday_date = date(1995, today.month, today.day)
        join_date_old = date(today.year - 3, today.month, today.day)

        self.emp1 = Employee.objects.create(
            organization=self.org,
            name="Alice Smith",
            date_of_birth=bday_date,
            joined_on=join_date_old,
            department=self.dept,
            position=self.pos,
            designation="Software Engineer",
            basic_salary=Decimal("50000.00"),
            employment_status="ACTIVE",
            is_active=True,
        )

        # Employee 2: Neither birthday nor anniversary today
        other_month = 1 if today.month != 1 else 2
        self.emp2 = Employee.objects.create(
            organization=self.org,
            name="Bob Jones",
            date_of_birth=date(1990, other_month, 15),
            joined_on=date(today.year, other_month, 1),
            department=self.dept,
            position=self.pos,
            designation="DevOps Engineer",
            basic_salary=Decimal("60000.00"),
            employment_status="ACTIVE",
            is_active=True,
        )

    def test_highlights_today_selector(self):
        today = date.today()
        highlights = selectors.highlights_today(today, user=self.hr_user)
        self.assertTrue(highlights["has_highlights"])

        # Check birthdays
        bday_names = [b["employee"].name for b in highlights["birthdays"]]
        self.assertIn("Alice Smith", bday_names)
        self.assertNotIn("Bob Jones", bday_names)

        # Check anniversaries (Alice joined 3 years ago today)
        anniv_names = [a["employee"].name for a in highlights["anniversaries"]]
        self.assertIn("Alice Smith", anniv_names)
        self.assertNotIn("Bob Jones", anniv_names)
        alice_anniv = [a for a in highlights["anniversaries"] if a["employee"].name == "Alice Smith"][0]
        self.assertEqual(alice_anniv["years"], 3)
        self.assertIn("3rd Anniversary", alice_anniv["milestone"])

    def test_dashboard_view_renders_highlights_and_stats(self):
        self.client.force_login(self.hr_user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HRMS Dashboard")
        self.assertContains(response, "Celebrations")
        self.assertContains(response, "Alice Smith")
        self.assertContains(response, "Total Employees")

    def test_department_management_crud(self):
        self.client.force_login(self.hr_user)

        # List
        list_url = reverse("department_list")
        resp = self.client.get(list_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Engineering")

        # Create
        add_url = reverse("department_add")
        resp_post = self.client.post(add_url, {
            "name": "Finance",
            "code": "FIN",
            "work_schedule": self.schedule.pk,
            "is_active": True,
        })
        self.assertRedirects(resp_post, list_url)
        self.assertTrue(Department.objects.filter(code="FIN", organization=self.org).exists())

        # Update
        fin_dept = Department.objects.get(code="FIN")
        edit_url = reverse("department_edit", args=[fin_dept.pk])
        resp_edit = self.client.post(edit_url, {
            "name": "Finance & Accounting",
            "code": "FIN",
            "work_schedule": self.schedule.pk,
            "is_active": True,
        })
        self.assertRedirects(resp_edit, list_url)
        fin_dept.refresh_from_db()
        self.assertEqual(fin_dept.name, "Finance & Accounting")

    def test_designation_management_crud(self):
        self.client.force_login(self.hr_user)

        # List
        list_url = reverse("designation_list")
        resp = self.client.get(list_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Software Engineer")

        # Create
        add_url = reverse("designation_add")
        resp_post = self.client.post(add_url, {
            "title": "Product Manager",
            "department": self.dept.pk,
            "is_active": True,
        })
        self.assertRedirects(resp_post, list_url)
        self.assertTrue(JobPosition.objects.filter(title="Product Manager", organization=self.org).exists())

        # Update
        pm = JobPosition.objects.get(title="Product Manager")
        edit_url = reverse("designation_edit", args=[pm.pk])
        resp_edit = self.client.post(edit_url, {
            "title": "Senior Product Manager",
            "department": self.dept.pk,
            "is_active": True,
        })
        self.assertRedirects(resp_edit, list_url)
        pm.refresh_from_db()
        self.assertEqual(pm.title, "Senior Product Manager")

    def test_payslip_download_view(self):
        self.client.force_login(self.hr_user)
        salary = Salary.objects.create(
            emp=self.emp1,
            month=date.today().month,
            year=date.today().year,
            gross=Decimal("50000.00"),
            deduction=Decimal("2000.00"),
            net=Decimal("48000.00"),
            per_day_pay=Decimal("1666.67"),
            absent_days=Decimal("0.00"),
        )

        url = reverse("slip_download", args=[salary.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment; filename=", resp["Content-Disposition"])
        self.assertContains(resp, "Alice Smith")
        self.assertContains(resp, "48000.00")
