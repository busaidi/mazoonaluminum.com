from decimal import Decimal

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from website.models import Product
from .cart import Cart


@require_POST
def cart_add(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)

    qty_str = request.POST.get("quantity", "1")
    try:
        quantity = Decimal(qty_str)
        if quantity <= 0:
            quantity = Decimal("1")
    except Exception:
        quantity = Decimal("1")

    cart.add(product, quantity=quantity)
    return redirect("cart:detail")


def cart_remove(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)
    return redirect("cart:detail")


def cart_detail(request):
    cart = Cart(request)
    return render(request, "cart/detail.html", {"cart": cart})
