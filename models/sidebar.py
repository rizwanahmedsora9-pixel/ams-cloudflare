"""Customisable sidebar layout (Sidebar Settings).

The sidebar used to be hard-coded inside ``templates/layout.html``.  These two
tables store the manager's own layout instead:

  * :class:`SidebarCategory` — a collapsible category ("Inventory", …)
  * :class:`SidebarItem`     — one link placed in a category (or at top level)

``SidebarItem.key`` is the stable key of a link from the registry in
``app/services/sidebar_nav.py`` (label / icon / URL / permission all live in
code so a code update never loses an option).  The rows only remember
*placement*: which category, in what order, and whether it is hidden from the
sidebar or has a custom label/icon.

No rows at all means "use the built-in default layout", so a fresh database
renders exactly the sidebar the app shipped with.
"""
from __future__ import annotations

from .__base import *  # noqa
from .helpers import *  # noqa


class SidebarCategory(db.Model):
    __tablename__ = 'sidebar_category'

    id = db.Column(db.Integer, primary_key=True)
    # Stable key used by the drag & drop snapshot API ("inventory", "c1a2b3", …)
    key = db.Column(db.String(60), unique=True, index=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    icon = db.Column(db.String(80), default='bi-folder2', nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=pk_model_now)
    updated_at = db.Column(db.DateTime, default=pk_model_now, onupdate=pk_model_now)


class SidebarItem(db.Model):
    __tablename__ = 'sidebar_item'

    id = db.Column(db.Integer, primary_key=True)
    # Registry key of the link (e.g. "stock_summary"), unique per row.
    key = db.Column(db.String(80), unique=True, index=True, nullable=False)
    # Category key, or NULL for a top-level (uncategorised) link.
    category_key = db.Column(db.String(60), index=True, nullable=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False, index=True)
    # Hidden items stay in the layout but are not drawn in the sidebar.
    is_hidden = db.Column(db.Boolean, default=False, nullable=False)
    # Optional label / icon overrides (NULL = use the registry default).
    label = db.Column(db.String(120), nullable=True)
    icon = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_model_now)
    updated_at = db.Column(db.DateTime, default=pk_model_now, onupdate=pk_model_now)
