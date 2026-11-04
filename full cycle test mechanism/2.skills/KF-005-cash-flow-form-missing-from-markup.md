# KF-005 — `/cash_flow` ships the JavaScript for a form that is not in the page

**Severity:** medium — the feature is unreachable for a human user
**Status:** open
**Found by:** asserting the *presence* of an element, not just the page status

---

## Symptom

The page returns 200 and every figure on it is correct, but there is **no way to
record a cash-flow movement from the UI**:

```python
'id="cfRecordForm"'  in html   ->  False
'cfRecordForm'       in html   ->  True      # inside <script>
```

`templates/cash_flow.html` line 888 onward:

```javascript
const form = document.getElementById('cfRecordForm');       // null
const directionEl = document.getElementById('cfDirection'); // null
...
document.getElementById('cfFormAction').value = 'record_movement';
```

The markup for `#cfRecordForm`, `#cfDirection`, `#cfAmount`, `#cfCategory`,
`#cfFormAction` and the *Post Received / Post Spent* buttons is missing, so the
script binds to nothing.

The backend is fine: `POST /cash_flow` with `action=record_movement` creates the
entry, the `account_transaction` and the balance change correctly — which is how
the mechanism seeds it.

## Impact

* A user cannot record an owner investment, an expense or a transfer.
* The seeded dataset in every automated run uses an endpoint no human can reach,
  so the UI gap is invisible to functional testing.

## Fix

Restore the form block (tab `#tab-transactions`) with the ids the script expects:

```html
<form id="cfRecordForm" method="post" action="{{ url_for('cash_flow') }}">
  <input type="hidden" name="action" id="cfFormAction" value="record_movement">
  <input type="hidden" name="idempotency_key" id="cfIdem" value="{{ cf_idem }}">
  <select name="direction" id="cfDirection"> ... in / out / transfer ... </select>
  <input name="amount" id="cfAmount" type="number" step="0.01" min="0.01">
  <select name="cash_account_id" id="cfAccount"> ... </select>
  <select name="category_id" id="cfCategory"> ... </select>
  <input name="description" id="cfDescription">
  <input name="movement_date" id="cfDate" type="date">
  <button type="submit" id="cfSaveBtn">Post Received</button>
</form>
```

The script already handles the direction→label swap and the account-balance
preview, so no JS change is needed once the ids exist.

## Acceptance

| Check | Before | After |
|---|---|---|
| `W-07` `id="cfRecordForm"` in markup | absent | present |
| A human can post a 5,000 receipt | ✗ | ✓ |
| `cash_flow_entry` + `account_transaction` created from the UI | ✗ | ✓ |

Remove `known=D_CFFORM_MARKUP` from `W-07`. Note `W-07` currently asserts the
element is present, so it flips to green on fix with no edit beyond the flag.
