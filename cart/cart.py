# /home/ubuntu/Documents/mazoonaluminum.com/cart/cart.py
from decimal import Decimal
from typing import Dict, Iterator, Any

from django.conf import settings
from website.models import Product

# Session key used to store the cart
CART_SESSION_ID = getattr(settings, "CART_SESSION_ID", "cart")


class Cart:
    """
    Session-based shopping cart.

    Structure in session:
    {
        "<product_id>": {
            "quantity": "<decimal_as_string>",
            "price": "<decimal_as_string>",
        },
        ...
    }
    """

    def __init__(self, request):
        """
        Initialize the cart from the current session.
        """
        self.session = request.session
        cart = self.session.get(CART_SESSION_ID)

        # Ensure cart is always a dict
        if not isinstance(cart, dict):
            cart = {}
            self.session[CART_SESSION_ID] = cart

        self.cart: Dict[str, Dict[str, str]] = cart

    # -----------------
    # Internal helpers
    # -----------------
    def _save(self) -> None:
        """Persist cart into the session."""
        self.session[CART_SESSION_ID] = self.cart
        self.session.modified = True

    def _ensure_item(self, product: Product) -> Dict[str, str]:
        """
        Ensure a cart line exists for the product and return it.
        Does NOT change quantity, only initializes the line if missing.
        """
        product_id = str(product.id)
        item = self.cart.get(product_id)

        if item is None:
            item = {
                "quantity": "0",  # stored as string for JSON serializability
                "price": str(product.price or Decimal("0")),
            }
            self.cart[product_id] = item

        return item

    # -----------------
    # Public API
    # -----------------
    def save(self) -> None:
        """
        Backwards-compatible public save method.
        Delegates to the internal _save().
        """
        self._save()

    def add(self, product: Product, quantity: int = 1, override_quantity: bool = False) -> None:
        """
        Add a product to the cart or update its quantity.

        :param product: Product instance
        :param quantity: Quantity to add or set
        :param override_quantity: If True, quantity will be replaced instead of incremented
        """
        product_id = str(product.id)
        item = self._ensure_item(product)

        if override_quantity:
            # Keep behavior: store quantity exactly as provided
            item["quantity"] = str(quantity)
        else:
            current_qty = Decimal(item["quantity"])
            item["quantity"] = str(current_qty + Decimal(quantity))

        self._save()

    def remove(self, product: Product) -> None:
        """
        Remove a product from the cart (if it exists).
        """
        product_id = str(product.id)
        if product_id in self.cart:
            del self.cart[product_id]
            self._save()

    def clear(self) -> None:
        """
        Remove the cart completely from the session.
        """
        self.session[CART_SESSION_ID] = {}
        self.session.modified = True
        # Also keep internal reference in sync
        self.cart = {}

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        """
        Iterate over the items in the cart, attaching Product instances
        and computed total_price for each line.
        """
        product_ids = self.cart.keys()
        products = Product.objects.filter(id__in=product_ids)

        # Build a map for faster lookup
        products_map = {str(p.id): p for p in products}

        # Use a shallow copy so we don't mutate self.cart directly
        cart_copy = self.cart.copy()

        for product_id, data in cart_copy.items():
            product = products_map.get(product_id)
            if not product:
                # Product may have been deleted from DB; skip silently
                continue

            price = Decimal(data["price"])
            quantity = Decimal(data["quantity"])

            yield {
                "product": product,
                "price": price,
                "quantity": quantity,
                "total_price": price * quantity,
            }

    def __len__(self) -> int:
        """
        Return the number of distinct products in the cart.
        (Keeps existing behavior for backward compatibility.)
        """
        return len(self.cart)

    def get_total_price(self) -> Decimal:
        """
        Return total cart value as a Decimal.
        """
        return sum(
            Decimal(item["price"]) * Decimal(item["quantity"])
            for item in self.cart.values()
        )

    def is_empty(self) -> bool:
        """
        Check if the cart has no items.
        """
        return len(self.cart) == 0

    # Optional convenience method (doesn't break anything else)
    def get_total_quantity(self) -> Decimal:
        """
        Return total quantity of all items in the cart.
        (Not used elsewhere; safe addition.)
        """
        return sum(Decimal(item["quantity"]) for item in self.cart.values())
