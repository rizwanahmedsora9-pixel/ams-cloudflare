"""client — split from ledgers.py."""
from ._common import *  # noqa

@bp.route('/client_ledger/<int:id>')
@login_required
def client_ledger(id):
    client = db.session.get(Client, id)
    if client:
        page = request.args.get('page', 1, type=int)
        # The on-screen Material Ledger, the printed sheet and the PDF must all
        # report the same figures, so the filter and the summary live in one
        # place (app.services.ledgers) and every view calls them.
        entry_filter = client_material_entry_filter(client)
        pagination = Entry.query.filter(entry_filter, Entry.is_void == False).order_by(
            Entry.date.desc()).paginate(page=page, per_page=10)
        summary, total_qty = client_material_summary(client)

        pending_photos = {
            b.bill_no: b.photo_url
            for b in PendingBill.query.filter(PendingBill.photo_url != '', PendingBill.is_void == False).all() if b.bill_no
        }

        clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
        materials = list(Material.query.order_by(Material.name.asc()).all()) + list(Service.query.order_by(Service.name.asc()).all())

        return render_template('ledger.html',
                               client=client,
                               entries=pagination.items,
                               pagination=pagination,
                               total_qty=total_qty,
                               summary=summary,
                               pending_photos=pending_photos,
                               clients=clients,
                               materials=materials)
    return redirect(url_for('clients'))
