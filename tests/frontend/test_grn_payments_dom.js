/* Offline DOM test for static/grn_payments.js.

   The GRN payment page is server-authoritative: the fixture supplies the
   server-calculated obligation values as option data attributes.  This test
   pins the browser-only contract:

     1. selecting an obligation shows its current payable and paid amount;
     2. typing a payment repaints the selected and total remaining balances;
     3. the source-account balance after payment is visible;
     4. overpayments are explained and blocked unless an advance is enabled;
     5. Pay remaining fills the exact current obligation.

   Run: npm i jsdom && node tests/frontend/test_grn_payments_dom.js
*/
const fs = require("fs");
const path = require("path");
let JSDOM;
try { JSDOM = require("jsdom").JSDOM; }
catch (_) { JSDOM = require("/tmp/node_modules/jsdom").JSDOM; }

const code = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "grn_payments.js"),
    "utf8"
);

const PAGE = `<!doctype html><html><body>
<form id="grnPaymentForm" data-total-remaining="13000.00">
  <select id="grnObligationSelect" name="obligation_key">
    <option value="SUPPLIER:7" data-label="Supplier material" data-original="12000.00" data-paid="2000.00" data-remaining="10000.00">Supplier material</option>
    <option value="CHARGE:31" data-label="Vehicle Fare" data-original="3000.00" data-paid="500.00" data-remaining="2500.00">Vehicle Fare</option>
  </select>
  <div id="grnPaymentPayable"></div>
  <div id="grnPaymentAlreadyPaid"></div>
  <div id="grnTotalPayable"></div>
  <div id="grnTotalRemaining"></div>
  <div id="grnPaymentEntered"></div>
  <div id="grnPaymentRemaining"></div>
  <div id="grnPaymentOverpaymentRow" class="d-none"><span id="grnPaymentOverpayment"></span></div>
  <div id="grnPaymentStatus" class="d-none"></div>
  <select id="grnPaymentAccount" name="payment_account_id">
    <option value="">Select account</option>
    <option value="cash" data-balance="15000.00">Main cash</option>
  </select>
  <div id="grnAccountBalanceAfter"></div>
  <div id="grnAccountStatus" class="d-none"></div>
  <input id="grnPaymentAmount" name="amount">
  <input id="grnAllowAdvance" type="checkbox">
  <button type="button" id="grnPayRemaining">Pay remaining</button>
</form>
</body></html>`;

const dom = new JSDOM(PAGE, {
    url: "http://localhost/accounts/grn_payments?grn_id=7",
    runScripts: "outside-only",
    pretendToBeVisual: true
});
const w = dom.window;
const d = w.document;
w.eval(code);
const api = w.FBMGrnPayments;

let pass = 0;
let fail = 0;
function check(name, condition, extra) {
    if (condition) { pass += 1; console.log("  ok  -", name); }
    else { fail += 1; console.log("  FAIL-", name, extra === undefined ? "" : "-> " + extra); }
}
function input(value) {
    const el = d.getElementById("grnPaymentAmount");
    el.value = value;
    el.dispatchEvent(new w.Event("input", { bubbles: true }));
}
function change(id) {
    d.getElementById(id).dispatchEvent(new w.Event("change", { bubbles: true }));
}

check("script exposes FBMGrnPayments", !!api);
api.init(d);
check("selected obligation payable", d.getElementById("grnPaymentPayable").textContent === "Rs. 10,000.00");
check("selected obligation already paid", d.getElementById("grnPaymentAlreadyPaid").textContent === "Rs. 2,000.00");
check("total GRN balance", d.getElementById("grnTotalPayable").textContent === "Rs. 13,000.00");

input("3000");
check("partial selected balance", d.getElementById("grnPaymentRemaining").textContent === "Rs. 7,000.00");
check("partial total balance", d.getElementById("grnTotalRemaining").textContent === "Rs. 10,000.00");

const account = d.getElementById("grnPaymentAccount");
account.value = "cash";
change("grnPaymentAccount");
check("account balance after payment", d.getElementById("grnAccountBalanceAfter").textContent === "Rs. 12,000.00");

/* Changing the recipient uses its own server-provided remaining amount. */
d.getElementById("grnObligationSelect").value = "CHARGE:31";
change("grnObligationSelect");
check("charge payable", d.getElementById("grnPaymentPayable").textContent === "Rs. 2,500.00");
check("charge balance reacts to existing input", d.getElementById("grnPaymentRemaining").textContent === "Rs. 0.00");

/* An overpayment is visible and the submit guard blocks it until advance is on. */
input("3000");
check("overpayment row becomes visible", !d.getElementById("grnPaymentOverpaymentRow").classList.contains("d-none"));
check("overpayment amount", d.getElementById("grnPaymentOverpayment").textContent === "Rs. 500.00");
const blocked = new w.Event("submit", { bubbles: true, cancelable: true });
d.getElementById("grnPaymentForm").dispatchEvent(blocked);
check("overpayment is blocked without advance", blocked.defaultPrevented);

d.getElementById("grnAllowAdvance").checked = true;
change("grnAllowAdvance");
const allowed = new w.Event("submit", { bubbles: true, cancelable: true });
d.getElementById("grnPaymentForm").dispatchEvent(allowed);
check("advance allows overpayment", !allowed.defaultPrevented);

/* Return to supplier and use the exact server-provided current balance. */
d.getElementById("grnObligationSelect").value = "SUPPLIER:7";
change("grnObligationSelect");
d.getElementById("grnPayRemaining").click();
check("Pay remaining fills current balance", d.getElementById("grnPaymentAmount").value === "10000.00");

if (fail) {
    console.log("\n" + fail + " check(s) failed; " + pass + " passed.");
    process.exit(1);
}
console.log("\n" + pass + " checks passed.");
