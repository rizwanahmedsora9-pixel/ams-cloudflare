"""Canonical dataset for the full-cycle run.

Every number the checks assert derives from the constants here.  Change a
value here and the expected figure in ``checks.py`` changes with it — never
hard-code a total in two places.
"""

# ---------------------------------------------------------------- suppliers
SUPPLIERS = [
    dict(name="Ravi Cement Supplier", phone="0300-1234567", address="Ravi Road, Lahore"),
    dict(name="Kohat Traders", phone="0301-7654321", address="Kohat Bazaar"),
]

# ------------------------------------------------------------ categories
EXTRA_CATEGORIES = ["Cement", "Sand & Gravel", "Sheets & Covers"]

# --------------------------------------------------------------- materials
MATERIALS = [
    dict(name="DG Cement", category="Cement", unit="Bag", code="DG"),
    dict(name="Pioneer Cement", category="Cement", unit="Bag", code="PIO"),
    dict(name="Chenab Sand", category="Sand & Gravel", unit="Cft", code="SAND"),
    dict(name="TRANSPARENT SHEET", category="Sheets & Covers", unit="Pcs", code="SHT"),
]
SERVICE = dict(name="CEMENT RENT", unit="Trip", code="SRV-RENT")

# ------------------------------------------------------------ directories
CLIENT = dict(name="Bilal Construction", code="CYC-CL-1", category="General",
              phone="0321-1112223", address="Islamabad")
DRIVER = dict(name="Akram Driver", phone="0333-9998887")

CASH_ACCOUNT = dict(name="Main Cash", opening=200_000.0, cls="Assets",
                    sub="Cash", kind="Main Cash")
BANK_ACCOUNT = dict(name="Meezan Bank", opening=500_000.0, cls="Assets",
                    sub="Bank", kind="Operating Bank",
                    bank_name="Meezan Bank", holder="Ahmed Cement",
                    number="0123456789")

# ------------------------------------------------------------------- GRNs
# (manual_bill, supplier_id, supplier_name, date, material, qty, price)
GRNS = [
    ("CYC-GRN-1", 1, "Ravi Cement Supplier", "2026-10-02", "DG Cement", 100, 1200),
    ("CYC-GRN-2", 1, "Ravi Cement Supplier", "2026-10-04", "DG Cement", 50, 1350),
    ("CYC-GRN-3", 2, "Kohat Traders", "2026-10-06", "DG Cement", 80, 1400),
    ("CYC-GRN-4", 1, "Ravi Cement Supplier", "2026-10-08", "Pioneer Cement", 60, 1600),
    ("CYC-GRN-5", 2, "Kohat Traders", "2026-10-10", "Chenab Sand", 200, 55),
    ("CYC-GRN-6", 1, "Ravi Cement Supplier", "2026-10-12", "TRANSPARENT SHEET", 40, 300),
]
GRN_TOTAL = sum(qty * price for *_h, qty, price in GRNS)          # 418,500
RAVI_PURCHASE = sum(qty * price for _b, sid, _sup, _d, _m, qty, price in GRNS if sid == 1)   # 295,500
KOHAT_PURCHASE = sum(qty * price for _b, sid, _sup, _d, _m, qty, price in GRNS if sid == 2)  # 123,000

# ---------------------------------------------------------------- booking
BOOKING = dict(qty=20, rate=1500, paid=10_000.0, bill="CYC-BK-1",
               date="2026-10-13", note="20 bags booked at 1500")

# ------------------------------------------------------------------ sales
# category, client, date, qty, rate, paid, rent, bill, idem
SALES = [
    dict(category="Cash", client=None, client_name="Walk-in Customer",
         date="2026-10-14", qty=5, rate=1700, paid=8500.0, rent=200.0,
         bill="CYC-CASH-1", idem="cyc-cash-1", amount=8500.0,
         ignore_booking="1"),
    dict(category="Credit Customer", client="CYC-CL-1", client_name=None,
         date="2026-10-15", qty=10, rate=1650, paid=5000.0, rent=400.0,
         bill="CYC-CR-1", idem="cyc-cr-1", amount=16500.0,
         ignore_booking="1"),
    dict(category="Booking Delivery", client="CYC-CL-1", client_name=None,
         date="2026-10-16", qty=20, rate=1500, paid=0.0, rent=800.0,
         bill="CYC-BD-1", idem="cyc-bd-1", amount=30000.0,
         ignore_booking="0"),
]
DELIVERY_RENT_TOTAL = sum(s["rent"] for s in SALES)               # 1,400

# --------------------------------------------------------------- payments
CLIENT_RECEIPTS = [
    dict(amount=8000.0, method="Cash", account="Main Cash", date="2026-10-18",
         bill="CYC-RCPT-1", note="part receipt against credit sale", idem="cyc-rcpt-1"),
    dict(amount=3000.0, method="Bank Transfer", account="Meezan Bank",
         date="2026-10-19", bill="CYC-RCPT-2", note="bank receipt", idem="cyc-rcpt-2"),
]
GRN_PAYMENT = dict(grn_index=0, amount=60_000.0, method="Cash", account="Main Cash",
                   date="2026-10-20", reference="CYC-GRNPAY-1")
SUPPLIER_PAYMENT = dict(supplier_id=1, amount=20_000.0, method="Bank Transfer",
                        account="Meezan Bank", date="2026-10-21",
                        bill="CYC-SUPPAY-1", note="part payment Ravi")
DRIVER_PAYMENT = dict(amount=1000.0, method="Cash", account="Main Cash",
                      date="2026-10-22", reference="CYC-DRV-1",
                      note="part driver settlement", idem="cyc-drv-1")

# -------------------------------------------------------------- cash flow
CF_CATEGORY = dict(name="Owner Investment", direction="in")
CF_ENTRY = dict(direction="in", amount=5000.0, account="Main Cash",
                description="Owner put cash in", date="2026-10-23",
                reference="CYC-CF-IN", idem="cyc-cf-in")
PHYSICAL_CASH = 175_500.0            # what the drawer actually holds on 2026-10-31
RECON_DATE = "2026-10-31"

# ---------------------------------------------------------------- returns
RETURN = dict(client="CYC-CL-1", date="2026-10-26", material="DG Cement",
              qty=2, rate=1650.0, bill="CYC-RTN-1", note="2 bags returned")

PENDING_BILL = dict(client="CYC-CL-1", bill="CYC-PB-1", amount=4500.0,
                    reason="Manual charge: extra loading")

# =====================================================================
# Derived expectations — one place for every total the checks assert
# =====================================================================
PERIOD = dict(start="2026-10-01", end="2026-10-31")

EXPECT = {
    # accounts
    "cash_closing": 175_500.0,           # 200,000 + 36,500 - 61,000
    "bank_closing": 483_000.0,           # 500,000 + 3,000 - 20,000
    "company_total": 658_500.0,
    "cash_in_all": 39_500.0,             # 10,000 + 8,500 + 5,000 + 8,000 + 3,000 + 5,000
    "cash_out_all": 81_000.0,            # 60,000 + 20,000 + 200 + 400 + 400
    # stock
    "stock_dg": 195.0,
    "stock_pioneer": 60.0,
    "stock_sand": 200.0,
    "stock_sheet": 40.0,
    "stock_total": 495.0,
    "stock_received": 530.0,
    "stock_delivered": 35.0,
    # clients
    "client_due": 46_500.0,
    "client_paid": 26_000.0,
    "client_net": 20_500.0,
    # suppliers
    "purchase_total": GRN_TOTAL,
    "supplier_paid": 80_000.0,
    "supplier_payable": GRN_TOTAL - 80_000.0,      # 338,500
    "ravi_purchase": RAVI_PURCHASE,
    "ravi_payable": RAVI_PURCHASE - 80_000.0,      # 215,500
    "kohat_payable": KOHAT_PURCHASE,               # 123,000
    # p&l
    "pl_sales": 55_000.0,
    "pl_cogs": 43_400.0,
    "pl_profit": 11_600.0,
    "pl_material_cost": 42_000.0,
    "pl_actual_cost": 18_000.0,
    "pl_estimated_cost": 24_000.0,
    "pl_delivery_cost": 1_400.0,
    "pl_money_received": 34_500.0,
    "pl_margin": 21.09,
    "pl_markup": 26.73,
    # cash flow report
    "cf_opening": 200_000.0,
    "cf_received": 39_500.0,
    "cf_spent": 81_000.0,
    "cf_closing": 158_500.0,             # see defect 22.7: cash-only opening vs all-account movement
    "cf_recon_difference": 17_000.0,     # physical 175,500 - calculated 158,500
    # rent
    "rent_earned": 1_400.0,
    "rent_paid": 1_000.0,
    "rent_due": 400.0,
    # pending bills
    "pending_bk": 9_000.0,
    "pending_cr": 11_500.0,
    "pending_total_unpaid": 20_500.0,
}
