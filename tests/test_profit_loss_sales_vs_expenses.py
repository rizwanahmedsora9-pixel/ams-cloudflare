"""Tests separating sales transactions from dedicated expense transactions on Profit & Loss."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
import re

import pytest
from openpyxl import load_workbook

from models import (
    Account,
    AccountTransaction,
    CashFlowCategory,
    CashFlowParty,
    CashFlowSubcategory,
    Client,
    DirectSale,
    DirectSaleItem,
    Entry,
    FbmCashDrawerEntry,
    GRN,
    GRNCharge,
    GRNItem,
    Material,
    Supplier,
    WaiveOff,
    db,
)


def _login(client):
    response = client.post(
        "/login",
        data={"username": "Admin", "password": "Admin@fbm12345"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _section(html: str, card_id: str, next_marker: str | None = None) -> str:
    start = html.find(f'id="{card_id}"')
    assert start != -1, f"Missing section {card_id}"
    if next_marker:
        end = html.find(next_marker, start)
        if end != -1:
            return html[start:end]
    return html[start:]


@pytest.fixture()
def pl_split_data(app, client):
    _login(client)
    day = datetime(2026, 11, 10, 11, 0)
    with app.app_context():
        cash = Account(
            name="Main Cash",
            type="company",
            category="cash",
            source_category="Company",
            account_type="company",
            balance=100_000.0,
            balance_minor=10_000_000,
            opening_balance=100_000.0,
            opening_balance_minor=10_000_000,
            opening_balance_date=datetime(2026, 1, 1),
            is_active=True,
        )
        cust = Client(name="Alpha Builders", code="C-101", is_active=True)
        supp = Supplier(name="Lucky Cement", is_active=True)
        mat = Material(name="Cement OPC", code="CEM-OPC", unit="Bags", total=100.0)
        cat = CashFlowCategory(name="Office Expenses", direction="out", is_active=True)
        db.session.add_all([cash, cust, supp, mat, cat])
        db.session.flush()

        sub = CashFlowSubcategory(category_id=cat.id, name="Office Rent", is_active=True)
        party = CashFlowParty(name="Tariq Landlord", party_type="person", is_active=True)
        db.session.add_all([sub, party])
        db.session.flush()

        grn = GRN(
            supplier_id=supp.id,
            supplier=supp.name,
            manual_bill_no="GRN-501",
            auto_bill_no="AGRN-501",
            date_posted=day,
            is_void=False,
        )
        db.session.add(grn)
        db.session.flush()

        grn_item = GRNItem(
            grn_id=grn.id,
            mat_name="Cement OPC",
            qty=100.0,
            price_at_time=1000.0,
            landed_unit_cost=1000.0,
            base_rate_minor=100_000,
            allocated_charges_minor=0,
            line_landed_cost_minor=10_000_000,
            landed_unit_cost_minor=100_000,
            is_void=False,
        )
        db.session.add(grn_item)
        db.session.flush()

        grn_expense = GRNCharge(
            grn_id=grn.id,
            charge_type="UNLOADING",
            label="Godown Labour Unloading",
            amount=600.0,
            amount_minor=60_000,
            recipient_type="LABOUR",
            recipient_name="Godown Team",
            cost_treatment="EXPENSE",
            include_in_supplier=False,
            is_void=False,
        )
        db.session.add(grn_expense)

        sale = DirectSale(
            client_name=cust.name,
            client_code=cust.code,
            category="Cash",
            amount=15_000.0,
            paid_amount=15_000.0,
            manual_bill_no="INV-901",
            auto_bill_no="DS-901",
            date_posted=day,
            is_void=False,
        )
        db.session.add(sale)
        db.session.flush()

        sale_item = DirectSaleItem(
            sale_id=sale.id,
            product_name="Cement OPC",
            qty=10.0,
            price_at_time=1500.0,
            grn_item_id=grn_item.id,
            cost_rate_at_sale=1000.0,
        )
        out_entry = Entry(
            type="OUT",
            material="Cement OPC",
            qty=10.0,
            client=cust.name,
            client_code=cust.code,
            bill_no="INV-901",
            auto_bill_no="DS-901",
            date="2026-11-10",
            time="11:00",
            is_void=False,
        )
        drawer_expense = FbmCashDrawerEntry(
            entry_type="out",
            amount=400.0,
            category="Staff Tea & Refreshments",
            method="Cash",
            note="Daily chai",
            date_posted=day,
            is_void=False,
        )
        waive = WaiveOff(
            client_code=cust.code,
            client_name=cust.name,
            bill_no="WAIVE-1",
            amount=200.0,
            reason="Rounding discount",
            date_posted=day,
            is_void=False,
        )
        db.session.add_all([sale_item, out_entry, drawer_expense, waive])
        db.session.commit()

        from app.services.cash_flow_svc import SRC_ACCOUNT_EXPENSE, save_manual_cash_flow_entry

        entry, _ = save_manual_cash_flow_entry(
            direction="out",
            amount=2500.0,
            account_id=cash.id,
            category_id=cat.id,
            subcategory_id=sub.id,
            party_id=party.id,
            party_name="",
            description="November office rent",
            note="Cash voucher paid",
            reference="EXP-901",
            date_posted=day,
            idempotency_key="pl-split-exp-1",
            create_missing=False,
            require_party=True,
            allow_party_create=False,
            entry_source=SRC_ACCOUNT_EXPENSE,
        )
        db.session.commit()

        return {
            "cash_id": cash.id,
            "cust_name": cust.name,
            "cust_code": cust.code,
            "cat_id": cat.id,
            "sub_id": sub.id,
            "party_id": party.id,
            "tx_id": entry.account_tx_id,
            "drawer_id": drawer_expense.id,
            "grn_charge_id": grn_expense.id,
            "sale_id": sale.id,
            "waive_id": waive.id,
        }


def test_sales_and_expense_transactions_are_separated_and_reconciled(app, client, pl_split_data):
    with app.app_context():
        from app.services.profit_loss import build_profit_loss_report

        report = build_profit_loss_report(
            start_date="2026-11-10",
            end_date="2026-11-10",
            include_position=False,
        )

        # Gross profit: 15,000 - 10,000 = 5,000
        # Operating expenses: 2,500 (rent) + 400 (tea) + 600 (GRN unloading) = 3,500
        # Other losses (WaiveOff): 200
        # Net profit: 5,000 - 3,500 - 200 = 1,300
        assert report["summary"]["total_revenue"] == pytest.approx(15_000.0)
        assert report["summary"]["total_cogs"] == pytest.approx(10_000.0)
        assert report["summary"]["total_expenses"] == pytest.approx(3_500.0)
        assert report["summary"]["total_other_losses"] == pytest.approx(200.0)
        assert report["summary"]["total_profit"] == pytest.approx(1_300.0)
        assert report["breakdown"]["reconcile"]["matches"] is True
        assert report["breakdown"]["reconcile"]["operating_expenses"] == pytest.approx(3_500.0)

        # Sales table contains ONLY sales rows (never expenses or waive-offs)
        assert len(report["sales_transactions"]) == 1
        assert report["sales_transactions"][0]["reference"] == "MB NO.INV-901"
        assert all(row["entry_type"] != "expense" for row in report["sales_transactions"])
        assert report["sales_summary"]["profit"] == pytest.approx(5_000.0)

        # Dedicated expense table contains ALL 3 expense sources
        assert len(report["expense_transactions"]) == 3
        exp_refs = {row["reference"] for row in report["expense_transactions"]}
        assert exp_refs == {
            f"ATX-{pl_split_data['tx_id']}",
            f"DRAWER-{pl_split_data['drawer_id']}",
            f"GRNCH-{pl_split_data['grn_charge_id']}",
        }
        assert report["expense_summary"]["expense"] == pytest.approx(3_500.0)
        assert report["expense_summary"]["profit"] == pytest.approx(-3_500.0)

        # Other gains/losses contains WaiveOff only
        assert len(report["other_transactions"]) == 1
        assert report["other_transactions"][0]["reference"] == "WAIVE-1"
        assert report["other_summary"]["other_loss"] == pytest.approx(200.0)

        # Combined profit reconciles across the three mutually-exclusive tables
        assert (
            report["sales_summary"]["profit"]
            + report["expense_summary"]["profit"]
            + report["other_summary"]["profit"]
        ) == pytest.approx(report["summary"]["total_profit"])

    # Verify rendered HTML keeps expenses out of "Profit / loss by sales transaction"
    # and renders them cleanly in "Profit / loss by expense transaction".
    resp = client.get("/profit_reports?period=custom&start_date=2026-11-10&end_date=2026-11-10")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    sales_card = _section(html, "pl-sales-transactions", 'id="pl-expense-transactions"')
    expense_card = _section(html, "pl-expense-transactions", 'id="pl-other-transactions"')
    other_card = _section(html, "pl-other-transactions", "Collections &amp; credit")

    assert "Profit / loss by sales transaction" in sales_card
    assert "INV-901" in sales_card
    assert "Cement OPC" in sales_card
    assert "Office Expenses" not in sales_card
    assert "Staff Tea &amp; Refreshments" not in sales_card
    assert "Godown Labour Unloading" not in sales_card
    assert "WAIVE-1" not in sales_card
    assert f"ATX-{pl_split_data['tx_id']}" not in sales_card
    assert "view=entries" not in sales_card

    assert "Profit / loss by expense transaction" in expense_card
    assert f"ATX-{pl_split_data['tx_id']}" in expense_card
    assert "EXP-901" in expense_card
    assert "Office Expenses" in expense_card
    assert "Office Rent" in expense_card
    assert "Tariq Landlord" in expense_card
    assert "November office rent" in expense_card
    assert "Cash voucher paid" in expense_card
    assert "[SRC:CashFlow:" not in expense_card
    assert "Staff Tea &amp; Refreshments" in expense_card
    assert "Godown Labour Unloading" in expense_card
    assert "Godown Team" in expense_card
    assert "3,500.00" in expense_card

    assert "WAIVE-1" in other_card
    assert "Rounding discount" in other_card

    # Partial AJAX update and explorer views both succeed cleanly
    partial = client.get(
        "/profit_reports?period=custom&start_date=2026-11-10&end_date=2026-11-10&partial=1"
    )
    assert partial.status_code == 200
    assert 'id="pl-expense-transactions"' in partial.get_data(as_text=True)

    entries_exp = client.get(
        "/profit_reports?period=custom&start_date=2026-11-10&end_date=2026-11-10&view=entries&transaction_group=expenses"
    )
    assert entries_exp.status_code == 200
    entries_html = entries_exp.get_data(as_text=True)
    assert "Operating Expense Entries" in entries_html
    assert "November office rent" in entries_html


def test_independent_pagination_and_sorting_for_sales_and_expenses(app, client, pl_split_data):
    day = datetime(2026, 11, 10, 12, 0)
    with app.app_context():
        # Add 11 more sales (12 total) and 10 more drawer expenses (13 total)
        # so per_page=10 produces 2 pages for sales and 2 pages for expenses.
        grn_item = GRNItem.query.first()
        for idx in range(2, 13):
            sale = DirectSale(
                client_name="Alpha Builders",
                client_code="C-101",
                category="Cash",
                amount=1500.0,
                paid_amount=1500.0,
                manual_bill_no=f"INV-{900 + idx}",
                auto_bill_no=f"DS-{900 + idx}",
                date_posted=day,
                is_void=False,
            )
            db.session.add(sale)
            db.session.flush()
            db.session.add(
                DirectSaleItem(
                    sale_id=sale.id,
                    product_name="Cement OPC",
                    qty=1.0,
                    price_at_time=1500.0,
                    grn_item_id=grn_item.id,
                    cost_rate_at_sale=1000.0,
                )
            )
        for idx in range(1, 11):
            db.session.add(
                FbmCashDrawerEntry(
                    entry_type="out",
                    amount=float(100 + idx),
                    category=f"Misc Expense {idx:02d}",
                    method="Cash",
                    note=f"Drawer note {idx:02d}",
                    date_posted=day,
                    is_void=False,
                )
            )
        db.session.commit()

    # Sales page 2, Expense page 1
    r1 = client.get(
        "/profit_reports?period=custom&start_date=2026-11-10&end_date=2026-11-10&per_page=10&page=2&exp_page=1"
    )
    assert r1.status_code == 200
    h1 = r1.get_data(as_text=True)
    assert "Showing 11–12 of 12 sales entries" in h1
    assert "Showing 1–10 of 13 expense entries" in h1

    # Expense page 2 preserves sales page 2
    r2 = client.get(
        "/profit_reports?period=custom&start_date=2026-11-10&end_date=2026-11-10&per_page=10&page=2&exp_page=2"
    )
    assert r2.status_code == 200
    h2 = r2.get_data(as_text=True)
    assert "Showing 11–12 of 12 sales entries" in h2
    assert "Showing 11–13 of 13 expense entries" in h2

    exp_card_p2 = _section(h2, "pl-expense-transactions", 'id="pl-other-transactions"')
    assert "exp_sort=expense" in exp_card_p2
    assert "page=2" in exp_card_p2

    # Sorting expenses by amount ascending puts Rs. 101.00 first on page 1,
    # and preserves the active sales page=2.
    r3 = client.get(
        "/profit_reports?period=custom&start_date=2026-11-10&end_date=2026-11-10&per_page=10&page=2&exp_sort=expense&exp_order=asc"
    )
    assert r3.status_code == 200
    h3 = r3.get_data(as_text=True)
    assert "Showing 11–12 of 12 sales entries" in h3
    exp_card = _section(h3, "pl-expense-transactions", 'id="pl-other-transactions"')
    assert "Misc Expense 01" in exp_card
    assert "2,500.00" not in exp_card.split("<tfoot>")[0]
    assert "page=2" in exp_card


def test_excel_and_pdf_template_include_dedicated_sales_and_expense_sections(app, client, pl_split_data):
    excel_resp = client.get(
        "/profit_reports/export/excel?period=custom&start_date=2026-11-10&end_date=2026-11-10"
    )
    assert excel_resp.status_code == 200
    wb = load_workbook(BytesIO(excel_resp.data), data_only=True)
    assert "Transactions" in wb.sheetnames
    assert "Sales Transactions" in wb.sheetnames
    assert "Expense Transactions" in wb.sheetnames
    assert "Expenses by Category" in wb.sheetnames

    sales_rows = list(wb["Sales Transactions"].iter_rows(min_row=2, values_only=True))
    exp_rows = list(wb["Expense Transactions"].iter_rows(min_row=2, values_only=True))
    assert len(sales_rows) == 1
    assert sales_rows[0][2] == "MB NO.INV-901"
    assert len(exp_rows) == 3
    assert sum(float(r[10] or 0) for r in exp_rows) == pytest.approx(3_500.0)

    # Render the PDF template directly to confirm separate sales and expense sections
    from flask import render_template
    from app.blueprints.reports._profit_profit_reports import _template_context
    from app.services.profit_loss import build_profit_loss_report

    with app.test_request_context(
        "/profit_reports/export/pdf?period=custom&start_date=2026-11-10&end_date=2026-11-10"
    ):
        report = build_profit_loss_report(
            start_date="2026-11-10", end_date="2026-11-10", include_position=False
        )
        ctx = _template_context(report, "custom", "Custom", lambda *a, **kw: "#")
        ctx.update({
            "summary": report["export_summary"],
            "previous_summary": report["export_previous_summary"],
            "comparison": report["export_comparison"],
            "daily_insights": report["export_daily_insights"],
            "top_items": report["export_top_items"],
        })
        pdf_html = render_template("profit_report_pdf.html", **ctx)
    assert "Profit / loss by sales transaction (1 rows" in pdf_html
    assert "Profit / loss by expense transaction (3 rows" in pdf_html
    assert "INV-901" in pdf_html
    assert "November office rent" in pdf_html
    assert re.search(r"Total operating expenses \(3\).*?3,500\.00", pdf_html, re.S)


def test_personal_expense_and_filters_target_expense_table(app, client, pl_split_data):
    # Post Pay Money -> Personal Expense via the Accounts endpoint
    post_resp = client.post(
        "/accounts/transactions/new",
        data={
            "tx_mode": "pay",
            "pay_target": "personal_expense",
            "pay_from_account_id": str(pl_split_data["cash_id"]),
            "amount": "500",
            "method": "Cash",
            "target_label": "Personal home utility bill",
            "expense_category_id": str(pl_split_data["cat_id"]),
            "expense_subcategory_id": str(pl_split_data["sub_id"]),
            "expense_party_id": str(pl_split_data["party_id"]),
            "note": "Owner drawing",
            "reference": "PERS-55",
            "date_posted": "2026-11-10T14:00",
            "idempotency_key": "pl-split-pers-55",
        },
        follow_redirects=False,
    )
    assert post_resp.status_code in (302, 303)

    # Search by recipient name narrows #pl-expense-transactions without touching sales
    search_resp = client.get(
        "/profit_reports?period=custom&start_date=2026-11-10&end_date=2026-11-10&q=Landlord"
    )
    assert search_resp.status_code == 200
    search_html = search_resp.get_data(as_text=True)
    sales_card = _section(search_html, "pl-sales-transactions", 'id="pl-expense-transactions"')
    exp_card = _section(search_html, "pl-expense-transactions", "Collections &amp; credit")
    assert "No sales transactions match these filters." in sales_card
    assert "November office rent" in exp_card
    assert "Personal home utility bill" in exp_card
    assert "PERS-55" in exp_card

    # Filtering by transaction_group=expenses shows all 4 expenses (3,500 + 500 = 4,000)
    group_resp = client.get(
        "/profit_reports?period=custom&start_date=2026-11-10&end_date=2026-11-10&transaction_group=expenses"
    )
    assert group_resp.status_code == 200
    group_html = group_resp.get_data(as_text=True)
    group_exp_card = _section(group_html, "pl-expense-transactions", "Collections &amp; credit")
    assert "4,000.00" in group_exp_card
    assert "Personal home utility bill" in group_exp_card

