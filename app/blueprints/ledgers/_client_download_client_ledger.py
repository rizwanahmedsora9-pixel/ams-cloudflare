"""client — split from ledgers.py."""
from ._common import *  # noqa

@bp.route('/download_client_ledger/<int:id>')
@login_required
def download_client_ledger(id):
    client = Client.query.get_or_404(id)
    action = (request.args.get('action') or 'download').lower()
    disposition = 'inline' if action == 'print' else 'attachment'
    # 'en' by default; '?lang=ur' produces a separate, Urdu-only document.
    lang = resolve_export_lang()

    (
        financial_history,
        pending_bills,
        total_debit,
        total_credit,
        total_balance,
        material_history_grouped
    ) = _build_client_ledger_rows(client)

    generated_at = pk_now()

    # The printed sheet must be the same document the user was reading, so the
    # material section is fed from the very helpers the on-screen Material
    # Ledger uses — same rows, same columns, same totals.
    material_summary, material_total_qty = client_material_summary(client)
    ctx = dict(
        client=client,
        financial_history=financial_history,
        pending_bills=pending_bills,
        total_debit=total_debit,
        total_credit=total_credit,
        total_balance=total_balance,
        material_history_grouped=material_history_grouped,
        # The same Entry rows, columns and figures the web page shows.
        movement_rows=client_movement_rows(client),
        material_summary=material_summary,
        material_total_qty=material_total_qty,
        generated_at=generated_at,
    )

    rendered = render_template(
        'client_ledger_print.html',
        auto_print=(action == 'print'),
        pdf_error=False,
        **ctx
    )

    if action != 'print':
        pdf_response = _try_render_weasy_pdf(
            rendered,
            _download_filename('CLIENTLEDGER', 'pdf'),
            disposition=disposition,
            lang=lang,
            urdu_labels=True,
            doc_title=f'Client Ledger - {client.name}',
        )
        if pdf_response:
            return pdf_response

        rendered = render_template(
            'client_ledger_print.html',
            auto_print=False,
            pdf_error=True,
            **ctx
        )

    if action == 'print':
        # The browser print/save-as-PDF path must use the same language layer
        # as the generated PDF, otherwise the printed sheet and the downloaded
        # file disagree.
        rendered = _bilingual_print_html(rendered, lang=lang, urdu_labels=True)

    response = make_response(rendered)
    fallback_name = _download_filename('CLIENTLEDGER', 'html')
    response.headers['Content-Disposition'] = f'{disposition}; filename={fallback_name}'
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    _disable_response_cache(response)
    return response

