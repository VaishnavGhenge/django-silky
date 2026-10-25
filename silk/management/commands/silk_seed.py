"""Generate synthetic production traffic for a fictional Django kitchenware shop.

    DB_ENGINE=sqlite3 .venv/bin/python project/manage.py silk_seed --clear --requests 1000 --seed 42

The records simulate a storefront API, cart and checkout, customer accounts, the
Django admin, payment webhooks and a staff sales report. They do not replay HTTP
requests, and the application modules named in tracebacks do not exist on disk.
"""

import json
import math
import random
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from silk import models

APP_ROOT = Path("/srv/harbor/shop")
SITE_PACKAGES = Path("/srv/harbor/.venv/lib/python3.12/site-packages")

CATEGORIES = {1: "Cookware", 2: "Knives", 3: "Tableware", 4: "Kitchen textiles", 5: "Storage", 6: "Coffee & tea"}
_PRODUCTS = [
    ("Cast Iron Skillet 26 cm", 1, 4990), ("Enamelled Dutch Oven 24 cm", 1, 12900),
    ("Carbon Steel Wok 32 cm", 1, 5490), ("Stainless Saucepan 18 cm", 1, 3990),
    ("Non-stick Frying Pan 28 cm", 1, 3490), ("Chef's Knife 21 cm", 2, 8900),
    ("Paring Knife 9 cm", 2, 2490), ("Bread Knife 23 cm", 2, 4490),
    ("Whetstone 1000/6000", 2, 3990), ("Magnetic Knife Rack 40 cm", 2, 2990),
    ("Stoneware Dinner Plate 27 cm", 3, 1490), ("Stoneware Bowl 15 cm", 3, 1190),
    ("Tumbler Glass 30 cl, set of 6", 3, 2490), ("Oak Serving Board", 3, 3990),
    ("Linen Tea Towel", 4, 1290), ("Waxed Canvas Apron", 4, 4490),
    ("Oven Glove Pair", 4, 1890), ("Linen Napkins, set of 4", 4, 2690),
    ("Glass Storage Jar 1 l", 5, 990), ("Beeswax Wraps, set of 3", 5, 1590),
    ("Stackable Lunch Box", 5, 2290), ("Bamboo Bread Bin", 5, 3490),
    ("Pour-over Dripper", 6, 2490), ("Gooseneck Kettle 1 l", 6, 6490),
    ("Hand Coffee Grinder", 6, 7990), ("French Press 8 Cup", 6, 3490),
    ("Loose-leaf Tea Infuser", 6, 890),
]
PRODUCTS = [
    {"id": pk, "slug": "-".join(name.lower().replace(",", "").replace("'", "").replace("/", "-").split()),
     "name": name, "category_id": cat, "price_cents": price}
    for pk, (name, cat, price) in enumerate(_PRODUCTS, 101)
]
SEARCH_TERMS = ["skillet", "linen", "knife", "stoneware", "kettle", "oak", "grinder", "jar", "wok",
                "apron", "cast iron", "bread", "pan", "glass", "teapot", "dutch oven"]
FIRST_NAMES = ["ines", "lars", "fatima", "jonas", "sofie", "mehmet", "elena", "pieter", "amira", "tom",
               "noor", "lucas", "hanna", "youssef", "marie", "wout", "chloe", "arjun", "lotte", "sam"]
LAST_NAMES = ["peeters", "jansen", "elamrani", "maes", "dubois", "devries", "yilmaz", "claes",
              "novak", "bakker", "martin", "wouters", "rossi", "hendriks", "nguyen"]
LANGUAGES = ["nl-BE,nl;q=0.9,en;q=0.8", "en-GB,en;q=0.9", "fr-BE,fr;q=0.9,en;q=0.7", "de-DE,de;q=0.9,en;q=0.8"]
BROWSERS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "HarborShop/4.12.0 (iOS 18.0; iPhone15,2)", "HarborShop/4.11.3 (Android 14; SM-S918B)",
]
# Relative traffic by hour of day (UTC) for a shop selling mostly in Belgium and the Netherlands.
HOURLY = [0.15, 0.1, 0.08, 0.07, 0.08, 0.15, 0.35, 0.6, 0.8, 0.9, 0.95, 1.0,
          1.0, 0.95, 0.9, 0.9, 0.95, 1.0, 1.1, 1.25, 1.3, 1.1, 0.7, 0.35]

# Call sites, outermost first. Paths under django/ live in site-packages, the rest in the app.
WHERE = {
    "health": [("core/views.py", 18, "healthz", 'cursor.execute("SELECT 1")')],
    "session": [("django/contrib/sessions/backends/db.py", 49, "_get_session_from_db", "return self.model.objects.get(")],
    "customer": [("accounts/middleware.py", 24, "__call__", 'request.customer = Customer.objects.get(pk=request.session["customer_id"])')],
    "categories": [("catalog/views.py", 22, "category_list", "categories = list(Category.objects.filter(is_active=True).order_by(\"position\"))")],
    "products.count": [("catalog/views.py", 47, "product_list", 'page = paginator.get_page(request.GET.get("page"))')],
    "products.page": [("catalog/views.py", 48, "product_list", "data = [serialize_product(p) for p in page]")],
    "product.get": [("catalog/views.py", 63, "product_detail", 'product = get_object_or_404(Product.objects.select_related("category"), slug=slug, is_active=True)')],
    "product.variants": [("catalog/views.py", 64, "product_detail", "variants = list(product.variants.filter(is_active=True))")],
    "product.reviews": [("catalog/views.py", 65, "product_detail", 'rating = product.reviews.aggregate(avg=Avg("stars"), n=Count("id"))')],
    "product.rate": [("catalog/views.py", 66, "product_detail", '"variants": [serialize_variant(v, currency) for v in variants],'),
                     ("catalog/serializers.py", 31, "serialize_variant", "rate = ExchangeRate.objects.get(currency=currency).rate")],
    "search.count": [("catalog/views.py", 87, "search", "total = matches.count()")],
    "search.page": [("catalog/views.py", 88, "search", "results = [serialize_product(p) for p in matches[:20]]")],
    "cart.get": [("cart/views.py", 19, "cart_detail", 'cart, _ = Cart.objects.get_or_create(customer=request.customer, status="open")')],
    "cart.items": [("cart/views.py", 20, "cart_detail", 'items = list(cart.items.select_related("variant__product"))')],
    "cart.variant": [("cart/views.py", 37, "add_item", 'variant = ProductVariant.objects.select_related("product").get(pk=payload["variant_id"])')],
    "cart.upsert": [("cart/views.py", 41, "add_item", 'item, created = cart.items.get_or_create(variant=variant, defaults={"quantity": quantity})')],
    "checkout.cart": [("orders/views.py", 52, "checkout", 'cart = Cart.objects.select_related("customer").get(customer=request.customer, status="open")')],
    "checkout.lines": [("orders/views.py", 53, "checkout", 'lines = list(cart.items.select_related("variant"))')],
    "checkout.lock": [("orders/views.py", 56, "checkout", 'order = place_order(cart, lines, payload["shipping_address_id"])'),
                      ("orders/services.py", 34, "place_order", "variants = ProductVariant.objects.select_for_update().filter(pk__in=variant_ids)")],
    "checkout.order": [("orders/views.py", 56, "checkout", 'order = place_order(cart, lines, payload["shipping_address_id"])'),
                       ("orders/services.py", 41, "place_order", 'order = Order.objects.create(customer=cart.customer, shipping_address_id=address_id, total_cents=total, status="pending")')],
    "checkout.item": [("orders/views.py", 56, "checkout", 'order = place_order(cart, lines, payload["shipping_address_id"])'),
                      ("orders/services.py", 44, "place_order", "OrderItem.objects.create(order=order, variant=line.variant, quantity=line.quantity, price_cents=line.variant.price_cents)")],
    "checkout.stock": [("orders/views.py", 56, "checkout", 'order = place_order(cart, lines, payload["shipping_address_id"])'),
                       ("orders/services.py", 45, "place_order", 'ProductVariant.objects.filter(pk=line.variant_id).update(stock=F("stock") - line.quantity)')],
    "checkout.payment": [("orders/views.py", 57, "checkout", 'payment = gateway.charge(order, payload["payment_token"])'),
                         ("payments/gateway.py", 58, "charge", "payment = Payment.objects.create(order=order, amount_cents=order.total_cents, reference=result.id, status=result.status)")],
    "checkout.close": [("orders/views.py", 58, "checkout", 'Cart.objects.filter(pk=cart.pk).update(status="converted")')],
    "orders.list": [("orders/views.py", 18, "order_list", 'orders = list(request.customer.orders.order_by("-created_at")[:20])')],
    "orders.address": [("orders/views.py", 19, "order_list", 'return JsonResponse({"results": [serialize_order(o) for o in orders]})'),
                       ("orders/serializers.py", 12, "serialize_order", '"ship_to": order.shipping_address.city,')],
    "orders.items": [("orders/views.py", 19, "order_list", 'return JsonResponse({"results": [serialize_order(o) for o in orders]})'),
                     ("orders/serializers.py", 14, "serialize_order", '"items": order.items.count(),')],
    "order.get": [("orders/views.py", 31, "order_detail", 'order = get_object_or_404(Order.objects.select_related("shipping_address"), pk=pk, customer=request.customer)')],
    "order.items": [("orders/views.py", 32, "order_detail", 'items = list(order.items.select_related("variant__product"))')],
    "order.payments": [("orders/views.py", 33, "order_detail", 'payments = list(order.payments.order_by("created_at"))')],
    "login.attempts": [("accounts/views.py", 23, "login", "if LoginAttempt.objects.filter(email=email, created_at__gte=window).count() >= 5:")],
    "login.user": [("accounts/views.py", 27, "login", 'user = authenticate(request, email=email, password=payload["password"])'),
                   ("django/contrib/auth/backends.py", 46, "authenticate", "user = UserModel._default_manager.get_by_natural_key(username)")],
    "login.failed": [("accounts/views.py", 29, "login", "LoginAttempt.objects.create(email=email, succeeded=False)")],
    "login.last_login": [("accounts/views.py", 31, "login", "auth_login(request, user)"),
                         ("django/contrib/auth/models.py", 23, "update_last_login", 'user.save(update_fields=["last_login"])')],
    "login.session": [("accounts/views.py", 31, "login", "auth_login(request, user)"),
                      ("django/contrib/sessions/backends/db.py", 114, "save", "obj.save(force_insert=must_create, force_update=not must_create, using=using)")],
    "me": [("accounts/views.py", 44, "me", "addresses = list(request.customer.addresses.all())")],
    "webhook.seen": [("payments/webhooks.py", 29, "payment_webhook", 'if PaymentEvent.objects.filter(external_id=event["id"]).exists():')],
    "webhook.insert": [("payments/webhooks.py", 31, "payment_webhook", 'PaymentEvent.objects.create(external_id=event["id"], kind=event["type"], payload=event)')],
    "webhook.order": [("payments/webhooks.py", 33, "payment_webhook", 'Order.objects.filter(pk=event["order_id"]).update(status=STATUS_FOR[event["type"]])')],
    "admin.count": [("django/contrib/admin/views/main.py", 278, "get_results", "result_count = paginator.count")],
    "admin.page": [("django/contrib/admin/views/main.py", 296, "get_results", "result_list = paginator.page(self.page_num).object_list")],
    "admin.customer": [("django/contrib/admin/templatetags/admin_list.py", 233, "items_for_result", "f, attr, value = lookup_field(field_name, result, cl.model_admin)"),
                       ("orders/admin.py", 27, "customer_email", "return obj.customer.email")],
    "report.daily": [("reports/views.py", 21, "sales_report", "report = build_sales_report(start, end)"),
                     ("reports/sales.py", 38, "build_sales_report", 'daily = list(paid.annotate(day=TruncDate("created_at")).values("day").annotate(revenue=Sum("total_cents"), orders=Count("id")))')],
    "report.top": [("reports/views.py", 21, "sales_report", "report = build_sales_report(start, end)"),
                   ("reports/sales.py", 45, "build_sales_report", 'top = list(OrderItem.objects.filter(order__in=paid).values("variant__product__name").annotate(units=Sum("quantity")).order_by("-units")[:10])')],
    "report.categories": [("reports/views.py", 21, "sales_report", "report = build_sales_report(start, end)"),
                          ("reports/sales.py", 52, "build_sales_report", 'by_category = list(OrderItem.objects.filter(order__in=paid).values("variant__product__category__name").annotate(revenue=Sum(F("price_cents") * F("quantity"))))')],
}


# Functions wrapped in @silk_profile, at their def line.
PROFILED = {
    "place_order": ("orders/services.py", 28, "place_order"),
    "charge": ("payments/gateway.py", 41, "charge"),
    "build_sales_report": ("reports/sales.py", 30, "build_sales_report"),
}


def _frame_path(path):
    return SITE_PACKAGES / path if path.startswith("django/") else APP_ROOT / path


def _traceback(where):
    stack = [("django/core/handlers/base.py", 197, "_get_response",
              "response = wrapped_callback(request, *callback_args, **callback_kwargs)")]
    stack += WHERE[where]
    stack.append(("django/db/models/sql/compiler.py", 1574, "execute_sql", "cursor.execute(sql, params)"))
    return "\n".join(f'  File "{_frame_path(path)}", line {line}, in {func}\n    {code}'
                     for path, line, func, code in stack)


def _cols(table, *names):
    return ", ".join(f'"{table}"."{name}"' for name in names)


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


_PRODUCT = _cols("catalog_product", "id", "slug", "name", "description", "category_id", "price_cents", "is_active", "created_at")
_VARIANT = _cols("catalog_productvariant", "id", "product_id", "sku", "colour", "price_cents", "stock", "is_active")
_CUSTOMER = _cols("accounts_customer", "id", "password", "last_login", "email", "first_name", "last_name", "is_active", "is_staff", "date_joined")
_ORDER = _cols("orders_order", "id", "customer_id", "shipping_address_id", "status", "total_cents", "currency", "created_at", "updated_at")
_ADDRESS = _cols("orders_address", "id", "customer_id", "line1", "postcode", "city", "country")
_SESSION = ('SELECT "django_session"."session_key", "django_session"."session_data", "django_session"."expire_date" '
            'FROM "django_session" WHERE ("django_session"."expire_date" > {now} AND "django_session"."session_key" = {key}) LIMIT 21')


_SERVER_ERROR = ('<!doctype html>\n<html lang="en">\n<head><title>Server Error (500)</title></head>\n'
                 '<body><h1>Server Error (500)</h1><p></p></body>\n</html>\n')


def q(sql, where, median_ms, spread=0.45):
    return ("sql", sql, where, median_ms, spread)


def work(median_ms, spread=0.5):
    return ("work", median_ms, spread)


def span(name, where, steps, exception=False):
    return ("span", name, where, steps, exception)


def _product_json(p):
    return {"id": p["id"], "slug": p["slug"], "name": p["name"], "category": CATEGORIES[p["category_id"]],
            "price": {"amount": p["price_cents"] / 100, "currency": "EUR"}}


class Traffic:
    """Endpoint generators. Each returns the request, the response and the timeline of work inside it."""

    def __init__(self, rng, now):
        self.rng = rng
        self.now = now
        self.next_order = 48213
        self.next_event = 90411

    def _ts(self):
        return _quote((self.now - timedelta(seconds=self.rng.randint(0, 600))).strftime("%Y-%m-%d %H:%M:%S.%f+00:00"))

    def _session(self):
        key = "".join(self.rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(32))
        return q(_SESSION.format(now=self._ts(), key=_quote(key)), "session", 0.6)

    def _auth(self, customer):
        return [self._session(),
                q(f'SELECT {_CUSTOMER} FROM "accounts_customer" WHERE "accounts_customer"."id" = {customer} LIMIT 21', "customer", 0.5)]

    def customer(self):
        return self.rng.randint(1, 2400)

    def spec(self, view, path, steps, response, status=200, method="GET", params=None, body=None,
             content_type="application/json", authenticated=False, agent=None):
        return {"view": view, "path": path, "steps": steps, "response": response, "status": status,
                "method": method, "params": params or {}, "body": body, "content_type": content_type,
                "authenticated": authenticated, "agent": agent}

    def healthz(self):
        return self.spec("core:healthz", "/healthz/", [work(0.2), q("SELECT 1", "health", 0.3, 0.3)],
                         {"status": "ok"}, agent="kube-probe/1.31")

    def categories(self):
        sql = (f'SELECT {_cols("catalog_category", "id", "slug", "name", "position", "is_active")} FROM "catalog_category" '
               'WHERE "catalog_category"."is_active" ORDER BY "catalog_category"."position" ASC')
        return self.spec("catalog:category_list", "/api/v1/categories/", [q(sql, "categories", 0.8), work(1)],
                         {"results": [{"id": k, "name": v} for k, v in CATEGORIES.items()]})

    def product_list(self):
        rng = self.rng
        category = rng.choice([None, *CATEGORIES])
        page = rng.choices([1, 2, 3], weights=[80, 15, 5])[0]
        rows = [p for p in PRODUCTS if category is None or p["category_id"] == category]
        where = ' WHERE "catalog_product"."is_active"'
        params = {"page": str(page)} if page > 1 else {}
        if category:
            where += f' AND "catalog_product"."category_id" = {category}'
            params["category"] = str(category)
        shown = rows[(page - 1) * 12:page * 12]
        ids = ", ".join(str(p["id"]) for p in shown) or "NULL"
        steps = [
            q(f'SELECT COUNT(*) AS "__count" FROM "catalog_product"{where}', "products.count", 2.5),
            q(f'SELECT {_PRODUCT} FROM "catalog_product"{where} ORDER BY "catalog_product"."created_at" DESC '
              f'LIMIT 12 OFFSET {(page - 1) * 12}', "products.page", 4),
            q(f'SELECT {_cols("catalog_productimage", "id", "product_id", "image", "position")} FROM "catalog_productimage" '
              f'WHERE "catalog_productimage"."product_id" IN ({ids}) ORDER BY "catalog_productimage"."position" ASC',
              "products.page", 2),
            work(6),
        ]
        return self.spec("catalog:product_list", "/api/v1/products/", steps,
                         {"count": len(rows), "page": page, "results": [_product_json(p) for p in shown]}, params=params)

    def product_detail(self):
        rng = self.rng
        product = rng.choice(PRODUCTS)
        slug = product["slug"] if rng.random() > 0.04 else rng.choice(["copper-saucepan-16-cm", "santoku-knife", "teapot-1-l"])
        get = q(f'SELECT {_PRODUCT}, {_cols("catalog_category", "id", "slug", "name")} FROM "catalog_product" '
                'INNER JOIN "catalog_category" ON ("catalog_product"."category_id" = "catalog_category"."id") '
                f'WHERE ("catalog_product"."is_active" AND "catalog_product"."slug" = {_quote(slug)}) LIMIT 21', "product.get", 1.2)
        if slug != product["slug"]:
            return self.spec("catalog:product_detail", f"/api/v1/products/{slug}/", [get, work(2)],
                             {"detail": "No Product matches the given query."}, status=404)
        pk = product["id"]
        n_variants = rng.randint(2, 4)
        currency = rng.choices(["EUR", "GBP"], weights=[85, 15])[0]
        rate = q(f'SELECT {_cols("core_exchangerate", "id", "currency", "rate", "updated_at")} FROM "core_exchangerate" '
                 f'WHERE "core_exchangerate"."currency" = {_quote(currency)} LIMIT 21', "product.rate", 0.4)
        steps = [
            get,
            q(f'SELECT {_VARIANT} FROM "catalog_productvariant" WHERE ("catalog_productvariant"."product_id" = {pk} '
              'AND "catalog_productvariant"."is_active")', "product.variants", 1),
            q('SELECT AVG("catalog_review"."stars") AS "avg", COUNT("catalog_review"."id") AS "n" FROM "catalog_review" '
              f'WHERE "catalog_review"."product_id" = {pk}', "product.reviews", 3, 0.6),
            *[rate for _ in range(n_variants + 1)],
            work(4),
        ]
        colours = rng.sample(["Black", "Natural", "Sage", "Slate", "Terracotta"], n_variants)
        body = {**_product_json(product), "rating": {"average": round(rng.uniform(3.6, 4.9), 1), "count": rng.randint(3, 240)},
                "variants": [{"id": pk * 10 + i, "sku": f"HB-{pk}-{c[:3].upper()}", "colour": c, "in_stock": rng.random() > 0.15}
                             for i, c in enumerate(colours, 1)]}
        return self.spec("catalog:product_detail", f"/api/v1/products/{slug}/", steps, body,
                         params={"currency": currency} if currency != "EUR" else {})

    def search(self):
        rng = self.rng
        term = rng.choice(SEARCH_TERMS)
        hits = [p for p in PRODUCTS if term in p["name"].lower()]
        like = _quote(f"%{term}%")
        where = (f' WHERE ("catalog_product"."is_active" AND (UPPER("catalog_product"."name"::text) LIKE UPPER({like}) '
                 f'OR UPPER("catalog_product"."description"::text) LIKE UPPER({like})))')
        count = q(f'SELECT COUNT(*) AS "__count" FROM "catalog_product"{where}', "search.count", 35, 0.6)
        if rng.random() < 0.03:
            # statement_timeout = 5s cancels the leading-wildcard scan on a cold cache.
            return self.spec("catalog:search", "/api/v1/search/", [count[:3] + (5000, 0.01), work(3)], _SERVER_ERROR,
                             status=500, params={"q": term}, content_type="text/html; charset=utf-8")
        steps = [
            count,
            q(f'SELECT {_PRODUCT} FROM "catalog_product"{where} ORDER BY "catalog_product"."name" ASC LIMIT 20', "search.page", 45, 0.6),
            work(5),
        ]
        return self.spec("catalog:search", "/api/v1/search/", steps,
                         {"query": term, "count": len(hits), "results": [_product_json(p) for p in hits]},
                         params={"q": term})

    def cart_detail(self):
        rng = self.rng
        customer = self.customer()
        cart_id = 30000 + customer
        lines = rng.sample(PRODUCTS, rng.randint(0, 4))
        steps = [
            *self._auth(customer),
            q(f'SELECT {_cols("cart_cart", "id", "customer_id", "status", "created_at")} FROM "cart_cart" '
              f'WHERE ("cart_cart"."customer_id" = {customer} AND "cart_cart"."status" = \'open\') LIMIT 21', "cart.get", 0.7),
            q(f'SELECT {_cols("cart_cartitem", "id", "cart_id", "variant_id", "quantity")}, {_VARIANT}, {_PRODUCT} FROM "cart_cartitem" '
              'INNER JOIN "catalog_productvariant" ON ("cart_cartitem"."variant_id" = "catalog_productvariant"."id") '
              'INNER JOIN "catalog_product" ON ("catalog_productvariant"."product_id" = "catalog_product"."id") '
              f'WHERE "cart_cartitem"."cart_id" = {cart_id}', "cart.items", 1.5),
            work(3),
        ]
        items = [{"product": _product_json(p), "quantity": rng.randint(1, 3)} for p in lines]
        total = sum(i["product"]["price"]["amount"] * i["quantity"] for i in items)
        return self.spec("cart:cart_detail", "/api/v1/cart/", steps,
                         {"id": cart_id, "items": items, "total": {"amount": round(total, 2), "currency": "EUR"}},
                         authenticated=True)

    def add_item(self):
        rng = self.rng
        customer = self.customer()
        product = rng.choice(PRODUCTS)
        variant = product["id"] * 10 + rng.randint(1, 3)
        quantity = rng.choices([1, 2, 3, 0], weights=[70, 18, 8, 4])[0]
        body = {"variant_id": variant, "quantity": quantity}
        steps = self._auth(customer)
        if quantity == 0:
            return self.spec("cart:add_item", "/api/v1/cart/items/", steps + [work(1)],
                             {"quantity": ["Ensure this value is greater than or equal to 1."]},
                             status=400, method="POST", body=body, authenticated=True)
        steps += [
            q(f'SELECT {_cols("cart_cart", "id", "customer_id", "status", "created_at")} FROM "cart_cart" '
              f'WHERE ("cart_cart"."customer_id" = {customer} AND "cart_cart"."status" = \'open\') LIMIT 21', "cart.get", 0.7),
            q(f'SELECT {_VARIANT}, {_PRODUCT} FROM "catalog_productvariant" '
              'INNER JOIN "catalog_product" ON ("catalog_productvariant"."product_id" = "catalog_product"."id") '
              f'WHERE "catalog_productvariant"."id" = {variant} LIMIT 21', "cart.variant", 0.8),
        ]
        if rng.random() < 0.05:
            return self.spec("cart:add_item", "/api/v1/cart/items/", steps + [work(1)],
                             {"detail": "Only 1 left in stock.", "code": "insufficient_stock"},
                             status=409, method="POST", body=body, authenticated=True)
        item = rng.randint(700000, 799999)
        steps += [
            q(f'SELECT {_cols("cart_cartitem", "id", "cart_id", "variant_id", "quantity")} FROM "cart_cartitem" '
              f'WHERE ("cart_cartitem"."cart_id" = {30000 + customer} AND "cart_cartitem"."variant_id" = {variant}) LIMIT 21',
              "cart.upsert", 0.6),
            q(f'INSERT INTO "cart_cartitem" ("cart_id", "variant_id", "quantity") VALUES ({30000 + customer}, {variant}, {quantity}) '
              'RETURNING "cart_cartitem"."id"', "cart.upsert", 1.8),
            work(2),
        ]
        return self.spec("cart:add_item", "/api/v1/cart/items/", steps,
                         {"id": item, "variant_id": variant, "quantity": quantity},
                         status=201, method="POST", body=body, authenticated=True)

    def checkout(self):
        rng = self.rng
        customer = self.customer()
        cart_id = 30000 + customer
        lines = [(p, p["id"] * 10 + rng.randint(1, 3), rng.randint(1, 2)) for p in rng.sample(PRODUCTS, rng.randint(1, 5))]
        subtotal = sum(p["price_cents"] * n for p, _, n in lines)
        total = subtotal + (0 if subtotal >= 5000 else 495)  # free shipping from EUR 50
        address = 50000 + customer
        body = {"shipping_address_id": address, "payment_token": "tok_" + "".join(rng.choice("abcdef0123456789") for _ in range(16))}
        order = self.next_order
        self.next_order += 1
        variant_ids = ", ".join(str(v) for _, v, _ in lines)
        place = [
            q(f'SELECT {_VARIANT} FROM "catalog_productvariant" WHERE "catalog_productvariant"."id" IN ({variant_ids}) FOR UPDATE',
              "checkout.lock", 2.5, 0.7),
            q('INSERT INTO "orders_order" ("customer_id", "shipping_address_id", "status", "total_cents", "currency", "created_at", "updated_at") '
              f"VALUES ({customer}, {address}, 'pending', {total}, 'EUR', {self._ts()}, {self._ts()}) RETURNING \"orders_order\".\"id\"",
              "checkout.order", 1.6),
        ]
        for product, variant, n in lines:
            place.append(q('INSERT INTO "orders_orderitem" ("order_id", "variant_id", "quantity", "price_cents") '
                           f'VALUES ({order}, {variant}, {n}, {product["price_cents"]}) '
                           'RETURNING "orders_orderitem"."id"', "checkout.item", 1.2))
            place.append(q(f'UPDATE "catalog_productvariant" SET "stock" = ("catalog_productvariant"."stock" - {n}) '
                           f'WHERE "catalog_productvariant"."id" = {variant}', "checkout.stock", 1.1))
        steps = [
            *self._auth(customer),
            q(f'SELECT {_cols("cart_cart", "id", "customer_id", "status", "created_at")}, {_CUSTOMER} FROM "cart_cart" '
              'INNER JOIN "accounts_customer" ON ("cart_cart"."customer_id" = "accounts_customer"."id") '
              f'WHERE ("cart_cart"."customer_id" = {customer} AND "cart_cart"."status" = \'open\') LIMIT 21', "checkout.cart", 0.9),
            q(f'SELECT {_cols("cart_cartitem", "id", "cart_id", "variant_id", "quantity")}, {_VARIANT} FROM "cart_cartitem" '
              'INNER JOIN "catalog_productvariant" ON ("cart_cartitem"."variant_id" = "catalog_productvariant"."id") '
              f'WHERE "cart_cartitem"."cart_id" = {cart_id}', "checkout.lines", 1.2),
            span("place_order", "place_order", place + [work(3)]),
        ]
        outcome = rng.choices(["paid", "declined", "timeout"], weights=[88, 7, 5])[0]
        if outcome == "timeout":
            steps.append(span("gateway.charge", "charge", [work(10000, 0.05)], exception=True))
            return self.spec("orders:checkout", "/api/v1/checkout/", steps, _SERVER_ERROR, status=500, method="POST", body=body, content_type="text/html; charset=utf-8", authenticated=True)
        payment_status = "authorised" if outcome == "paid" else "declined"
        steps.append(span("gateway.charge", "charge", [
            work(420, 0.35),
            q('INSERT INTO "payments_payment" ("order_id", "amount_cents", "reference", "status", "created_at") '
              f"VALUES ({order}, {total}, 'pi_{rng.randint(10**11, 10**12 - 1)}', '{payment_status}', {self._ts()}) "
              'RETURNING "payments_payment"."id"', "checkout.payment", 1.4),
        ]))
        if outcome == "declined":
            return self.spec("orders:checkout", "/api/v1/checkout/", steps + [work(2)],
                             {"detail": "Your card was declined.", "code": "card_declined", "order_id": order},
                             status=402, method="POST", body=body, authenticated=True)
        steps += [q(f'UPDATE "cart_cart" SET "status" = \'converted\' WHERE "cart_cart"."id" = {cart_id}', "checkout.close", 1), work(4)]
        return self.spec("orders:checkout", "/api/v1/checkout/", steps,
                         {"order_id": order, "status": "paid", "total": {"amount": total / 100, "currency": "EUR"}},
                         status=201, method="POST", body=body, authenticated=True)

    def order_list(self):
        rng = self.rng
        customer = self.customer()
        if rng.random() < 0.03:
            return self.spec("orders:order_list", "/api/v1/orders/", [self._session(), work(1)],
                             {"detail": "Authentication credentials were not provided."}, status=401)
        orders = sorted(rng.sample(range(31000, self.next_order), rng.randint(1, 14)), reverse=True)
        steps = [
            *self._auth(customer),
            q(f'SELECT {_ORDER} FROM "orders_order" WHERE "orders_order"."customer_id" = {customer} '
              'ORDER BY "orders_order"."created_at" DESC LIMIT 20', "orders.list", 1.5),
        ]
        # serialize_order follows shipping_address and counts items per order: the N+1 this endpoint is known for.
        for pk in orders:
            steps.append(q(f'SELECT {_ADDRESS} FROM "orders_address" WHERE "orders_address"."id" = {50000 + customer} LIMIT 21',
                           "orders.address", 0.5))
            steps.append(q(f'SELECT COUNT(*) AS "__count" FROM "orders_orderitem" WHERE "orders_orderitem"."order_id" = {pk}',
                           "orders.items", 0.6))
        steps.append(work(3))
        city = rng.choice(["Gent", "Antwerpen", "Leuven", "Mechelen", "Utrecht", "Rotterdam", "Brussel", "Hasselt"])
        results = [{"id": pk, "status": rng.choices(["delivered", "shipped", "paid"], weights=[80, 12, 8])[0],
                    "ship_to": city, "items": rng.randint(1, 5)} for pk in orders]
        return self.spec("orders:order_list", "/api/v1/orders/", steps, {"results": results}, authenticated=True)

    def order_detail(self):
        rng = self.rng
        customer = self.customer()
        pk = rng.randint(31000, self.next_order - 1)
        get = q(f'SELECT {_ORDER}, {_ADDRESS} FROM "orders_order" '
                'LEFT OUTER JOIN "orders_address" ON ("orders_order"."shipping_address_id" = "orders_address"."id") '
                f'WHERE ("orders_order"."customer_id" = {customer} AND "orders_order"."id" = {pk}) LIMIT 21', "order.get", 0.9)
        if rng.random() < 0.03:
            return self.spec("orders:order_detail", f"/api/v1/orders/{pk}/", [*self._auth(customer), get, work(1)],
                             {"detail": "No Order matches the given query."}, status=404, authenticated=True)
        lines = rng.sample(PRODUCTS, rng.randint(1, 4))
        steps = [
            *self._auth(customer), get,
            q(f'SELECT {_cols("orders_orderitem", "id", "order_id", "variant_id", "quantity", "price_cents")}, {_VARIANT}, {_PRODUCT} '
              'FROM "orders_orderitem" INNER JOIN "catalog_productvariant" ON ("orders_orderitem"."variant_id" = "catalog_productvariant"."id") '
              'INNER JOIN "catalog_product" ON ("catalog_productvariant"."product_id" = "catalog_product"."id") '
              f'WHERE "orders_orderitem"."order_id" = {pk}', "order.items", 1.4),
            q(f'SELECT {_cols("payments_payment", "id", "order_id", "amount_cents", "reference", "status", "created_at")} FROM "payments_payment" '
              f'WHERE "payments_payment"."order_id" = {pk} ORDER BY "payments_payment"."created_at" ASC', "order.payments", 0.7),
            work(3),
        ]
        return self.spec("orders:order_detail", f"/api/v1/orders/{pk}/", steps,
                         {"id": pk, "status": "delivered", "items": [{"product": _product_json(p), "quantity": 1} for p in lines]},
                         authenticated=True)

    def login(self):
        rng = self.rng
        email = f"{rng.choice(FIRST_NAMES)}.{rng.choice(LAST_NAMES)}@example.com"
        body = {"email": email, "password": "********"}
        attempts = q('SELECT COUNT(*) AS "__count" FROM "accounts_loginattempt" WHERE ("accounts_loginattempt"."created_at" >= '
                     f'{self._ts()} AND "accounts_loginattempt"."email" = {_quote(email)})', "login.attempts", 0.8)
        outcome = rng.choices(["ok", "bad", "locked"], weights=[88, 10, 2])[0]
        if outcome == "locked":
            return self.spec("accounts:login", "/api/v1/auth/login/", [self._session(), attempts, work(1)],
                             {"detail": "Too many failed attempts. Try again in 15 minutes."}, status=429, method="POST", body=body)
        steps = [
            self._session(), attempts,
            q(f'SELECT {_CUSTOMER} FROM "accounts_customer" WHERE UPPER("accounts_customer"."email"::text) = UPPER({_quote(email)}) LIMIT 21',
              "login.user", 1.1),
            # PBKDF2 with Django's default iteration count costs most of a login request.
            work(260, 0.12),
        ]
        if outcome == "bad":
            steps += [q('INSERT INTO "accounts_loginattempt" ("email", "succeeded", "created_at") '
                        f'VALUES ({_quote(email)}, false, {self._ts()}) RETURNING "accounts_loginattempt"."id"', "login.failed", 1.2)]
            return self.spec("accounts:login", "/api/v1/auth/login/", steps + [work(1)],
                             {"detail": "Invalid email or password."}, status=401, method="POST", body=body)
        customer = self.customer()
        steps += [
            q(f'UPDATE "accounts_customer" SET "last_login" = {self._ts()} WHERE "accounts_customer"."id" = {customer}', "login.last_login", 1.3),
            q('INSERT INTO "django_session" ("session_key", "session_data", "expire_date") '
              f"VALUES ('{rng.getrandbits(128):032x}', '.eJxVjEEOwiAQRe_C2hCgQItL956BMDNUqgaS0q6Md7dNutD1-_9_s6DXNYe-pzXMxC5MsdM_g4ivVHZAz1Tuldda2jID3yv8oI3fKqX39ej-DXJsee0aDGbPTWvoT2wlE6FFb7ZRRJ2coqRBFSdvoxScJNpHTq', "
              f'{self._ts()})', "login.session", 1.4),
            work(2),
        ]
        return self.spec("accounts:login", "/api/v1/auth/login/", steps, {"id": customer, "email": email}, method="POST", body=body)

    def me(self):
        rng = self.rng
        customer = self.customer()
        if rng.random() < 0.04:
            return self.spec("accounts:me", "/api/v1/me/", [self._session(), work(1)],
                             {"detail": "Authentication credentials were not provided."}, status=401)
        steps = [*self._auth(customer),
                 q(f'SELECT {_ADDRESS} FROM "orders_address" WHERE "orders_address"."customer_id" = {customer}', "me", 0.7), work(2)]
        return self.spec("accounts:me", "/api/v1/me/", steps,
                         {"id": customer, "email": f"{rng.choice(FIRST_NAMES)}.{rng.choice(LAST_NAMES)}@example.com",
                          "addresses": rng.randint(1, 3)}, authenticated=True)

    def payment_webhook(self):
        rng = self.rng
        event = f"evt_{self.next_event}"
        self.next_event += 1
        order = rng.randint(31000, self.next_order - 1)
        kind = rng.choices(["payment.captured", "payment.refunded", "payment.failed"], weights=[85, 9, 6])[0]
        body = {"id": event, "type": kind, "order_id": order}
        if rng.random() < 0.03:
            return self.spec("payments:webhook", "/webhooks/payments/", [work(2)], {"detail": "Invalid signature."},
                             status=400, method="POST", body=body, agent="PaymentsHook/2.4")
        seen = q(f'SELECT 1 AS "a" FROM "payments_paymentevent" WHERE "payments_paymentevent"."external_id" = {_quote(event)} LIMIT 1',
                 "webhook.seen", 0.6)
        insert = q('INSERT INTO "payments_paymentevent" ("external_id", "kind", "payload", "created_at") '
                   f"VALUES ({_quote(event)}, {_quote(kind)}, {_quote(json.dumps(body))}, {self._ts()}) "
                   'RETURNING "payments_paymentevent"."id"', "webhook.insert", 1.5)
        if rng.random() < 0.05:
            # The provider retried before the first delivery committed: both pass the exists() check
            # and the second INSERT hits the unique constraint on external_id.
            return self.spec("payments:webhook", "/webhooks/payments/", [seen, work(2), insert, work(3)], _SERVER_ERROR,
                             status=500, method="POST", body=body, content_type="text/html; charset=utf-8",
                             agent="PaymentsHook/2.4")
        steps = [
            seen,
            insert,
            q(f'UPDATE "orders_order" SET "status" = {_quote({"payment.captured": "paid", "payment.refunded": "refunded", "payment.failed": "failed"}[kind])} '
              f'WHERE "orders_order"."id" = {order}', "webhook.order", 1.2),
            work(1),
        ]
        return self.spec("payments:webhook", "/webhooks/payments/", steps, {"received": True},
                         method="POST", body=body, agent="PaymentsHook/2.4")

    def admin_orders(self):
        rng = self.rng
        status = rng.choice([None, "paid", "shipped"])
        where = f' WHERE "orders_order"."status" = {_quote(status)}' if status else ""
        page = rng.choices([0, 1, 2], weights=[75, 18, 7])[0]
        steps = [
            self._session(),
            q(f'SELECT {_CUSTOMER} FROM "accounts_customer" WHERE "accounts_customer"."id" = {rng.randint(1, 6)} LIMIT 21', "customer", 0.5),
            q(f'SELECT COUNT(*) AS "__count" FROM "orders_order"{where}', "admin.count", 18, 0.4),
            q(f'SELECT {_ORDER} FROM "orders_order"{where} ORDER BY "orders_order"."created_at" DESC, "orders_order"."id" DESC '
              f'LIMIT 100 OFFSET {page * 100}', "admin.page", 9),
        ]
        # customer_email in list_display reads obj.customer for every row without list_select_related.
        for _ in range(100):
            steps.append(q(f'SELECT {_CUSTOMER} FROM "accounts_customer" WHERE "accounts_customer"."id" = {rng.randint(1, 2400)} LIMIT 21',
                           "admin.customer", 0.4))
        steps.append(work(70, 0.3))
        return self.spec("admin:orders_order_changelist", "/admin/orders/order/", steps,
                         "<!doctype html>\n<html lang=\"en\"><head><title>Select order to change | Harbor admin</title></head>"
                         "<body><div id=\"changelist\">...</div></body></html>",
                         params={"status__exact": status} if status else ({"p": str(page)} if page else {}),
                         content_type="text/html; charset=utf-8", authenticated=True, agent=BROWSERS[0])

    def sales_report(self):
        rng = self.rng
        days = rng.choice([7, 30, 90])
        start = (self.now - timedelta(days=days)).date()
        paid = (f'"orders_order"."status" IN (\'paid\', \'shipped\', \'delivered\') AND "orders_order"."created_at" >= '
                f"'{start} 00:00:00+00:00'")
        report = [
            q('SELECT ("orders_order"."created_at" AT TIME ZONE \'UTC\')::date AS "day", SUM("orders_order"."total_cents") AS "revenue", '
              f'COUNT("orders_order"."id") AS "orders" FROM "orders_order" WHERE ({paid}) GROUP BY 1 ORDER BY 1',
              "report.daily", 140 * days ** 0.5, 0.35),
            q('SELECT "catalog_product"."name", SUM("orders_orderitem"."quantity") AS "units" FROM "orders_orderitem" '
              'INNER JOIN "orders_order" ON ("orders_orderitem"."order_id" = "orders_order"."id") '
              'INNER JOIN "catalog_productvariant" ON ("orders_orderitem"."variant_id" = "catalog_productvariant"."id") '
              'INNER JOIN "catalog_product" ON ("catalog_productvariant"."product_id" = "catalog_product"."id") '
              f'WHERE ({paid}) GROUP BY 1 ORDER BY 2 DESC LIMIT 10', "report.top", 220 * days ** 0.5, 0.35),
            q('SELECT "catalog_category"."name", SUM(("orders_orderitem"."price_cents" * "orders_orderitem"."quantity")) AS "revenue" '
              'FROM "orders_orderitem" INNER JOIN "orders_order" ON ("orders_orderitem"."order_id" = "orders_order"."id") '
              'INNER JOIN "catalog_productvariant" ON ("orders_orderitem"."variant_id" = "catalog_productvariant"."id") '
              'INNER JOIN "catalog_product" ON ("catalog_productvariant"."product_id" = "catalog_product"."id") '
              'INNER JOIN "catalog_category" ON ("catalog_product"."category_id" = "catalog_category"."id") '
              f'WHERE ({paid}) GROUP BY 1', "report.categories", 120 * days ** 0.5, 0.35),
            work(40 * days ** 0.5, 0.3),
        ]
        steps = [self._session(),
                 q(f'SELECT {_CUSTOMER} FROM "accounts_customer" WHERE "accounts_customer"."id" = {rng.randint(1, 6)} LIMIT 21', "customer", 0.5),
                 span("build_sales_report", "build_sales_report", report), work(15)]
        return self.spec("reports:sales", "/reports/sales/", steps,
                         {"from": str(start), "to": str(self.now.date()), "orders": rng.randint(80, 140) * days,
                          "revenue": {"amount": rng.randint(4000, 7000) * days, "currency": "EUR"}},
                         params={"days": str(days)}, authenticated=True, agent=BROWSERS[0])


ENDPOINTS = [
    ("healthz", 14), ("categories", 4), ("product_list", 18), ("product_detail", 20), ("search", 9),
    ("cart_detail", 8), ("add_item", 6), ("checkout", 2.5), ("order_list", 4), ("order_detail", 3),
    ("login", 3), ("me", 6), ("payment_webhook", 2), ("admin_orders", 1.2), ("sales_report", 0.5),
]


def _timeline(spec, start, rng):
    """Lay the steps out in time: queries run one after another with application work between them."""
    # Roughly 1 in 60 requests lands on a busy database (vacuum, lock wait) and every query slows down.
    db_factor = rng.uniform(4, 15) if rng.random() < 0.017 else 1
    queries, spans = [], []
    cursor = start + timedelta(milliseconds=rng.uniform(0.4, 2.5))  # middleware before the view

    def run(steps, collected):
        nonlocal cursor
        for step in steps:
            kind = step[0]
            if kind == "work":
                cursor += timedelta(milliseconds=rng.lognormvariate(math.log(step[1]), step[2]))
            elif kind == "sql":
                _, sql, where, median, spread = step
                cursor += timedelta(milliseconds=rng.uniform(0.05, 0.4))
                duration = rng.lognormvariate(math.log(median), spread) * db_factor
                queries.append({"sql": sql, "where": where, "start": cursor, "end": cursor + timedelta(milliseconds=duration)})
                collected.append(len(queries) - 1)
                cursor = queries[-1]["end"]
            else:
                _, name, where, inner, exception = step
                opened = cursor
                cursor += timedelta(milliseconds=rng.uniform(0.05, 0.3))
                own = []
                run(inner, own)
                cursor += timedelta(milliseconds=rng.uniform(0.05, 0.3))
                spans.append({"name": name, "where": where, "start": opened, "end": cursor,
                              "queries": own, "exception": exception})
                collected.extend(own)

    run(spec["steps"], [])
    end = cursor + timedelta(milliseconds=rng.uniform(0.5, 4))  # serialisation and response middleware
    return queries, spans, end


def _pstats(seconds, rows):
    """Plausible pstats text whose cumulative top line matches the recorded duration."""
    # Only the interesting rows are listed; the header counts the long tail of small calls too.
    calls = sum(int(str(n).split("/")[0]) for n, *_ in rows) + int(seconds * 48000)
    lines = [f"         {calls} function calls ({int(calls * 0.93)} primitive calls) in {seconds:.3f} seconds", "", "   Ordered by: cumulative time", "",
             "   ncalls  tottime  percall  cumtime  percall filename:lineno(function)"]
    for ncalls, tottime, cumtime, location in rows:
        n = int(str(ncalls).split("/")[-1])
        lines.append(f"{ncalls:>9} {tottime:8.3f} {tottime / n:8.3f} {cumtime:8.3f} {cumtime / n:8.3f} {location}")
    return "\n".join(lines) + "\n"


def _pyprofile(spec, queries, spans, seconds):
    sql = sum((q["end"] - q["start"]).total_seconds() for q in queries)
    n = len(queries)
    if spec["view"] == "reports:sales":
        build = next(s for s in spans if s["name"] == "build_sales_report")
        built = (build["end"] - build["start"]).total_seconds()
        return _pstats(seconds, [
            (1, 0.0, seconds, f"{APP_ROOT}/reports/views.py:14(sales_report)"),
            (1, 0.004, built, f"{APP_ROOT}/reports/sales.py:30(build_sales_report)"),
            (n, 0.002, sql, f"{SITE_PACKAGES}/django/db/models/sql/compiler.py:1532(execute_sql)"),
            (n, sql * 0.97, sql * 0.97, "{method 'execute' of 'psycopg.Cursor' objects}"),
            (1, (built - sql) * 0.8, (built - sql) * 0.9, f"{APP_ROOT}/reports/sales.py:71(_fill_missing_days)"),
            (1, 0.003, max(seconds - built, 0.004) * 0.6, f"{SITE_PACKAGES}/django/http/response.py:731(__init__)"),
        ])
    charge = next(s for s in spans if s["name"] == "gateway.charge")
    gateway = (charge["end"] - charge["start"]).total_seconds()
    return _pstats(seconds, [
        (1, 0.0, seconds, f"{APP_ROOT}/orders/views.py:44(checkout)"),
        (1, 0.001, gateway, f"{APP_ROOT}/payments/gateway.py:41(charge)"),
        (1, 0.0, gateway * 0.98, f"{SITE_PACKAGES}/requests/sessions.py:500(request)"),
        (14, gateway * 0.95, gateway * 0.95, "{method 'read' of '_ssl._SSLSocket' objects}"),
        (n, 0.001, sql, f"{SITE_PACKAGES}/django/db/models/sql/compiler.py:1532(execute_sql)"),
        (n, sql * 0.95, sql * 0.95, "{method 'execute' of 'psycopg.Cursor' objects}"),
    ])


def _headers(spec, rng):
    agent = spec["agent"] or rng.choice(BROWSERS)
    headers = {"host": "shop.harbor.example", "user-agent": agent, "accept": spec["content_type"].split(";")[0],
               "x-forwarded-for": f"{rng.choice([81, 84, 91, 94, 178, 213])}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
               "x-request-id": f"{rng.getrandbits(128):032x}"}
    if not agent.startswith(("kube-probe", "PaymentsHook")):
        headers["accept-language"] = rng.choice(LANGUAGES)
        headers["cookie"] = "********************"
    if agent.startswith("PaymentsHook"):
        headers["x-signature"] = "********************"
    return headers


def _record(spec, start, rng):
    queries, spans, end = _timeline(spec, start, rng)
    body = json.dumps(spec["body"]) if spec["body"] is not None else ""
    headers = _headers(spec, rng)
    if body:
        headers["content-type"] = "application/json"
        headers["content-length"] = str(len(body.encode()))
    req = models.Request.objects.create(
        method=spec["method"], path=spec["path"], query_params=json.dumps(spec["params"]) if spec["params"] else "",
        start_time=start, end_time=end, view_name=spec["view"],
        encoded_headers=json.dumps(headers), body=body, raw_body=body,
        meta_time=rng.uniform(0.2, 1.5), meta_num_queries=rng.randint(2, 4),
        meta_time_spent_queries=rng.uniform(0.1, 0.8),
    )
    is_json = spec["content_type"] == "application/json"
    response_body = json.dumps(spec["response"]) if is_json else spec["response"]
    models.Response.objects.create(
        request=req, status_code=spec["status"], body=response_body, raw_body=response_body,
        encoded_headers=json.dumps({"content-type": spec["content_type"], "content-length": str(len(response_body.encode())),
                                    "vary": "Cookie, Accept-Language", "x-frame-options": "DENY"}),
    )
    saved = [models.SQLQuery.objects.create(request=req, query=q["sql"], start_time=q["start"], end_time=q["end"],
                                            traceback=_traceback(q["where"]))
             for q in queries]
    for s in spans:
        path, line, func = PROFILED[s["where"]]
        profile = models.Profile.objects.create(
            request=req, name=s["name"], file_path=str(_frame_path(path)), line_num=line, func_name=func,
            start_time=s["start"], end_time=s["end"], exception_raised=s["exception"],
        )
        profile.queries.set([saved[i] for i in s["queries"]])
    if spec["view"] == "reports:sales" or (spec["view"] == "orders:checkout" and spec["status"] != 500 and rng.random() < 0.3):
        req.pyprofile = _pyprofile(spec, queries, spans, (end - start).total_seconds())
        req.save(update_fields=["pyprofile"])
    return req


def _start_times(rng, now, days, count):
    """Follow the shop's daily rhythm: quiet nights, an evening peak, slightly lighter weekends."""
    # Leave room before now for the slowest request (a checkout gateway timeout) to finish.
    span_seconds = days * 86400 - 120
    window_start = now - timedelta(days=days)
    starts = []
    while len(starts) < count:
        t = window_start + timedelta(seconds=rng.uniform(0, span_seconds))
        weight = HOURLY[t.hour] * (0.8 if t.weekday() >= 5 else 1)
        if rng.random() * 1.3 < weight:
            starts.append(t)
    starts.sort()
    if starts:
        starts[-1] = max(starts[-1], now - timedelta(seconds=90))
    return starts


class Command(BaseCommand):
    help = "Seed synthetic production-style traffic for a fictional Django shop."

    def add_arguments(self, parser):
        parser.add_argument("--requests", type=int, default=200, help="Requests to create (default: 200)")
        parser.add_argument("--days", type=int, default=7, help="Past days to cover (default: 7)")
        parser.add_argument("--clear", action="store_true", help="Delete existing Silk profiling records first")
        parser.add_argument("--seed", type=int, help="Random seed for repeatable traffic")

    @transaction.atomic
    def handle(self, *args, **options):
        count, days = options["requests"], options["days"]
        if count < 0:
            raise CommandError("--requests must be zero or greater")
        if days < 1:
            raise CommandError("--days must be at least 1")
        if options["clear"]:
            self.stdout.write("Clearing existing Silk profiling records…")
            models.Profile.objects.all().delete()
            models.SQLQuery.objects.all().delete()
            models.Request.objects.all().delete()
        # Preserve compatibility with callers using random.seed(), such as benchmarks.
        rng = random.Random(options["seed"]) if options["seed"] is not None else random
        now = timezone.now()
        traffic = Traffic(rng, now)
        names = [name for name, _ in ENDPOINTS]
        weights = [weight for _, weight in ENDPOINTS]
        for start in _start_times(rng, now, days, count):
            _record(getattr(traffic, rng.choices(names, weights=weights)[0])(), start, rng)
        self.stdout.write(self.style.SUCCESS(
            f"Created {count} requests across {days} days. "
            f"Database totals: {models.Request.objects.count()} requests, "
            f"{models.SQLQuery.objects.count()} SQL queries, {models.Profile.objects.count()} profiles."
        ))
