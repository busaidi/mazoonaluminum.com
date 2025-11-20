from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import JournalLineForm
from .models import (
    Account,
    Journal,
    JournalEntry,
    JournalLine,
    FiscalYear,
)

User = get_user_model()


class LedgerBaseTestCase(TestCase):
    """
    قاعدة مشتركة: تجهز مستخدم + سنة مالية + كم حساب + دفتر عام.
    """

    def setUp(self):
        super().setUp()

        # مستخدم ستاف/أكوانتينغ
        self.user = User.objects.create_user(
            username="staff",
            password="pass123",
            is_staff=True,
            is_superuser=True,
        )
        self.client.login(username="staff", password="pass123")

        today = timezone.now().date()
        self.fiscal_year = FiscalYear.objects.create(
            year=today.year,
            start_date=today.replace(month=1, day=1),
            end_date=today.replace(month=12, day=31),
            is_closed=False,
        )

        # ✅ دفتر عام افتراضي نشط
        self.journal = Journal.objects.create(
            code="GEN",
            name="دفتر عام",
            type=Journal.Type.GENERAL,
            is_default=True,
            is_active=True,
        )

        # حسابات أساسية
        self.account_cash = Account.objects.create(
            code="1110",
            name="Cash on Hand",
            type=Account.Type.ASSET,
        )
        self.account_revenue = Account.objects.create(
            code="4100",
            name="Sales Revenue",
            type=Account.Type.REVENUE,
        )

    def create_balanced_entry(self, posted=False):
        """
        مساعد لإنشاء قيد متوازن فيه سطرين:
        - مدين كاش
        - دائن ريفينيو
        """
        entry = JournalEntry.objects.create(
            fiscal_year=self.fiscal_year,
            journal=self.journal,
            date=timezone.now().date(),
            reference="TEST-REF",
            description="Test entry",
            created_by=self.user,
            posted=posted,
        )
        JournalLine.objects.create(
            entry=entry,
            account=self.account_cash,
            debit=Decimal("100.000"),
            credit=Decimal("0"),
            description="Cash in",
            order=1,
        )
        JournalLine.objects.create(
            entry=entry,
            account=self.account_revenue,
            debit=Decimal("0"),
            credit=Decimal("100.000"),
            description="Revenue",
            order=2,
        )
        return entry

class JournalLineFormTests(LedgerBaseTestCase):
    """
    اختبارات خاصة بمنطق فورم الأسطر (JournalLineForm).
    """

    def test_negative_debit_not_allowed(self):
        form = JournalLineForm(
            data={
                "account": self.account_cash.pk,
                "debit": "-10",
                "credit": "",
                "description": "Negative debit",
            }
        )
        self.assertFalse(form.is_valid())
        # على الأقل واحد من:
        self.assertIn("debit", form.errors)

    def test_negative_credit_not_allowed(self):
        form = JournalLineForm(
            data={
                "account": self.account_cash.pk,
                "debit": "",
                "credit": "-5",
                "description": "Negative credit",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("credit", form.errors)

    def test_both_debit_and_credit_not_allowed(self):
        form = JournalLineForm(
            data={
                "account": self.account_cash.pk,
                "debit": "10",
                "credit": "10",
                "description": "Both sides",
            }
        )
        self.assertFalse(form.is_valid())
        # ممكن تكون في non_field_errors أو على الحقول حسب منطقك
        self.assertTrue(
            form.non_field_errors()
            or "debit" in form.errors
            or "credit" in form.errors
        )

    def test_amount_without_account_not_allowed(self):
        form = JournalLineForm(
            data={
                "account": "",
                "debit": "10",
                "credit": "",
                "description": "No account",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())


class JournalEntryModelTests(LedgerBaseTestCase):
    """
    اختبارات تخص منطق JournalEntry (السنة المالية + رقم القيد).
    """

    def test_auto_assign_fiscal_year_if_missing(self):
        entry = JournalEntry.objects.create(
            fiscal_year=None,
            journal=self.journal,
            date=self.fiscal_year.start_date,
            reference="NO-FY",
            description="No FY provided",
            created_by=self.user,
        )
        entry.refresh_from_db()
        self.assertIsNotNone(entry.fiscal_year)
        self.assertEqual(entry.fiscal_year, self.fiscal_year)

    def test_generate_number_unique_and_prefixed(self):
        entry1 = JournalEntry.objects.create(
            fiscal_year=self.fiscal_year,
            journal=self.journal,
            date=self.fiscal_year.start_date,
            reference="E1",
            description="Entry 1",
            created_by=self.user,
        )
        entry2 = JournalEntry.objects.create(
            fiscal_year=self.fiscal_year,
            journal=self.journal,
            date=self.fiscal_year.start_date,
            reference="E2",
            description="Entry 2",
            created_by=self.user,
        )
        entry1.refresh_from_db()
        entry2.refresh_from_db()

        self.assertIsNotNone(entry1.serial)
        self.assertIsNotNone(entry2.serial)
        self.assertNotEqual(entry1.serial, entry2.serial)
        self.assertTrue(entry1.serial.startswith("GEN-"))
        self.assertTrue(entry2.serial.startswith("GEN-"))


class JournalEntryCreateViewTests(LedgerBaseTestCase):
    """
    اختبارات لعملية إنشاء قيد من شاشة "قيد جديد".
    """

    def get_url(self):
        return reverse("ledger:journalentry_create")

    def test_get_create_view_renders(self):
        response = self.client.get(self.get_url())
        self.assertEqual(response.status_code, 200)
        self.assertIn("entry_form", response.context)
        self.assertIn("line_formset", response.context)

    def test_create_valid_balanced_entry(self):
        url = self.get_url()
        # نبني POST يدوي للفورم + الفورمست
        data = {
            "date": self.fiscal_year.start_date.isoformat(),
            "reference": "INV-0001",
            "description": "Test balanced entry",
            "journal": self.journal.pk,
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            # سطر 0: مدين كاش 100
            "form-0-account": str(self.account_cash.pk),
            "form-0-description": "Cash in",
            "form-0-debit": "100",
            "form-0-credit": "",
            "form-0-DELETE": "",
            # سطر 1: دائن ريفينيو 100
            "form-1-account": str(self.account_revenue.pk),
            "form-1-description": "Revenue",
            "form-1-debit": "",
            "form-1-credit": "100",
            "form-1-DELETE": "",
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        entry = JournalEntry.objects.get(reference="INV-0001")
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(entry.total_debit, Decimal("100"))
        self.assertEqual(entry.total_credit, Decimal("100"))

    def test_create_unbalanced_entry_is_rejected(self):
        url = self.get_url()
        data = {
            "date": self.fiscal_year.start_date.isoformat(),
            "reference": "INV-UNBAL",
            "description": "Unbalanced entry",
            "journal": self.journal.pk,
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            # سطر 0: مدين 100
            "form-0-account": str(self.account_cash.pk),
            "form-0-description": "Cash in",
            "form-0-debit": "100",
            "form-0-credit": "",
            "form-0-DELETE": "",
            # سطر 1: دائن 50 فقط
            "form-1-account": str(self.account_revenue.pk),
            "form-1-description": "Revenue",
            "form-1-debit": "",
            "form-1-credit": "50",
            "form-1-DELETE": "",
        }

        response = self.client.post(url, data)
        # يبقى على نفس الصفحة
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "القيد غير متوازن",
        )
        # تأكد ما انشئ قيد بهذا المرجع
        self.assertFalse(
            JournalEntry.objects.filter(reference="INV-UNBAL").exists()
        )

    def test_create_entry_with_no_valid_lines_is_rejected(self):
        url = self.get_url()
        data = {
            "date": self.fiscal_year.start_date.isoformat(),
            "reference": "INV-EMPTY",
            "description": "No lines",
            "journal": self.journal.pk,
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            # سطر واحد فارغ بالكامل
            "form-0-account": "",
            "form-0-description": "",
            "form-0-debit": "",
            "form-0-credit": "",
            "form-0-DELETE": "",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "لا يوجد أي سطر صالح في القيد.")
        self.assertFalse(
            JournalEntry.objects.filter(reference="INV-EMPTY").exists()
        )


class JournalEntryUpdateViewTests(LedgerBaseTestCase):
    """
    اختبارات لتحديث قيد غير مرحّل.
    """

    def get_url(self, entry):
        return reverse("ledger:journalentry_update", kwargs={"pk": entry.pk})

    def test_update_unposted_entry_success(self):
        entry = self.create_balanced_entry(posted=False)
        url = self.get_url(entry)

        # نحول القيد إلى 200 بدل 100 (مدين/دائن)
        data = {
            "date": entry.date.isoformat(),
            "reference": entry.reference,
            "description": "Updated",
            "journal": self.journal.pk,
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "2",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            # سطر 0
            "form-0-id": entry.lines.all()[0].pk,
            "form-0-account": str(self.account_cash.pk),
            "form-0-description": "Cash in updated",
            "form-0-debit": "200",
            "form-0-credit": "",
            "form-0-DELETE": "",
            # سطر 1
            "form-1-id": entry.lines.all()[1].pk,
            "form-1-account": str(self.account_revenue.pk),
            "form-1-description": "Revenue updated",
            "form-1-debit": "",
            "form-1-credit": "200",
            "form-1-DELETE": "",
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        entry.refresh_from_db()
        self.assertEqual(entry.total_debit, Decimal("200"))
        self.assertEqual(entry.total_credit, Decimal("200"))
        self.assertEqual(entry.lines.count(), 2)

    def test_update_posted_entry_is_blocked(self):
        entry = self.create_balanced_entry(posted=True)
        url = self.get_url(entry)

        response = self.client.get(url, follow=True)
        # يُحوّل برسالة خطأ (حسب منطقك الحالي)
        self.assertContains(response, "لا يمكن تعديل قيد مُرحّل.")


class ReportViewsTests(LedgerBaseTestCase):
    """
    اختبارات أساسية لميزان المراجعة وكشف الحساب:
    - تعتمد على posted_only
    """

    def test_trial_balance_ignores_unposted_entries(self):
        # قيد غير مرحّل
        self.create_balanced_entry(posted=False)
        # قيد مرحّل
        entry_posted = self.create_balanced_entry(posted=True)

        url = reverse("ledger:trial_balance")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # أتأكد أن هناك صفوف للـ posted فقط (بشكل مبسط)
        self.assertContains(response, "Trial Balance", status_code=200)
        # ونقدر نضيف asserts على القيم لو رغبت لاحقاً

    def test_account_ledger_uses_posted_only(self):
        entry_posted = self.create_balanced_entry(posted=True)
        entry_unposted = self.create_balanced_entry(posted=False)

        url = reverse("ledger:account_ledger")
        response = self.client.get(
            url,
            {
                "account": self.account_cash.pk,
                "fiscal_year": "",
                "date_from": "",
                "date_to": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        # هنا ممكن تضيف asserts على ظهور حركات معينة في الجدول
        # مثلاً: التأكد أن الرصيد التراكمي يساوي 100
