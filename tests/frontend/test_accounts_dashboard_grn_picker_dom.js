/* Offline DOM test for the Accounts → Make New Transaction GRN picker.

   The picker must be invisible/disabled for Supplier Payment, and visible only
   for Pay GRN Expenses.  When a GRN is selected, the note below the picker
   shows the server-authoritative GRN date and amount still to be paid,
   including expenses that were not added to the supplier ledger.

   Run: npm i jsdom && node tests/frontend/test_accounts_dashboard_grn_picker_dom.js
*/
const fs = require("fs");
const path = require("path");
let JSDOM;
try { JSDOM = require("jsdom").JSDOM; }
catch (_) { JSDOM = require("/tmp/node_modules/jsdom").JSDOM; }

const template = fs.readFileSync(
    path.join(__dirname, "..", "..", "templates", "accounts", "dashboard.html"),
    "utf8"
);

function slice(startMarker, endMarker) {
    const start = template.indexOf(startMarker);
    const end = template.indexOf(endMarker, start + startMarker.length);
    if (start < 0 || end < 0) {
        throw new Error("Could not extract " + startMarker + " from dashboard.html");
    }
    return template.slice(start, end);
}

/* Both blocks are plain JavaScript (Jinja expressions live elsewhere). */
const code = [
    slice("function formatDashboardMoney", "function selectPayClient"),
    slice("function setPayTargetMode", "function syncDriverSelection")
].join("\n");

const PAGE = `<!doctype html><html><body>
<input type="radio" name="tx_mode" value="pay" checked>
<div id="txAmountWrap"><input id="tx_amount" value="123.00" required></div>
<div id="txMethodWrap"><select name="method"><option>Cash</option></select></div>
<div id="paySection">
  <div id="payFromAccountWrap"><select id="pay_from_account_id" required></select></div>
  <select id="pay_target">
    <option value="supplier">Supplier Payment</option>
    <option value="grn_payment">Pay GRN Expenses</option>
  </select>
  <div id="grnPaymentWrap" class="d-none">
    <select id="grnPaymentGrnSelect" disabled>
      <option value="">— Open Pay GRN Expenses —</option>
      <option value="7"
              data-bill-ref="GRN-7"
              data-supplier="Cement Works"
              data-date-label="20/Oct/2026"
              data-total-due="6500.00"
              data-supplier-ledger-due="6000.00"
              data-recipient-expenses-due="500.00">GRN-7 · Cement Works · 20/Oct/2026</option>
    </select>
    <div id="grnPaymentSelectionInfo" class="d-none">
      <div id="grnPaymentSelectedInfo"></div>
      <div id="grnPaymentDateInfo"></div>
      <div id="grnPaymentDueInfo"></div>
      <div id="grnPaymentExpenseInfo"></div>
    </div>
    <div id="grnPaymentEmptyInfo"></div>
  </div>
  <div id="payToAccountWrap"><select id="pay_to_account_id"></select></div>
  <div id="supplierWrap">
    <input id="supplier_id"><input id="paySupplierInput">
  </div>
  <div id="targetLabelWrap"><input id="target_label"></div>
  <div id="clientRefundWrap"><input id="payClientInput"></div>
  <button id="newTransactionSubmit">Submit Transaction</button>
</div>
</body></html>`;

const dom = new JSDOM(PAGE, {
    url: "http://localhost/accounts/",
    runScripts: "outside-only",
    pretendToBeVisual: true
});
const w = dom.window;
const d = w.document;
w.eval(code);

let pass = 0;
let fail = 0;
function check(name, condition, extra) {
    if (condition) { pass += 1; console.log("  ok  -", name); }
    else { fail += 1; console.log("  FAIL-", name, extra === undefined ? "" : "-> " + extra); }
}

const target = d.getElementById("pay_target");
const grnWrap = d.getElementById("grnPaymentWrap");
const grnSelect = d.getElementById("grnPaymentGrnSelect");
const amount = d.getElementById("tx_amount");
const payFrom = d.getElementById("pay_from_account_id");
const submit = d.getElementById("newTransactionSubmit");

/* 1. A supplier payment must not show or submit the GRN field. */
target.value = "supplier";
grnSelect.value = "7";
w.setPayTargetMode();
check("supplier target hides the GRN picker", grnWrap.classList.contains("d-none"));
check("supplier target disables the GRN picker", grnSelect.disabled === true);
check("supplier target clears a stale GRN selection", grnSelect.value === "");
check("supplier target keeps the amount required", amount.required === true);
check("supplier target keeps the source account required", payFrom.required === true);
check("supplier target uses the normal submit label", submit.textContent === "Submit Transaction");

/* 2. Pay GRN Expenses shows the date and all payable amounts. */
target.value = "grn_payment";
grnSelect.value = "7";
w.setPayTargetMode();
check("GRN expenses target shows the picker", !grnWrap.classList.contains("d-none"));
check("GRN expenses target enables the picker", grnSelect.disabled === false);
check("GRN expenses target hides the generic amount", d.getElementById("txAmountWrap").classList.contains("d-none"));
check("GRN expenses target does not require a modal amount", amount.required === false && amount.value === "");
check("GRN expenses target does not require a source account", payFrom.required === false);
check("GRN expenses target changes the submit label", submit.textContent === "Open Pay GRN Expenses");
check("GRN selection note is visible", !d.getElementById("grnPaymentSelectionInfo").classList.contains("d-none"));
check("GRN selection note shows the GRN date",
    d.getElementById("grnPaymentDateInfo").textContent.includes("20/Oct/2026"));
check("GRN selection note shows the total to be paid",
    d.getElementById("grnPaymentDueInfo").textContent.includes("Rs. 6,500.00"));
check("GRN selection note shows off-ledger expenses",
    d.getElementById("grnPaymentExpenseInfo").textContent.includes("Rs. 500.00"));

/* 3. Clearing the selection restores the prompt. */
grnSelect.value = "";
w.updateGrnPaymentInfo();
check("empty GRN hides the amount note",
    d.getElementById("grnPaymentSelectionInfo").classList.contains("d-none"));
check("empty GRN shows the selection prompt",
    !d.getElementById("grnPaymentEmptyInfo").classList.contains("d-none"));

if (fail) {
    console.log("\n" + fail + " check(s) failed; " + pass + " passed.");
    process.exit(1);
}
console.log("\n" + pass + " checks passed.");
