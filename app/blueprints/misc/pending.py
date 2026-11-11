"""pending — split from misc.py."""
from ._common import *  # noqa
from app.services.grn_costing import charge_billed_to_supplier
from sqlalchemy.exc import IntegrityError

@bp.route('/add_pending_bill', methods=['POST'])
@login_required
def add_pending_bill():
    note = request.form.get('note', '').strip()
    client_code = request.form.get('client_code', '').strip()
    client_obj = get_client_by_input(client_code)
    photo_path = save_photo(request.files.get('photo'))

    if not client_obj:
        flash('Invalid Client Code.', 'danger')
        return redirect(url_for('pending_bills'))

    raw_bill_no = request.form.get('bill_no', '').strip()
    normalized_bill_no = normalize_manual_bill(raw_bill_no)
    if not normalized_bill_no:
        flash('Bill number is required', 'danger')
        return redirect(url_for('pending_bills'))

    conflict = find_bill_conflict(normalized_bill_no)
    if conflict:
        flash(f"Bill '{normalized_bill_no}' already exists in {conflict[0]} #{conflict[1]}.", 'danger')
        return redirect(url_for('pending_bills'))

    bill = PendingBill(client_code=client_code,
                       client_name=client_obj.name,
                       bill_no=normalized_bill_no,
                       bill_kind='MB',
                       is_manual=True,
                       nimbus_no=request.form.get('nimbus_no', '').strip(),
                       amount=float(request.form.get('amount') or 0),
                       reason=request.form.get('reason', '').strip(),
                       photo_url=request.form.get('photo_url', '').strip(),
                       photo_path=photo_path,
                       created_at=pk_now().strftime('%Y-%m-%d %H:%M'),
                       created_by=current_user.username,
                       note=note)
    db.session.add(bill)
    db.session.commit()
    flash('Pending bill added', 'success')
    return redirect(url_for('pending_bills'))


@bp.route('/edit_pending_bill/<int:id>', methods=['POST'])
@login_required
def edit_pending_bill(id):
    bill = db.session.get(PendingBill, id)
    if bill:
        old_bill_no = bill.bill_no
        old_client_code = bill.client_code

        client_code = request.form.get('client_code', '').strip()
        client_obj = get_client_by_input(client_code)

        if not client_obj:
            flash('Invalid Client Code.', 'danger')
            return redirect(url_for('pending_bills'))

        bill.client_code = client_code
        bill.client_name = client_obj.name
        raw_bill_no = request.form.get('bill_no', '').strip()
        bill.bill_no = normalize_manual_bill(raw_bill_no) if raw_bill_no else ''
        bill.bill_kind = parse_bill_kind(bill.bill_no)
        bill.is_manual = (bill.bill_kind == 'MB')
        if bill.bill_no:
            conflict = find_bill_conflict(bill.bill_no)
            if conflict and not (conflict[0] == 'PendingBill' and conflict[1] == bill.id):
                flash(f"Bill '{bill.bill_no}' already exists in {conflict[0]} #{conflict[1]}.", 'danger')
                return redirect(url_for('pending_bills'))
        bill.nimbus_no = request.form.get('nimbus_no', '').strip()
        bill.amount = float(request.form.get('amount') or 0)
        bill.reason = request.form.get('reason', '').strip()
        bill.photo_url = request.form.get('photo_url', '').strip()
        bill.note = request.form.get('note', '').strip()
        
        new_photo = save_photo(request.files.get('photo'))
        if new_photo:
            bill.photo_path = new_photo

        update_data = {
            'bill_no': bill.bill_no,
            'client': bill.client_name,
            'client_code': bill.client_code
        }
        Entry.query.filter_by(bill_no=old_bill_no, client_code=old_client_code).update(update_data)

        db.session.commit()
        flash('Bill updated', 'success')
    return redirect(url_for('pending_bills'))


@bp.route('/delete_pending_bill/<int:id>', methods=['POST'])
@login_required
def delete_pending_bill(id):
    bill = db.session.get(PendingBill, id)
    if bill:
        # Policy: deletes remove the row — no void flags are left behind.
        # Follow-up reminders/contacts of this bill go with it.
        try:
            from app.services.void_rebuild import hard_delete_pending_bill
            hard_delete_pending_bill(bill)
        except Exception:
            db.session.rollback()
            FollowUpContact.query.filter_by(pending_bill_id=id).delete(
                synchronize_session=False)
            FollowUpReminder.query.filter_by(pending_bill_id=id).delete(
                synchronize_session=False)
            db.session.delete(bill)
        db.session.commit()
        flash('Bill deleted', 'warning')
    return redirect(url_for('pending_bills'))


@bp.route('/export_pending_bills')
@login_required
def export_pending_bills():
    if current_user.role not in ['admin', 'root']:
        flash('Only tenant admin or root can run import/export operations.', 'danger')
        return redirect(url_for('index'))
    """Redirects to the generic export function for pending bills."""
    # This is a convenience route to fix a template error.
    # It redirects to the actual export endpoint in the import_export blueprint.
    args = request.args.to_dict()
    args['dataset'] = 'pending_bills'
    return redirect(url_for('import_export.export_data', **args))


@bp.route('/import_pending_bills', methods=['GET', 'POST'])
@login_required
def import_pending_bills():
    if current_user.role not in ['admin', 'root']:
        flash('Only tenant admin or root can run import/export operations.', 'danger')
        return redirect(url_for('index'))
    """Legacy pending-bills import endpoint (GET+POST compatibility)."""
    if request.method == 'GET':
        return redirect(url_for('import_export.import_export_page'))

    file = request.files.get('file')
    if not file:
        flash('No file selected for import.', 'danger')
        return redirect(url_for('pending_bills'))

    try:
        import pandas as pd
        from blueprints.import_export import backup_database, _process_pending_bills

        ok, msg = backup_database()
        if not ok:
            flash(f'Backup failed: {msg}', 'danger')
            return redirect(url_for('pending_bills'))

        if file.filename.lower().endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        df.columns = [c.lower().strip().replace(' ', '_') for c in df.columns]
        df = df.fillna('')
        report = {'imported': 0, 'updated': 0, 'skipped': 0, 'errors': 0, 'error_details': [], 'discrepancies': []}
        _process_pending_bills(
            df=df,
            strategy='update',
            missing_client_strategy='create',
            report=report,
            allow_missing=False
        )
        db.session.commit()
        flash(
            f"Pending Bills import complete. Imported: {report['imported']}, Updated: {report['updated']}, "
            f"Skipped: {report['skipped']}, Errors: {report['errors']}",
            'success'
        )
    except Exception as exc:
        db.session.rollback()
        logging.getLogger('pending_bills').exception('Pending bills import failed')
        flash(f'Import failed: {exc or "the file could not be processed. No data was changed. Check the file format and try again."}', 'danger')

    return redirect(url_for('pending_bills'))


@bp.route('/edit_grn/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_grn(id):
    from app.blueprints.ops.grn import _parse_grn_money
    grn_obj = GRN.query.get_or_404(id)
    restricted = _enforce_grn_backdate_policy(grn_obj.date_posted, 'Edit GRN', entity_id=grn_obj.id)
    if restricted:
        return restricted

    if request.method == 'POST':
        from app.services.grn_costing import recompute_landed_costs
        from app.services.grn_edit import recost_consuming_sales, sync_items_from_form

        is_landed = (getattr(grn_obj, 'costing_mode', '') or '').upper() == 'LANDED'
        old_supplier_id = grn_obj.supplier_id
        old_auto_pay = _find_grn_auto_supplier_payment(grn_obj)
        old_pay_account_id = None
        old_pay_amount = 0.0
        if old_auto_pay and not bool(getattr(old_auto_pay, 'is_void', False)):
            old_pay_account_id = getattr(old_auto_pay, 'payment_account_id', None)
            old_pay_amount = float(getattr(old_auto_pay, 'amount', 0) or 0)
        # 1. Update GRN header fields.  Stock lines are synced in place further
        #    down (app/services/grn_edit.py), after the supplier / date / bill
        #    fields they are stamped with are final.
        supplier_input = request.form.get('supplier', '').strip()
        supplier_id_input = (request.form.get('supplier_id') or '').strip()
        supplier_obj = None
        if supplier_id_input.isdigit():
            supplier_obj = db.session.get(Supplier, int(supplier_id_input))
        if not supplier_obj and supplier_input:
            supplier_obj = get_supplier_by_input(supplier_input)
        if not supplier_obj and supplier_input:
            supplier_obj = Supplier(name=supplier_input, is_active=True)
            db.session.add(supplier_obj)
            db.session.flush()

        grn_obj.supplier = supplier_obj.name if supplier_obj else supplier_input
        grn_obj.supplier_id = supplier_obj.id if supplier_obj else None
        manual_bill_raw = request.form.get('manual_bill_no', '').strip()
        grn_obj.manual_bill_no = normalize_manual_bill(manual_bill_raw) if manual_bill_raw else ''
        grn_obj.note = request.form.get('note', '').strip()
        # Only overwrite photo_url when the form actually carries a value;
        # the wizard has no photo_url input, so blindly assigning '' was
        # erasing the stored link on every edit.
        if (request.form.get('photo_url') or '').strip():
            grn_obj.photo_url = request.form.get('photo_url', '').strip()

        new_photo = save_photo(request.files.get('photo'))
        if new_photo:
            grn_obj.photo_path = new_photo

        # Legacy flat charge columns: only touch them when the old form
        # actually posted them, otherwise a charge-grid form would silently
        # erase historical values.  LANDED GRNs use grn_charge rows instead.
        try:
            if 'loading_cost' in request.form:
                grn_obj.loading_cost = _parse_grn_money(request.form.get('loading_cost', 0), 'Load Expense')
            if 'freight_cost' in request.form:
                grn_obj.freight_cost = _parse_grn_money(request.form.get('freight_cost', 0), 'Freight Expense')
            if 'other_expense' in request.form:
                grn_obj.other_expense = _parse_grn_money(request.form.get('other_expense', 0), 'Other Expense')
            if 'adjustment_amount' in request.form:
                grn_obj.adjustment_amount = _parse_grn_money(request.form.get('adjustment_amount', 0), 'Adjustment Amount')
        except ValueError as ve:
            flash(str(ve), 'danger')
            return redirect(url_for('edit_grn', id=grn_obj.id))
        try:
            grn_obj.discount, _ = _parse_discount_fields(
                request.form.get('discount', 0),
                '',
                label='GRN discount',
                require_reason=False
            )
        except ValueError as ve:
            flash(str(ve), 'danger')
            return redirect(url_for('edit_grn', id=grn_obj.id))
        if is_landed:
            # A1: a GRN never pays, on edit either.
            grn_obj.paid_amount = 0
            grn_obj.payment_type = 'Credit'
            grn_obj.payment_account_id = None
            grn_obj.bank_name = grn_obj.account_name = grn_obj.account_no = ''
            payment_account_id = None
            expected_pay_category = None
        else:
            try:
                grn_obj.paid_amount = _parse_grn_money(request.form.get('paid_amount', 0), 'Paid Amount')
            except ValueError as ve:
                flash(str(ve), 'danger')
                return redirect(url_for('edit_grn', id=grn_obj.id))
            grn_obj.payment_type = request.form.get('payment_type', '').strip()
            payment_account_id = request.form.get('payment_account_id')
            grn_obj.bank_name = request.form.get('bank_name', '').strip()
            grn_obj.account_name = request.form.get('account_name', '').strip()
            grn_obj.account_no = request.form.get('account_no', '').strip()
        try:
            grn_obj.tax_percent = _parse_grn_money(request.form.get('tax_percent', 0), 'Purchase Tax %')
            grn_obj.tax_amount = _parse_grn_money(request.form.get('tax_amount', 0), 'Purchase Tax Amount')
        except ValueError as ve:
            flash(str(ve), 'danger')
            return redirect(url_for('edit_grn', id=grn_obj.id))
        grn_obj.tax_type = request.form.get('tax_type', '').strip()
        grn_obj.supplier_invoice_no = request.form.get('supplier_invoice_no', '').strip()

        if not is_landed:
            expected_pay_category = _payment_expected_account_category(grn_obj.payment_type)
            pay_account = None
            if payment_account_id:
                try:
                    payment_account_id = int(payment_account_id)
                except Exception:
                    payment_account_id = None

            if float(grn_obj.paid_amount or 0) > 0 and expected_pay_category in ['cash', 'bank'] and not payment_account_id:
                # Auto-pick rather than refuse: the GRN header, items and costs
                # are already complete, and losing them over an empty dropdown
                # is exactly the kind of mid-CRUD blocker being removed.  The
                # chosen account is shown to the operator in the flash.
                from app.services.edit_policy import resolve_payment_account

                auto_id, auto_account = resolve_payment_account(None, grn_obj.payment_type)
                if auto_account is None:
                    flash(
                        f'No active {expected_pay_category} account exists to pay this GRN from. '
                        'Add one under Accounts, or set the paid amount to 0 and save.',
                        'danger',
                    )
                    return redirect(url_for('edit_grn', id=grn_obj.id))
                payment_account_id = auto_id
                flash(
                    f'GRN paid amount auto-posted to '
                    f'{auto_account.account_holder_name or auto_account.name} ({expected_pay_category}).',
                    'info',
                )

            if payment_account_id:
                pay_account = Account.query.get(payment_account_id)
                if not pay_account or bool(getattr(pay_account, 'is_active', True)) is False:
                    flash('Please select a valid payment account.', 'danger')
                    return redirect(url_for('edit_grn', id=grn_obj.id))
                if expected_pay_category and (pay_account.category or '').strip().lower() != expected_pay_category:
                    flash(f"Selected payment account must be a {expected_pay_category} account for payment type '{grn_obj.payment_type}'.", 'danger')
                    return redirect(url_for('edit_grn', id=grn_obj.id))

                new_paid = float(grn_obj.paid_amount or 0)
                if payment_account_id == old_pay_account_id:
                    delta = new_paid - float(old_pay_amount or 0)
                    if delta > 0 and float(pay_account.balance or 0) + 0.00001 < delta:
                        flash('Insufficient balance in selected payment account for the increased paid amount.', 'danger')
                        return redirect(url_for('edit_grn', id=grn_obj.id))
                else:
                    if new_paid > 0 and float(pay_account.balance or 0) + 0.00001 < new_paid:
                        flash('Insufficient balance in selected payment account.', 'danger')
                        return redirect(url_for('edit_grn', id=grn_obj.id))

                if expected_pay_category == 'bank':
                    grn_obj.bank_name = pay_account.bank_name or ''
                    grn_obj.account_name = pay_account.account_holder_name or pay_account.name or ''
                    grn_obj.account_no = pay_account.account_number or ''
                else:
                    grn_obj.bank_name = ''
                    grn_obj.account_name = ''
                    grn_obj.account_no = ''

            grn_obj.payment_account_id = (payment_account_id if (float(grn_obj.paid_amount or 0) > 0 and expected_pay_category in ['cash', 'bank']) else None)

        # A1: LANDED GRNs keep payment_account_id/paid_amount cleared above.

        if grn_obj.manual_bill_no:
            conflict = find_bill_conflict(grn_obj.manual_bill_no)
            if conflict and not (conflict[0] == 'GRN' and conflict[1] == grn_obj.id):
                flash(f"Manual bill '{grn_obj.manual_bill_no}' already exists in {conflict[0]} #{conflict[1]}.", 'danger')
                return redirect(url_for('edit_grn', id=grn_obj.id))

        # Manual date / time override — same parser as the add path, so an
        # edit accepts exactly what an add accepts (24-hour, 12-hour with
        # AM/PM, optional seconds).  Older code silently fell back to the
        # server clock on unreadable input, which mis-stamped the record.
        # A post that carries neither field (programmatic callers) leaves the
        # stored stamp untouched, exactly like before.
        date_raw = request.form.get('date')
        time_raw = request.form.get('time')
        if (date_raw or '').strip() or (time_raw or '').strip():
            try:
                date_posted = parse_grn_datetime(date_raw, time_raw)
            except ValueError as ve:
                flash(str(ve), 'danger')
                return redirect(url_for('edit_grn', id=grn_obj.id))

            if date_posted != grn_obj.date_posted:
                restricted = _enforce_grn_backdate_policy(date_posted, 'Edit GRN', entity_id=grn_obj.id)
                if restricted:
                    return restricted
                grn_obj.date_posted = date_posted
                # Keep the GRN's stock-ledger rows on the same stamp.  On a
                # full edit the old rows are recreated below; on a header-only
                # edit (locked lots) they are reused, and this is what used to
                # drift away from the GRN's own date/time.
                sync_grn_entry_timestamps(grn_obj)

        # Bill Date / Due Date are real form fields on the wizard — save them.
        # (Previously they were read on ADD but silently ignored on EDIT.)
        # Only touch the stored value when the form actually carries the key:
        # a browser submit always includes it (empty = cleared by user),
        # while programmatic posts that omit the key keep the old value.
        if 'bill_date' in request.form:
            bill_date_str = (request.form.get('bill_date') or '').strip()
            try:
                grn_obj.bill_date = datetime.strptime(bill_date_str, '%Y-%m-%d').date() if bill_date_str else None
            except ValueError:
                pass
        if 'due_date' in request.form:
            due_date_str = (request.form.get('due_date') or '').strip()
            try:
                grn_obj.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else None
            except ValueError:
                pass

        # 2. Stock lines: updated IN PLACE so every lot keeps its GRNItem.id
        #    and the sales that already consumed it keep pointing at it.  Only
        #    impossible numbers are refused (a lot cannot shrink below what it
        #    already sold, a sold lot cannot be removed, a delivered line
        #    cannot be renamed) — see app/services/grn_edit.py.
        #    A POST that carries no item rows at all (header-only update from
        #    another screen) leaves the stored lines untouched.
        edit_skipped_lines = []
        if ('item_grid_present' in request.form
                or any(key in request.form for key in ('mat_name[]', 'grn_item_id[]', 'qty[]'))):
            try:
                item_result = sync_items_from_form(grn_obj, request.form, actor=current_user.username)
            except ValueError as ve:
                db.session.rollback()
                flash(str(ve), 'danger')
                return redirect(url_for('edit_grn', id=grn_obj.id))
            edit_skipped_lines = item_result.get('skipped') or []

        # Charge grid (LANDED) and exact landed-cost recomputation.  Each
        # expense carries its own supplier-billing choice.  A charge or billing
        # route with posted payments cannot be changed silently (see service).
        # ``charge_grid_present`` is posted by the wizard even when the grid has
        # no rows, so removing the last charge really clears it instead of
        # leaving the stored charges untouched.
        if (
            'charge_grid_present' in request.form
            or 'charge_type[]' in request.form
            or 'charge_amount[]' in request.form
            or 'charge_supplier_billing_present' in request.form
        ):
            try:
                sync_charges_from_form(grn_obj, request.form, actor=current_user.username)
                mirror_legacy_charge_columns(grn_obj)
            except ValueError as ve:
                db.session.rollback()
                flash(str(ve), 'danger')
                return redirect(url_for('edit_grn', id=grn_obj.id))
        if is_landed:
            recompute_landed_costs(grn_obj, actor=current_user.username)

        # 3. Sales that already consumed these lots carry a frozen FIFO cost.
        #    Rather than refusing the edit (the old behaviour, which blocked
        #    almost every real correction), re-cost them to the corrected
        #    landed cost so stock value and those sales' COGS still agree.
        recost = recost_consuming_sales(grn_obj)

        # The auto supplier payment follows the GRN's date/time (and paid
        # amount).  Moving a paid GRN into an already-reconciled period is
        # refused by the accounting guard with a ValueError; surface that as a
        # readable flash instead of an HTTP 500, and roll everything back so
        # the record keeps its previous date/time.
        try:
            _sync_grn_auto_supplier_payment(grn_obj, old_supplier_id=old_supplier_id)
            db.session.commit()
        except ValueError as ve:
            db.session.rollback()
            flash(str(ve), 'danger')
            return redirect(url_for('edit_grn', id=grn_obj.id))
        except IntegrityError:
            db.session.rollback()
            flash('GRN not saved: the bill number or one of the values is already used by another record.', 'danger')
            return redirect(url_for('edit_grn', id=grn_obj.id))
        if edit_skipped_lines:
            flash(
                'GRN updated, but these item lines were NOT saved because quantity was 0 or negative: '
                + '; '.join(edit_skipped_lines),
                'warning'
            )
        if recost.get('sale_items'):
            flash(
                f"Sale COGS re-costed: {recost['sale_items']} sold line(s) on "
                f"{recost['sales']} sale(s) now use this GRN's corrected landed cost.",
                'info',
            )
        flash('GRN updated successfully', 'success')
        return redirect(url_for('grn'))

    def _grn_has_consumed_for_edit(grn):
        """True when some of this GRN's stock has already left the yard.

        Only used to explain the rule on screen (saving re-costs those sales);
        it never blocks the save.
        """
        try:
            from app.services.grn_costing import grn_has_consumed_quantity
            return bool(grn_has_consumed_quantity(grn))
        except Exception:
            return False

    grns = GRN.query.options(selectinload(GRN.items)).order_by(
        GRN.date_posted.desc(),
        GRN.id.desc()
    ).all()
    materials = Material.query.order_by(Material.name.asc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    suppliers_list = Supplier.query.filter_by(is_active=True).order_by(Supplier.name.asc()).all()
    settings = Settings.query.first()
    
    accounts = Account.query.filter(
        func.coalesce(Account.is_active, True) == True,
        func.lower(func.trim(Account.category)).in_(['cash', 'bank']),
    ).order_by(Account.category.asc(), Account.name.asc()).all()

    try:
        grn_breakdowns = {g.id: grn_breakdown(g) for g in grns}
    except Exception:
        logging.getLogger('grn').exception('GRN cost breakdown failed')
        grn_breakdowns = {}

    return render_template(
        'grn_wizard.html',
        grns=grns,
        grn_breakdowns=grn_breakdowns,
        charge_billed_to_supplier=charge_billed_to_supplier,
        materials=materials,
        settings=settings,
        clients=clients,
        suppliers=suppliers_list,
        accounts=accounts,
        grn_parties=CashFlowParty.query.filter(
            func.coalesce(CashFlowParty.is_active, True) == True
        ).order_by(CashFlowParty.name.asc()).limit(500).all(),
        today_date=pk_today().strftime('%Y-%m-%d'),
        now_time=pk_now().strftime('%H:%M'),
        edit_grn=grn_obj,
        # True when part of this GRN has already been sold: the wizard shows
        # that saving a cost change re-costs those sales (nothing is blocked).
        grn_has_sold_stock=_grn_has_consumed_for_edit(grn_obj),
        search='',
        sort='date',
        start_date=None,
        end_date=None
    )


@bp.route('/export_grn')
@login_required
def export_grn():
    if current_user.role not in ['admin', 'root']:
        flash('Only tenant admin or root can run import/export operations.', 'danger')
        return redirect(url_for('index'))
    search = request.args.get('search', '').strip()
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = GRN.query
    if search:
        query = query.filter(or_(
            GRN.supplier.ilike(f'%{search}%'),
            GRN.manual_bill_no.ilike(f'%{search}%'),
            GRN.auto_bill_no.ilike(f'%{search}%')
        ))
    if start_date:
        query = query.filter(func.date(GRN.date_posted) >= start_date)
    if end_date:
        query = query.filter(func.date(GRN.date_posted) <= end_date)
    
    grns = query.order_by(
        GRN.date_posted.desc(),
        GRN.id.desc()
    ).all()
    
    data = []
    for g in grns:
        bd = grn_breakdown(g)
        total = bd['landed_cost_total']
        data.append({
            'Date': g.date_posted.strftime('%Y-%m-%d') if g.date_posted else '',
            'GRN #': g.manual_bill_no or g.auto_bill_no,
            'Supplier': g.supplier,
            'Items Count': len([i for i in (g.items or []) if not bool(getattr(i, 'is_void', False))]),
            'Total Qty': sum((i.qty or 0) for i in (g.items or []) if not bool(getattr(i, 'is_void', False))),
            'Discount': g.discount,
            'Tax': g.tax_amount,
            'Supplier Material Amount': bd['supplier_material_amount'],
            'Vehicle Fare': bd['vehicle_fare'],
            'Loading': bd['loading'],
            'Unloading': bd['unloading'],
            'Other Charges': bd['other_charges'],
            'Expenses': bd['capitalised_charge_total'],
            'Total Actual Purchase Cost': total,
            'Avg Actual Cost Per Unit': bd['average_actual_rate'],
            'Supplier Paid': bd['supplier_paid'],
            'Supplier Remaining': bd['supplier_remaining'],
            'Additional Charges Paid': bd['additional_paid'],
            'Additional Charges Remaining': bd['additional_remaining'],
            'Total Cash Actually Paid': bd['total_cash_paid'],
            'Net Amount': total,
            'Note': g.note
        })
    
    from utils.excel_export import single_sheet_xlsx
    output = single_sheet_xlsx('GRN List', data, [
        'Date', 'GRN #', 'Supplier', 'Items Count', 'Total Qty', 'Discount',
        'Tax', 'Supplier Material Amount', 'Vehicle Fare', 'Loading',
        'Unloading', 'Other Charges', 'Expenses', 'Total Actual Purchase Cost',
        'Avg Actual Cost Per Unit', 'Supplier Paid', 'Supplier Remaining',
        'Additional Charges Paid', 'Additional Charges Remaining',
        'Total Cash Actually Paid', 'Net Amount', 'Note',
    ])
    
    return send_file(
        output,
        as_attachment=True,
        download_name=_download_filename('GRNEXPORT', 'xlsx'),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


