"""Isolated checks. Never imports the production DATABASE_URL.

Run: tmp/python-runtime/python.exe -m unittest discover -s tests -v
ADMIN_TEST_DATABASE_URL may point to a disposable local PostgreSQL database.
"""
import io
import os
import re
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

test_database = os.environ.get("ADMIN_TEST_DATABASE_URL", "sqlite:///:memory:")
if test_database != "sqlite:///:memory:" and not test_database.startswith("postgresql+psycopg://admin_test:"):
    raise RuntimeError("Only an isolated admin_test PostgreSQL role is allowed")
os.environ["DATABASE_URL"] = test_database
os.environ["SECRET_KEY"] = "isolated-admin-tests-only"
os.environ["ADMIN_USERNAME"] = "isolated-admin"
os.environ["ADMIN_PASSWORD"] = "isolated-tests-only"
os.environ["COOKIE_SECURE"] = "false"

from PIL import Image
from flask import g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app import app, db, Category, Product, News, Customer, Order, OrderItem, _cleanup_product_image
from flask_migrate import upgrade

with app.app_context():
    upgrade()


class ProductAdministrationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.uploads = tempfile.TemporaryDirectory(prefix="admin-test-")
        app.config["UPLOAD_FOLDER"] = self.uploads.name
        self.client = app.test_client()
        self.context = app.app_context()
        self.context.push()
        with self.client.session_transaction() as session:
            session["admin_authenticated"] = True

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        self.context.pop()
        self.uploads.cleanup()

    def product(self, **kwargs):
        values = dict(name="Prueba " + secrets.token_hex(5), category_id=db.session.scalar(select(Category.id)), price=125000, stock=10, active=True)
        values.update(kwargs)
        product = Product(**values)
        db.session.add(product)
        db.session.commit()
        return product

    def photo(self):
        filename = secrets.token_hex(16) + ".png"
        path = Path(self.uploads.name) / filename
        Image.new("RGB", (16, 16), "navy").save(path)
        return "/uploads/" + filename, path

    def token(self):
        g.pop("csrf_token", None)
        html = self.client.get("/admin").get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, pid, action, data=None):
        return self.client.post(f"/admin/productos/{pid}/{action}", data={"csrf_token": self.token(), **(data or {})}, follow_redirects=True)

    def fresh(self, pid):
        db.session.remove()
        return db.session.get(Product, pid)

    def test_authorization_csrf_and_methods(self):
        p = self.product()
        for action in ["editar", "foto", "foto/eliminar", "activar", "desactivar", "eliminar"]:
            path = f"/admin/productos/{p.id}/{action}"
            self.assertEqual(self.client.get(path).status_code, 405)
            self.assertEqual(self.client.post(path).status_code, 400)
            anonymous = app.test_client()
            g.pop("csrf_token", None)
            html = anonymous.get("/admin").get_data(as_text=True)
            token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
            result = anonymous.post(path, data={"csrf_token": token, "confirm": "yes"})
            self.assertEqual(result.status_code, 302)
            self.assertTrue(result.location.endswith("/admin"))
        self.assertIsNotNone(self.fresh(p.id))

    def test_photo_delete_and_reupload_preserves_product_fields(self):
        url, path = self.photo()
        p = self.product(image_url=url)
        pid = p.id
        self.assertEqual(self.post(pid, "foto/eliminar", {"confirm": "yes", "expected_image_url": url}).status_code, 200)
        p = self.fresh(pid)
        self.assertEqual((p.image_url, p.price, p.stock, p.active), ("", 125000, 10, True))
        self.assertFalse(path.exists())
        self.assertIn("Sin fotografía", self.client.get("/admin").get_data(as_text=True))
        image = io.BytesIO(); Image.new("RGB", (12, 12), "gold").save(image, format="PNG"); image.seek(0)
        response = self.post(pid, "foto", {"expected_image_url": "", "image": (image, "new.png")})
        self.assertEqual(response.status_code, 200)
        p = self.fresh(pid)
        self.assertTrue(p.image_url.startswith("/uploads/"))
        self.assertTrue((Path(self.uploads.name) / p.image_url.split("/")[-1]).exists())
        self.assertEqual((p.price, p.stock), (125000, 10))

    def test_shared_images_and_external_files_are_preserved(self):
        url, path = self.photo()
        p = self.product(image_url=url)
        other = self.product(image_url=url)
        note = News(title="Shared image", content="test", image_url="https://samudiohnos.com" + url + "?v=1")
        db.session.add(note); db.session.commit()
        self.post(p.id, "foto/eliminar", {"confirm": "yes", "expected_image_url": url})
        self.assertTrue(path.exists())
        self.post(other.id, "eliminar", {"confirm": "yes"})
        self.assertTrue(path.exists())  # News still refers to it.
        db.session.delete(note); db.session.commit()
        self.assertTrue(_cleanup_product_image(url)); self.assertFalse(path.exists())
        sentinel = Path(self.uploads.name) / "keep.txt"; sentinel.write_text("keep")
        for url in ["https://example.com/image.jpg", "/static/img/logo-samudio-hnos.png", "/uploads/../keep.txt", "/uploads/keep.txt"]:
            p = self.product(image_url=url)
            self.post(p.id, "foto/eliminar", {"confirm": "yes", "expected_image_url": url})
        self.assertEqual(sentinel.read_text(), "keep")

    def test_stale_selection_and_confirmation(self):
        url, path = self.photo(); p = self.product(image_url=url)
        for data in [{"expected_image_url": url}, {"confirm": "yes", "expected_image_url": "/old.png"}]:
            self.post(p.id, "foto/eliminar", data)
            self.assertEqual(self.fresh(p.id).image_url, url)
        self.post(p.id, "eliminar")
        self.assertIsNotNone(self.fresh(p.id)); self.assertTrue(path.exists())
        response = self.post(2147483647, "eliminar", {"confirm": "yes"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("ya no está disponible", response.get_data(as_text=True))

    def test_database_failure_retains_old_photo_and_cleans_new_upload(self):
        url, path = self.photo(); p = self.product(image_url=url); pid = p.id
        with patch.object(db.session, "commit", side_effect=SQLAlchemyError("test failure")):
            self.post(pid, "foto/eliminar", {"confirm": "yes", "expected_image_url": url})
        self.assertEqual(self.fresh(pid).image_url, url); self.assertTrue(path.exists())
        image = io.BytesIO(); Image.new("RGB", (12, 12)).save(image, format="PNG"); image.seek(0)
        with patch.object(db.session, "commit", side_effect=SQLAlchemyError("test failure")):
            self.post(pid, "foto", {"expected_image_url": url, "image": (image, "replacement.png")})
        self.assertEqual(self.fresh(pid).image_url, url)
        self.assertEqual(len(list(Path(self.uploads.name).iterdir())), 1)

    def test_cleanup_failure_is_reported_after_safe_database_commit(self):
        url, path = self.photo(); p = self.product(image_url=url); pid = p.id
        with patch.object(Path, "unlink", side_effect=PermissionError("test storage failure")):
            response = self.post(pid, "foto/eliminar", {"confirm": "yes", "expected_image_url": url})
        self.assertEqual(self.fresh(pid).image_url, "")
        self.assertTrue(path.exists())
        self.assertIn("no se pudo quitar el archivo", response.get_data(as_text=True))

    def test_activation_and_catalog_and_cart(self):
        p = self.product(); pid = p.id; name = p.name
        self.client.post(f"/carrito/agregar/{pid}", data={"csrf_token": self.token()})
        self.assertIn(name, self.client.get("/carrito").get_data(as_text=True))
        self.post(pid, "desactivar")
        self.assertFalse(self.fresh(pid).active)
        self.assertNotIn(name, self.client.get("/catalogo").get_data(as_text=True))
        self.assertNotIn(name, self.client.get("/carrito").get_data(as_text=True))
        self.post(pid, "activar")
        self.assertTrue(self.fresh(pid).active)
        self.assertIn(name, self.client.get("/catalogo").get_data(as_text=True))

    def test_delete_without_orders_cleans_file(self):
        url, path = self.photo(); p = self.product(image_url=url); pid = p.id
        self.post(pid, "eliminar", {"confirm": "yes"})
        self.assertIsNone(self.fresh(pid)); self.assertFalse(path.exists())

    def test_history_is_preserved(self):
        url, path = self.photo(); p = self.product(image_url=url); pid = p.id
        customer = Customer(name="Historical customer", phone="0981000000", city="Test")
        order = Order(customer=customer, total=250000, status="Pendiente")
        order.items.append(OrderItem(product_id=pid, quantity=2, unit_price=125000))
        db.session.add(order); db.session.commit(); oid = order.id; cid = customer.id
        response = self.post(pid, "eliminar", {"confirm": "yes"})
        p = self.fresh(pid)
        self.assertFalse(p.active); self.assertEqual(p.image_url, url); self.assertTrue(path.exists())
        order = db.session.get(Order, oid)
        self.assertEqual((order.total, order.customer_id, order.items[0].quantity, order.items[0].unit_price), (250000, cid, 2, 125000))
        with self.client.get(f"/pedidos/{oid}/resumen.pdf") as pdf:
            self.assertEqual(pdf.status_code, 200)
        self.assertIn("historial de pedidos", response.get_data(as_text=True))

    def test_integrity_failure_does_not_remove_product_or_file(self):
        url, path = self.photo(); p = self.product(image_url=url); pid = p.id
        with patch.object(db.session, "commit", side_effect=IntegrityError("test", {}, Exception("reference"))):
            self.post(pid, "eliminar", {"confirm": "yes"})
        self.assertIsNotNone(self.fresh(pid)); self.assertTrue(path.exists())

    def test_edit_and_invalid_upload_are_separate_actions(self):
        p = self.product(); pid = p.id
        data = dict(name="Edited product", category_id=str(p.category_id), price="90000", stock="7", description="Updated", featured="on")
        self.post(pid, "editar", data)
        p = self.fresh(pid)
        self.assertEqual((p.name, p.price, p.stock, p.image_url, p.featured), ("Edited product", 90000, 7, "", True))
        self.post(pid, "editar", {**data, "price": "-1"})
        self.assertEqual(self.fresh(pid).price, 90000)
        self.post(pid, "foto", {"expected_image_url": "", "image": (io.BytesIO(b"not-image"), "fake.png")})
        self.assertEqual(self.fresh(pid).image_url, "")

    def test_admin_only_styles_and_templates(self):
        for template in app.jinja_env.list_templates(): app.jinja_env.get_template(template)
        admin = self.client.get("/admin").get_data(as_text=True)
        self.assertIn('class="admin-theme"', admin); self.assertIn("css/admin.css", admin)
        for route in ["/", "/catalogo", "/novedades", "/carrito"]:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("css/admin.css", response.get_data(as_text=True))
        for path in ["/static/css/admin.css", "/static/js/admin-products.js"]:
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
