"""Tests for Settings → Sidebar Settings (custom categories + drag & drop layout)."""
from __future__ import annotations

from werkzeug.security import generate_password_hash

from models import SidebarCategory, SidebarItem, User, db


def _login(client, username="Admin", password="Admin@fbm12345"):
    # /login bounces an already-authenticated browser, so switch users cleanly.
    client.get("/logout")
    resp = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def _sidebar_html(client, path="/"):
    resp = client.get(path)
    assert resp.status_code == 200, path
    return resp.get_data(as_text=True)


def test_sidebar_settings_page_requires_permission(app, client):
    # Not logged in → login page redirect.
    anon = client.get("/settings/sidebar", follow_redirects=False)
    assert anon.status_code in (302, 303)

    with app.app_context():
        clerk = User(
            username="sb_clerk",
            password_hash=generate_password_hash("Clerk@12345"),
            role="user",
            status="active",
        )
        clerk.can_access_settings = False
        db.session.add(clerk)
        db.session.commit()

    _login(client, "sb_clerk", "Clerk@12345")
    blocked = client.get("/settings/sidebar", follow_redirects=False)
    assert blocked.status_code in (302, 303)
    assert "/settings/sidebar" not in (blocked.headers.get("Location") or "")

    denied = client.post("/settings/sidebar/save", json={"categories": [], "items": []})
    # Either the endpoint permission gate (302 + flash) or the route's own
    # JSON guard (403) may answer — both mean "not allowed".
    assert denied.status_code in (302, 303, 403)


def test_sidebar_settings_page_lists_every_option_and_category(client):
    _login(client)
    html = _sidebar_html(client, "/settings/sidebar")
    assert "Sidebar Settings" in html
    assert "All sidebar options" in html
    # Every default category is offered for editing.
    for name in ("Inventory", "Transactions", "Accounts", "Ledger", "Directory", "System"):
        assert name in html
    # A registry option is present for dragging.
    assert "Stock Summary" in html


def test_custom_category_receives_dragged_option_and_sidebar_follows(app, client):
    _login(client)

    payload = {
        "categories": [
            {"key": "mine", "name": "Yard Work", "icon": "bi-truck", "is_active": True},
        ],
        "items": [
            {"key": "stock_summary", "category": "mine", "hidden": False},
            {"key": "delivery_rents", "category": "mine", "hidden": False},
            {"key": "dashboard", "category": None, "hidden": False},
            {"key": "settings", "category": None, "hidden": True},
        ],
    }
    resp = client.post("/settings/sidebar/save", json=payload)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["ok"] is True

    with app.app_context():
        assert SidebarCategory.query.count() == 1
        assert SidebarItem.query.filter_by(key="stock_summary").one().category_key == "mine"
        assert SidebarItem.query.filter_by(key="settings").one().is_hidden is True

    html = _sidebar_html(client)
    assert "Yard Work" in html
    assert "nav-toggle-btn" in html
    # Hidden option is gone from the sidebar.
    assert "Legacy Data Migration" not in html
    # Dashboard stayed a top-level link.
    assert 'href="/"' in html

    # Rename the category → sidebar label follows.
    payload["categories"][0]["name"] = "Yard Operations"
    assert client.post("/settings/sidebar/save", json=payload).status_code == 200
    assert "Yard Operations" in _sidebar_html(client)


def test_sidebar_item_active_state_uses_custom_placement(client):
    _login(client)
    payload = {
        "categories": [{"key": "money", "name": "Money", "icon": "bi-cash", "is_active": True}],
        "items": [
            {"key": "cash_flow", "category": "money", "hidden": False},
            {"key": "dashboard", "category": None, "hidden": False},
        ],
    }
    assert client.post("/settings/sidebar/save", json=payload).status_code == 200

    html = _sidebar_html(client, "/cash_flow")
    assert "Money" in html
    # The category holding the current page is expanded.
    assert "nav-submenu show" in html
    assert "Cash Flow" in html


def test_inactive_category_and_hidden_items_are_not_rendered(client):
    _login(client)
    payload = {
        "categories": [
            {"key": "visible", "name": "Visible Group", "icon": "bi-eye", "is_active": True},
            {"key": "off", "name": "Hidden Group", "icon": "bi-eye-slash", "is_active": False},
        ],
        "items": [
            {"key": "stock_summary", "category": "visible", "hidden": False},
            {"key": "history", "category": "off", "hidden": False},
            {"key": "dashboard", "category": None, "hidden": False},
        ],
    }
    assert client.post("/settings/sidebar/save", json=payload).status_code == 200
    html = _sidebar_html(client)
    assert "Visible Group" in html
    assert "Hidden Group" not in html
    # The option sits inside the disabled category, so no sidebar link is drawn.
    assert 'bi-clock-history"></i> History' not in html


def test_reset_restores_the_default_layout(app, client):
    _login(client)
    payload = {
        "categories": [{"key": "only", "name": "Only Group", "icon": "bi-star", "is_active": True}],
        "items": [{"key": "stock_summary", "category": "only", "hidden": False}],
    }
    assert client.post("/settings/sidebar/save", json=payload).status_code == 200
    assert "Only Group" in _sidebar_html(client)

    resp = client.post("/settings/sidebar/reset")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    with app.app_context():
        assert SidebarCategory.query.count() == 0
        assert SidebarItem.query.count() == 0

    html = _sidebar_html(client)
    assert "Only Group" not in html
    for name in ("Inventory", "Transactions", "Accounts", "Ledger", "Directory", "System"):
        assert name in html


def test_invalid_payload_is_rejected(client):
    _login(client)
    resp = client.post("/settings/sidebar/save", json={"categories": "nope"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_permissions_still_filter_a_custom_layout(app, client):
    _login(client)
    payload = {
        "categories": [{"key": "everything", "name": "Everything", "icon": "bi-grid", "is_active": True}],
        "items": [
            {"key": "stock_summary", "category": "everything", "hidden": False},
            {"key": "settings", "category": "everything", "hidden": False},
        ],
    }
    assert client.post("/settings/sidebar/save", json=payload).status_code == 200

    with app.app_context():
        clerk = User(
            username="sb_limited",
            password_hash=generate_password_hash("Limited@12345"),
            role="user",
            status="active",
        )
        db.session.add(clerk)
        db.session.commit()

    _login(client, "sb_limited", "Limited@12345")
    html = _sidebar_html(client)
    # The category is drawn (one readable option) but Settings is not.
    assert "Everything" in html
    assert "Stock Summary" in html
    assert "> Settings" not in html


def test_removed_registry_option_is_still_offered_in_settings(client):
    """A saved layout from an older release must not lose newly added options."""
    _login(client)
    payload = {
        "categories": [{"key": "one", "name": "One", "icon": "bi-1-circle", "is_active": True}],
        "items": [{"key": "stock_summary", "category": "one", "hidden": False}],
    }
    assert client.post("/settings/sidebar/save", json=payload).status_code == 200

    page = _sidebar_html(client, "/settings/sidebar")
    # The option that was not part of the snapshot is offered again (hidden by
    # default on the server) instead of silently disappearing.
    assert "Cash Flow" in page


def test_settings_page_has_the_sidebar_settings_entry(client):
    _login(client)
    html = _sidebar_html(client, "/settings")
    assert "/settings/sidebar" in html
    assert "Sidebar Settings" in html


def test_settings_manager_with_permission_can_open_the_designer(app, client):
    with app.app_context():
        manager = User(
            username="sb_manager",
            password_hash=generate_password_hash("Manager@12345"),
            role="user",
            status="active",
        )
        manager.can_access_settings = True
        db.session.add(manager)
        db.session.commit()

    _login(client, "sb_manager", "Manager@12345")
    resp = client.get("/settings/sidebar")
    assert resp.status_code == 200
    assert "Sidebar Settings" in resp.get_data(as_text=True)

    saved = client.post(
        "/settings/sidebar/save",
        json={
            "categories": [{"key": "mg", "name": "Manager Group", "icon": "bi-star", "is_active": True}],
            "items": [{"key": "settings", "category": "mg", "hidden": False}],
        },
    )
    assert saved.status_code == 200
    assert saved.get_json()["ok"] is True


def test_icon_names_are_normalised_and_labels_are_escaped(client):
    _login(client)
    resp = client.post(
        "/settings/sidebar/save",
        json={
            "categories": [{"key": "grp", "name": "Group", "icon": "bi bi-fire", "is_active": True}],
            "items": [
                {
                    "key": "stock_summary",
                    "category": "grp",
                    "hidden": False,
                    "label": "<script>alert(1)</script>Stock",
                    "icon": "fire",
                }
            ],
        },
    )
    assert resp.status_code == 200
    layout = resp.get_json()["layout"]
    assert layout["categories"][0]["icon"] == "bi-fire"
    stock = next(i for i in layout["items"] if i["key"] == "stock_summary")
    assert stock["icon"] == "bi-fire"
    assert stock["label"] == "<script>alert(1)</script>Stock"

    # Jinja escapes the stored label — no injected markup reaches the browser.
    html = _sidebar_html(client)
    assert "<script>alert(1)</script>Stock" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;Stock" in html
