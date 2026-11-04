"""Sidebar navigation registry and layout resolution.

The sidebar is **data driven**: every link the application can show lives in
:data:`SIDEBAR_LINKS` together with its label, icon, URL and permission rule.
:class:`SidebarCategory` / :class:`SidebarItem` rows (see ``models/sidebar.py``)
only remember *where* the manager put each link.

Public helpers
--------------
``build_nav(user)``        → structure used by ``templates/layout.html``
``effective_layout()``     → the layout in force (DB rows or built-in defaults)
``save_layout(payload)``   → persist a whole layout snapshot (Sidebar Settings)
``reset_layout()``         → drop the custom layout, back to built-in defaults
``available_links()``      → every option with metadata (Sidebar Settings page)
"""
from __future__ import annotations

import logging
import re
import secrets
import string
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from flask import has_request_context, request, url_for
from flask_login import current_user

from models import SidebarCategory, SidebarItem, db

log = logging.getLogger(__name__)

PERMISSION_CALL = Callable[[Callable[[str], bool], object], bool]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NavLink:
    """One sidebar option.

    ``exact`` / ``prefix`` decide which request paths highlight the link;
    ``exclude_prefix`` removes a path that another link owns (Accounts vs
    Pay Supplier).  ``src_arg`` / ``src_not_arg`` mirror the ``?src=dir``
    dual use of ``/delivery_persons``.
    """

    key: str
    label: str
    icon: str
    endpoint: Optional[str] = None
    fallback_url: str = "/"
    exact: Tuple[str, ...] = field(default_factory=tuple)
    prefix: Tuple[str, ...] = field(default_factory=tuple)
    exclude_prefix: Tuple[str, ...] = field(default_factory=tuple)
    src_arg: Optional[str] = None
    src_not_arg: Optional[str] = None
    perm: PERMISSION_CALL = lambda can, user: True
    default_category: Optional[str] = None
    description: str = ""

    # -- URL ---------------------------------------------------------------
    def url(self) -> str:
        if self.endpoint:
            try:
                return url_for(self.endpoint)
            except Exception:  # blueprint missing / endpoint renamed
                pass
        return self.fallback_url

    # -- permission --------------------------------------------------------
    def allowed(self, can: Callable[[str], bool], user) -> bool:
        try:
            return bool(self.perm(can, user))
        except Exception:
            log.exception("Sidebar permission check failed for %s", self.key)
            return False

    # -- active state ------------------------------------------------------
    def is_active(self, path: str, src: str) -> bool:
        if self.src_arg is not None and (src or "") != self.src_arg:
            return False
        if self.src_not_arg is not None and (src or "") == self.src_not_arg:
            return False
        if any(path.startswith(p) for p in self.exclude_prefix):
            # A path owned by another link (Accounts vs Pay Supplier).
            return False
        if path in self.exact:
            return True
        return any(path.startswith(p) for p in self.prefix)


def _only(permission: str) -> PERMISSION_CALL:
    return lambda can, user: can(permission)


def _any_permission(*permissions: str) -> PERMISSION_CALL:
    return lambda can, user: any(can(p) for p in permissions)


def _ledger_admin_or(*permission: str) -> PERMISSION_CALL:
    """Visible to admins/root or to users holding *permission*."""

    def _check(can: Callable[[str], bool], user) -> bool:
        if getattr(user, "role", None) in ("admin", "root"):
            return True
        return can(permission[0])

    return _check


SIDEBAR_LINKS: Tuple[NavLink, ...] = (
    # ---- Top level ------------------------------------------------------
    NavLink(
        key="dashboard",
        label="Dashboard",
        icon="bi-speedometer2",
        fallback_url="/",
        exact=("/",),
        perm=_only("can_view_dashboard"),
        default_category=None,
        description="Main dashboard / home screen.",
    ),
    # ---- Inventory ------------------------------------------------------
    NavLink(
        key="stock_summary",
        label="Stock Summary",
        icon="bi-graph-up",
        endpoint="inventory.stock_summary",
        fallback_url="/inventory/stock_summary",
        exact=("/stock_summary",),
        prefix=("/inventory/stock_summary",),
        perm=_only("can_view_stock"),
        default_category="inventory",
        description="Material stock on hand with values.",
    ),
    NavLink(
        key="daily_transactions",
        label="Daily Breakdown",
        icon="bi-list-check",
        endpoint="inventory.daily_transactions",
        fallback_url="/inventory/daily_transactions",
        exact=("/daily_transactions", "/dispatching"),
        prefix=("/inventory/daily_transactions",),
        perm=_only("can_view_daily"),
        default_category="inventory",
        description="Day-by-day dispatch / transaction breakdown.",
    ),
    NavLink(
        key="history",
        label="History",
        icon="bi-clock-history",
        fallback_url="/tracking",
        exact=("/tracking", "/inventory/log"),
        prefix=("/material_ledger",),
        perm=_only("can_view_history"),
        default_category="inventory",
        description="Tracking and material ledger history.",
    ),
    # ---- Transactions ---------------------------------------------------
    NavLink(
        key="grn",
        label="GRN (Receiving)",
        icon="bi-box-arrow-in-down",
        fallback_url="/grn",
        prefix=("/grn", "/receiving"),
        perm=_only("can_manage_grn"),
        default_category="transactions",
        description="Goods received notes / purchases.",
    ),
    NavLink(
        key="bookings",
        label="Bookings",
        icon="bi-bookmark-plus",
        fallback_url="/bookings",
        prefix=("/bookings",),
        perm=_only("can_manage_bookings"),
        default_category="transactions",
        description="Client bookings.",
    ),
    NavLink(
        key="direct_sales",
        label="Sales",
        icon="bi-cart-check",
        fallback_url="/direct_sales",
        prefix=("/direct_sales", "/view_bill"),
        perm=_only("can_manage_sales"),
        default_category="transactions",
        description="Direct sales and bill viewing.",
    ),
    NavLink(
        key="material_returns",
        label="Material Return",
        icon="bi-arrow-counterclockwise",
        fallback_url="/material_returns",
        prefix=("/material_returns",),
        perm=_only("can_manage_sales"),
        default_category="transactions",
        description="Returned material entries.",
    ),
    NavLink(
        key="pending_bills",
        label="Pending Bills",
        icon="bi-receipt",
        fallback_url="/pending_bills",
        prefix=("/pending_bills",),
        perm=_only("can_manage_pending_bills"),
        default_category="transactions",
        description="Pending / unpaid bills.",
    ),
    NavLink(
        key="delivery_rents",
        label="Delivery Rent",
        icon="bi-truck",
        fallback_url="/delivery_rents",
        prefix=("/delivery_rents",),
        perm=_only("can_view_delivery_rent"),
        default_category="transactions",
        description="Delivery rent transactions.",
    ),
    # ---- Accounts -------------------------------------------------------
    NavLink(
        key="payments",
        label="Payments",
        icon="bi-cash-stack",
        fallback_url="/payments",
        prefix=("/payments",),
        perm=_only("can_manage_payments"),
        default_category="accounts",
        description="Client payments.",
    ),
    NavLink(
        key="accounts",
        label="Accounts",
        icon="bi-bank",
        endpoint="accounts.dashboard",
        fallback_url="/accounts",
        prefix=("/accounts",),
        exclude_prefix=("/accounts/payments/suppliers", "/pay_supplier",
                        "/accounts/pay_grn"),
        perm=_any_permission("can_manage_accounts", "can_manage_payments"),
        default_category="accounts",
        description="Financial accounts dashboard.",
    ),
    NavLink(
        key="cash_flow",
        label="Cash Flow",
        icon="bi-water",
        endpoint="cash_flow",
        fallback_url="/cash_flow",
        prefix=("/cash_flow",),
        perm=_only("can_view_cash_flow"),
        default_category="accounts",
        description="Cash flow statements and entries.",
    ),
    NavLink(
        key="daily_reconciliation",
        label="Daily Reconciliation",
        icon="bi-check2-circle",
        endpoint="daily_reconciliation",
        fallback_url="/daily_reconciliation",
        prefix=("/daily_reconciliation",),
        perm=_only("can_view_cash_flow"),
        default_category="accounts",
        description="Daily cash / drawer reconciliation.",
    ),
    NavLink(
        key="pay_grn",
        label="PAY GRN (STOCK / EXPENSES)",
        icon="bi-receipt",
        endpoint="accounts.pay_grn",
        fallback_url="/accounts/pay_grn",
        prefix=("/accounts/pay_grn",),
        perm=lambda can, user: can("can_manage_payments") or can("can_manage_accounts"),
        default_category="accounts",
        description="Pay one GRN: stock (qty × rate) and its expenses as separate payables.",
    ),
    NavLink(
        key="pay_supplier",
        label="Pay Supplier",
        icon="bi-cash-coin",
        endpoint="accounts.supplier_payments",
        fallback_url="/accounts/payments/suppliers",
        prefix=("/accounts/payments/suppliers", "/pay_supplier"),
        perm=lambda can, user: can("can_view_supplier_ledger")
        and (can("can_manage_accounts") or can("can_manage_payments")),
        default_category="accounts",
        description="Supplier payment vouchers — each settles a GRN payable.",
    ),
    NavLink(
        key="grn_payments",
        label="PAY EXISTING GRN",
        icon="bi-cash-coin",
        endpoint="accounts.grn_payments",
        fallback_url="/accounts/grn_payments",
        prefix=("/accounts/grn_payments",),
        perm=lambda can, user: can("can_manage_payments") or can("can_manage_accounts"),
        default_category="accounts",
        description="Full obligation breakdown: supplier, expenses and every charge recipient.",
    ),
    NavLink(
        key="profit_reports",
        label="Profit Reports",
        icon="bi-bar-chart-line",
        fallback_url="/profit_reports",
        prefix=("/profit_reports", "/financial_details", "/mixed_transactions"),
        perm=_only("can_view_reports"),
        default_category="accounts",
        description="Profit reports and financial detail views.",
    ),
    # ---- Ledger ---------------------------------------------------------
    NavLink(
        key="supplier_ledger",
        label="Supplier Ledger",
        icon="bi-journal-richtext",
        fallback_url="/suppliers",
        exact=("/suppliers",),
        prefix=("/supplier_ledger",),
        perm=_only("can_view_supplier_ledger"),
        default_category="ledger",
        description="Supplier ledger and balances.",
    ),
    NavLink(
        key="client_ledger",
        label="Client Ledger",
        icon="bi-journal-text",
        fallback_url="/clients",
        exact=("/clients",),
        prefix=("/ledger", "/client_ledger", "/financial_ledger"),
        perm=_only("can_view_client_ledger"),
        default_category="ledger",
        description="Client ledger and balances.",
    ),
    NavLink(
        key="client_categories",
        label="Client Categories",
        icon="bi-tags",
        fallback_url="/client-ledger/categories",
        prefix=("/client-ledger/categories",),
        perm=lambda can, user: can("can_view_client_ledger")
        and (
            getattr(user, "role", None) in ("admin", "root")
            or can("can_manage_clients")
        ),
        default_category="ledger",
        description="Client grouping categories.",
    ),
    NavLink(
        key="delivery_person_ledger",
        label="Delivery Person Ledger",
        icon="bi-journal-check",
        fallback_url="/delivery_persons",
        exact=("/delivery_persons",),
        prefix=("/delivery_person_ledger", "/delivery_ledger"),
        src_not_arg="dir",
        perm=_only("can_view_delivery_rent"),
        default_category="ledger",
        description="Per-driver ledger and payments.",
    ),
    NavLink(
        key="decision_ledger",
        label="Decision Ledger",
        icon="bi-clipboard-data",
        fallback_url="/decision_ledger",
        prefix=("/decision_ledger",),
        perm=_only("can_view_decision_ledger"),
        default_category="ledger",
        description="Decision ledger entries.",
    ),
    NavLink(
        key="current_payables",
        label="Current Payables",
        icon="bi-wallet2",
        fallback_url="/current_payables",
        exact=("/unpaid_transactions", "/current_payables"),
        perm=_only("can_view_reports"),
        default_category="ledger",
        description="Outstanding payables summary.",
    ),
    NavLink(
        key="notifications",
        label="Notifications",
        icon="bi-bell",
        fallback_url="/notifications",
        prefix=("/notifications",),
        perm=_only("can_manage_notifications"),
        default_category="ledger",
        description="Reminders and due notifications.",
    ),
    # ---- Directory ------------------------------------------------------
    NavLink(
        key="materials",
        label="Material Brands",
        icon="bi-tags",
        fallback_url="/materials",
        prefix=("/materials",),
        perm=_only("can_manage_materials"),
        default_category="directory",
        description="Material / brand master list.",
    ),
    NavLink(
        key="services",
        label="Services & Charges",
        icon="bi-receipt-cutoff",
        fallback_url="/services",
        prefix=("/services",),
        perm=_only("can_manage_materials"),
        default_category="directory",
        description="Service and charge master list.",
    ),
    NavLink(
        key="delivery_persons_dir",
        label="Delivery Persons",
        icon="bi-person-badge",
        fallback_url="/delivery_persons?src=dir",
        exact=("/delivery_persons",),
        src_arg="dir",
        perm=_only("can_manage_delivery_persons"),
        default_category="directory",
        description="Driver master list (Directory view).",
    ),
    # ---- System ---------------------------------------------------------
    NavLink(
        key="import_export",
        label="Import & Export",
        icon="bi-arrow-left-right",
        endpoint="import_export.import_export_page",
        fallback_url="/import_export",
        prefix=("/import_export", "/data_lab", "/full_raw_import"),
        perm=_only("can_import_export"),
        default_category="system",
        description="Excel import / export and data lab.",
    ),
    NavLink(
        key="legacy_migration",
        label="Legacy Data Migration",
        icon="bi-database-gear",
        endpoint="legacy_migration.dashboard",
        fallback_url="/legacy-migration",
        prefix=("/legacy-migration",),
        perm=_only("can_import_export"),
        default_category="system",
        description="Legacy database migration tools.",
    ),
    NavLink(
        key="settings",
        label="Settings",
        icon="bi-gear",
        fallback_url="/settings",
        prefix=("/settings", "/activity_log", "/void_audit", "/system_report"),
        perm=_only("can_access_settings"),
        default_category="system",
        description="Settings, audit log, sidebar settings.",
    ),
)

LINK_BY_KEY: Dict[str, NavLink] = {link.key: link for link in SIDEBAR_LINKS}

DEFAULT_CATEGORIES: Tuple[Dict[str, str], ...] = (
    {"key": "inventory", "name": "Inventory", "icon": "bi-boxes"},
    {"key": "transactions", "name": "Transactions", "icon": "bi-diagram-3"},
    {"key": "accounts", "name": "Accounts", "icon": "bi-calculator"},
    {"key": "ledger", "name": "Ledger", "icon": "bi-journals"},
    {"key": "directory", "name": "Directory", "icon": "bi-folder2-open"},
    {"key": "system", "name": "System", "icon": "bi-gear-wide-connected"},
)

DEFAULT_CATEGORY_KEYS = tuple(c["key"] for c in DEFAULT_CATEGORIES)

ICON_CHOICES: Tuple[str, ...] = (
    "bi-speedometer2", "bi-boxes", "bi-box-seam", "bi-graph-up", "bi-list-check",
    "bi-clock-history", "bi-diagram-3", "bi-box-arrow-in-down", "bi-bookmark-plus",
    "bi-cart-check", "bi-arrow-counterclockwise", "bi-receipt", "bi-truck",
    "bi-calculator", "bi-cash-stack", "bi-bank", "bi-water", "bi-check2-circle",
    "bi-cash-coin", "bi-bar-chart-line", "bi-journals", "bi-journal-richtext",
    "bi-journal-text", "bi-journal-check", "bi-tags", "bi-clipboard-data",
    "bi-wallet2", "bi-bell", "bi-person-badge", "bi-receipt-cutoff",
    "bi-folder2-open", "bi-folder2", "bi-gear-wide-connected", "bi-gear",
    "bi-arrow-left-right", "bi-database-gear", "bi-people", "bi-archive",
    "bi-briefcase", "bi-building", "bi-compass", "bi-cpu", "bi-eyedropper",
    "bi-fire", "bi-hdd-stack", "bi-hospital", "bi-houses", "bi-inboxes",
    "bi-lightning-charge", "bi-patch-check", "bi-piggy-bank", "bi-shield-check",
    "bi-star", "bi-table", "bi-tools", "bi-ticket-perforated",
)


# ---------------------------------------------------------------------------
# Layout: stored rows or built-in defaults
# ---------------------------------------------------------------------------
def _default_layout() -> Dict[str, object]:
    items = [
        {
            "key": link.key,
            "category": link.default_category,
            "hidden": False,
            "label": None,
            "icon": None,
        }
        for link in SIDEBAR_LINKS
    ]
    categories = [
        {
            "key": c["key"],
            "name": c["name"],
            "icon": c["icon"],
            "is_active": True,
        }
        for c in DEFAULT_CATEGORIES
    ]
    return {"customized": False, "categories": categories, "items": items}


def effective_layout() -> Dict[str, object]:
    """Return the layout in force, falling back to the shipped defaults."""
    try:
        categories_rows = (
            SidebarCategory.query.order_by(
                SidebarCategory.sort_order.asc(), SidebarCategory.id.asc()
            ).all()
        )
        item_rows = (
            SidebarItem.query.order_by(
                SidebarItem.sort_order.asc(), SidebarItem.id.asc()
            ).all()
        )
    except Exception:
        log.exception("Could not load the custom sidebar layout; using defaults.")
        try:
            db.session.rollback()
        except Exception:
            pass
        return _default_layout()

    if not categories_rows and not item_rows:
        return _default_layout()

    categories = [
        {
            "key": row.key,
            "name": row.name,
            "icon": row.icon or "bi-folder2",
            "is_active": bool(row.is_active),
        }
        for row in categories_rows
    ]
    known_categories = {c["key"] for c in categories}

    items: List[Dict[str, object]] = []
    seen = set()
    for row in item_rows:
        if row.key not in LINK_BY_KEY or row.key in seen:
            continue
        seen.add(row.key)
        category = row.category_key
        if category and category not in known_categories:
            category = None
        items.append(
            {
                "key": row.key,
                "category": category,
                "hidden": bool(row.is_hidden),
                "label": row.label or None,
                "icon": row.icon or None,
            }
        )
    # Options added to the code after the layout was saved keep their default
    # home instead of disappearing from the sidebar.
    for link in SIDEBAR_LINKS:
        if link.key in seen:
            continue
        category = link.default_category
        if category not in known_categories:
            category = None
        items.append(
            {
                "key": link.key,
                "category": category,
                "hidden": False,
                "label": None,
                "icon": None,
            }
        )
    return {"customized": True, "categories": categories, "items": items}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _dom_id(key: str, order: int) -> str:
    safe = re.sub(r"[^0-9a-zA-Z]+", "", str(key or "")) or "group"
    return f"navGroup{order}{safe[:24]}"


def build_nav(user=None) -> Dict[str, object]:
    """Build the sidebar structure for *user* on the current request."""
    if user is None:
        user = current_user
    empty = {"root_items": [], "categories": []}
    if user is None or not getattr(user, "is_authenticated", False):
        return empty
    if getattr(user, "role", None) == "root":
        # Root keeps the legacy "no sidebar" behaviour.
        return empty

    try:
        from app.services.permissions import _user_can
    except Exception:
        log.exception("Could not import permission helper for the sidebar.")
        return empty

    try:
        layout = effective_layout()
        if has_request_context():
            path = request.path or "/"
            src = request.args.get("src") or ""
        else:
            path, src = "/", ""
    except Exception:
        log.exception("Could not build the sidebar navigation.")
        return empty

    categories = layout.get("categories") or []
    category_keys = [c["key"] for c in categories]
    active_categories = {c["key"] for c in categories if c.get("is_active")}

    root_items: List[Dict[str, object]] = []
    grouped: Dict[str, List[Dict[str, object]]] = {key: [] for key in category_keys}

    for placed in layout.get("items") or []:
        if placed.get("hidden"):
            continue
        link = LINK_BY_KEY.get(placed.get("key"))
        if link is None:
            continue
        if not link.allowed(_user_can, user):
            continue
        entry = {
            "key": link.key,
            "label": placed.get("label") or link.label,
            "icon": placed.get("icon") or link.icon,
            "href": link.url(),
            "active": False,
        }
        try:
            entry["active"] = link.is_active(path, src)
        except Exception:
            entry["active"] = False
        category = placed.get("category")
        if category and category in grouped:
            grouped[category].append(entry)
        elif not category:
            root_items.append(entry)

    built_categories = []
    for order, category in enumerate(categories):
        if category["key"] not in active_categories:
            continue
        items = grouped.get(category["key"]) or []
        if not items:
            continue
        opened = any(item.get("active") for item in items)
        built_categories.append(
            {
                "key": category["key"],
                "name": category.get("name") or "Category",
                "icon": category.get("icon") or "bi-folder2",
                "dom_id": _dom_id(category["key"], order),
                "items": items,
                "open": opened,
                "has_active": opened,
            }
        )

    return {"root_items": root_items, "categories": built_categories}


# ---------------------------------------------------------------------------
# Sidebar Settings helpers
# ---------------------------------------------------------------------------
def _new_category_key(taken: Sequence[str]) -> str:
    alphabet = string.ascii_lowercase + string.digits
    while True:
        candidate = "cat_" + "".join(secrets.choice(alphabet) for _ in range(6))
        if candidate not in taken:
            return candidate


def _clean_text(value, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _clean_icon(value) -> Optional[str]:
    """Normalise a bootstrap-icon name ("bi bi-fire", "fire", "bi-fire")."""
    text = _clean_text(value, 80)
    if not text:
        return None
    # Only whitelisted class names are stored (they are rendered inside
    # class="bi …", so nothing else may leak into the attribute).
    text = text.split()[-1]
    if text.startswith("bi-"):
        text = text[3:]
    if not re.fullmatch(r"[a-z0-9-]{1,60}", text or ""):
        return None
    return f"bi-{text}"


def save_layout(payload: Dict[str, object]) -> Dict[str, object]:
    """Replace the stored layout with a validated snapshot.

    The snapshot shape is what the Sidebar Settings page posts::

        {"categories": [{"key", "name", "icon", "is_active"}],
         "items": [{"key", "category", "hidden", "label", "icon"}]}
    """
    raw_categories = payload.get("categories") if isinstance(payload, dict) else None
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_categories, list) or not isinstance(raw_items, list):
        raise ValueError("Invalid sidebar layout payload.")

    category_rows: List[Dict[str, object]] = []
    seen_keys: List[str] = []
    seen_names = set()
    for order, raw in enumerate(raw_categories):
        if not isinstance(raw, dict):
            continue
        name = _clean_text(raw.get("name"), 120)
        if not name or name.lower() in seen_names:
            continue
        key = _clean_text(raw.get("key"), 60) or _new_category_key(seen_keys)
        key = re.sub(r"[^0-9a-zA-Z_-]+", "", key)[:60] or _new_category_key(seen_keys)
        if key in seen_keys:
            key = _new_category_key(seen_keys)
        seen_keys.append(key)
        seen_names.add(name.lower())
        category_rows.append(
            {
                "key": key,
                "name": name,
                "icon": _clean_icon(raw.get("icon")) or "bi-folder2",
                "is_active": bool(raw.get("is_active", True)),
                "sort_order": order,
            }
        )

    known = {c["key"] for c in category_rows}
    item_rows: List[Dict[str, object]] = []
    seen_items = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        link_key = _clean_text(raw.get("key"), 80)
        if not link_key or link_key not in LINK_BY_KEY or link_key in seen_items:
            continue
        seen_items.add(link_key)
        category = _clean_text(raw.get("category"), 60)
        if category not in known:
            category = None
        item_rows.append(
            {
                "key": link_key,
                "category_key": category,
                "is_hidden": bool(raw.get("hidden")),
                "label": _clean_text(raw.get("label"), 120),
                "icon": _clean_icon(raw.get("icon")),
            }
        )
    # Any registry option the snapshot forgot is remembered as hidden, so a
    # client that posts a partial list can never make options vanish silently.
    for link in SIDEBAR_LINKS:
        if link.key in seen_items:
            continue
        item_rows.append(
            {
                "key": link.key,
                "category_key": None,
                "is_hidden": True,
                "label": None,
                "icon": None,
            }
        )

    # Per-category ordering follows the snapshot order.
    order_counter: Dict[Optional[str], int] = {}
    for row in item_rows:
        cat = row["category_key"]
        row["sort_order"] = order_counter.get(cat, 0)
        order_counter[cat] = row["sort_order"] + 1

    try:
        SidebarItem.query.delete(synchronize_session=False)
        SidebarCategory.query.delete(synchronize_session=False)
        db.session.flush()
        for row in category_rows:
            db.session.add(SidebarCategory(**row))
        db.session.flush()
        for row in item_rows:
            db.session.add(SidebarItem(**row))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return effective_layout()


def reset_layout() -> Dict[str, object]:
    """Forget the custom layout — the sidebar goes back to the default."""
    try:
        SidebarItem.query.delete(synchronize_session=False)
        SidebarCategory.query.delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return _default_layout()


def available_links() -> List[Dict[str, object]]:
    """Every option the sidebar can show, with its registry metadata."""
    return [
        {
            "key": link.key,
            "label": link.label,
            "icon": link.icon,
            "href": link.url(),
            "default_category": link.default_category,
            "description": link.description,
        }
        for link in SIDEBAR_LINKS
    ]


def layout_payload() -> Dict[str, object]:
    """Layout snapshot in exactly the shape :func:`save_layout` accepts."""
    layout = effective_layout()
    return {
        "categories": [
            {
                "key": c["key"],
                "name": c["name"],
                "icon": c["icon"],
                "is_active": bool(c["is_active"]),
            }
            for c in layout.get("categories") or []
        ],
        "items": [
            {
                "key": i["key"],
                "category": i["category"],
                "hidden": bool(i["hidden"]),
                "label": i["label"],
                "icon": i["icon"],
            }
            for i in layout.get("items") or []
        ],
    }
