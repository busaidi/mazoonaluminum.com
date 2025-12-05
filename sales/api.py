# sales/api.py

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from inventory.models import Product


# ============================================================
# Helpers (serializer-style) – DRF-like JSON
# ============================================================

def _uom_payload(uom):
    """
    Serialize a UnitOfMeasure instance into a small JSON payload.

    Structure:
    {
      "id": 1,
      "code": "M",
      "name": "Meter",
      "symbol": "m"  # optional
    }
    """
    if not uom:
        return None

    return {
        "id": uom.id,
        "code": getattr(uom, "code", None),
        "name": getattr(uom, "name", str(uom)),
        "symbol": getattr(uom, "symbol", None),
    }


def _serialize_product_list_item(product: Product) -> dict:
    """
    Minimal product representation for search/autocomplete.

    This is what will be used in:
      GET /sales/product/api/?q=...
    inside the "results" list.
    """
    return {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "short_description": product.short_description,
        "product_type": product.product_type,
        "product_type_display": product.get_product_type_display(),
        "is_active": product.is_active,
        "is_stock_item": product.is_stock_item,
        "default_sale_price": str(product.default_sale_price),
        "base_uom": _uom_payload(product.base_uom),
        "alt_uom": _uom_payload(product.alt_uom),
        "image_url": product.image_url,
    }


def _serialize_product_detail(product: Product) -> dict:
    """
    Full product details including UoMs and sale prices.

    This is what will be used in:
      GET /sales/product/api/<pk>/
    """

    # --- Base / alt prices using the existing domain logic ---
    base_price = product.get_price_for_uom(
        uom=product.base_uom,
        kind="sale",
    )

    alt_price = None
    if product.alt_uom and product.alt_factor:
        alt_price = product.get_price_for_uom(
            uom=product.alt_uom,
            kind="sale",
        )

    return {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "short_description": product.short_description,
        "description": product.description,
        "product_type": product.product_type,
        "product_type_display": product.get_product_type_display(),
        "is_active": product.is_active,
        "is_stock_item": product.is_stock_item,
        "is_published": product.is_published,

        # Units of measure
        "base_uom": _uom_payload(product.base_uom),
        "alt_uom": _uom_payload(product.alt_uom),
        "alt_factor": str(product.alt_factor or ""),

        # Pricing (base / cost)
        "default_sale_price": str(product.default_sale_price),
        "default_cost_price": str(product.default_cost_price),

        # Effective sale prices per UoM
        "base_price": str(base_price or ""),
        "alt_price": str(alt_price or ""),

        # Weight information
        "weight_uom": _uom_payload(product.weight_uom),
        "weight_per_base": (
            str(product.weight_per_base)
            if product.weight_per_base is not None
            else ""
        ),

        # Image
        "image_url": product.image_url,
    }


# ============================================================
# API endpoints – DRF-like shapes
# ============================================================

@require_GET
def product_api_search(request):
    """
    GET /sales/product/api/?q=MZN

    DRF-like paginated shape:
    {
      "count": 1,
      "next": null,
      "previous": null,
      "results": [ {product_list_item}, ... ]
    }
    """
    q = (request.GET.get("q") or "").strip()

    qs = Product.objects.filter(is_active=True)
    if q:
        qs = qs.filter(code__icontains=q)

    qs = qs.order_by("code")[:10]
    results = [_serialize_product_list_item(p) for p in qs]

    payload = {
        "count": len(results),
        "next": None,
        "previous": None,
        "results": results,
    }
    return JsonResponse(payload)


@require_GET
def product_api_uom(request, pk: int):
    """
    GET /sales/product/api/<pk>/

    Returns a single product JSON object with:
    - base/alt UoM
    - conversion factor
    - sale prices per UoM
    - weight info
    """
    product = get_object_or_404(Product, pk=pk, is_active=True)
    data = _serialize_product_detail(product)
    return JsonResponse(data)
