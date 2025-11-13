from decimal import Decimal

from django.conf import settings
from website.models import Product


CART_SESSION_ID = getattr(settings, "CART_SESSION_ID", "cart")


class Cart:
    def __init__(self, request):
        self.session = request.session
        cart = self.session.get(CART_SESSION_ID)
        if not cart:
            cart = self.session[CART_SESSION_ID] = {}
        self.cart = cart

    def save(self):
        self.session[CART_SESSION_ID] = self.cart
        self.session.modified = True

    def add(self, product, quantity=1, override_quantity=False):
        product_id = str(product.id)
        if product_id not in self.cart:
            self.cart[product_id] = {
                "quantity": "0",
                "price": str(product.price or 0),
            }
        if override_quantity:
            self.cart[product_id]["quantity"] = str(quantity)
        else:
            current = Decimal(self.cart[product_id]["quantity"])
            self.cart[product_id]["quantity"] = str(current + Decimal(quantity))
        self.save()

    def remove(self, product):
        product_id = str(product.id)
        if product_id in self.cart:
            del self.cart[product_id]
            self.save()

    def clear(self):
        self.session[CART_SESSION_ID] = {}
        self.session.modified = True

    def __iter__(self):
        product_ids = self.cart.keys()
        products = Product.objects.filter(id__in=product_ids)

        cart = self.cart.copy()
        for product in products:
            item = cart[str(product.id)]
            item["product"] = product
            item["price"] = Decimal(item["price"])
            item["quantity"] = Decimal(item["quantity"])
            item["total_price"] = item["price"] * item["quantity"]
            yield item

    def __len__(self):
        return len(self.cart)

    def get_total_price(self):
        from decimal import Decimal as D
        return sum(D(i["price"]) * D(i["quantity"]) for i in self.cart.values())

    def is_empty(self):
        return len(self.cart) == 0
