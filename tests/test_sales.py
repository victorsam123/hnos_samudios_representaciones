"""Functional commercial tests. Uses only isolated databases, never .env data."""
import importlib.util
import io
import os
import re
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

test_database = os.environ.get("ADMIN_TEST_DATABASE_URL", "sqlite:///:memory:")
if test_database != "sqlite:///:memory:" and not test_database.startswith("postgresql+psycopg://admin_test:"):
    raise RuntimeError("Only a disposable admin_test database is allowed")
os.environ["DATABASE_URL"] = test_database
os.environ["SECRET_KEY"] = "isolated-admin-tests-only"
os.environ["ADMIN_USERNAME"] = "isolated-admin"
os.environ["ADMIN_PASSWORD"] = "isolated-tests-only"
os.environ["COOKIE_SECURE"] = "false"

from flask import g
from flask_migrate import upgrade
from pypdf import PdfReader
from sqlalchemy import create_engine, inspect, select, func
from sqlalchemy.exc import SQLAlchemyError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.autogenerate import compare_metadata
from werkzeug.security import check_password_hash, generate_password_hash
from app import app, db, Product, Category, Customer, Order, OrderItem
from sales_models import SalesUser, SalesStore, SalesCart, SalesCartItem, SalesOrder, SalesAudit
from local_time import paraguay_datetime

with app.app_context():
    upgrade()

PASSWORD = "TestingSecure2026!"


class CommercialTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.ctx = app.app_context(); self.ctx.push()
        self.admin = app.test_client()
        with self.admin.session_transaction() as session: session["admin_authenticated"] = True
        self.client = app.test_client()

    def tearDown(self):
        db.session.rollback(); db.session.remove(); self.ctx.pop()

    def csrf(self, client=None, path="/vendedor/ingresar"):
        g.pop("csrf_token", None)
        response = (client or self.client).get(path)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        token = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(token, path)
        return token.group(1)

    def post(self, path, data=None, client=None, follow=True):
        client = client or self.client
        token = self.csrf(client)
        defaults = {"csrf_token": token}
        if path.startswith("/vendedor/carrito"):
            with client.session_transaction() as state:
                current = db.session.scalar(select(SalesCart).where(SalesCart.seller_id == state.get("sales_user_id")))
            if current:
                defaults["cart_key"] = current.checkout_key
        return client.post(path, data={**defaults, **(data or {})}, follow_redirects=follow)

    def user(self, login=True):
        user = SalesUser(first_name="Juan", last_name="Pérez", username="v"+secrets.token_hex(5), password_hash=generate_password_hash(PASSWORD), role="vendedor", active=True)
        db.session.add(user); db.session.commit()
        if login:
            response = self.post("/vendedor/ingresar", {"username": user.username, "password": PASSWORD})
            self.assertEqual(response.status_code, 200)
        return user

    def product(self, **kw):
        values = dict(name="Comercial " + secrets.token_hex(5), price=120000, stock=10, active=True, category_id=db.session.scalar(select(Category.id)), description="Descripción real de prueba")
        values.update(kw)
        product = Product(**values); db.session.add(product); db.session.commit()
        return product

    def start(self, name=None):
        return self.post("/vendedor/nuevo", dict(name=name or "Comercio " + secrets.token_hex(5), responsible="Responsable", phone="0981000000", city="Asunción", address="Calle de prueba", notes="Visita comercial"))

    def add(self, product, quantity=1):
        return self.post(f"/vendedor/carrito/{product.id}", dict(action="add", quantity=str(quantity)))

    def quote(self, client=None):
        response = (client or self.client).get("/vendedor/resumen")
        self.assertEqual(response.status_code, 200, response.location)
        return unescape(re.search(r'name="quote" value="([^"]+)"', response.get_data(as_text=True)).group(1))

    def commercial(self, user):
        db.session.expire_all()
        return db.session.scalar(select(SalesOrder).where(SalesOrder.seller_id == user.id).order_by(SalesOrder.order_id.desc()))

    def test_admin_create_edit_password_and_activation(self):
        username = "new"+secrets.token_hex(4)
        data = dict(first_name="Ana", last_name="López", username=username, password=PASSWORD, role="administrador")
        self.post("/admin/vendedores", data, self.admin)
        user = db.session.scalar(select(SalesUser).where(SalesUser.username == username))
        self.assertIsNotNone(user); self.assertEqual(user.role, "vendedor")
        self.assertNotEqual(user.password_hash, PASSWORD); self.assertTrue(check_password_hash(user.password_hash, PASSWORD))
        self.post("/vendedor/ingresar", dict(username=username, password=PASSWORD))
        self.assertEqual(self.client.get("/vendedor/").status_code, 200)
        self.post(f"/admin/vendedores/{user.id}/desactivar", client=self.admin)
        self.assertEqual(self.client.get("/vendedor/").status_code, 302)
        self.post(f"/admin/vendedores/{user.id}/activar", client=self.admin)
        self.post(f"/admin/vendedores/{user.id}/password", dict(password="ReplacementPass2026!"), self.admin)
        response = self.post("/vendedor/ingresar", dict(username=username, password=PASSWORD))
        self.assertIn("incorrectos", response.get_data(as_text=True))
        self.post("/vendedor/ingresar", dict(username=username, password="ReplacementPass2026!"))
        self.assertEqual(self.client.get("/vendedor/").status_code, 200)
        self.post(f"/admin/vendedores/{user.id}/editar", dict(first_name="Ana María", last_name="López", username=username), self.admin)
        self.assertEqual(self.client.get("/vendedor/").status_code, 302)

    def test_invalid_password_and_duplicate_user(self):
        user = self.user(False)
        count = db.session.scalar(select(func.count()).select_from(SalesUser))
        for password, username in [("short", "new"+secrets.token_hex(4)), (PASSWORD, user.username)]:
            response = self.post("/admin/vendedores", dict(first_name="Test", last_name="User", username=username, password=password), self.admin)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(db.session.scalar(select(func.count()).select_from(SalesUser)), count)

    def test_role_restrictions_csrf_and_logout(self):
        self.user()
        for route in ["/admin/vendedores", "/admin/vendedores/pedidos", "/admin/vendedores/comercios"]:
            self.assertEqual(self.client.get(route).status_code, 302)
        self.assertNotIn("Productos registrados", self.client.get("/admin").get_data(as_text=True))
        for route in ["/vendedor/nuevo", "/vendedor/resumen", "/vendedor/salir", "/admin/vendedores"]:
            self.assertEqual(self.client.post(route).status_code, 400)
        self.post("/vendedor/salir")
        self.assertEqual(self.client.get("/vendedor/").status_code, 302)

    def test_login_throttle(self):
        username = "unknown"+secrets.token_hex(4)
        for _ in range(8):
            self.assertEqual(self.post("/vendedor/ingresar", dict(username=username, password="incorrect")).status_code, 200)
        self.assertEqual(self.post("/vendedor/ingresar", dict(username=username, password="incorrect")).status_code, 429)

    def test_store_validation_reuse_and_switch(self):
        user = self.user(); p = self.product()
        response = self.post("/vendedor/nuevo", dict(name=""))
        self.assertIn("obligatorio", response.get_data(as_text=True))
        name = "Don " + secrets.token_hex(5)
        self.start(name); self.add(p, 2)
        count = db.session.scalar(select(func.count()).select_from(SalesStore).where(SalesStore.seller_id == user.id))
        self.start(name.upper())
        self.assertEqual(db.session.scalar(select(func.count()).select_from(SalesStore).where(SalesStore.seller_id == user.id)), count)
        response = self.start("Otro negocio")
        self.assertIn("Confirma el cambio", response.get_data(as_text=True))
        cart = db.session.scalar(select(SalesCart).where(SalesCart.seller_id == user.id))
        self.assertEqual(len(cart.items), 1)
        self.post("/vendedor/nuevo", dict(name="Otro negocio", confirm_switch="yes"))
        db.session.expire_all(); self.assertEqual(len(cart.items), 0)

    def test_catalog_filters_and_cart_quantities(self):
        user = self.user(); p = self.product(); self.start()
        response = self.client.get("/vendedor/catalogo?q="+p.name+"&categoria="+p.category.slug)
        self.assertIn(p.name, response.get_data(as_text=True))
        self.add(p, 2); self.add(p, 1)
        cart = db.session.scalar(select(SalesCart).where(SalesCart.seller_id == user.id))
        self.assertEqual(cart.items[0].quantity, 3)
        for qty in ["-1", "abc", "999999999", "1.5"]:
            self.post(f"/vendedor/carrito/{p.id}", dict(action="update", quantity=qty))
            db.session.expire_all(); self.assertEqual(cart.items[0].quantity, 3)
        self.post(f"/vendedor/carrito/{p.id}", dict(action="update", quantity="1"))
        db.session.expire_all(); self.assertEqual(cart.items[0].quantity, 1)
        self.post(f"/vendedor/carrito/{p.id}", dict(action="remove", quantity="0"))
        db.session.expire_all(); self.assertEqual(len(cart.items), 0)

    def test_complete_order_totals_idempotency_and_history_snapshots(self):
        user = self.user(); first = self.product(); second = self.product(price=65000)
        self.start(); self.add(first, 2); self.add(second, 3)
        quote = self.quote()
        response = self.post("/vendedor/resumen", dict(quote=quote, total="1", price="1"))
        self.assertEqual(response.status_code, 200)
        commercial = self.commercial(user)
        self.assertEqual(commercial.order.total, 435000)
        self.assertEqual(commercial.order.status, "Pendiente")
        self.assertEqual(len(commercial.order.items), 2)
        self.assertEqual(commercial.seller_id, user.id)
        self.assertEqual(commercial.store_snapshot["city"], "Asunción")
        self.assertEqual(db.session.get(Product, first.id).stock, 8)
        self.assertEqual(db.session.get(Product, second.id).stock, 7)
        oid = commercial.order_id
        self.post("/vendedor/resumen", dict(quote=quote))
        self.assertEqual(db.session.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.seller_id == user.id)), 1)
        self.assertEqual(db.session.get(Product, first.id).stock, 8)
        user.first_name = "Changed"; first.name = "Changed product"
        store = db.session.get(SalesStore, commercial.store_id); store.name = "Changed store"
        db.session.commit()
        html = self.client.get(f"/vendedor/pedidos/{oid}").get_data(as_text=True)
        self.assertIn("Juan Pérez", html); self.assertNotIn("Changed product", html); self.assertNotIn("Changed store", html)
        with self.client.get(f"/vendedor/pedidos/{oid}/resumen.pdf") as response:
            self.assertEqual(response.status_code, 200)
            text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(response.data)).pages)
            self.assertIn("435.000", text); self.assertIn("Juan Pérez", text); self.assertIn("0983620676", text)
        self.assertIsNotNone(db.session.scalar(select(SalesAudit).where(SalesAudit.event == "commercial_order_created", SalesAudit.subject_id == oid)))

    def test_changed_price_or_stock_requires_new_review(self):
        user = self.user(); p = self.product(); self.start(); self.add(p, 2)
        token = self.quote(); p.price = 130000; db.session.commit()
        response = self.post("/vendedor/resumen", dict(quote=token))
        self.assertIn("precio", response.get_data(as_text=True))
        self.assertIsNone(self.commercial(user)); self.assertEqual(db.session.get(Product, p.id).stock, 10)
        token = self.quote(); p.stock = 1; db.session.commit()
        self.post("/vendedor/resumen", dict(quote=token))
        self.assertIsNone(self.commercial(user)); self.assertEqual(db.session.get(Product, p.id).stock, 1)

    def test_two_sellers_are_isolated_and_public_cart_is_preserved(self):
        p = self.product(); user = self.user(); self.start(); self.add(p)
        token = self.quote(); self.post("/vendedor/resumen", dict(quote=token)); first_order = self.commercial(user)
        oid, store_id = first_order.order_id, first_order.store_id
        other = self.user(False)
        with self.client.session_transaction() as session: session["cart"] = {str(p.id): 2}
        self.post("/vendedor/ingresar", dict(username=other.username, password=PASSWORD))
        with self.client.session_transaction() as session: self.assertEqual(session["cart"], {str(p.id): 2})
        for suffix in ["", "/resumen.pdf"]:
            self.assertEqual(self.client.get(f"/vendedor/pedidos/{oid}"+suffix).status_code, 404)
        self.assertEqual(self.post("/vendedor/nuevo", dict(store_id=store_id), follow=False).status_code, 404)
        self.assertNotIn(f"Pedido comercial #{oid}", self.client.get("/vendedor/pedidos").get_data(as_text=True))
        self.post("/vendedor/resumen", dict(quote=token))
        self.assertIsNone(self.commercial(other))

    def test_transaction_failure_does_not_leave_partial_order(self):
        user = self.user(); p = self.product(); self.start(); self.add(p, 3); token = self.quote()
        customer_count = db.session.scalar(select(func.count()).select_from(Customer))
        csrf = self.csrf()
        with patch.object(db.session, "commit", side_effect=SQLAlchemyError("simulated commit failure")):
            response = self.client.post("/vendedor/resumen", data={"csrf_token": csrf, "quote": token})
        self.assertEqual(response.status_code, 503)
        db.session.expire_all()
        self.assertIsNone(self.commercial(user)); self.assertEqual(db.session.get(Product, p.id).stock, 10)
        self.assertEqual(db.session.scalar(select(func.count()).select_from(Customer)), customer_count)

    def test_admin_history_filters_status_audit_and_seller_readonly(self):
        user = self.user(); p = self.product(); self.start(); self.add(p); self.post("/vendedor/resumen", dict(quote=self.quote()))
        commercial = self.commercial(user); oid = commercial.order_id
        response = self.admin.get(f"/admin/vendedores/pedidos?seller={user.id}&q={commercial.store_name}&status=Pendiente")
        self.assertIn(f"Pedido comercial #{oid}", response.get_data(as_text=True))
        self.assertIn("Pedido comercial", self.admin.get("/admin").get_data(as_text=True))
        csrf = self.csrf(self.admin, "/admin")
        self.admin.post(f"/admin/pedidos/{oid}/estado", data={"csrf_token": csrf, "status": "Confirmado"})
        db.session.expire_all(); self.assertEqual(commercial.order.status, "Confirmado")
        self.assertEqual(db.session.get(Product, p.id).stock, 9)
        self.assertIsNotNone(db.session.scalar(select(SalesAudit).where(SalesAudit.event == "commercial_order_status", SalesAudit.subject_id == oid)))
        self.assertIn("Ventas efectivamente reconocidas", self.admin.get("/admin/vendedores").get_data(as_text=True))
        self.assertEqual(self.client.post(f"/vendedor/pedidos/{oid}", data={"csrf_token": self.csrf()}).status_code, 405)

    def test_paraguay_dates_and_date_filters(self):
        user = self.user(); p = self.product(); self.start(); self.add(p); self.post("/vendedor/resumen", dict(quote=self.quote()))
        commercial = self.commercial(user); oid = commercial.order_id
        commercial.order.created_at = datetime(2026, 11, 11, 2, 45, 37, tzinfo=timezone.utc); db.session.commit()
        self.assertEqual(paraguay_datetime(commercial.order.created_at).strftime("%d/%m/%Y %H:%M:%S"), "10/11/2026 23:45:37")
        self.assertIn("10/11/2026 23:45:37", self.client.get(f"/vendedor/pedidos/{oid}").get_data(as_text=True))
        self.assertIn(f"Pedido comercial #{oid}", self.client.get("/vendedor/pedidos?from=2026-11-10&to=2026-11-10").get_data(as_text=True))
        self.assertNotIn(f"Pedido comercial #{oid}", self.client.get("/vendedor/pedidos?from=2026-11-11").get_data(as_text=True))

    def test_postgres_concurrent_orders_cannot_oversell(self):
        if db.engine.dialect.name != "postgresql": self.skipTest("Requires PostgreSQL row locks")
        p = self.product(stock=5)
        jobs = []
        for _ in range(2):
            user = self.user(); self.start(); self.add(p, 3)
            jobs.append((self.client.get_cookie("session").value, self.quote(), self.csrf()))
        db.session.remove()
        def confirm(job):
            client = app.test_client(); client.set_cookie("session", job[0])
            return client.post("/vendedor/resumen", data={"quote": job[1], "csrf_token": job[2]}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(confirm, jobs))
        self.assertEqual(results, [302, 302])
        self.assertEqual(db.session.get(Product, p.id).stock, 2)
        count = db.session.scalar(select(func.count()).select_from(OrderItem).where(OrderItem.product_id == p.id))
        self.assertEqual(count, 1)

    def test_postgres_concurrent_duplicate_confirmation(self):
        if db.engine.dialect.name != "postgresql": self.skipTest("Requires PostgreSQL row locks")
        user = self.user(); p = self.product(); self.start(); self.add(p, 2)
        job = (self.client.get_cookie("session").value, self.quote(), self.csrf())
        db.session.remove()
        def confirm(_):
            client = app.test_client(); client.set_cookie("session", job[0])
            return client.post("/vendedor/resumen", data={"quote": job[1], "csrf_token": job[2]}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(confirm, range(2)))
        self.assertEqual(results, [302, 302])
        self.assertEqual(db.session.get(Product, p.id).stock, 8)
        self.assertEqual(db.session.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.seller_id == user.id)), 1)

    def test_additive_migrations_preserve_existing_data(self):
        engine = create_engine("sqlite:///:memory:")
        def module(name):
            spec = importlib.util.spec_from_file_location(name, Path("migrations/versions") / (name+".py"))
            value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
        baseline, commercial = module("0001_legacy"), module("0002_sales")
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                baseline.upgrade()
                connection.execute(db.metadata.tables["category"].insert(), dict(id=777, name="Existing category", slug="existing"))
                connection.execute(db.metadata.tables["product"].insert(), dict(id=777, category_id=777, name="Existing product", description="Preserve", price=98765, stock=19, image_url="", active=True, featured=False, created_at=datetime.now(timezone.utc)))
                baseline.upgrade()  # Existing-schema adoption must not recreate anything.
                commercial.upgrade()
                result = connection.execute(select(db.metadata.tables["product"]).where(db.metadata.tables["product"].c.id == 777)).mappings().one()
                self.assertEqual((result["price"], result["stock"], result["name"]), (98765, 19, "Existing product"))
                self.assertIn("sales_order", inspect(connection).get_table_names())

    def test_migrations_match_current_models(self):
        with db.engine.connect() as connection:
            self.assertEqual(compare_metadata(MigrationContext.configure(connection), db.metadata), [])

    def test_stale_cart_from_another_store_is_rejected(self):
        user = self.user(); p = self.product(); self.start(); self.add(p)
        cart = db.session.scalar(select(SalesCart).where(SalesCart.seller_id == user.id))
        old_key = cart.checkout_key
        self.post("/vendedor/nuevo", dict(name="Another store", confirm_switch="yes"))
        response = self.post(f"/vendedor/carrito/{p.id}", dict(cart_key=old_key, action="add", quantity="1"))
        self.assertIn("otra pestaña", response.get_data(as_text=True))
        db.session.expire_all(); self.assertEqual(len(cart.items), 0)

    def test_home_hero_has_seller_button_next_to_admin_and_login_works(self):
        class HeroLinks(HTMLParser):
            def __init__(self):
                super().__init__(); self.in_actions = False; self.current = None; self.links = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "div" and attrs.get("class") == "hero-actions": self.in_actions = True
                if self.in_actions and tag == "a": self.current = [attrs.get("href"), "", attrs.get("class", "")]
            def handle_data(self, value):
                if self.current is not None: self.current[1] += value
            def handle_endtag(self, tag):
                if tag == "a" and self.current is not None:
                    self.links.append(self.current); self.current = None
                if tag == "div" and self.in_actions: self.in_actions = False
        parser = HeroLinks(); parser.feed(self.client.get("/").get_data(as_text=True))
        labels = [text.strip() for href, text, classes in parser.links]
        index = labels.index("Acceso administrador")
        self.assertEqual(labels[index + 1], "Acceso vendedor")
        target, text, classes = parser.links[index + 1]
        self.assertEqual(target, "/vendedor/ingresar")
        self.assertIn("btn", classes.split())
        response = self.client.get(target)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Acceso de vendedores", response.get_data(as_text=True))


if __name__ == "__main__": unittest.main()
