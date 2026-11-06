from .__base import *  # noqa
from .helpers import *  # noqa

class ClientCategory(db.Model):
    """User-managed classification for client ledger records."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)


class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    # Urdu name printed on the Urdu bill/receipt.  Empty means "no Urdu name
    # recorded", and the bill then prints the English name unchanged.
    name_ur = db.Column(db.String(150), default='', nullable=True)
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))
    category = db.Column(db.String(50), default='General')
    opening_balance = db.Column(db.Float, default=0)
    opening_balance_date = db.Column(db.DateTime, default=pk_model_now, index=True)
    is_active = db.Column(db.Boolean, default=True)
    transferred_to_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=True)
    require_manual_invoice = db.Column(db.Boolean, default=False)
    book_no = db.Column(db.String(50))
    financial_page = db.Column(db.String(50))
    cement_page = db.Column(db.String(50))
    steel_page = db.Column(db.String(50))
    financial_book_no = db.Column(db.String(50))
    cement_book_no = db.Column(db.String(50))
    steel_book_no = db.Column(db.String(50))
    location_url = db.Column(db.String(500))
    page_notes = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)


class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    transferred_to_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))
    opening_balance = db.Column(db.Float, default=0)
    opening_balance_date = db.Column(db.DateTime, default=pk_model_now, index=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)


class SupplierPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False, index=True)
    amount = db.Column(db.Float, default=0)
    amount_minor = db.Column(db.BigInteger, nullable=True)  # authoritative paisa/cents
    method = db.Column(db.String(50))
    payment_type = db.Column(db.String(30), default='Payment', index=True)
    source_type = db.Column(db.String(50), nullable=True, index=True)
    source_id = db.Column(db.Integer, nullable=True, index=True)
    date_posted = db.Column(db.DateTime, default=pk_model_now, index=True)
    note = db.Column(db.String(500))
    is_void = db.Column(db.Boolean, default=False, index=True)
    bank_name = db.Column(db.String(100))
    account_name = db.Column(db.String(100))
    account_no = db.Column(db.String(50))
    payment_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    manual_bill_no = db.Column(db.String(50))
    auto_bill_no = db.Column(db.String(50))
    idempotency_key = db.Column(db.String(64), nullable=True, unique=True, index=True)
    idempotency_payload_hash = db.Column(db.String(64), nullable=True, index=True)
    revision = db.Column(db.Integer, default=1, nullable=True)
    created_by = db.Column(db.String(80))
    updated_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)
    updated_at = db.Column(db.DateTime, default=pk_model_now, onupdate=pk_model_now, index=True)

    # --- GRN payment linkage (additive; the ONE payment table) -------------
    # A payment targets exactly ONE obligation: either (grn_id, SUPPLIER) for
    # the supplier's material amount, or (grn_id, grn_charge_id) for one charge.
    # supplier_id stays NOT NULL as the GRN's *context* supplier; recipient_type
    # is the sole authority for which party ledger this payment belongs to.
    grn_id = db.Column(db.Integer, db.ForeignKey('grn.id'), nullable=True, index=True)
    grn_charge_id = db.Column(db.Integer, db.ForeignKey('grn_charge.id'), nullable=True, index=True)
    recipient_type = db.Column(db.String(30), nullable=True, index=True)  # SUPPLIER|TRANSPORTER|LABOUR|OTHER ; NULL/legacy => SUPPLIER
    recipient_party_id = db.Column(db.Integer, db.ForeignKey('cash_flow_party.id'), nullable=True, index=True)
    recipient_name = db.Column(db.String(160), index=True)
    payment_kind = db.Column(db.String(30), nullable=True, index=True)  # GRN_MATERIAL|GRN_CHARGE|STANDALONE|ADVANCE|LEGACY_GRN_AUTO
    cash_posted = db.Column(db.Boolean, default=False, index=True)
    reference = db.Column(db.String(80), index=True)

    supplier = db.relationship('Supplier', backref='payments')
    payment_account = db.relationship('Account', foreign_keys=[payment_account_id], backref='supplier_payments')
    grn_charge = db.relationship('GRNCharge', foreign_keys=[grn_charge_id])
    recipient_party = db.relationship('CashFlowParty', foreign_keys=[recipient_party_id])
    __mapper_args__ = {'version_id_col': revision}


class DeliveryPerson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    # Urdu name printed on the Urdu bill/receipt.  Empty means "no Urdu name
    # recorded", and the bill then prints the English name unchanged.
    name_ur = db.Column(db.String(150), default='', nullable=True)
    phone = db.Column(db.String(30))
    # Opening balance is additive and optional.  Positive means the business
    # owes the delivery person; negative means an advance/prepayment.
    opening_balance = db.Column(db.Float, default=0)
    opening_balance_date = db.Column(db.DateTime, default=pk_model_now, index=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)

