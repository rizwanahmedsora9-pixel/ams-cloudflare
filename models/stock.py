from .__base import *  # noqa
from .helpers import *  # noqa

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    time = db.Column(db.String(20))
    type = db.Column(db.String(10))
    material = db.Column(db.String(100))
    client = db.Column(db.String(100))
    client_code = db.Column(db.String(50))
    client_category = db.Column(db.String(50))
    qty = db.Column(db.Float, default=0)
    bill_no = db.Column(db.String(50))
    auto_bill_no = db.Column(db.String(50))
    nimbus_no = db.Column(db.String(50))
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=True)
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)
    is_void = db.Column(db.Boolean, default=False)
    transaction_category = db.Column(db.String(50))
    driver_name = db.Column(db.String(100))
    note = db.Column(db.String(500))
    booked_material = db.Column(db.String(100))
    is_alternate = db.Column(db.Boolean, default=False)
    source_module = db.Column(db.String(50), index=True)
    source_table = db.Column(db.String(50), index=True)
    source_id = db.Column(db.Integer, index=True)
    source_bill_no = db.Column(db.String(50), index=True)
    transaction_type = db.Column(db.String(50), index=True)


class GRN(db.Model):
    """Goods Receipt Note - for stock receiving.

    A GRN is a *receiving/costing document only*: it never pays anybody and
    never creates a cash movement (owner rule A1).  All payments are posted
    from Accounts against the obligations recorded here.

    Supplier Ledger credit is controlled by ``include_charges_in_supplier``:
    unchecked = material qty × supplier rate only; checked = material plus the
    GRN's applicable vehicle/loading/unloading/other charges.  The same rule
    drives Accounts payables and GRN payment obligations.  Landed inventory
    cost is independent of this billing choice.
    """
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)
    supplier = db.Column(db.String(100))
    manual_bill_no = db.Column(db.String(50))
    auto_bill_no = db.Column(db.String(50))
    photo_path = db.Column(db.String(200))
    photo_url = db.Column(db.String(500))
    # Legacy flat charge columns.  Kept for imports / old reports; for LANDED
    # GRNs they are only a compatibility mirror of GRNCharge rows and are
    # NEVER added to the supplier payable or to FIFO cost.
    loading_cost = db.Column(db.Float, default=0)
    freight_cost = db.Column(db.Float, default=0)
    other_expense = db.Column(db.Float, default=0)
    adjustment_amount = db.Column(db.Float, default=0)
    discount = db.Column(db.Float, default=0)
    # Legacy GRN-only payment field.  New GRNs always leave this at 0.
    paid_amount = db.Column(db.Float, default=0)
    payment_type = db.Column(db.String(50))
    payment_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    tax_percent = db.Column(db.Float, default=0)
    tax_amount = db.Column(db.Float, default=0)
    tax_type = db.Column(db.String(50))
    bank_name = db.Column(db.String(100))
    account_name = db.Column(db.String(100))
    account_no = db.Column(db.String(50))
    supplier_invoice_no = db.Column(db.String(50))
    due_date = db.Column(db.Date)
    bill_date = db.Column(db.Date)
    date_posted = db.Column(db.DateTime, default=pk_model_now, index=True)
    items = db.relationship('GRNItem', backref='grn', lazy=True, cascade='all, delete-orphan')
    charges = db.relationship('GRNCharge', backref='grn', lazy=True, cascade='all, delete-orphan')
    supplier_rel = db.relationship('Supplier', backref='grns')
    payment_account = db.relationship('Account', foreign_keys=[payment_account_id], backref='grn_payments')
    is_void = db.Column(db.Boolean, default=False)
    note = db.Column(db.String(500))

    # --- Landed-cost / obligations (additive, nullable, auto-migrated) --------
    costing_mode = db.Column(db.String(20), default='LEGACY', index=True)  # LEGACY | LANDED
    supplier_material_amount = db.Column(db.Float, default=0)
    supplier_material_amount_minor = db.Column(db.BigInteger, nullable=True)  # authoritative
    capitalised_charge_total = db.Column(db.Float, default=0)
    capitalised_charge_total_minor = db.Column(db.BigInteger, nullable=True)
    landed_cost_total = db.Column(db.Float, default=0)
    landed_cost_total_minor = db.Column(db.BigInteger, nullable=True)
    expense_charge_total = db.Column(db.Float, default=0)
    expense_charge_total_minor = db.Column(db.BigInteger, nullable=True)
    allocation_basis_default = db.Column(db.String(20), default='VALUE')  # VALUE | QUANTITY | MANUAL
    include_charges_in_supplier = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    # --- Audit / cancellation ----------------------------------------------
    revision = db.Column(db.Integer, default=1, nullable=True)
    created_by = db.Column(db.String(80))
    updated_by = db.Column(db.String(80))
    is_cancelled = db.Column(db.Boolean, default=False, index=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by = db.Column(db.String(80))
    cancel_reason = db.Column(db.String(500))


class GRNCharge(db.Model):
    """One material-related charge / payment obligation on a GRN.

    A charge is either capitalised into the GRN lots (INVENTORY) or recognised
    as a separate operating expense (EXPENSE).  If the parent GRN has
    ``include_charges_in_supplier`` enabled, the charge is billed through the
    supplier ledger instead of creating a second recipient payable.
    ``declared_status`` is display-only: a GRN never settles a charge (A1).
    Balances are derived from Accounts payments.
    """
    __tablename__ = 'grn_charge'
    id = db.Column(db.Integer, primary_key=True)
    grn_id = db.Column(db.Integer, db.ForeignKey('grn.id'), nullable=False, index=True)
    charge_type = db.Column(db.String(30), default='OTHER', index=True)  # VEHICLE_FARE|TRANSPORT|LOADING|UNLOADING|OTHER
    label = db.Column(db.String(160))
    amount = db.Column(db.Float, default=0)
    amount_minor = db.Column(db.BigInteger, nullable=False, default=0)  # authoritative paisa
    recipient_type = db.Column(db.String(30), default='OTHER', index=True)  # TRANSPORTER|LABOUR|OTHER|UNSPECIFIED
    recipient_party_id = db.Column(db.Integer, db.ForeignKey('cash_flow_party.id'), nullable=True, index=True)
    recipient_name = db.Column(db.String(160), index=True)
    declared_status = db.Column(db.String(20), default='UNPAID', index=True)  # PAID|UNPAID|NOT_APPLICABLE (display only)
    cost_treatment = db.Column(db.String(30), default='INVENTORY', index=True)  # INVENTORY|EXPENSE|NON_MATERIAL|UNTRACKED_LEGACY
    allocation_basis = db.Column(db.String(20), default='VALUE')  # VALUE|QUANTITY|MANUAL
    allocation_json = db.Column(db.Text)
    is_void = db.Column(db.Boolean, default=False, index=True)
    is_legacy_mirror = db.Column(db.Boolean, default=False, index=True)
    legacy_column = db.Column(db.String(40), nullable=True)
    revision = db.Column(db.Integer, default=1, nullable=True)
    created_by = db.Column(db.String(80))
    updated_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)
    updated_at = db.Column(db.DateTime, default=pk_model_now, onupdate=pk_model_now)
    note = db.Column(db.String(500))

    party = db.relationship('CashFlowParty', foreign_keys=[recipient_party_id])

    __table_args__ = (
        db.Index('ix_grn_charge_grn_active', 'grn_id', 'is_void'),
    )


class GRNItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    grn_id = db.Column(db.Integer, db.ForeignKey('grn.id'), nullable=False)
    mat_name = db.Column(db.String(100))
    qty = db.Column(db.Float, default=0)
    price_at_time = db.Column(db.Float, default=0)  # supplier rate (never overwritten)
    is_void = db.Column(db.Boolean, default=False, index=True)
    is_locked = db.Column(db.Boolean, default=False, index=True)  # True while consumed by an active sale
    # --- Landed cost (additive) --------------------------------------------
    base_rate_minor = db.Column(db.BigInteger, nullable=True)
    allocated_charges_minor = db.Column(db.BigInteger, default=0)
    line_landed_cost_minor = db.Column(db.BigInteger, nullable=True)
    landed_unit_cost = db.Column(db.Float, default=0)  # 6dp float for qty x rate maths
    landed_unit_cost_minor = db.Column(db.BigInteger, nullable=True)
    allocation_basis = db.Column(db.String(20), default='VALUE')
    cost_revision = db.Column(db.Integer, default=0)
    cost_revised_at = db.Column(db.DateTime, nullable=True)


class Delivery(db.Model):
    """Delivery records for dispatching"""
    id = db.Column(db.Integer, primary_key=True)
    client_name = db.Column(db.String(100))
    manual_bill_no = db.Column(db.String(50))
    auto_bill_no = db.Column(db.String(50))
    photo_path = db.Column(db.String(200))
    date_posted = db.Column(db.DateTime, default=pk_model_now, index=True)
    items = db.relationship('DeliveryItem', backref='delivery', lazy=True, cascade='all, delete-orphan')


class DeliveryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey('delivery.id'), nullable=False)
    product = db.Column(db.String(100))
    qty = db.Column(db.Float, default=0)

