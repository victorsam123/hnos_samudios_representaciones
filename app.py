from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
import unicodedata
import warnings
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import urlencode

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    send_file,
    send_from_directory,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, generate_csrf
from itsdangerous import BadSignature, URLSafeSerializer
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from local_time import PARAGUAY_TIMEZONE, format_paraguay_datetime

load_dotenv()

db = SQLAlchemy()
csrf = CSRFProtect()
F = TypeVar("F", bound=Callable[..., Any])


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    slug = db.Column(db.String(100), nullable=False, unique=True)
    products = db.relationship("Product", back_populates="category")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(
        db.Integer, db.ForeignKey("category.id"), nullable=False, index=True
    )
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    price = db.Column(db.Integer, nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    image_url = db.Column(db.String(500), nullable=False, default="")
    featured = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    category = db.relationship("Category", back_populates="products")


class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(250), nullable=False, default="")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(
        db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True
    )
    total = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(40), nullable=False, default="Pendiente")
    notes = db.Column(db.String(1000), nullable=False, default="")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    customer = db.relationship("Customer")
    items = db.relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(
        db.Integer, db.ForeignKey("order.id"), nullable=False, index=True
    )
    product_id = db.Column(
        db.Integer, db.ForeignKey("product.id"), nullable=False
    )
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Integer, nullable=False)
    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product")


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        database_path = Path(__file__).resolve().parent / "instance" / "store.db"
        return f"sqlite:///{database_path.as_posix()}"
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _category_slug(name: str) -> str:
    normalized = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    )
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _seed_categories() -> None:
    categories = (
        ("Bazar", "bazar"),
        ("Bicicletas", "bicicletas"),
        ("Artículos para bebés", "articulos-bebes"),
        ("Camping", "camping"),
        ("Artículos de cocina", "articulos-cocina"),
        ("Termos", "termos"),
    )
    existing_slugs = set(db.session.scalars(select(Category.slug)).all())
    for name, slug in categories:
        if slug not in existing_slugs:
            db.session.add(Category(name=name, slug=slug))
    db.session.commit()


def _cart_contents() -> list[dict[str, Any]]:
    raw_cart = session.get("cart", {})
    if not isinstance(raw_cart, dict):
        session.pop("cart", None)
        return []

    quantities: dict[int, int] = {}
    for raw_id, raw_quantity in raw_cart.items():
        try:
            product_id = int(raw_id)
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and quantity > 0:
            quantities[product_id] = quantity

    if not quantities:
        session["cart"] = {}
        return []

    products = db.session.scalars(
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.id.in_(quantities), Product.active.is_(True))
    ).all()
    items = []
    valid_cart: dict[str, int] = {}
    for product in products:
        quantity = min(quantities[product.id], product.stock)
        if quantity <= 0:
            continue
        valid_cart[str(product.id)] = quantity
        items.append(
            {
                "product": product,
                "quantity": quantity,
                "subtotal": product.price * quantity,
            }
        )
    session["cart"] = valid_cart
    return items


def _cart_count() -> int:
    return sum(item["quantity"] for item in _cart_contents())


def _admin_required(view: F) -> F:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not session.get("admin_authenticated"):
            flash("Inicia sesión para acceder a la administración.", "error")
            return redirect(url_for("admin"))
        return view(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def _save_uploaded_image() -> str:
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        return ""

    extensions = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".webp": "WEBP",
        ".gif": "GIF",
    }
    extension = Path(upload.filename).suffix.lower()
    if extension not in extensions:
        raise ValueError("Selecciona una imagen JPG, PNG, WEBP o GIF.")

    upload.stream.seek(0, 2)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > 5 * 1024 * 1024:
        raise ValueError("La imagen no debe superar los 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload.stream) as image:
                if image.format != extensions[extension]:
                    raise ValueError("El formato de la imagen no coincide con su extensión.")
                image.verify()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("El archivo no es una imagen válida o es demasiado grande.") from exc
    upload.stream.seek(0)

    folder = Path(app.config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(16)}{extension}"
    upload.save(folder / filename)
    return url_for("uploaded_image", filename=filename)


def _format_money(value: int | float) -> str:
    return f"{int(value):,}".replace(",", ".") + " Gs."


app = Flask(__name__, instance_relative_config=True)
os.makedirs(app.instance_path, exist_ok=True)

secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    secret_key = secrets.token_hex(32)
    logging.warning(
        "SECRET_KEY is not configured; sessions will not survive application restarts."
    )

app.config.from_mapping(
    SECRET_KEY=secret_key,
    SQLALCHEMY_DATABASE_URI=_database_url(),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    WTF_CSRF_TIME_LIMIT=3600,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "").lower() == "true",
    ADMIN_USERNAME=os.getenv("ADMIN_USERNAME", "").strip(),
    ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", ""),
    WHATSAPP_NUMBER=os.getenv("WHATSAPP_NUMBER", "595983620676"),
    UPLOAD_FOLDER=str(Path(app.instance_path) / "uploads"),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)
db.init_app(app)
csrf.init_app(app)


@app.errorhandler(413)
def upload_too_large(error):
    flash("La carga es demasiado grande. Selecciona una imagen de hasta 5 MB.", "error")
    return redirect(url_for("admin"))


@app.get("/uploads/<filename>")
def uploaded_image(filename: str):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.context_processor
def inject_template_values() -> dict[str, Any]:
    return {
        "now_year": datetime.now(PARAGUAY_TIMEZONE).year,
        "whatsapp": app.config["WHATSAPP_NUMBER"],
        "cart_count": _cart_count(),
        "csrf_token": generate_csrf,
    }


@app.template_filter("money")
def money(value: int | float) -> str:
    return _format_money(value)


@app.template_filter("paraguay_date")
def paraguay_date(value: datetime, date_only: bool = False) -> str:
    return format_paraguay_datetime(value, date_only=date_only)


with app.app_context():
    db.create_all()
    _seed_categories()


@app.get("/")
def index() -> str:
    categories = db.session.scalars(select(Category).order_by(Category.name)).all()
    featured = db.session.scalars(
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.active.is_(True))
        .order_by(Product.featured.desc(), Product.created_at.desc())
        .limit(8)
    ).all()
    news = db.session.scalars(
        select(News).order_by(News.created_at.desc()).limit(3)
    ).all()
    return render_template(
        "index.html", categories=categories, products=featured, news=news
    )


@app.get("/catalogo")
def catalogo() -> str:
    search = request.args.get("q", "").strip()[:100]
    category_slug = request.args.get("categoria", "").strip()[:100]
    query = (
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.active.is_(True))
        .order_by(Product.created_at.desc())
    )
    if search:
        query = query.where(Product.name.ilike(f"%{search}%"))
    if category_slug:
        query = query.join(Product.category).where(Category.slug == category_slug)
    products = db.session.scalars(query).all()
    categories = db.session.scalars(select(Category).order_by(Category.name)).all()
    return render_template(
        "catalogo.html",
        products=products,
        categories=categories,
        search=search,
        category_slug=category_slug,
    )


@app.get("/catalogo/pdf")
def descargar_catalogo_pdf():
    from catalog_pdf import build_catalog_pdf

    products = db.session.scalars(
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.active.is_(True))
        .order_by(Product.created_at.desc())
    ).all()
    pdf = build_catalog_pdf(
        products, app.config["UPLOAD_FOLDER"], app.static_folder
    )
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="catalogo-wilson-samudio.pdf",
        max_age=0,
    )


@app.get("/producto/<int:product_id>")
def producto(product_id: int) -> str:
    product = db.session.scalar(
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.id == product_id, Product.active.is_(True))
    )
    if product is None:
        abort(404)
    return render_template("producto.html", product=product)


@app.get("/carrito")
def carrito() -> str:
    items = _cart_contents()
    total = sum(item["subtotal"] for item in items)
    return render_template("carrito.html", items=items, total=total)


@app.post("/carrito/agregar/<int:product_id>")
def agregar_carrito(product_id: int):
    product = db.session.get(Product, product_id)
    if product is None or not product.active:
        abort(404)
    if product.stock < 1:
        flash("Este producto no tiene unidades disponibles.", "error")
        return redirect(url_for("catalogo"))

    cart = session.get("cart", {})
    if not isinstance(cart, dict):
        cart = {}
    current_quantity = cart.get(str(product_id), 0)
    try:
        current_quantity = int(current_quantity)
    except (TypeError, ValueError):
        current_quantity = 0
    cart[str(product_id)] = min(current_quantity + 1, product.stock)
    session["cart"] = cart
    flash(f"{product.name} se agregó al carrito.", "success")
    return redirect(url_for("catalogo"))


@app.post("/carrito/actualizar/<int:product_id>")
def actualizar_carrito(product_id: int):
    cart = session.get("cart", {})
    if not isinstance(cart, dict):
        cart = {}
    product = db.session.get(Product, product_id)
    if product is None or not product.active:
        cart.pop(str(product_id), None)
        session["cart"] = cart
        flash("El producto ya no está disponible.", "error")
        return redirect(url_for("carrito"))

    try:
        quantity = int(request.form.get("quantity", ""))
    except ValueError:
        flash("Ingresa una cantidad válida.", "error")
        return redirect(url_for("carrito"))
    if quantity < 0:
        flash("La cantidad no puede ser negativa.", "error")
    elif quantity == 0:
        cart.pop(str(product_id), None)
        flash("Producto eliminado del carrito.", "success")
    elif quantity > product.stock:
        flash(f"Solo hay {product.stock} unidad(es) disponibles.", "error")
    else:
        cart[str(product_id)] = quantity
        flash("Carrito actualizado.", "success")
    session["cart"] = cart
    return redirect(url_for("carrito"))


@app.post("/carrito/eliminar/<int:product_id>")
def eliminar_carrito(product_id: int):
    cart = session.get("cart", {})
    if isinstance(cart, dict):
        cart.pop(str(product_id), None)
    else:
        cart = {}
    session["cart"] = cart
    flash("Producto eliminado del carrito.", "success")
    return redirect(url_for("carrito"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    items = _cart_contents()
    if not items:
        flash("Agrega productos al carrito antes de continuar.", "error")
        return redirect(url_for("carrito"))
    total = sum(item["subtotal"] for item in items)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        city = request.form.get("city", "").strip()
        address = request.form.get("address", "").strip()
        notes = request.form.get("notes", "").strip()
        if not name or not phone or not city:
            flash("Completa tu nombre, teléfono y ciudad.", "error")
            return render_template("checkout.html", items=items, total=total)

        customer = Customer(
            name=name[:160],
            phone=phone[:30],
            city=city[:120],
            address=address[:250],
        )
        order = Order(
            customer=customer, total=total, notes=notes[:1000], status="Pendiente"
        )
        db.session.add(order)
        db.session.flush()
        for item in items:
            product = item["product"]
            quantity = item["quantity"]
            result = db.session.execute(
                update(Product)
                .where(
                    Product.id == product.id,
                    Product.active.is_(True),
                    Product.stock >= quantity,
                )
                .values(stock=Product.stock - quantity)
            )
            if result.rowcount != 1:
                db.session.rollback()
                flash(
                    f"No hay suficiente stock de {product.name}. Revisa tu carrito.",
                    "error",
                )
                return redirect(url_for("carrito"))
            order.items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=product.price,
                )
            )
        db.session.commit()

        session["cart"] = {}
        message = (
            f"Hola, realicé el pedido #{order.id}. "
            f"Total: {_format_money(order.total)}."
        )
        whatsapp_url = (
            f"https://wa.me/{app.config['WHATSAPP_NUMBER']}?"
            f"{urlencode({'text': message})}"
        )
        return render_template(
            "checkout.html",
            completed=True,
            order=order,
            whatsapp_url=whatsapp_url,
            summary_token=URLSafeSerializer(
                app.config["SECRET_KEY"], salt="order-summary"
            ).dumps(order.id),
        )

    return render_template("checkout.html", items=items, total=total)


@app.get("/pedidos/<int:order_id>/resumen.pdf")
def descargar_resumen_pedido(order_id: int):
    if not session.get("admin_authenticated"):
        try:
            authorized_id = URLSafeSerializer(
                app.config["SECRET_KEY"], salt="order-summary"
            ).loads(request.args.get("token", ""))
        except BadSignature:
            abort(404)
        if authorized_id != order_id:
            abort(404)

    order = db.session.scalar(
        select(Order)
        .options(
            joinedload(Order.customer),
            joinedload(Order.items).joinedload(OrderItem.product),
        )
        .where(Order.id == order_id)
    )
    if order is None:
        abort(404)

    from order_pdf import build_order_pdf

    response = send_file(
        build_order_pdf(order), mimetype="application/pdf", as_attachment=True,
        download_name=f"pedido-{order.id}-wilson-samudio.pdf",
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/novedades")
def novedades() -> str:
    news = db.session.scalars(select(News).order_by(News.created_at.desc())).all()
    return render_template("novedades.html", news=news)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        configured_username = app.config["ADMIN_USERNAME"]
        configured_password = app.config["ADMIN_PASSWORD"]
        if not configured_username or not configured_password:
            flash(
                "La administración no está configurada. Define ADMIN_USERNAME "
                "y ADMIN_PASSWORD en el archivo .env.",
                "error",
            )
        elif hmac.compare_digest(username, configured_username) and hmac.compare_digest(
            password, configured_password
        ):
            session.clear()
            session["admin_authenticated"] = True
            flash("Sesión iniciada correctamente.", "success")
            return redirect(url_for("admin"))
        else:
            flash("Usuario o contraseña incorrectos.", "error")

    if not session.get("admin_authenticated"):
        return render_template("login.html")

    products = db.session.scalars(
        select(Product)
        .options(joinedload(Product.category))
        .order_by(Product.created_at.desc())
    ).all()
    categories = db.session.scalars(select(Category).order_by(Category.name)).all()
    orders = db.session.scalars(
        select(Order)
        .options(joinedload(Order.customer))
        .order_by(Order.created_at.desc())
        .limit(50)
    ).all()
    news = db.session.scalars(
        select(News).order_by(News.created_at.desc()).limit(50)
    ).all()
    return render_template(
        "admin.html", products=products, categories=categories, orders=orders, news=news
    )


@app.post("/admin/logout")
def logout():
    session.pop("admin_authenticated", None)
    flash("Sesión cerrada.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/categorias")
@_admin_required
def crear_categoria():
    name = " ".join(request.form.get("name", "").split())
    slug = _category_slug(name)
    if not name or len(name) > 80 or not slug:
        flash(
            "Ingresa un nombre de categoría de hasta 80 caracteres con letras o números.",
            "error",
        )
        return redirect(url_for("admin"))

    categories = db.session.scalars(select(Category)).all()
    if any(
        category.slug == slug or _category_slug(category.name) == slug
        for category in categories
    ):
        flash("Ya existe una categoría con ese nombre.", "error")
        return redirect(url_for("admin"))

    db.session.add(Category(name=name, slug=slug))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Ya existe una categoría con ese nombre.", "error")
        return redirect(url_for("admin"))
    flash(
        "Categoría agregada. Ya está disponible en el catálogo y al cargar productos.",
        "success",
    )
    return redirect(url_for("admin"))


@app.post("/admin/productos")
@_admin_required
def crear_producto():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    try:
        category_id = int(request.form.get("category_id", ""))
        price = int(request.form.get("price", ""))
        stock = int(request.form.get("stock", ""))
    except ValueError:
        flash("Categoría, precio y stock deben ser valores válidos.", "error")
        return redirect(url_for("admin"))
    category = db.session.get(Category, category_id)
    if (
        not name
        or category is None
        or price < 0
        or stock < 0
    ):
        flash("Revisa los datos del producto e inténtalo nuevamente.", "error")
        return redirect(url_for("admin"))

    try:
        image_url = _save_uploaded_image()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin"))

    db.session.add(
        Product(
            name=name[:160],
            category=category,
            price=price,
            stock=stock,
            image_url=image_url[:500],
            description=description[:5000],
            featured="featured" in request.form,
        )
    )
    db.session.commit()
    flash("Producto creado correctamente.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/productos/<int:product_id>/desactivar")
@_admin_required
def desactivar_producto(product_id: int):
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    product.active = False
    db.session.commit()
    flash("Producto desactivado.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/novedades")
@_admin_required
def crear_novedad():
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    if not title or not content:
        flash("Revisa el título y contenido de la novedad.", "error")
        return redirect(url_for("admin"))
    try:
        image_url = _save_uploaded_image()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin"))
    db.session.add(
        News(
            title=title[:180],
            content=content[:10000],
            image_url=image_url[:500],
        )
    )
    db.session.commit()
    flash("Novedad publicada.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/pedidos/<int:order_id>/estado")
@_admin_required
def cambiar_estado_pedido(order_id: int):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    allowed_statuses = {
        "Pendiente",
        "Confirmado",
        "En preparación",
        "Enviado",
        "Entregado",
        "Cancelado",
    }
    status = request.form.get("status", "")
    if status not in allowed_statuses:
        flash("El estado indicado no es válido.", "error")
        return redirect(url_for("admin"))
    order.status = status
    db.session.commit()
    flash(f"El pedido #{order.id} se actualizó.", "success")
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "").lower() == "true")
