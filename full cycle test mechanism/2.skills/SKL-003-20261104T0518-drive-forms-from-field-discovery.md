# SKL-003 — Drive an unlabelled form by discovering its fields first

**Confidence:** high — every write path in this app was reached this way
**Reuse:** adding coverage for a new page, or debugging a 400/404 on a POST
**Cost:** one GET per page

---

## The problem

This app has 566 routes and 126 templates, several with wildcard-imported
helpers (`from ._common import *`). Guessing a form's field names wastes turns:
`from_account_id` vs `from_account`, `reminder_at` vs `remind_at`,
`return_type=normal` vs `"Normal Return"` — each wrong guess is a 200 with a
silent no-op, which is worse than an error.

## The technique

Never POST until you have listed the inputs.

```python
import re
def fields(session, path):
    status, html = session.html(path)
    return sorted(set(re.findall(
        r'<(?:input|select|textarea)[^>]*name="([^"]+)"', html)))

fields(s, "/material_returns")
# ['bill_no', 'client', 'client_code', 'date', 'material_id[]',
#  'material_name[]', 'note', 'qty[]', 'return_type', 'service_id[]',
#  'unit_rate[]', ...]
```

Three things fall out immediately:

1. **the real field names**, including array suffixes (`qty[]` is not `qty`)
2. **which fields are optional** — anything absent is not in the form
3. **the enum values**, by pulling the `<option>` list the same way

## Getting the enum values

```python
def options(session, path, field):
    _status, html = session.html(path)
    block = re.search(
        rf'<select[^>]*name="{field}"[^>]*>(.*?)</select>', html, re.S)
    return re.findall(r'<option[^>]*value="([^"]*)"', block.group(1)) if block else []
```

This is how the transfer form was found to use `from_account`/`to_account` while
the accounts modal uses `pay_from_account_id`/`pay_to_account_id` for the same
pair — three names for one concept, none guessable.

## The second technique: find the route by grep, not by guess

`_audit/routes.txt` lists all 566 routes. When a form posts somewhere:

```bash
grep -E "material_return" _audit/routes.txt
# /add_material_return   POST
# /material_returns      GET
```

That is how `/material_return` (singular, 404) was ruled out and
`/add_material_return` confirmed. Guessing cost one wasted POST.

## Reading the flash message as the assertion

Every write returns a *flash string*, and the exact wording is the cheapest
correctness signal available:

```python
r = session.post("/add_material_return", {...})
assert "Material return saved successfully" in session.flash_text(r)
```

Two behaviours to know:

* flashes are suffixed `— by Admin`, so match on a **substring** of the message,
  never the whole thing
* a 302 followed by a 200 is success; assert on the followed page's flash, not
  on the status code

## Traps found this way (all now in `seed.py`)

| Trap | Correct value |
|---|---|
| transfer between accounts | `from_account` / `to_account` |
| accounts modal transfer | `pay_from_account_id` / `pay_to_account_id` |
| cash-flow transfer | `cash_account_id` / `to_account_id` |
| material return type | `normal` or `booked` |
| reminder datetime | `remind_at`, `YYYY-MM-DDTHH:MM` |
| GRN charges | full `charge_*[]` arrays; `charge_grid_present=1` alone is ignored |
| GRN payment obligation | `obligation_key=SUPPLIER:<supplier_id>` |
| pending bill | `is_manual=1` for a manually-keyed bill |

## Order of operations that avoids wasted turns

1. `GET` the page, extract fields + options.
2. `GET` a *populated* instance of the page (after seeding one row) — the
   populated form reveals rows of a repeating grid that an empty form hides.
3. `POST` the smallest valid payload.
4. Assert the flash, then query the DB for the side effects.
5. Only then add the happy-path check to `checks.py`.

Skipping step 2 is the classic mistake: an empty GRN form shows one item row,
so array syntax (`mat_name[]`) never appears in the markup until a second row
exists.
