"""Terms and conditions for Urdu sales receipts.

Active rows are offered on the Urdu receipt print/download dialog; only the
chosen ones are printed.  Admin users manage the full list from
Settings -> Terms & Conditions, so new terms can be added without code
changes.
"""
from __future__ import annotations

from models import TermsAndCondition


def get_active_terms():
    """Return all active terms ordered by sort_order then title."""
    try:
        return (TermsAndCondition.query
                .filter_by(is_active=True)
                .order_by(TermsAndCondition.sort_order.asc(),
                          TermsAndCondition.title.asc())
                .all())
    except Exception:
        # Table may not exist yet on a very first boot before migrations run.
        return []


def get_selected_terms(term_ids):
    """Return the active terms whose ids are in *term_ids*, in display order."""
    ids = []
    for raw in (term_ids or []):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    try:
        return (TermsAndCondition.query
                .filter(TermsAndCondition.id.in_(ids),
                        TermsAndCondition.is_active == True)  # noqa: E712
                .order_by(TermsAndCondition.sort_order.asc(),
                          TermsAndCondition.title.asc())
                .all())
    except Exception:
        return []
