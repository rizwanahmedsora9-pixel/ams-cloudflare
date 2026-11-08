"""bills — split from sales.py."""
from ._common import *  # noqa
from app.services.urdu_names import urdu_name
from app.services.terms import get_selected_terms

def _material_urdu_names():
    """``{english material name (casefolded): urdu name}`` for printed bills.

    Materials carry an optional Urdu name (``Material.name_ur``) that the Urdu
    bill prints instead of the English brand name; anything without one keeps
    its English name so a bill is never left with a blank line.
    """
    try:
        rows = Material.query.filter(
            Material.name_ur.isnot(None), Material.name_ur != ''
        ).all()
    except Exception:
        return {}
    return {(r.name or '').strip().casefold(): r.name_ur.strip()
            for r in rows if (r.name or '').strip() and (r.name_ur or '').strip()}


def _field(item, *names, default=None):
    """Read *names* from a dict row or an ORM/namespace object."""
    for name in names:
        if isinstance(item, dict):
            value = item.get(name)
        else:
            value = getattr(item, name, None)
        if value not in (None, ''):
            return value
    return default


def _with_urdu_item_names(items, lang):
    """Return bill rows with ``name_ur`` filled from the material catalogue."""
    rows = []
    names = _material_urdu_names() if lang == 'ur' else {}
    for item in items or []:
        name = _field(item, 'name', 'product_name', 'material_name', 'material', 'mat_name',
                      default='')
        urdu = ''
        if lang == 'ur':
            urdu = str(_field(item, 'name_ur', default='') or '').strip()
            if not urdu:
                urdu = names.get(str(name).strip().casefold(), '')
            urdu = urdu_name(name, urdu)
        rows.append({
            'name': name,
            'name_ur': urdu,
            'qty': _field(item, 'qty', default=0),
            'price_at_time': _field(item, 'price_at_time', default=0),
        })
    return rows


@bp.route('/download_invoice/<path:bill_no>')
@login_required
def download_invoice(bill_no):
    booking, payment, invoice, sale, grn, pending = _lookup_bill(
        bill_no,
        hint_type=request.args.get('src'),
        hint_id=request.args.get('src_id'),
        hint_client_code=request.args.get('client_code'),
        hint_client_name=request.args.get('client_name'),
        hint_entry_id=request.args.get('entry_id')
    )
    entry_hint_id = request.args.get('entry_id')
    hint_type = (request.args.get('src') or '').strip().lower()
    hint_id = (request.args.get('src_id') or '').strip()

    candidates_map = _bill_lookup_candidates_map(booking, payment, invoice, sale, grn, pending)
    effective_candidates = _effective_collision_candidates(candidates_map)
    if not hint_type and not hint_id and len(effective_candidates) > 1:
        flash('Multiple records match this bill reference. Please choose the exact document type first.', 'warning')
        return redirect(url_for('view_bill', bill_no=bill_no))

    bill_obj = None
    grn_bd = None
    bill_type = ''
    items = []

    client = None
    client_balance = 0
    previous_balance = 0
    recent_deliveries = []
    material_ledger_recent = []
    material_stock_summary = []
    direct_sale_rent_reconciliation = None
    delivery_people = None

    if booking or payment or invoice or sale or pending:
        bill_obj_temp = booking or payment or invoice or sale or pending
        c_name = getattr(bill_obj_temp, 'client_name', None)
        c_code = getattr(bill_obj_temp, 'client_code', None)
        if c_code: client = Client.query.filter_by(code=c_code).first()
        if not client and c_name: client = Client.query.filter_by(name=c_name).first()

        if client:
            cutoff_dt = _bill_cutoff_dt_for_snapshot(
                booking=booking,
                payment=payment,
                invoice=invoice,
                sale=sale,
                pending=pending
            )
            client_balance = _client_balance_as_of(client, cutoff_dt=cutoff_dt)

            effect = 0
            if booking: effect = (booking.amount or 0) - (booking.paid_amount or 0)
            elif sale: effect = (sale.amount or 0) - (getattr(sale, 'discount', 0) or 0) - (sale.paid_amount or 0)
            elif payment: effect = -(payment.amount or 0)
            elif invoice: effect = invoice.balance or 0
            elif pending: effect = pending.amount or 0

            previous_balance = client_balance - effect

            is_booking_flow = False
            if booking:
                is_booking_flow = True
            elif sale and normalize_sale_category(getattr(sale, 'category', None)) in ['Booking Delivery', 'Mixed Transaction']:
                is_booking_flow = True
            elif invoice and getattr(invoice, 'direct_sales', None):
                for ds in invoice.direct_sales:
                    if normalize_sale_category(ds.category) in ['Booking Delivery', 'Mixed Transaction']:
                        is_booking_flow = True
                        break

            delivery_query = Entry.query.filter(
                (Entry.client_code == client.code) | (Entry.client == client.name),
                Entry.type == 'OUT',
                Entry.is_void == False
            )
            if is_booking_flow:
                delivery_query = delivery_query.filter(Entry.client_category == 'Booking Delivery')
            delivery_rows = delivery_query.all()
            if cutoff_dt:
                filtered_rows = []
                for d in delivery_rows:
                    d_dt = _parse_dt_safe(f"{d.date} {d.time}") or _parse_dt_safe(d.date) or datetime.min
                    if d_dt <= cutoff_dt:
                        filtered_rows.append(d)
                delivery_rows = filtered_rows
            recent_deliveries = sorted(
                delivery_rows,
                key=lambda d: (
                    _parse_dt_safe(f"{d.date} {d.time}") or _parse_dt_safe(d.date) or datetime.min,
                    d.id or 0
                ),
                reverse=True
            )[:5]
            if is_booking_flow:
                material_ledger_recent = _material_ledger_recent(
                    client,
                    only_booking=True,
                    limit_per_material=5,
                    cutoff_dt=cutoff_dt
                )

            bill_refs = []
            if booking:
                bill_refs = [booking.manual_bill_no, booking.auto_bill_no, f"BK-{booking.id}"]
            elif payment:
                bill_refs = [payment.manual_bill_no, payment.auto_bill_no, f"PAY-{payment.id}"]
            elif sale:
                bill_refs = [sale.manual_bill_no, sale.auto_bill_no, f"DS-{sale.id}", f"CSH-{sale.id}"]
                if getattr(sale, 'invoice', None) and sale.invoice and getattr(sale.invoice, 'invoice_no', None):
                    bill_refs.append(sale.invoice.invoice_no)
            elif invoice:
                bill_refs = [invoice.invoice_no]
                if getattr(invoice, 'direct_sales', None):
                    for ds in invoice.direct_sales:
                        bill_refs.extend([ds.manual_bill_no, ds.auto_bill_no, f"DS-{ds.id}", f"CSH-{ds.id}"])
            elif pending:
                bill_refs = [pending.bill_no]

            if is_booking_flow:
                material_stock_summary = _material_ledger_current_summary(material_ledger_recent, bill_refs)
            else:
                material_stock_summary = []

    if booking:
        bill_obj = booking
        bill_type = 'Booking'
        items = booking.items
        if not (getattr(booking, 'driver_name', None) or '').strip():
            inferred_driver = _infer_driver_name_from_refs(
                [booking.manual_bill_no, booking.auto_bill_no, f"BK-{booking.id}"],
                allow_booking=True
            )
            if inferred_driver:
                setattr(booking, 'driver_name', inferred_driver)
    elif payment:
        bill_obj = payment
        bill_type = 'Payment'
    elif sale:
        bill_obj = sale
        bill_type = 'DirectSale'
        if not (getattr(sale, 'note', None) or '').strip():
            if getattr(sale, 'invoice', None) and (getattr(sale.invoice, 'note', None) or '').strip():
                sale.note = sale.invoice.note.strip()
        sale_entries = Entry.query.filter(
            Entry.source_module == 'sales',
            Entry.source_table == 'direct_sale',
            Entry.source_id == sale.id,
            Entry.is_void == False
        ).order_by(Entry.id.asc()).all()
        entry_map = {}
        for e in sale_entries:
            key = ((e.material or '').strip(), float(e.qty or 0))
            entry_map.setdefault(key, []).append(e)

        items = []
        for it in (sale.items or []):
            key = ((it.product_name or '').strip(), float(it.qty or 0))
            entry = entry_map.get(key, []).pop(0) if entry_map.get(key) else None
            name = it.product_name
            if entry and entry.booked_material and entry.material and entry.booked_material.strip() != entry.material.strip():
                name = format_alt_material_label(entry.booked_material, entry.material)
            items.append({'name': name, 'qty': it.qty, 'price_at_time': it.price_at_time})

        if not (sale.driver_name or '').strip():
            inferred_driver = _infer_driver_name_from_refs(_direct_sale_bill_refs(sale))
            if inferred_driver:
                sale.driver_name = inferred_driver
        delivery_people = []
        for alloc in (getattr(sale, 'delivery_person_allocations', None) or []):
            if getattr(alloc, 'is_void', False):
                continue
            dp = getattr(alloc, 'delivery_person', None)
            name = (getattr(dp, 'name', None) or '').strip()
            if name:
                delivery_people.append(name)
        if not delivery_people and (sale.driver_name or '').strip():
            delivery_people = [sale.driver_name.strip()]
        rent_row = DeliveryRent.query.filter_by(sale_id=sale.id, is_void=False).order_by(DeliveryRent.id.desc()).first()
        sale_items_payload = [
            {
                'product_name': it.product_name,
                'qty': it.qty,
                'price_at_time': it.price_at_time
            }
            for it in (sale.items or [])
        ]
        fallback_delivery_cost = float(rent_row.amount or 0) if rent_row else 0.0
        effective_delivery_cost = float(getattr(sale, 'delivery_rent_cost', 0) or 0)
        if effective_delivery_cost <= 0:
            effective_delivery_cost = fallback_delivery_cost
        calc_rec = _rent_reconciliation_from_items(
            sale_items_payload,
            delivery_rent_cost=effective_delivery_cost,
            client_name=sale.client_name
        )
        direct_sale_rent_reconciliation = {
            'rent_item_revenue': float(getattr(sale, 'rent_item_revenue', 0) or calc_rec['rent_item_revenue']),
            'delivery_rent_cost': float(getattr(sale, 'delivery_rent_cost', 0) or calc_rec['delivery_rent_cost']),
            'rent_variance_loss': float(getattr(sale, 'rent_variance_loss', 0) or calc_rec['rent_variance_loss'])
        }
    elif invoice:
        bill_obj = invoice
        bill_type = 'Invoice'
        invoice.amount = invoice.total_amount
        if not (getattr(invoice, 'note', None) or '').strip():
            ds_notes = [ds.note.strip() for ds in (getattr(invoice, 'direct_sales', None) or []) if (getattr(ds, 'note', None) or '').strip()]
            if ds_notes:
                invoice.note = ' | '.join(dict.fromkeys(ds_notes))
            elif getattr(invoice, 'entries', None):
                entry_notes = [e.note.strip() for e in invoice.entries if (getattr(e, 'note', None) or '').strip()]
                if entry_notes:
                    invoice.note = ' | '.join(dict.fromkeys(entry_notes))
        driver_name = ''
        if getattr(invoice, 'direct_sales', None):
            for ds in invoice.direct_sales:
                if (ds.driver_name or '').strip():
                    driver_name = ds.driver_name.strip()
                    break
            if not driver_name:
                refs = []
                for ds in invoice.direct_sales:
                    refs.extend(_direct_sale_bill_refs(ds))
                driver_name = _infer_driver_name_from_refs(list(set(refs)), allow_booking=True)
        if driver_name:
            setattr(invoice, 'driver_name', driver_name)
        delivery_people = []
        if getattr(invoice, 'direct_sales', None):
            for ds in invoice.direct_sales:
                for alloc in (getattr(ds, 'delivery_person_allocations', None) or []):
                    if getattr(alloc, 'is_void', False):
                        continue
                    dp = getattr(alloc, 'delivery_person', None)
                    name = (getattr(dp, 'name', None) or '').strip()
                    if name:
                        delivery_people.append(name)
        if not delivery_people and (getattr(invoice, 'driver_name', None) or '').strip():
            delivery_people = [invoice.driver_name.strip()]
        # Calculate discount from linked sales
        invoice_discount = 0
        if getattr(invoice, 'direct_sales', None):
            invoice_discount = sum((getattr(ds, 'discount', 0) or 0) for ds in invoice.direct_sales)
        invoice.discount = invoice_discount
        invoice.paid_amount = max(0, (invoice.total_amount or 0) - invoice_discount - (invoice.balance or 0))
        invoice.date_posted = _parse_dt_safe(getattr(invoice, 'created_at', None)) or (datetime.combine(invoice.date, datetime.min.time()) if invoice.date else None)
        if getattr(invoice, 'entries', None) and invoice.entries:
            entry_total_qty = sum(float(e.qty or 0) for e in invoice.entries)
            inferred_rate = (float(invoice.total_amount or 0) / entry_total_qty) if entry_total_qty > 0 else 0
            items = []
            for e in invoice.entries:
                name = (e.material or '').strip()
                if e.booked_material and e.material and e.booked_material.strip() != e.material.strip():
                    name = format_alt_material_label(e.booked_material, e.material)
                items.append({
                    'name': name,
                    'qty': e.qty,
                    'price_at_time': inferred_rate
                })
        elif getattr(invoice, 'direct_sales', None) and invoice.direct_sales:
            ds = invoice.direct_sales[0]
            # Preserve item rates so line amount matches invoice totals on first-open.
            items = [
                {
                    'name': it.product_name,
                    'qty': it.qty,
                    'price_at_time': (it.price_at_time or 0)
                }
                for it in ds.items
            ]
    elif grn:
        bill_obj = grn
        bill_type = 'GRN'
        from app.services.grn_costing import grn_breakdown
        grn_bd = grn_breakdown(grn)
        grn.amount = grn_bd['supplier_bill_amount']
        grn.paid_amount = grn_bd['supplier_paid']
        items = grn.items
    elif pending:
        bill_obj = SimpleNamespace(
            manual_bill_no=pending.bill_no,
            auto_bill_no='',
            invoice_no='',
            date_posted=_parse_dt_safe(pending.created_at),
            client_name=pending.client_name,
            client_code=pending.client_code,
            amount=pending.amount or 0,
            paid_amount=0,
            reason=pending.reason or '',
            nimbus_no=pending.nimbus_no or '',
            method='',
            photo_path='',
            note=(pending.note or '').strip()
        )
        bill_type = 'PendingBill'
        items = []

    if not bill_obj:
        flash('Bill not found for download', 'danger')
        return redirect(url_for('index'))

    action = (request.args.get('action') or 'download').lower()
    disposition = 'inline' if action in ['print', 'view'] else 'attachment'
    # The approved Urdu layout is a single A5 sheet by default.  ?copies=2
    # asks for the carbon-copy leaf (original + office copy on one A4).
    copies = 2 if (request.args.get('copies') or '').strip() == '2' else 1
    # Bills are single-language documents: ?lang=en (default) or ?lang=ur.
    lang = (request.args.get('lang') or 'en').strip().lower()
    if lang in ('ur', 'urdu', 'urd'):
        lang = 'ur'
    else:
        lang = 'en'

    # Urdu receipts ask before printing/downloading whether terms and
    # conditions should be shown, and which of them.  A direct link without
    # the answer lands on a small confirmation screen first; the bill view
    # page opens the same dialog as a modal so the normal flow is one click.
    show_terms_ur = False
    selected_terms_ur = []
    if lang == 'ur' and 'tc' not in request.args:
        return render_template(
            'urdu_terms_confirm.html',
            bill_no=bill_no,
            action=action,
            copies=copies,
            src=request.args.get('src'),
            src_id=request.args.get('src_id'),
            client_code=request.args.get('client_code'),
            client_name=request.args.get('client_name'),
            entry_id=request.args.get('entry_id'),
        )

    if lang == 'ur':
        tc_raw = (request.args.get('tc') or '').strip().lower()
        want_tc = tc_raw in ('1', 'yes', 'true', 'on')
        tc_ids = []
        for raw in ','.join(request.args.getlist('tc_ids')).split(','):
            raw = raw.strip()
            if raw:
                try:
                    tc_ids.append(int(raw))
                except ValueError:
                    pass
        if want_tc:
            show_terms_ur = True
            selected_terms_ur = get_selected_terms(tc_ids)

    # Prefer saved Urdu names; otherwise use a best-effort transliteration.
    items = _with_urdu_item_names(items, lang)
    client_name_ur = ''
    driver_name_ur = ''
    if lang == 'ur':
        if client is not None:
            client_name_ur = (getattr(client, 'name_ur', None) or '').strip()
        driver_name = (getattr(bill_obj, 'driver_name', None) or '').strip()
        if driver_name:
            driver = DeliveryPerson.query.filter(
                func.lower(func.trim(DeliveryPerson.name)) == driver_name.lower()
            ).first()
            driver_name_ur = urdu_name(driver_name, getattr(driver, 'name_ur', None))
        client_name = getattr(bill_obj, 'client_name', None) or getattr(client, 'name', '')
        client_name_ur = urdu_name(client_name, client_name_ur)
        if delivery_people:
            translated_people = []
            for name in delivery_people:
                driver = DeliveryPerson.query.filter(
                    func.lower(func.trim(DeliveryPerson.name)) == name.strip().lower()
                ).first()
                translated_people.append(urdu_name(name, getattr(driver, 'name_ur', None)))
            delivery_people = translated_people
    tx_code, tx_label, tx_note = _resolve_transaction_type(bill_type, bill_obj, entry_hint_id=entry_hint_id)
    if lang == 'ur':
        from app.services.bilingual import urdu_tx_label, urdu_tx_note
        tx_label = urdu_tx_label(tx_code, tx_label)
        tx_note = urdu_tx_note(tx_note)
        # An Urdu bill is its own document (app/services/urdu_receipt.py), not
        # the English receipt with swapped labels: it has its own sheet,
        # header, meta strip, panel, table, summary and terms.  It is also a
        # single approved A5 sheet by default; ?copies=2 lays the same receipt
        # out twice on one A4 leaf.  Both "Urdu PDF" and "Urdu Print" return it
        # here.
        return _urdu_bill_response(
            bill_type=bill_type,
            bill=bill_obj,
            items=items,
            client=client,
            previous_balance=previous_balance,
            client_balance=client_balance,
            delivery_people=delivery_people,
            driver_name_ur=driver_name_ur,
            client_name_ur=client_name_ur,
            transaction_label=tx_label,
            transaction_note=tx_note,
            terms=selected_terms_ur,
            grn_bd=grn_bd,
            action=action,
            disposition=disposition,
            copies=copies,
        )
    section_map = {
        'Booking': 'BOOKING',
        'Payment': 'PAYMENT',
        'DirectSale': 'DIRECTSALE',
        'Invoice': 'INVOICE',
        'GRN': 'GRN',
        'PendingBill': 'PENDINGBILL'
    }
    section = section_map.get(bill_type, 'BILL')
    template_name = 'view_bill.html'
    if bill_type == 'Payment':
        template_name = 'payment_receipt.html'

    rendered = render_template(
        template_name,
        bill=bill_obj,
        type=bill_type,
        grn_bd=grn_bd,
        items=items,
        client=client,
        client_balance=client_balance,
        previous_balance=previous_balance,
        recent_deliveries=recent_deliveries,
        material_ledger_recent=material_ledger_recent,
        material_stock_summary=material_stock_summary,
        transaction_type_code=tx_code,
        transaction_type_label=tx_label,
        transaction_type_note=tx_note,
        direct_sale_rent_reconciliation=direct_sale_rent_reconciliation,
        delivery_people=delivery_people,
        client_name_ur=client_name_ur,
        driver_name_ur=driver_name_ur,
        pk_now=pk_now,
        auto_print=(action == 'print'),
        bill_lang=lang,
        show_terms_ur=show_terms_ur,
        selected_terms_ur=selected_terms_ur,
    )

    # Keep the two language downloads distinguishable on disk.  The suffix is
    # added after _download_filename() because that helper strips hyphens from
    # the section name.
    def _lang_name(ext):
        base = _download_filename(section, ext)
        stem, _, suffix = base.rpartition('.')
        return f"{stem}-{'UR' if lang == 'ur' else 'EN'}.{suffix}"

    if action != 'print':
        pdf_response = _try_render_weasy_pdf(
            rendered,
            _lang_name('pdf'),
            disposition=disposition,
            lang=lang
        )
        if pdf_response:
            return pdf_response

    if action == 'print':
        # Browser printing gets the same single-language layer as the PDF.
        rendered = _bilingual_print_html(rendered, lang=lang)

    response = make_response(rendered)
    fallback_name = _lang_name('html')
    response.headers['Content-Disposition'] = f'{disposition}; filename={fallback_name}'
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response


# ---------------------------------------------------------------------------
# Urdu bill
# ---------------------------------------------------------------------------
# The Urdu bill is a fixed sheet defined in ``app/services/urdu_receipt.py``;
# this route only collects the bill's data and hands it over.  Keeping the
# document out of ``view_bill.html`` is deliberate: the Urdu sheet must not
# inherit the English receipt's layout (or its black rules, ``INVOICE`` badge
# and English table header) when a label is translated.  The sheet is composed
# onto paper here too: ``copies=1`` (default) prints the single approved A5
# sheet, ``copies=2`` lays the receipt out twice on one A4 landscape leaf.

_URDU_SECTION = {
    'Booking': 'BOOKING',
    'Payment': 'PAYMENT',
    'DirectSale': 'DIRECTSALE',
    'Invoice': 'INVOICE',
    'GRN': 'GRN',
    'PendingBill': 'PENDINGBILL',
}


def _urdu_bill_response(*, bill_type, bill, items, client, previous_balance,
                        client_balance, delivery_people, driver_name_ur,
                        client_name_ur, transaction_label, transaction_note,
                        terms, grn_bd, action, disposition, copies=1):
    """Return the Urdu bill as a PDF (download) or as the print page.

    ``copies`` is the carbon-copy switch: 1 (the default) prints the single
    approved A5 sheet; 2 prints the same receipt twice on one A4 landscape
    leaf - original for the customer on the right, office copy on the left.
    """
    from app.services import bill_urdu
    from app.services.files_pdf import _safe_download_name
    from app.services.time_money import pk_now

    settings_obj = Settings.query.first()
    client_name = getattr(bill, 'client_name', '') or (
        getattr(client, 'name', '') if client is not None else '')
    party_label = ''

    document = bill_urdu.build_document(
        bill_type=bill_type,
        bill=bill,
        items=items,
        client=client,
        previous_balance=previous_balance,
        client_balance=client_balance,
        delivery_people=delivery_people,
        driver_name_ur=driver_name_ur,
        client_name_ur=client_name_ur,
        transaction_label=transaction_label,
        transaction_note=transaction_note,
        settings=settings_obj,
        terms=terms,
        grn_bd=grn_bd,
        party_label=party_label,
    )

    stamp = pk_now().strftime('%d-%m-%Y_%I-%M%p')
    section = _URDU_SECTION.get(bill_type, 'BILL')
    title = f"Urdu {bill_type or 'Bill'} - {document.get('bill_no') or ''}".strip()

    if action == 'print':
        html = bill_urdu.render_html(document, title=title,
                                     auto_print=False, copies=copies)
        response = make_response(html)
        name = _safe_download_name(f'{section}-{stamp}-UR.html', 'bill-ur.html')
        response.headers['Content-Disposition'] = f'{disposition}; filename={name}'
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    data = bill_urdu.render_pdf(document, title=title, copies=copies)
    if not data:
        # ReportLab is a hard dependency of the PDF path; if it is missing the
        # printable page is still a correct Urdu bill, so serve that instead of
        # an error.
        html = bill_urdu.render_html(document, title=title, copies=copies)
        response = make_response(html)
        name = _safe_download_name(f'{section}-{stamp}-UR.html', 'bill-ur.html')
        response.headers['Content-Disposition'] = f'{disposition}; filename={name}'
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        return response

    name = _safe_download_name(f'{section}-{stamp}-UR.pdf', 'bill-ur.pdf')
    response = make_response(data)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Length'] = str(len(data))
    response.headers['Content-Disposition'] = f'{disposition}; filename={name}'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response
