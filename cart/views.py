from decimal import Decimal, InvalidOperation

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from website.models import Product
from .cart import Cart


def _get_valid_quantity(raw_value: str | None) -> Decimal:
    """
    Normalize quantity from POST data.
    """
    if raw_value is None:
        return Decimal("1")

    try:
        qty = Decimal(raw_value)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("1")

    if qty <= 0:
        return Decimal("1")

    return qty


@require_POST
def cart_add(request: HttpRequest, product_id: int) -> HttpResponse:
    """
    Add a product to the cart or update its quantity.
    """
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)

    raw_quantity = request.POST.get("quantity", "1")
    quantity = _get_valid_quantity(raw_quantity)

    # إذا جاي من صفحة السلة نرسل override=1 عشان يعدّل الكمية بدل ما يضيف عليها
    override = request.POST.get("override") == "1"

    cart.add(product, quantity=quantity, override_quantity=override)
    return redirect("cart:detail")


def cart_remove(request: HttpRequest, product_id: int) -> HttpResponse:
    """
    Remove a product completely from the cart.
    """
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)

    cart.remove(product)
    return redirect("cart:detail")


def cart_detail(request: HttpRequest) -> HttpResponse:
    """
    Display cart contents.
    """
    cart = Cart(request)
    context = {"cart": cart}
    return render(request, "cart/detail.html", context)
