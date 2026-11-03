/* Offline DOM test for static/grn_charges.js — the GRN charge grid.

   Owner rule under test: the GRN screen must NOT invent charge rows.  Vehicle
   fare / transportation / loading / unloading / other are dropdown choices,
   not four rows waiting to be filled in.  A charge line exists only because
   the operator pressed "Add charge", or because it is saved on the GRN.

   Pinned here:

     1. a new GRN renders zero charge rows and shows the empty-state notice;
     2. "Add charge" appends exactly one blank row per click, cloned from the
        inert <template> — never a copy of the previous row's values;
     3. choosing a charge fills that row's recipient type, and a recipient the
        operator picked by hand is never overwritten;
     4. every row is removable, including the last, and the empty state comes
        back;
     5. the capitalised preview counts INVENTORY charges only, ignores Not
        Applicable, and never changes with Paid / Unpaid;
     6. save-time validation drops untouched blank rows, refuses a row with no
        charge or no amount, and keeps the grid honest.

   Run:  npm i jsdom   then   node tests/frontend/test_grn_charges_dom.js
   Against a real rendered screen instead of the fixture:
         GRN_PAGE_HTML=instance/grn_page.html node tests/frontend/test_grn_charges_dom.js */
const fs = require("fs");
const path = require("path");
let JSDOM;
try { JSDOM = require("jsdom").JSDOM; }
catch (_) { JSDOM = require("/tmp/node_modules/jsdom").JSDOM; }

const code = fs.readFileSync(path.join(__dirname, "..", "..", "static", "grn_charges.js"), "utf8");

let pass = 0, fail = 0;
function check(name, cond, extra) {
    if (cond) { pass++; console.log("  ok  -", name); }
    else { fail++; console.log("  FAIL-", name, extra === undefined ? "" : "-> " + extra); }
}

/* One charge row, mirroring the charge_row() macro in templates/grn_wizard.html. */
function rowMarkup(saved) {
    const c = saved || {};
    const sel = (value, option) => value === option ? " selected" : "";
    return `<tr class="grn-charge-row">
  <td>
    <input type="hidden" name="charge_id[]" value="${c.id || ""}">
    <select class="form-select form-select-sm" name="charge_type[]">
      <option value=""${sel(c.type || "", "")}>Select charge…</option>
      <option value="VEHICLE_FARE"${sel(c.type, "VEHICLE_FARE")}>Vehicle Fare</option>
      <option value="TRANSPORT"${sel(c.type, "TRANSPORT")}>Transportation</option>
      <option value="LOADING"${sel(c.type, "LOADING")}>Loading</option>
      <option value="UNLOADING"${sel(c.type, "UNLOADING")}>Unloading</option>
      <option value="OTHER"${sel(c.type, "OTHER")}>Other Expenses</option>
    </select>
  </td>
  <td><input type="text" name="charge_label[]" value="${c.label || ""}"></td>
  <td><input type="number" name="charge_amount[]" step="any" min="0" value="${c.amount === undefined ? "" : c.amount}"></td>
  <td><select name="charge_recipient_type[]">
      <option value=""${sel(c.recipient || "", "")}>Select recipient…</option>
      <option value="TRANSPORTER"${sel(c.recipient, "TRANSPORTER")}>Vehicle / Transporter</option>
      <option value="LABOUR"${sel(c.recipient, "LABOUR")}>Loading / Labour</option>
      <option value="OTHER"${sel(c.recipient, "OTHER")}>Other charge recipient</option>
  </select></td>
  <td><input type="text" name="charge_recipient[]" value="${c.party || ""}"></td>
  <td><select name="charge_status[]">
      <option value="UNPAID"${sel(c.status || "UNPAID", "UNPAID")}>Unpaid</option>
      <option value="PAID"${sel(c.status, "PAID")}>Paid (declaration only)</option>
      <option value="NOT_APPLICABLE"${sel(c.status, "NOT_APPLICABLE")}>Not Applicable</option>
  </select></td>
  <td><select name="charge_treatment[]">
      <option value="INVENTORY"${sel(c.treatment || "INVENTORY", "INVENTORY")}>Include in material cost</option>
      <option value="EXPENSE"${sel(c.treatment, "EXPENSE")}>Separate expense</option>
      <option value="NON_MATERIAL"${sel(c.treatment, "NON_MATERIAL")}>Not material cost</option>
  </select></td>
  <td><select name="charge_basis[]">
      <option value="VALUE">By value</option><option value="QUANTITY">By quantity</option><option value="MANUAL">Manual</option>
  </select></td>
  <td><button type="button" class="grn-charge-remove">x</button></td>
</tr>`;
}

/* Mirrors the wizard: empty tbody for a new GRN, the inert blueprint, the
   empty-state notice, the Add charge button and the live totals strip. */
const FIXTURE = `<!doctype html><html><body>
<form id="grnForm">
  <input type="hidden" name="charge_grid_present" value="1">
  <button type="button" id="addGrnChargeBtn">Add charge</button>
  <div id="grnChargesEmpty">No charges on this GRN.</div>
  <div class="table-responsive" id="grnChargesWrap" hidden>
    <table id="grnChargesTable">
      <thead><tr><th>Charge</th><th>Label / Detail</th><th>Amount (Rs.)</th><th>Recipient Type</th>
        <th>Recipient / Person</th><th>Payment Status</th><th>Cost Treatment</th><th>Alloc. Basis</th><th></th></tr></thead>
      <tbody id="grnChargesBody"></tbody>
    </table>
  </div>
  <template id="grnChargeRowTemplate">${rowMarkup()}</template>
  <b id="grnCapitalisedCharges">0.00</b>
</form>
</body></html>`;

const pagePath = process.env.GRN_PAGE_HTML;
const source = pagePath ? fs.readFileSync(pagePath, "utf8") : FIXTURE;
if (pagePath) console.log("  (document:", pagePath + ")");

const dom = new JSDOM(source, { url: "http://localhost/grn", runScripts: "outside-only", pretendToBeVisual: true });
const w = dom.window, d = w.document;
w.eval(code);
const api = w.FBMGrnCharges;
check("script exposes FBMGrnCharges", !!api);

let repaints = 0;
api.init({ onChange: function () { repaints += 1; } });

const alerts = [];
const warn = (message) => alerts.push(message);
const tbody = d.getElementById("grnChargesBody");
const wrap = d.getElementById("grnChargesWrap");
const empty = d.getElementById("grnChargesEmpty");
const addBtn = d.getElementById("addGrnChargeBtn");
const val = (row, name) => row.querySelector('[name="' + name + '"]').value;
const set = (row, name, value) => {
    const el = row.querySelector('[name="' + name + '"]');
    el.value = value;
    el.dispatchEvent(new w.Event("change", { bubbles: true }));
};

/* ---- 1. nothing is pre-added ------------------------------------------ */
/* A real edit screen legitimately has saved rows; a new GRN must have none.
   The fixture is the new-GRN case, so assert zero only there. */
if (!pagePath) {
    check("new GRN starts with zero charge rows", api.rowCount() === 0, api.rowCount());
    check("charge table is hidden while empty", wrap.hidden === true);
    check("empty-state notice is visible", empty.hidden === false);
}
check("the blueprint row is inert (not in the table)",
    tbody.querySelectorAll("tr.grn-charge-row").length === api.rowCount());
check("blueprint lives in a <template>",
    d.getElementById("grnChargeRowTemplate").tagName === "TEMPLATE");
const beforeTemplate = api.rowCount();
check("template content is never counted as a charge",
    d.getElementById("grnChargeRowTemplate").content.querySelectorAll("tr.grn-charge-row").length === 1
    && api.rowCount() === beforeTemplate);

/* ---- 2. Add charge is the only way a row appears ---------------------- */
const first = api.addRow();
check("Add charge appends one row", api.rowCount() === beforeTemplate + 1, api.rowCount());
check("the new row is blank", val(first, "charge_type[]") === "" && val(first, "charge_amount[]") === ""
    && val(first, "charge_label[]") === "" && val(first, "charge_recipient[]") === "");
check("a hand-added row carries no stored charge id", val(first, "charge_id[]") === "");
check("table shown once a row exists", wrap.hidden === false);
check("empty-state notice hidden once a row exists", empty.hidden === true);

addBtn.click();
check("Add charge button appends exactly one row per click", api.rowCount() === beforeTemplate + 2, api.rowCount());
const second = api.rows()[api.rowCount() - 1];

/* Fill the first row, then add another: the new one must not inherit it. */
set(first, "charge_type[]", "VEHICLE_FARE");
set(first, "charge_label[]", "Rana Transport");
set(first, "charge_amount[]", "5000");
set(first, "charge_recipient[]", "Rana Transport");
const third = api.addRow();
check("a new row does not copy the previous charge's type", val(third, "charge_type[]") === "");
check("a new row does not copy the previous charge's amount", val(third, "charge_amount[]") === "");
check("a new row does not copy the previous charge's label", val(third, "charge_label[]") === "");
check("a new row does not copy the previous charge's recipient", val(third, "charge_recipient[]") === "");
check("a new row does not reuse the previous charge's id", val(third, "charge_id[]") === "");

/* ---- 3. recipient type follows the charge, on that row only ----------- */
check("vehicle fare defaults the recipient to transporter", val(first, "charge_recipient_type[]") === "TRANSPORTER",
    val(first, "charge_recipient_type[]"));
set(second, "charge_type[]", "LOADING");
check("loading defaults the recipient to labour", val(second, "charge_recipient_type[]") === "LABOUR");
set(second, "charge_type[]", "UNLOADING");
check("unloading defaults the recipient to labour", val(second, "charge_recipient_type[]") === "LABOUR");
set(second, "charge_type[]", "OTHER");
check("other expenses default the recipient to other", val(second, "charge_recipient_type[]") === "OTHER");
set(second, "charge_recipient_type[]", "TRANSPORTER");
set(second, "charge_type[]", "LOADING");
check("a recipient chosen by hand is never overwritten", val(second, "charge_recipient_type[]") === "TRANSPORTER",
    val(second, "charge_recipient_type[]"));
check("changing one row leaves the other row's recipient alone", val(first, "charge_recipient_type[]") === "TRANSPORTER");

/* ---- 4. the capitalised preview obeys the costing rule ---------------- */
set(second, "charge_amount[]", "1000");
set(second, "charge_treatment[]", "INVENTORY");
set(third, "charge_type[]", "OTHER");
set(third, "charge_amount[]", "500");
check("capitalised preview sums material-cost charges", api.capitalisedTotal() === 6500, api.capitalisedTotal());
set(third, "charge_treatment[]", "EXPENSE");
check("a separate expense is excluded from the capitalised preview", api.capitalisedTotal() === 6000, api.capitalisedTotal());
set(third, "charge_treatment[]", "NON_MATERIAL");
check("a non-material charge is excluded too", api.capitalisedTotal() === 6000, api.capitalisedTotal());
set(third, "charge_treatment[]", "INVENTORY");
set(third, "charge_status[]", "NOT_APPLICABLE");
check("Not Applicable contributes nothing", api.capitalisedTotal() === 6000, api.capitalisedTotal());
set(third, "charge_status[]", "PAID");
const paidTotal = api.capitalisedTotal();
set(third, "charge_status[]", "UNPAID");
check("Paid / Unpaid never changes the cost", api.capitalisedTotal() === paidTotal && paidTotal === 6500, paidTotal);
check("editing a charge triggers a totals repaint", repaints > 0, repaints);

/* ---- 5. every row is removable, including the last -------------------- */
third.querySelector(".grn-charge-remove").click();
check("remove drops that row only", api.rowCount() === beforeTemplate + 2, api.rowCount());
check("remove keeps the other rows' values", val(first, "charge_amount[]") === "5000");
api.rows().slice(beforeTemplate).forEach((row) => row.querySelector(".grn-charge-remove").click());
check("the last charge row can be removed", api.rowCount() === beforeTemplate, api.rowCount());
if (!pagePath) {
    check("empty state returns after removing the last row", empty.hidden === false && wrap.hidden === true);
    check("an empty grid contributes no capitalised cost", api.capitalisedTotal() === 0);
    check("Add charge still works on an empty grid", api.addRow() !== null && api.rowCount() === 1);
    api.rows()[0].querySelector(".grn-charge-remove").click();
}

/* ---- 6. save-time validation ------------------------------------------ */
if (!pagePath) {
    const blank = api.addRow();
    alerts.length = 0;
    check("an untouched blank row is dropped on save, not stored",
        api.validate(warn) === true && api.rowCount() === 0, api.rowCount());
    check("dropping a blank row raises no alert", alerts.length === 0, alerts.join(" | "));
    check("grid is empty again after the blank row is dropped", empty.hidden === false);

    const noType = api.addRow();
    set(noType, "charge_amount[]", "900");
    alerts.length = 0;
    check("a row with an amount but no charge is refused", api.validate(warn) === false);
    check("the refusal names the row and the fix", /Charge row 1/.test(alerts[0] || "") && /select the charge/i.test(alerts[0] || ""),
        alerts[0]);
    check("the refused row is kept for the operator to fix", api.rowCount() === 1);

    set(noType, "charge_type[]", "LOADING");
    set(noType, "charge_amount[]", "");
    alerts.length = 0;
    check("a new charge with no amount is refused", api.validate(warn) === false);
    check("the amount refusal is readable", /enter the amount/i.test(alerts[0] || ""), alerts[0]);

    set(noType, "charge_amount[]", "1000");
    alerts.length = 0;
    check("a complete charge row saves", api.validate(warn) === true && alerts.length === 0, alerts.join(" | "));
    check("validation fills the recipient type from the charge", val(noType, "charge_recipient_type[]") === "LABOUR");

    /* A Not Applicable row is a legitimate zero: it must not block the save. */
    set(noType, "charge_amount[]", "");
    set(noType, "charge_status[]", "NOT_APPLICABLE");
    alerts.length = 0;
    check("a Not Applicable charge may be zero", api.validate(warn) === true, alerts.join(" | "));
}

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
