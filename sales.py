"""Commercial accounts and ordering, isolated from the public shopping cart."""
from datetime import date, datetime, time, timedelta, timezone
from functools import wraps
import hashlib
import re
import secrets

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from local_time import PARAGUAY_TIMEZONE, paraguay_datetime
from sales_models import SalesUser, SalesStore, SalesCart, SalesCartItem, SalesOrder, SalesAudit, SalesLoginThrottle, utcnow

STATUSES = ("Pendiente", "Confirmado", "En preparación", "Enviado", "Entregado", "Cancelado")


def init_sales(app, models, admin_required):
    Product, Category, Customer, Order, OrderItem = models
    bp = Blueprint("sales", __name__)
    dummy_hash = generate_password_hash(secrets.token_hex(24))

    @app.template_filter("sales_datetime")
    def sales_datetime(value):
        return paraguay_datetime(value).strftime("%d/%m/%Y %H:%M:%S")

    def audit(event, subject=None, **details):
        actor = "administrador" if session.get("admin_authenticated") else f"vendedor:{g.sales_user.id}"
        db.session.add(SalesAudit(actor=actor, event=event, subject_id=subject, details=details))

    def seller_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = db.session.get(SalesUser, session.get("sales_user_id")) if session.get("sales_user_id") else None
            if not user or not user.active or user.role != "vendedor" or user.auth_version != session.get("sales_auth_version"):
                session.pop("sales_user_id", None)
                session.pop("sales_auth_version", None)
                flash("Inicia sesión con tu cuenta de vendedor.", "error")
                return redirect(url_for("sales.login"))
            g.sales_user = user
            return view(*args, **kwargs)
        return wrapped

    def lock_user():
        user = db.session.scalar(select(SalesUser).where(SalesUser.id == g.sales_user.id).with_for_update().execution_options(populate_existing=True))
        if not user or not user.active or user.role != "vendedor" or user.auth_version != session.get("sales_auth_version"):
            abort(403)
        g.sales_user = user
        return user

    def cart_for_user(create=False):
        cart = db.session.scalar(select(SalesCart).where(SalesCart.seller_id == g.sales_user.id))
        if not cart and create:
            cart = SalesCart(seller_id=g.sales_user.id)
            db.session.add(cart)
            db.session.flush()
        return cart

    def cart_rows(cart):
        rows = []
        if cart:
            for item in cart.items:
                product = item.product
                valid = bool(product and product.active and 0 < item.quantity <= product.stock)
                rows.append(dict(product=product, quantity=item.quantity, subtotal=product.price * item.quantity if product else 0, valid=valid))
        return rows

    def touch_cart(cart):
        cart.revision += 1

    def serializer():
        return URLSafeSerializer(app.config["SECRET_KEY"], salt="commercial-quote-v1")

    def quote(cart, rows):
        return dict(seller=g.sales_user.id, key=cart.checkout_key, revision=cart.revision,
                    items=sorted([[r["product"].id, r["quantity"], r["product"].price] for r in rows]))

    def bounded(name, maximum, required=False):
        value = request.form.get(name, "").strip()
        if len(value) > maximum or (required and not value):
            raise ValueError(f"Revisa el campo {name}: es obligatorio o supera el largo permitido.")
        return value

    def password_value():
        password = request.form.get("password", "")
        groups = sum(bool(re.search(pattern, password)) for pattern in [r"[a-z]", r"[A-Z]", r"[0-9]", r"[^a-zA-Z0-9]"])
        if not 12 <= len(password) <= 128 or groups < 3:
            raise ValueError("Usa una contraseña de 12 a 128 caracteres y combina al menos tres de estos grupos: minúsculas, mayúsculas, números y símbolos.")
        return password

    def account_fields():
        first = bounded("first_name", 100, True)
        last = bounded("last_name", 100, True)
        username = bounded("username", 50, True).lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,49}", username):
            raise ValueError("El usuario debe tener de 3 a 50 letras sin acentos, números, puntos, guiones o guiones bajos.")
        if username == app.config["ADMIN_USERNAME"].lower():
            raise ValueError("Ese nombre de usuario está reservado.")
        return first, last, username

    @bp.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Referrer-Policy"] = "same-origin"
        response.vary.add("Cookie")
        return response

    @bp.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.exception("Commercial operation failed")
        return render_template("sales/error.html"), 503

    @bp.context_processor
    def commercial_context():
        return dict(sales_now=utcnow(), sales_user=getattr(g, "sales_user", None), sales_statuses=STATUSES)

    @bp.route("/vendedor/ingresar", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()[:50]
            password = request.form.get("password", "")[:129]
            key = hashlib.sha256(f"{request.remote_addr}:{username}".encode()).hexdigest()
            # Upsert under a savepoint handles concurrent first login attempts.
            throttle = db.session.get(SalesLoginThrottle, key)
            if not throttle:
                try:
                    with db.session.begin_nested():
                        db.session.add(SalesLoginThrottle(key=key))
                        db.session.flush()
                except IntegrityError:
                    pass
            throttle = db.session.scalar(select(SalesLoginThrottle).where(SalesLoginThrottle.key == key).with_for_update())
            window_start = throttle.window_start
            if window_start.tzinfo is None:
                window_start = window_start.replace(tzinfo=timezone.utc)
            if utcnow() - window_start > timedelta(minutes=15):
                throttle.attempts = 0
                throttle.window_start = utcnow()
            if throttle.attempts >= 8:
                flash("Demasiados intentos. Espera 15 minutos antes de intentar de nuevo.", "error")
                return render_template("sales/login.html"), 429
            user = db.session.scalar(select(SalesUser).where(SalesUser.username == username))
            valid = check_password_hash(user.password_hash if user else dummy_hash, password)
            if valid and user and user.active and user.role == "vendedor":
                throttle.attempts = 0
                public_cart = session.get("cart", {})
                session.clear()
                session["cart"] = public_cart
                session["sales_user_id"] = user.id
                session["sales_auth_version"] = user.auth_version
                g.sales_user = user
                audit("seller_login", user.id)
                db.session.commit()
                return redirect(url_for("sales.dashboard"))
            throttle.attempts += 1
            db.session.add(SalesAudit(actor="anonymous", event="seller_login_failed", details={"key": key}))
            db.session.commit()
            flash("Usuario o contraseña incorrectos, o cuenta desactivada.", "error")
        return render_template("sales/login.html")

    @bp.post("/vendedor/salir")
    @seller_required
    def logout():
        audit("seller_logout", g.sales_user.id)
        db.session.commit()
        public_cart = session.get("cart", {})
        session.clear()
        session["cart"] = public_cart
        return redirect(url_for("sales.login"))

    @bp.get("/vendedor/")
    @seller_required
    def dashboard():
        count, total = db.session.execute(select(func.count(), func.coalesce(func.sum(Order.total), 0)).select_from(SalesOrder).join(Order).where(SalesOrder.seller_id == g.sales_user.id)).one()
        return render_template("sales/dashboard.html", count=count, total=total, cart=cart_for_user())

    @bp.route("/vendedor/nuevo", methods=["GET", "POST"])
    @seller_required
    def new_order():
        if request.method == "POST":
            try:
                lock_user()
                cart = cart_for_user(True)
                selected = request.form.get("store_id", "")
                if selected:
                    store = db.session.get(SalesStore, int(selected))
                    if not store or store.seller_id != g.sales_user.id:
                        abort(404)
                else:
                    name = bounded("name", 160, True)
                    normalized = " ".join(name.casefold().split())
                    if len(normalized) > 160:
                        raise ValueError("El nombre del comercio supera el largo permitido.")
                    store = db.session.scalar(select(SalesStore).where(SalesStore.seller_id == g.sales_user.id, SalesStore.normalized_name == normalized))
                    if not store:
                        store = SalesStore(seller_id=g.sales_user.id, name=name, normalized_name=normalized,
                                           responsible=bounded("responsible", 160), phone=bounded("phone", 30), city=bounded("city", 120),
                                           address=bounded("address", 250), notes=bounded("notes", 1000))
                        db.session.add(store)
                        db.session.flush()
                if cart.items and cart.store_id != store.id:
                    if request.form.get("confirm_switch") != "yes":
                        raise ValueError("Tienes un carrito abierto. Confirma el cambio de comercio para vaciarlo o continúa el pedido actual.")
                    cart.items.clear()
                if cart.store_id != store.id:
                    cart.checkout_key = secrets.token_hex(24)
                    cart.notes = store.notes
                cart.store_id = store.id
                touch_cart(cart)
                audit("commercial_store_selected", store.id)
                db.session.commit()
                return redirect(url_for("sales.catalog"))
            except (ValueError, IntegrityError) as error:
                db.session.rollback()
                flash(str(error) if isinstance(error, ValueError) else "No se pudo registrar el comercio. Revisa si ya existe.", "error")
        stores = db.session.scalars(select(SalesStore).where(SalesStore.seller_id == g.sales_user.id).order_by(SalesStore.name)).all()
        return render_template("sales/new.html", stores=stores, cart=cart_for_user())

    @bp.get("/vendedor/catalogo")
    @seller_required
    def catalog():
        search = request.args.get("q", "").strip()[:100]
        category = request.args.get("categoria", "")[:100]
        query = select(Product).where(Product.active.is_(True)).order_by(Product.name, Product.id)
        if search:
            query = query.where(Product.name.ilike(f"%{search}%"))
        if category:
            query = query.join(Category).where(Category.slug == category)
        pagination = db.paginate(query, per_page=24, max_per_page=24, error_out=False)
        categories = db.session.scalars(select(Category).order_by(Category.name)).all()
        return render_template("sales/catalog.html", products=pagination.items, pagination=pagination, categories=categories, search=search, category_slug=category, cart=cart_for_user())

    @bp.post("/vendedor/carrito/<int:product_id>")
    @seller_required
    def change_cart(product_id):
        try:
            lock_user()
            cart = cart_for_user()
            if not cart or not cart.store_id:
                flash("Identifica primero el comercio para iniciar un pedido.", "error")
                return redirect(url_for("sales.new_order"))
            if request.form.get("cart_key") != cart.checkout_key:
                raise ValueError("El comercio o carrito cambió en otra pestaña. Actualiza el catálogo antes de continuar.")
            action = request.form.get("action", "update")
            quantity = int(request.form.get("quantity", ""))
            if not 0 <= quantity <= 1000000 or action not in ("add", "update", "remove"):
                raise ValueError("Ingresa una cantidad válida.")
            item = db.session.get(SalesCartItem, (cart.id, product_id))
            if action == "remove" or (action == "update" and quantity == 0):
                if item:
                    db.session.delete(item)
            else:
                product = db.session.get(Product, product_id)
                desired = (item.quantity if item else 0) + quantity if action == "add" else quantity
                if not product or not product.active or not 0 < desired <= min(product.stock, 1000000):
                    raise ValueError("Producto no disponible o cantidad superior al stock actual.")
                if item:
                    item.quantity = desired
                else:
                    db.session.add(SalesCartItem(cart_id=cart.id, product_id=product_id, quantity=desired))
            touch_cart(cart)
            db.session.commit()
        except ValueError as error:
            db.session.rollback()
            flash(str(error) or "Ingresa una cantidad válida.", "error")
        return redirect(url_for("sales.cart"))

    @bp.route("/vendedor/carrito", methods=["GET", "POST"])
    @seller_required
    def cart():
        if request.method == "POST":
            try:
                lock_user()
                current = cart_for_user()
                if current:
                    if request.form.get("cart_key") != current.checkout_key:
                        raise ValueError("El carrito cambió en otra pestaña. Actualiza antes de guardar observaciones.")
                    current.notes = bounded("notes", 1000)
                    touch_cart(current)
                    db.session.commit()
                    flash("Observaciones guardadas.", "success")
            except ValueError as error:
                db.session.rollback()
                flash(str(error), "error")
            return redirect(url_for("sales.cart"))
        current = cart_for_user()
        rows = cart_rows(current)
        return render_template("sales/cart.html", cart=current, rows=rows, total=sum(r["subtotal"] for r in rows))

    @bp.route("/vendedor/resumen", methods=["GET", "POST"])
    @seller_required
    def review():
        if request.method == "POST":
            try:
                lock_user()
                try:
                    submitted = serializer().loads(request.form.get("quote", ""))
                except BadSignature:
                    raise ValueError("El resumen no es válido. Revísalo nuevamente.")
                if not isinstance(submitted, dict) or submitted.get("seller") != g.sales_user.id:
                    raise ValueError("El resumen no corresponde a esta sesión.")
                prior = db.session.scalar(select(SalesOrder).where(SalesOrder.checkout_key == submitted.get("key"), SalesOrder.seller_id == g.sales_user.id))
                if prior:
                    return redirect(url_for("sales.detail", order_id=prior.order_id))
                current = cart_for_user()
                if not current or not current.store_id or not current.items:
                    raise ValueError("El carrito está vacío o no tiene un comercio.")
                # Lock in product ID order to serialize concurrent sales and avoid overselling.
                products = db.session.scalars(select(Product).where(Product.id.in_([i.product_id for i in current.items])).order_by(Product.id).with_for_update().execution_options(populate_existing=True)).all()
                by_id = {p.id: p for p in products}
                rows = []
                for item in current.items:
                    product = by_id.get(item.product_id)
                    if not product or not product.active or product.price < 0 or not 0 < item.quantity <= product.stock:
                        raise ValueError("El stock cambió. Revisa las cantidades en el carrito.")
                    rows.append(dict(product=product, quantity=item.quantity, subtotal=product.price * item.quantity))
                if quote(current, rows) != submitted:
                    raise ValueError("Cambió el carrito o un precio. Revisa el resumen actualizado antes de confirmar.")
                store = db.session.get(SalesStore, current.store_id)
                if not store or store.seller_id != g.sales_user.id:
                    raise ValueError("El comercio no pertenece a esta cuenta.")
                total = sum(row["subtotal"] for row in rows)
                if total > 2147483647:
                    raise ValueError("El total supera el límite admitido. Divide la solicitud en pedidos menores.")
                snapshot = {key: getattr(store, key) for key in ("name", "responsible", "phone", "city", "address", "notes")}
                # A new customer is an order snapshot; existing public customer records are never edited.
                customer = Customer(name=store.name, phone=store.phone, city=store.city, address=store.address)
                order = Order(customer=customer, total=total, status="Pendiente", notes=current.notes, created_at=utcnow())
                db.session.add(order)
                db.session.flush()
                items_snapshot = []
                for row in rows:
                    product, quantity = row["product"], row["quantity"]
                    result = db.session.execute(update(Product).where(Product.id == product.id, Product.active.is_(True), Product.stock >= quantity).values(stock=Product.stock - quantity))
                    if result.rowcount != 1:
                        raise ValueError("No hay stock suficiente. El pedido no se registró.")
                    order.items.append(OrderItem(product_id=product.id, quantity=quantity, unit_price=product.price))
                    items_snapshot.append(dict(product_id=product.id, name=product.name, quantity=quantity, unit_price=product.price, subtotal=row["subtotal"]))
                commercial = SalesOrder(order_id=order.id, seller_id=g.sales_user.id, store_id=store.id, seller_name=g.sales_user.full_name,
                                        store_name=store.name, store_snapshot=snapshot, items_snapshot=items_snapshot, checkout_key=current.checkout_key)
                db.session.add(commercial)
                audit("commercial_order_created", order.id, total=total, store_id=store.id)
                current.items.clear()
                current.store_id = None
                current.notes = ""
                current.checkout_key = secrets.token_hex(24)
                touch_cart(current)
                db.session.commit()
                flash("Pedido comercial registrado como pendiente. No acredita pago ni entrega.", "success")
                return redirect(url_for("sales.detail", order_id=order.id))
            except ValueError as error:
                db.session.rollback()
                flash(str(error), "error")
                return redirect(url_for("sales.cart"))
        current = cart_for_user()
        rows = cart_rows(current)
        if not current or not current.store_id or not rows or not all(r["valid"] for r in rows):
            flash("Revisa el comercio, los productos y el stock antes de continuar.", "error")
            return redirect(url_for("sales.cart"))
        return render_template("sales/review.html", cart=current, rows=rows, total=sum(r["subtotal"] for r in rows), quote_token=serializer().dumps(quote(current, rows)))

    def filtered_orders(admin=False):
        query = select(SalesOrder).join(Order).order_by(Order.created_at.desc(), Order.id.desc())
        if not admin:
            query = query.where(SalesOrder.seller_id == g.sales_user.id)
        seller = request.args.get("seller", "") if admin else ""
        if seller:
            try:
                query = query.where(SalesOrder.seller_id == int(seller))
            except ValueError:
                abort(400)
        search = request.args.get("q", "").strip()[:160]
        if search:
            query = query.where(SalesOrder.store_name.ilike(f"%{search}%"))
        state = request.args.get("status", "") if admin else ""
        if state in STATUSES:
            query = query.where(Order.status == state)
        for name, end in (("from", False), ("to", True)):
            raw = request.args.get(name, "")
            if raw:
                try:
                    day = date.fromisoformat(raw) + (timedelta(days=1) if end else timedelta())
                    limit = datetime.combine(day, time(), tzinfo=PARAGUAY_TIMEZONE).astimezone(timezone.utc)
                except (ValueError, OverflowError):
                    abort(400)
                query = query.where(Order.created_at < limit if end else Order.created_at >= limit)
        return db.paginate(query, per_page=25, max_per_page=25, error_out=False)

    @bp.get("/vendedor/pedidos")
    @seller_required
    def history():
        pagination = filtered_orders()
        return render_template("sales/history.html", orders=pagination.items, pagination=pagination, admin_mode=False)

    def load_order(order_id, admin=False):
        commercial = db.session.get(SalesOrder, order_id)
        if not commercial or (not admin and commercial.seller_id != g.sales_user.id):
            abort(404)
        return commercial

    @bp.get("/vendedor/pedidos/<int:order_id>")
    @seller_required
    def detail(order_id):
        return render_template("sales/detail.html", commercial=load_order(order_id), admin_mode=False)

    @bp.get("/vendedor/pedidos/<int:order_id>/resumen.pdf")
    @seller_required
    def pdf(order_id):
        from sales_pdf import build_commercial_pdf
        commercial = load_order(order_id)
        return send_file(build_commercial_pdf(commercial), mimetype="application/pdf", as_attachment=True, download_name=f"pedido-comercial-{order_id}.pdf")

    @bp.route("/admin/vendedores", methods=["GET", "POST"])
    @admin_required
    def sellers():
        if request.method == "POST":
            try:
                first, last, username = account_fields()
                user = SalesUser(first_name=first, last_name=last, username=username, password_hash=generate_password_hash(password_value()), role="vendedor", active=True)
                db.session.add(user)
                db.session.flush()
                audit("seller_created", user.id)
                db.session.commit()
                flash("Cuenta de vendedor creada. Comunica la contraseña por un medio privado.", "success")
            except (ValueError, IntegrityError) as error:
                db.session.rollback()
                flash(str(error) if isinstance(error, ValueError) else "Ese nombre de usuario ya está en uso.", "error")
            return redirect(url_for("sales.sellers"))
        users = db.session.scalars(select(SalesUser).where(SalesUser.role == "vendedor").order_by(SalesUser.first_name)).all()
        metrics = {}
        for row in db.session.execute(select(SalesOrder.seller_id, func.count(), func.coalesce(func.sum(Order.total), 0),
                func.sum(case((Order.status == "Pendiente", 1), else_=0)), func.sum(case((Order.status == "Confirmado", 1), else_=0)),
                func.sum(case((Order.status == "Cancelado", 1), else_=0)), func.count(func.distinct(SalesOrder.store_id))).join(Order).group_by(SalesOrder.seller_id)):
            metrics[row[0]] = dict(count=row[1], total=row[2], pending=row[3], confirmed=row[4], cancelled=row[5], stores=row[6])
        return render_template("sales/sellers.html", users=users, metrics=metrics)

    @bp.post("/admin/vendedores/<int:user_id>/<action>")
    @admin_required
    def manage_seller(user_id, action):
        user = db.session.scalar(select(SalesUser).where(SalesUser.id == user_id, SalesUser.role == "vendedor").with_for_update())
        if not user:
            abort(404)
        try:
            if action == "editar":
                user.first_name, user.last_name, user.username = account_fields()
                user.auth_version += 1
            elif action == "password":
                user.password_hash = generate_password_hash(password_value())
                user.auth_version += 1
            elif action in ("activar", "desactivar"):
                user.active = action == "activar"
                user.auth_version += 1
            else:
                abort(404)
            audit("seller_" + action, user.id)
            db.session.commit()
            flash("Cuenta actualizada. Los cambios de acceso cierran las sesiones anteriores.", "success")
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(str(error) if isinstance(error, ValueError) else "El nombre de usuario ya está en uso.", "error")
        return redirect(url_for("sales.sellers"))

    @bp.get("/admin/vendedores/comercios")
    @admin_required
    def stores():
        query = select(SalesStore).order_by(SalesStore.seller_id, SalesStore.name)
        if request.args.get("seller", ""):
            try:
                query = query.where(SalesStore.seller_id == int(request.args["seller"]))
            except ValueError:
                abort(400)
        pagination = db.paginate(query, per_page=30, max_per_page=30, error_out=False)
        return render_template("sales/stores.html", stores=pagination.items, pagination=pagination)

    @bp.get("/admin/vendedores/pedidos")
    @admin_required
    def admin_history():
        pagination = filtered_orders(True)
        users = db.session.scalars(select(SalesUser).where(SalesUser.role == "vendedor").order_by(SalesUser.first_name)).all()
        return render_template("sales/history.html", orders=pagination.items, pagination=pagination, admin_mode=True, users=users)

    @bp.get("/admin/vendedores/pedidos/<int:order_id>")
    @admin_required
    def admin_detail(order_id):
        return render_template("sales/detail.html", commercial=load_order(order_id, True), admin_mode=True)

    @bp.get("/admin/vendedores/pedidos/<int:order_id>/resumen.pdf")
    @admin_required
    def admin_pdf(order_id):
        from sales_pdf import build_commercial_pdf
        return send_file(build_commercial_pdf(load_order(order_id, True)), mimetype="application/pdf", as_attachment=True, download_name=f"pedido-comercial-{order_id}.pdf")

    app.register_blueprint(bp)
