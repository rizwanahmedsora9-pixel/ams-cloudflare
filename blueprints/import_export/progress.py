"""import helpers."""
from ._common import *  # noqa


def _set_master_import_progress(job_id, **fields):
    with _MASTER_IMPORT_PROGRESS_LOCK:
        state = _MASTER_IMPORT_PROGRESS.get(job_id, {})
        state.update(fields)
        _MASTER_IMPORT_PROGRESS[job_id] = state


def _get_master_import_progress(job_id):
    with _MASTER_IMPORT_PROGRESS_LOCK:
        state = _MASTER_IMPORT_PROGRESS.get(job_id)
        return dict(state) if state else None


@import_export_bp.route('/full_raw_import_history_export')
@login_required
def full_raw_import_history_export():
    if current_user.role not in ['admin', 'root']:
        return "Forbidden", 403
    reports = _list_full_raw_reports()
    output = io.StringIO()
    # Report metadata has grown over time (status/updated/failed/warnings...).
    # A fixed fieldname list makes csv.DictWriter raise ValueError -> HTTP 500
    # as soon as an older or newer report carries an extra key, so build the
    # column set from the data and keep the known columns first.
    known = [
        'name', 'created_at', 'row_count', 'scope', 'mode', 'tenant_name',
        'inserted', 'updated', 'skipped', 'failed', 'status', 'warnings',
        'tables', 'source_file',
    ]
    extra = sorted({k for r in reports for k in r} - set(known))
    writer = csv.DictWriter(
        output,
        fieldnames=known + extra,
        extrasaction='ignore',
    )
    writer.writeheader()
    for report in reports:
        writer.writerow({
            key: (
                json.dumps(value, ensure_ascii=True)
                if isinstance(value, (dict, list)) else value
            )
            for key, value in report.items()
        })
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={_download_filename('IMPORTREPORTHISTORY', 'csv')}"}
    )


@import_export_bp.route('/master/import/status/<job_id>', methods=['GET'])
@login_required
def master_import_status(job_id):
    state = _get_master_import_progress(job_id)
    if not state:
        return jsonify({'error': 'Unknown job id'}), 404

    owner = state.get('user')
    if owner and owner != getattr(current_user, 'username', None) and getattr(current_user, 'role', None) not in ['admin', 'root']:
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify(state)


