from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Branch, Company, Division, Organization, Team


class OrganizationStructureTests(TestCase):
    def test_company_scoped_codes_and_hierarchy(self):
        organization = Organization.objects.create(name="Acme Group", code="ACME")
        company = Company.objects.create(organization=organization, name="Acme Nigeria", code="NG")
        branch = Branch.objects.create(company=company, name="Lagos", code="LOS")
        division = Division.objects.create(company=company, name="Operations", code="OPS")
        team = Team.objects.create(division=division, name="Support", code="SUP")

        self.assertEqual((branch.company, team.division.company), (company, company))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Company.objects.create(organization=organization, name="Duplicate", code="NG")
