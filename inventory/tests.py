from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from inventory.models import (
    ProductCategory,
    Product,
    Warehouse,
    StockLocation,
    StockMove,
    StockLevel,
)
from inventory import services


class BaseInventoryTestCase(TestCase):
    def setUp(self):
        # Categories
        self.cat_main = ProductCategory.objects.create(
            slug="main-cat",
            name="Main Category",
        )
        self.cat_other = ProductCategory.objects.create(
            slug="other-cat",
            name="Other Category",
            is_active=False,
        )

        # Products
        self.product_active = Product.objects.create(
            category=self.cat_main,
            code="P-001",
            name="Active Product",
            short_description="Active product",
            uom="PCS",
            is_stock_item=True,
            is_active=True,
            is_published=True,
        )
        self.product_inactive = Product.objects.create(
            category=self.cat_main,
            code="P-002",
            name="Inactive Product",
            uom="PCS",
            is_stock_item=True,
            is_active=False,
            is_published=False,
        )
        self.product_unpublished = Product.objects.create(
            category=self.cat_main,
            code="P-003",
            name="Unpublished Product",
            uom="PCS",
            is_stock_item=True,
            is_active=True,
            is_published=False,
        )

        # Warehouses
        self.wh1 = Warehouse.objects.create(
            code="WH1",
            name="Main Warehouse",
        )
        self.wh2 = Warehouse.objects.create(
            code="WH2",
            name="Secondary Warehouse",
        )

        # Locations
        self.loc1 = StockLocation.objects.create(
            warehouse=self.wh1,
            code="LOC1",
            name="Location 1",
        )
        self.loc2 = StockLocation.objects.create(
            warehouse=self.wh2,
            code="LOC2",
            name="Location 2",
        )


class ProductModelHelpersTests(BaseInventoryTestCase):
    def test_total_on_hand_and_has_stock(self):
        # No stock yet
        self.assertEqual(self.product_active.total_on_hand, Decimal("0"))
        self.assertFalse(self.product_active.has_stock())

        # Create stock levels in two warehouses
        StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
            quantity_on_hand=Decimal("5.000"),
        )
        StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh2,
            location=self.loc2,
            quantity_on_hand=Decimal("3.000"),
        )

        self.assertEqual(self.product_active.total_on_hand, Decimal("8"))
        self.assertTrue(self.product_active.has_stock())
        self.assertTrue(self.product_active.has_stock(self.wh1))
        self.assertTrue(self.product_active.has_stock(self.wh2))

        # Check per-warehouse helper
        self.assertEqual(
            self.product_active.total_on_hand_in_warehouse(self.wh1),
            Decimal("5"),
        )
        self.assertEqual(
            self.product_active.total_on_hand_in_warehouse(self.wh2),
            Decimal("3"),
        )

    def test_low_stock_helpers(self):
        level_ok = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
            quantity_on_hand=Decimal("10.000"),
            min_stock=Decimal("5.000"),
        )
        level_low = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh2,
            location=self.loc2,
            quantity_on_hand=Decimal("2.000"),
            min_stock=Decimal("5.000"),
        )

        low_qs = self.product_active.low_stock_levels()
        self.assertIn(level_low, low_qs)
        self.assertNotIn(level_ok, low_qs)
        self.assertTrue(self.product_active.has_low_stock_anywhere)


class StockLevelHelpersTests(BaseInventoryTestCase):
    def test_is_below_min_property(self):
        # نحتاج ثلاثة مستويات لمواقع مختلفة (عشان unique_together)
        # loc1 موجودة من BaseInventoryTestCase (warehouse=wh1)
        # loc2 موجودة من BaseInventoryTestCase (warehouse=wh2)
        # ننشئ لوكيشن إضافي في wh1
        extra_loc = StockLocation.objects.create(
            warehouse=self.wh1,
            code="LOC-EXTRA",
            name="Extra Location",
        )

        # أقل من الحد الأدنى → True
        lvl1 = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
            quantity_on_hand=Decimal("2.000"),
            min_stock=Decimal("5.000"),
        )

        # أعلى من الحد الأدنى → False
        lvl2 = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh1,
            location=extra_loc,
            quantity_on_hand=Decimal("10.000"),
            min_stock=Decimal("5.000"),
        )

        # min_stock = 0 → نعتبره غير مفعّل → False حتى لو الكمية صفر
        lvl3 = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh2,
            location=self.loc2,
            quantity_on_hand=Decimal("0.000"),
            min_stock=Decimal("0.000"),
        )

        self.assertTrue(lvl1.is_below_min)
        self.assertFalse(lvl2.is_below_min)
        self.assertFalse(lvl3.is_below_min)



class StockMoveCleanAndPostingTests(BaseInventoryTestCase):
    def test_clean_requires_correct_fields_for_in_move(self):
        # Missing destination for IN move
        move = StockMove(
            product=self.product_active,
            move_type=StockMove.MoveType.IN,
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        with self.assertRaises(ValidationError):
            move.clean()

        # Having source for IN move is not allowed
        move = StockMove(
            product=self.product_active,
            move_type=StockMove.MoveType.IN,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            to_warehouse=self.wh1,
            to_location=self.loc1,
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        with self.assertRaises(ValidationError):
            move.clean()

        # Valid IN move
        move = StockMove(
            product=self.product_active,
            move_type=StockMove.MoveType.IN,
            to_warehouse=self.wh1,
            to_location=self.loc1,
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        # Should not raise
        move.clean()

    def test_clean_requires_correct_fields_for_out_move(self):
        # Missing source for OUT move
        move = StockMove(
            product=self.product_active,
            move_type=StockMove.MoveType.OUT,
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        with self.assertRaises(ValidationError):
            move.clean()

        # Having destination for OUT move is not allowed
        move = StockMove(
            product=self.product_active,
            move_type=StockMove.MoveType.OUT,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            to_warehouse=self.wh1,
            to_location=self.loc1,
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        with self.assertRaises(ValidationError):
            move.clean()

        # Valid OUT move
        move = StockMove(
            product=self.product_active,
            move_type=StockMove.MoveType.OUT,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        # Should not raise
        move.clean()

    def test_clean_requires_correct_fields_for_transfer_move(self):
        # Missing some fields
        move = StockMove(
            product=self.product_active,
            move_type=StockMove.MoveType.TRANSFER,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        with self.assertRaises(ValidationError):
            move.clean()

        # Location warehouse mismatch
        other_loc = StockLocation.objects.create(
            warehouse=self.wh1,
            code="OTHER",
            name="Other Location",
        )
        move = StockMove(
            product=self.product_active,
            move_type=StockMove.MoveType.TRANSFER,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            to_warehouse=self.wh2,
            to_location=other_loc,  # wrong warehouse for location
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        with self.assertRaises(ValidationError):
            move.clean()

        # Valid transfer
        move = StockMove(
            product=self.product_active,
            move_type=StockMove.MoveType.TRANSFER,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            to_warehouse=self.wh2,
            to_location=self.loc2,
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        move.clean()  # Should not raise

    def test_create_in_move_done_applies_stock(self):
        move = StockMove.objects.create(
            product=self.product_active,
            move_type=StockMove.MoveType.IN,
            to_warehouse=self.wh1,
            to_location=self.loc1,
            quantity=Decimal("10.000"),
            uom="PCS",
            status=StockMove.Status.DONE,
        )

        level = StockLevel.objects.get(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
        )
        self.assertEqual(level.quantity_on_hand, Decimal("10.000"))

        # Deleting the move should revert stock via signal
        move.delete()
        level.refresh_from_db()
        self.assertEqual(level.quantity_on_hand, Decimal("0.000"))

    def test_status_transitions_apply_and_revert_stock(self):
        # Start with IN move in DRAFT: should not affect stock
        move = StockMove.objects.create(
            product=self.product_active,
            move_type=StockMove.MoveType.IN,
            to_warehouse=self.wh1,
            to_location=self.loc1,
            quantity=Decimal("5.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        self.assertFalse(
            StockLevel.objects.filter(
                product=self.product_active,
                warehouse=self.wh1,
                location=self.loc1,
            ).exists()
        )

        # DRAFT -> DONE: apply +5
        move.status = StockMove.Status.DONE
        move.save()

        level = StockLevel.objects.get(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
        )
        self.assertEqual(level.quantity_on_hand, Decimal("5.000"))

        # DONE -> DRAFT: revert -5
        move.status = StockMove.Status.DRAFT
        move.save()
        level.refresh_from_db()
        self.assertEqual(level.quantity_on_hand, Decimal("0.000"))

        # DRAFT -> CANCELLED: no effect
        move.status = StockMove.Status.CANCELLED
        move.save()
        level.refresh_from_db()
        self.assertEqual(level.quantity_on_hand, Decimal("0.000"))

        # CANCELLED -> DONE: apply +5 again
        move.status = StockMove.Status.DONE
        move.save()
        level.refresh_from_db()
        self.assertEqual(level.quantity_on_hand, Decimal("5.000"))

        # DONE -> CANCELLED: revert -5
        move.status = StockMove.Status.CANCELLED
        move.save()
        level.refresh_from_db()
        self.assertEqual(level.quantity_on_hand, Decimal("0.000"))

    def test_transfer_move_moves_stock_between_locations(self):
        # First, create initial stock in wh1/loc1 via IN move DONE
        StockMove.objects.create(
            product=self.product_active,
            move_type=StockMove.MoveType.IN,
            to_warehouse=self.wh1,
            to_location=self.loc1,
            quantity=Decimal("10.000"),
            uom="PCS",
            status=StockMove.Status.DONE,
        )

        # Transfer 4 units from wh1/loc1 to wh2/loc2
        transfer = StockMove.objects.create(
            product=self.product_active,
            move_type=StockMove.MoveType.TRANSFER,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            to_warehouse=self.wh2,
            to_location=self.loc2,
            quantity=Decimal("4.000"),
            uom="PCS",
            status=StockMove.Status.DONE,
        )

        level_src = StockLevel.objects.get(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
        )
        level_dst = StockLevel.objects.get(
            product=self.product_active,
            warehouse=self.wh2,
            location=self.loc2,
        )

        self.assertEqual(level_src.quantity_on_hand, Decimal("6.000"))
        self.assertEqual(level_dst.quantity_on_hand, Decimal("4.000"))

        # Deleting the transfer should revert both sides
        transfer.delete()
        level_src.refresh_from_db()
        level_dst.refresh_from_db()
        self.assertEqual(level_src.quantity_on_hand, Decimal("10.000"))
        self.assertEqual(level_dst.quantity_on_hand, Decimal("0.000"))


class ReservationServicesTests(BaseInventoryTestCase):
    def setUp(self):
        super().setUp()
        # Start with some stock on hand
        self.level = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
            quantity_on_hand=Decimal("10.000"),
            quantity_reserved=Decimal("3.000"),
        )

    def test_reserve_stock_success(self):
        # Available = 10 - 3 = 7, reserve 4 -> success
        updated = services.reserve_stock_for_order(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
            quantity=Decimal("4.000"),
            allow_negative=False,
        )
        self.assertEqual(updated.quantity_reserved, Decimal("7.000"))

    def test_reserve_stock_not_enough_available_raises(self):
        # Available = 7 (from setUp), trying to reserve 20 should fail
        with self.assertRaises(ValidationError):
            services.reserve_stock_for_order(
                product=self.product_active,
                warehouse=self.wh1,
                location=self.loc1,
                quantity=Decimal("20.000"),
                allow_negative=False,
            )

    def test_reserve_stock_allow_negative(self):
        # Even if not enough available, allow_negative=True should pass
        updated = services.reserve_stock_for_order(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
            quantity=Decimal("20.000"),
            allow_negative=True,
        )
        # 3 + 20 = 23
        self.assertEqual(updated.quantity_reserved, Decimal("23.000"))

    def test_release_stock_reservation_success(self):
        # Release part of reserved
        updated = services.release_stock_reservation(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
            quantity=Decimal("2.000"),
        )
        self.assertEqual(updated.quantity_reserved, Decimal("1.000"))

    def test_release_more_than_reserved_raises(self):
        with self.assertRaises(ValidationError):
            services.release_stock_reservation(
                product=self.product_active,
                warehouse=self.wh1,
                location=self.loc1,
                quantity=Decimal("50.000"),
            )

    def test_release_when_no_level_raises(self):
        with self.assertRaises(ValidationError):
            services.release_stock_reservation(
                product=self.product_active,
                warehouse=self.wh2,
                location=self.loc2,
                quantity=Decimal("1.000"),
            )

    def test_get_available_stock(self):
        # From setUp: on_hand=10, reserved=3
        available = services.get_available_stock(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
        )
        self.assertEqual(available, Decimal("7.000"))

        # No level at wh2/loc2 -> 0
        self.assertEqual(
            services.get_available_stock(
                product=self.product_active,
                warehouse=self.wh2,
                location=self.loc2,
            ),
            Decimal("0.000"),
        )


class StockQueryHelpersTests(BaseInventoryTestCase):
    def setUp(self):
        super().setUp()
        # Levels for below_min tests
        self.lvl_ok = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
            quantity_on_hand=Decimal("10.000"),
            min_stock=Decimal("5.000"),
        )
        self.lvl_low = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc2,
            quantity_on_hand=Decimal("2.000"),
            min_stock=Decimal("5.000"),
        )

    def test_filter_below_min_stock_levels(self):
        qs = StockLevel.objects.all()
        below_qs = services.filter_below_min_stock_levels(qs)
        self.assertIn(self.lvl_low, below_qs)
        self.assertNotIn(self.lvl_ok, below_qs)

    def test_get_low_stock_total(self):
        total = services.get_low_stock_total()
        self.assertEqual(total, 1)

    def test_get_low_stock_levels_matches_filter(self):
        from_filter = set(
            services.filter_below_min_stock_levels(StockLevel.objects.all())
            .values_list("pk", flat=True)
        )
        from_helper = set(
            services.get_low_stock_levels().values_list("pk", flat=True)
        )
        self.assertEqual(from_filter, from_helper)

    def test_get_stock_summary_per_warehouse(self):
        # Add another level in wh2
        StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh2,
            location=self.loc2,
            quantity_on_hand=Decimal("3.000"),
        )

        summary = list(services.get_stock_summary_per_warehouse())
        # Expect two rows: one for WH1, one for WH2
        summary_by_code = {row["warehouse__code"]: row["total_qty"] for row in summary}
        self.assertEqual(summary_by_code["WH1"], Decimal("12.000"))
        self.assertEqual(summary_by_code["WH2"], Decimal("3.000"))


class FilterFunctionsTests(BaseInventoryTestCase):
    def test_filter_products_queryset(self):
        qs = Product.objects.all()

        # No filters returns all products
        all_qs = services.filter_products_queryset(qs)
        self.assertEqual(all_qs.count(), 3)

        # Search by code/name
        res = services.filter_products_queryset(qs, q="P-001")
        self.assertEqual(list(res), [self.product_active])

        # Filter by category
        res = services.filter_products_queryset(qs, category_id=self.cat_main.id)
        self.assertEqual(res.count(), 3)

        # Only published
        res = services.filter_products_queryset(qs, only_published=True)
        self.assertEqual(list(res), [self.product_active])

        # Combined: category + published + q
        res = services.filter_products_queryset(
            qs,
            q="Active",
            category_id=self.cat_main.id,
            only_published=True,
        )
        self.assertEqual(list(res), [self.product_active])

    def test_filter_stock_moves_queryset(self):
        # Prepare some moves
        move_in_done = StockMove.objects.create(
            product=self.product_active,
            move_type=StockMove.MoveType.IN,
            to_warehouse=self.wh1,
            to_location=self.loc1,
            quantity=Decimal("1.000"),
            uom="PCS",
            status=StockMove.Status.DONE,
            reference="REF-IN-1",
        )
        move_out_draft = StockMove.objects.create(
            product=self.product_active,
            move_type=StockMove.MoveType.OUT,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            quantity=Decimal("1.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
            reference="REF-OUT-1",
        )

        base_qs = StockMove.objects.all()

        # Filter by q (code / name / reference / warehouse codes)
        res = services.filter_stock_moves_queryset(
            base_qs,
            q="REF-IN-1",
        )
        self.assertEqual(list(res), [move_in_done])

        # Filter by move_type
        res = services.filter_stock_moves_queryset(
            base_qs,
            move_type=StockMove.MoveType.IN,
        )
        self.assertEqual(list(res), [move_in_done])

        res = services.filter_stock_moves_queryset(
            base_qs,
            move_type=StockMove.MoveType.OUT,
        )
        self.assertEqual(list(res), [move_out_draft])

        # Filter by status
        res = services.filter_stock_moves_queryset(
            base_qs,
            status=StockMove.Status.DONE,
        )
        self.assertEqual(list(res), [move_in_done])

        res = services.filter_stock_moves_queryset(
            base_qs,
            status=StockMove.Status.DRAFT,
        )
        self.assertEqual(list(res), [move_out_draft])

        # Combined filters
        res = services.filter_stock_moves_queryset(
            base_qs,
            q="REF-",
            move_type=StockMove.MoveType.OUT,
            status=StockMove.Status.DRAFT,
        )
        self.assertEqual(list(res), [move_out_draft])


class ManagersTests(BaseInventoryTestCase):
    def test_product_managers(self):
        # active() should return only active products
        active_qs = Product.objects.active()
        self.assertIn(self.product_active, active_qs)
        self.assertIn(self.product_unpublished, active_qs)
        self.assertNotIn(self.product_inactive, active_qs)

        # published() should return only active + is_published=True
        published_qs = Product.objects.published()
        self.assertEqual(list(published_qs), [self.product_active])

        # stock_items() should include only is_stock_item=True
        stock_items_qs = Product.objects.stock_items()
        self.assertEqual(stock_items_qs.count(), 3)

    def test_category_manager_active(self):
        active_cats = ProductCategory.objects.active()
        self.assertIn(self.cat_main, active_cats)
        self.assertNotIn(self.cat_other, active_cats)

    def test_stock_level_queryset_helpers(self):
        lvl1 = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh1,
            location=self.loc1,
            quantity_on_hand=Decimal("1.000"),
            min_stock=Decimal("5.000"),
        )
        lvl2 = StockLevel.objects.create(
            product=self.product_active,
            warehouse=self.wh2,
            location=self.loc2,
            quantity_on_hand=Decimal("10.000"),
            min_stock=Decimal("5.000"),
        )

        below_qs = StockLevel.objects.below_min()
        self.assertIn(lvl1, below_qs)
        self.assertNotIn(lvl2, below_qs)

        self.assertEqual(
            list(StockLevel.objects.for_warehouse(self.wh1)),
            [lvl1],
        )
        self.assertEqual(
            list(StockLevel.objects.for_product(self.product_active).order_by("warehouse__code")),
            [lvl1, lvl2],
        )

    def test_stock_move_queryset_helpers(self):
        move_in = StockMove.objects.create(
            product=self.product_active,
            move_type=StockMove.MoveType.IN,
            to_warehouse=self.wh1,
            to_location=self.loc1,
            quantity=Decimal("1.000"),
            uom="PCS",
            status=StockMove.Status.DONE,
        )
        move_out = StockMove.objects.create(
            product=self.product_active,
            move_type=StockMove.MoveType.OUT,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            quantity=Decimal("1.000"),
            uom="PCS",
            status=StockMove.Status.DRAFT,
        )
        move_transfer = StockMove.objects.create(
            product=self.product_active,
            move_type=StockMove.MoveType.TRANSFER,
            from_warehouse=self.wh1,
            from_location=self.loc1,
            to_warehouse=self.wh2,
            to_location=self.loc2,
            quantity=Decimal("1.000"),
            uom="PCS",
            status=StockMove.Status.DONE,
        )

        self.assertEqual(list(StockMove.objects.incoming()), [move_in])
        self.assertEqual(list(StockMove.objects.outgoing()), [move_out])
        self.assertEqual(list(StockMove.objects.transfers()), [move_transfer])

        self.assertEqual(
            list(StockMove.objects.for_product(self.product_active).order_by("id")),
            [move_in, move_out, move_transfer],
        )

        # for_warehouse: WH1 appears as source or destination
        for_wh1 = list(StockMove.objects.for_warehouse(self.wh1).order_by("id"))
        self.assertEqual(for_wh1, [move_in, move_out, move_transfer])

        # for_warehouse: WH2 appears only as destination in transfer
        for_wh2 = list(StockMove.objects.for_warehouse(self.wh2))
        self.assertEqual(for_wh2, [move_transfer])
