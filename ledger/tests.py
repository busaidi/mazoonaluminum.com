# ledger/tests.py
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.db.models import Sum
from django.db.models.functions import Coalesce

from .models import FiscalYear, Account, JournalEntry, JournalLine
from .forms import AccountForm, JournalEntryForm, JournalLineForm

User = get_user_model()


class ModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
            is_staff=True,
        )

        self.fiscal_year = FiscalYear.objects.create(
            year=2024,
            start_date="2024-01-01",
            end_date="2024-12-31",
            is_closed=False,
        )

        self.asset_account = Account.objects.create(
            code="101",
            name="نقدية",
            type=Account.Type.ASSET,
            is_active=True,
        )

        self.liability_account = Account.objects.create(
            code="201",
            name="قروض",
            type=Account.Type.LIABILITY,
            is_active=True,
        )

    def test_fiscal_year_creation(self):
        """اختبار إنشاء سنة مالية"""
        self.assertEqual(self.fiscal_year.year, 2024)
        self.assertEqual(str(self.fiscal_year), "2024")

    def test_account_creation(self):
        """اختبار إنشاء حساب"""
        self.assertEqual(self.asset_account.code, "101")
        self.assertEqual(self.asset_account.type, Account.Type.ASSET)
        self.assertTrue(self.asset_account.is_active)

    def test_journal_entry_creation(self):
        """اختبار إنشاء قيد يومية"""
        entry = JournalEntry.objects.create(
            fiscal_year=self.fiscal_year,
            date="2024-01-15",
            reference="TEST001",
            description="قيد اختباري",
            created_by=self.user,
        )

        self.assertEqual(entry.reference, "TEST001")
        self.assertEqual(entry.created_by, self.user)
        self.assertFalse(entry.posted)

    def test_journal_line_creation(self):
        """اختبار إنشاء سطر في قيد اليومية"""
        entry = JournalEntry.objects.create(
            fiscal_year=self.fiscal_year,
            date="2024-01-15",
            created_by=self.user,
        )

        line = JournalLine.objects.create(
            entry=entry,
            account=self.asset_account,
            description="سطر اختباري",
            debit=Decimal("1000.000"),
            credit=Decimal("0.000"),
            order=1,
        )

        self.assertEqual(line.account, self.asset_account)
        self.assertEqual(line.debit, Decimal("1000.000"))
        self.assertEqual(line.credit, Decimal("0.000"))

    def test_journal_entry_totals(self):
        """اختبار حساب إجمالي المدين والدائن للقيد"""
        entry = JournalEntry.objects.create(
            fiscal_year=self.fiscal_year,
            date="2024-01-15",
            created_by=self.user,
        )

        JournalLine.objects.create(
            entry=entry,
            account=self.asset_account,
            debit=Decimal("500.000"),
            credit=Decimal("0.000"),
            order=1,
        )

        JournalLine.objects.create(
            entry=entry,
            account=self.liability_account,
            debit=Decimal("0.000"),
            credit=Decimal("500.000"),
            order=2,
        )

        self.assertEqual(entry.total_debit, Decimal("500.000"))
        self.assertEqual(entry.total_credit, Decimal("500.000"))
        self.assertTrue(entry.is_balanced)

    def test_fiscal_year_for_date(self):
        """اختبار إيجاد السنة المالية للتاريخ"""
        date_in_year = timezone.datetime(2024, 6, 1).date()
        fy = FiscalYear.for_date(date_in_year)
        self.assertEqual(fy, self.fiscal_year)

        date_outside = timezone.datetime(2023, 6, 1).date()
        fy = FiscalYear.for_date(date_outside)
        self.assertIsNone(fy)


class FormTests(TestCase):
    def setUp(self):
        self.asset_account = Account.objects.create(
            code="101",
            name="نقدية",
            type=Account.Type.ASSET,
        )

    def test_account_form_valid(self):
        """اختبار نموذج الحساب بصالح"""
        form_data = {
            "code": "102",
            "name": "بنك",
            "type": Account.Type.ASSET,
            "is_active": True,
        }
        form = AccountForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_account_form_invalid(self):
        """اختبار نموذج الحساب غير صالح"""
        form_data = {
            "code": "",
            "name": "",
            "type": "invalid_type",
        }
        form = AccountForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)
        self.assertIn("name", form.errors)
        self.assertIn("type", form.errors)

    def test_journal_entry_form_valid(self):
        """اختبار نموذج قيد اليومية صالح"""
        form_data = {
            "date": "2024-01-15",
            "reference": "TEST001",
            "description": "وصف اختباري",
        }
        form = JournalEntryForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_journal_line_form_valid(self):
        """اختبار نموذج سطر القيد صالح"""
        form_data = {
            "account": self.asset_account.id,
            "description": "سطر اختباري",
            "debit": "1000.000",
            "credit": "0.000",
        }
        form = JournalLineForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_journal_line_form_invalid_both_debit_credit(self):
        """اختبار نموذج سطر القيد غير صالح عند وجود مدين ودائن معاً"""
        form_data = {
            "account": self.asset_account.id,
            "debit": "1000.000",
            "credit": "1000.000",
        }
        form = JournalLineForm(data=form_data)
        self.assertFalse(form.is_valid())


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
            is_staff=True,
        )

        self.non_staff_user = User.objects.create_user(
            username="regularuser",
            password="testpass123",
            is_staff=False,
        )

        self.fiscal_year = FiscalYear.objects.create(
            year=2024,
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        self.asset_account = Account.objects.create(
            code="101",
            name="نقدية",
            type=Account.Type.ASSET,
        )

        self.liability_account = Account.objects.create(
            code="201",
            name="قروض",
            type=Account.Type.LIABILITY,
        )

    def test_dashboard_view_authenticated_staff(self):
        """اختبار لوحة التحكم للموظف المسجل"""
        self.client.login(username="testuser", password="testpass123")
        response = self.client.get(reverse("ledger:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ledger/dashboard.html")

    def test_dashboard_view_authenticated_non_staff(self):
        """اختبار لوحة التحكم لغير الموظف"""
        self.client.login(username="regularuser", password="testpass123")
        response = self.client.get(reverse("ledger:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_view_unauthenticated(self):
        """اختبار لوحة التحكم لغير المسجل"""
        response = self.client.get(reverse("ledger:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_account_list_view(self):
        """اختبار قائمة الحسابات"""
        self.client.login(username="testuser", password="testpass123")
        response = self.client.get(reverse("ledger:account_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ledger/accounts/list.html")
        self.assertContains(response, "نقدية")

    def test_account_create_view(self):
        """اختبار إنشاء حساب جديد"""
        self.client.login(username="testuser", password="testpass123")
        response = self.client.post(
            reverse("ledger:account_create"),
            {
                "code": "103",
                "name": "عملاء",
                "type": Account.Type.ASSET,
                "is_active": True,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Account.objects.filter(code="103").exists())

    def test_journal_entry_creation_flow(self):
        """اختبار سير عمل إنشاء قيد يومية"""
        self.client.login(username="testuser", password="testpass123")

        response = self.client.get(reverse("ledger:journalentry_create"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("ledger:journalentry_create"),
            {
                "date": "2024-01-15",
                "reference": "TEST001",
                "description": "قيد اختباري",
                "form-TOTAL_FORMS": "2",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-account": self.asset_account.id,
                "form-0-debit": "1000.000",
                "form-0-credit": "0.000",
                "form-1-account": self.liability_account.id,
                "form-1-debit": "0.000",
                "form-1-credit": "1000.000",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(JournalEntry.objects.filter(reference="TEST001").exists())

    def test_journal_entry_creation_unbalanced(self):
        """اختبار إنشاء قيد غير متوازن"""
        self.client.login(username="testuser", password="testpass123")

        response = self.client.post(
            reverse("ledger:journalentry_create"),
            {
                "date": "2024-01-15",
                "reference": "TEST002",
                "description": "قيد غير متوازن",
                "form-TOTAL_FORMS": "2",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-account": self.asset_account.id,
                "form-0-debit": "1000.000",
                "form-0-credit": "0.000",
                "form-1-account": self.liability_account.id,
                "form-1-debit": "0.000",
                "form-1-credit": "500.000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "غير متوازن")
        self.assertFalse(JournalEntry.objects.filter(reference="TEST002").exists())

    def test_trial_balance_report(self):
        """اختبار تقرير ميزان المراجعة"""
        self.client.login(username="testuser", password="testpass123")

        entry = JournalEntry.objects.create(
            fiscal_year=self.fiscal_year,
            date="2024-01-15",
            created_by=self.user,
        )
        JournalLine.objects.create(
            entry=entry,
            account=self.asset_account,
            debit=Decimal("1000.000"),
            credit=Decimal("0.000"),
            order=1,
        )

        response = self.client.get(reverse("ledger:trial_balance"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ledger/reports/trial_balance.html")

    def test_account_ledger_report(self):
        """اختبار تقرير كشف الحساب"""
        self.client.login(username="testuser", password="testpass123")

        response = self.client.get(reverse("ledger:account_ledger"))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            reverse("ledger:account_ledger") + f"?account={self.asset_account.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "نقدية")


class ReportLogicTests(TestCase):
    """اختبارات منطق التقارير"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
            is_staff=True,
        )

        self.fiscal_year = FiscalYear.objects.create(
            year=2024,
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        self.asset_account = Account.objects.create(
            code="101",
            name="نقدية",
            type=Account.Type.ASSET,
        )

        self.liability_account = Account.objects.create(
            code="201",
            name="قروض",
            type=Account.Type.LIABILITY,
        )

        entry1 = JournalEntry.objects.create(
            fiscal_year=self.fiscal_year,
            date="2024-01-15",
            created_by=self.user,
        )
        JournalLine.objects.create(
            entry=entry1,
            account=self.asset_account,
            debit=Decimal("2000.000"),
            credit=Decimal("0.000"),
            order=1,
        )
        JournalLine.objects.create(
            entry=entry1,
            account=self.liability_account,
            debit=Decimal("0.000"),
            credit=Decimal("2000.000"),
            order=2,
        )

        entry2 = JournalEntry.objects.create(
            fiscal_year=self.fiscal_year,
            date="2024-01-20",
            created_by=self.user,
        )
        JournalLine.objects.create(
            entry=entry2,
            account=self.asset_account,
            debit=Decimal("0.000"),
            credit=Decimal("500.000"),
            order=1,
        )
        JournalLine.objects.create(
            entry=entry2,
            account=self.liability_account,
            debit=Decimal("500.000"),
            credit=Decimal("0.000"),
            order=2,
        )

    def test_trial_balance_calculation(self):
        """اختبار حساب ميزان المراجعة"""
        lines = JournalLine.objects.select_related("account", "entry")
        lines = lines.filter(entry__fiscal_year=self.fiscal_year)

        balances = (
            lines.values("account__code", "account__name", "account__type")
            .annotate(
                debit=Coalesce(Sum("debit"), Decimal("0")),
                credit=Coalesce(Sum("credit"), Decimal("0")),
            )
            .order_by("account__code")
        )

        self.assertEqual(len(balances), 2)

        asset_balance = next(b for b in balances if b["account__code"] == "101")
        self.assertEqual(asset_balance["debit"], Decimal("2000.000"))
        self.assertEqual(asset_balance["credit"], Decimal("500.000"))

        liability_balance = next(b for b in balances if b["account__code"] == "201")
        self.assertEqual(liability_balance["debit"], Decimal("500.000"))
        self.assertEqual(liability_balance["credit"], Decimal("2000.000"))

    def test_account_ledger_balance_calculation(self):
        """اختبار حساب الرصيد في كشف الحساب"""
        lines = JournalLine.objects.filter(account=self.asset_account)

        totals = lines.aggregate(
            debit=Coalesce(Sum("debit"), Decimal("0")),
            credit=Coalesce(Sum("credit"), Decimal("0")),
        )
        balance = totals["debit"] - totals["credit"]
        self.assertEqual(balance, Decimal("1500.000"))

        lines_liability = JournalLine.objects.filter(account=self.liability_account)
        totals_liability = lines_liability.aggregate(
            debit=Coalesce(Sum("debit"), Decimal("0")),
            credit=Coalesce(Sum("credit"), Decimal("0")),
        )
        balance_liability = totals_liability["credit"] - totals_liability["debit"]
        self.assertEqual(balance_liability, Decimal("1500.000"))


class IntegrationTests(TestCase):
    """اختبارات التكامل"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
            is_staff=True,
        )
        self.client.login(username="testuser", password="testpass123")

        self.fiscal_year = FiscalYear.objects.create(
            year=2024,
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        self.asset_account = Account.objects.create(
            code="101",
            name="نقدية",
            type=Account.Type.ASSET,
        )

        self.expense_account = Account.objects.create(
            code="501",
            name="مرتبات",
            type=Account.Type.EXPENSE,
        )

    def test_complete_journal_workflow(self):
        """اختبار سير العمل الكامل للقيود"""
        response = self.client.post(
            reverse("ledger:journalentry_create"),
            {
                "date": "2024-01-15",
                "reference": "WORKFLOW001",
                "description": "قيد راتب",
                "form-TOTAL_FORMS": "2",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-account": self.asset_account.id,
                "form-0-debit": "0.000",
                "form-0-credit": "3000.000",
                "form-1-account": self.expense_account.id,
                "form-1-debit": "3000.000",
                "form-1-credit": "0.000",
            },
        )

        self.assertEqual(response.status_code, 302)
        entry = JournalEntry.objects.get(reference="WORKFLOW001")

        response = self.client.get(
            reverse("ledger:journalentry_detail", args=[entry.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "WORKFLOW001")

        response = self.client.get(reverse("ledger:journalentry_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "WORKFLOW001")

        response = self.client.get(reverse("ledger:trial_balance"))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            reverse("ledger:account_ledger") + f"?account={self.asset_account.id}"
        )
        self.assertEqual(response.status_code, 200)
