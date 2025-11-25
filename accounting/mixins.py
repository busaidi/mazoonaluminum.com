# مثلاً في accounting/mixins.py

import json
from django.utils.safestring import mark_safe
from django.core.serializers.json import DjangoJSONEncoder

from inventory.models import Product


class ProductJsonMixin:
    """
    Provides products_json for JS in invoice/order forms.

    PRODUCTS = {
        "1": {
            "description": "...",
            "price": 12.345,        # from default_sale_price
            "uom_id": 3,            # base_uom
            "allowed_uoms": [3, 7], # base_uom + alt_uom (if any)
        },
        ...
    }
    """

    def _build_products_payload(self) -> dict:
        """
        Build a normalized mapping used by order/invoice JS.
        """
        products = (
            Product.objects
            .filter(is_active=True)
            .select_related("base_uom", "alt_uom")
        )

        data: dict[str, dict] = {}

        for p in products:
            # Prefer short_description, then description, then __str__
            description = (p.short_description or p.description or str(p)).strip()

            # Default sale price (internal)
            price = p.default_sale_price or 0

            # Base + alt UoM IDs
            base_id = p.base_uom_id
            alt_id = p.alt_uom_id

            allowed_uoms: list[int] = []
            if base_id:
                allowed_uoms.append(int(base_id))
            if alt_id and alt_id not in allowed_uoms:
                allowed_uoms.append(int(alt_id))

            data[str(p.id)] = {
                "description": description,
                "price": float(price),
                "uom_id": base_id,
                "allowed_uoms": allowed_uoms,
            }

        return data

    def get_products_json(self):
        """
        Legacy helper for older templates.
        """
        payload = self._build_products_payload()
        return mark_safe(json.dumps(payload, cls=DjangoJSONEncoder))

    def inject_products_json(self, ctx: dict) -> dict:
        """
        Main helper used in OrderCreateView.
        """
        ctx["products_json"] = json.dumps(
            self._build_products_payload(),
            cls=DjangoJSONEncoder,
        )
        return ctx
