"""Additive commercial schema. Original customer and order tables stay intact."""
from datetime import datetime, timezone
import secrets
from extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class SalesUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="vendedor")
    active = db.Column(db.Boolean, nullable=False, default=True)
    auth_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (db.CheckConstraint("role IN ('vendedor', 'administrador')", name="ck_sales_user_role"),)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class SalesStore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("sales_user.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    normalized_name = db.Column(db.String(160), nullable=False)
    responsible = db.Column(db.String(160), nullable=False, default="")
    phone = db.Column(db.String(30), nullable=False, default="")
    city = db.Column(db.String(120), nullable=False, default="")
    address = db.Column(db.String(250), nullable=False, default="")
    notes = db.Column(db.String(1000), nullable=False, default="")
    seller = db.relationship("SalesUser")
    __table_args__ = (db.UniqueConstraint("seller_id", "normalized_name", name="uq_sales_store_owner_name"),)


class SalesCart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("sales_user.id"), nullable=False, unique=True)
    store_id = db.Column(db.Integer, db.ForeignKey("sales_store.id"), nullable=True)
    checkout_key = db.Column(db.String(64), nullable=False, default=lambda: secrets.token_hex(24))
    revision = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.String(1000), nullable=False, default="")
    store = db.relationship("SalesStore")
    items = db.relationship("SalesCartItem", cascade="all, delete-orphan", back_populates="cart")


class SalesCartItem(db.Model):
    cart_id = db.Column(db.Integer, db.ForeignKey("sales_cart.id"), primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), primary_key=True)
    quantity = db.Column(db.Integer, nullable=False)
    cart = db.relationship("SalesCart", back_populates="items")
    product = db.relationship("Product")
    __table_args__ = (db.CheckConstraint("quantity > 0 AND quantity <= 1000000", name="ck_sales_cart_quantity"),)


class SalesOrder(db.Model):
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("sales_user.id"), nullable=False, index=True)
    store_id = db.Column(db.Integer, db.ForeignKey("sales_store.id"), nullable=False, index=True)
    seller_name = db.Column(db.String(201), nullable=False)
    store_name = db.Column(db.String(160), nullable=False, index=True)
    store_snapshot = db.Column(db.JSON, nullable=False)
    items_snapshot = db.Column(db.JSON, nullable=False)
    checkout_key = db.Column(db.String(64), nullable=False, unique=True)
    order = db.relationship("Order")
    seller = db.relationship("SalesUser")


class SalesAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(80), nullable=False)
    event = db.Column(db.String(60), nullable=False)
    subject_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class SalesLoginThrottle(db.Model):
    key = db.Column(db.String(64), primary_key=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    window_start = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
