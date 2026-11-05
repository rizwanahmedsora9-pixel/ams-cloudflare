/* Offline DOM test for static/pay_grn.js (PAY GRN — stock / expenses).

   The page is server-authoritative: each payable block carries its own
   `data-remaining` produced by app/services/grn_costing.py.  This test pins
   the browser-only contract:

     1. "Pay full" fills exactly what that ONE payable is due, including an
        expense that was not added to the supplier ledger;
     2. the entered total adds every box and never merges the payables;
     3. an amount above a payable is flagged and blocked before submit;
     4. an empty submit is refused;
     5. the calculator never disables a permitted submit.

   Run: npm i jsdom && node tests/frontend/test_pay_grn_dom.js
*/
const fs = require("fs");
const path = require("path");
let JSDOM;
try { JSDOM = require("jsdom").JSDOM; }
catch (_) { JSDOM = require("/tmp/node_modules/jsdom").JSDOM; }

const code = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "pay_grn.js"),
    "utf8"
);

const PAGE = `<!doctype html><html><body>
<form id="payGrnForm" data-can-edit="1">
  <div data-pay-block="MATERIAL" data-remaining="150000.00">
    <input type="hidden" name="pay_obligation_key[]" value="MATERIAL:7">
    <input type="number" name="pay_amount[]" id="payGrnMaterial">
    <button type="button" data-pay-full="payGrnMaterial">Pay full</button>
  </div>
  <div data-pay-block="EXPENSES" data-remaining="6000.00">
    <input type="hidden" name="pay_obligation_key[]" value="EXPENSES:7">
    <input type="number" name="pay_amount[]" id="payGrnExpenses">
    <button type="button" data-pay-full="payGrnExpenses">Pay full</button>
  </div>
  <div data-pay-block="CHARGE:31" data-remaining="500.00">
    <input type="hidden" name="pay_obligation_key[]" value="CHARGE:31">
    <input type="number" name="pay_amount[]" id="payGrnCharge31">
    <button type="button" data-pay-full="payGrnCharge31">Pay full</button>
  </div>
  <b id="payGrnEntered">Rs. 0.00</b>
  <div id="payGrnStatus" class="d-none"></div>
  <button id="payGrnSubmit" data-can-edit="1">Save payment</button>
</form>
</body></html>`;

const dom = new JSDOM(PAGE, {
    url: "http://localhost/accounts/pay_grn?grn_id=7",
    runScripts: "outside-only",
    pretendToBeVisual: true
});
const w = dom.window;
const d = w.document;
w.eval(code);
const api = w.FBMPayGrn;

let pass = 0;
let fail = 0;
function check(name, condition, extra) {
    if (condition) { pass += 1; console.log("  ok  -", name); }
    else { fail += 1; console.log("  FAIL-", name, extra === undefined ? "" : "-> " + extra); }
}
function input(id, value) {
    const el = d.getElementById(id);
    el.value = value;
    el.dispatchEvent(new w.Event("input", { bubbles: true }));
}
function submit() {
    const event = new w.Event("submit", { bubbles: true, cancelable: true });
    d.getElementById("payGrnForm").dispatchEvent(event);
    return event;
}

check("script exposes FBMPayGrn", !!api);
api.init(d);

/* 1. Pay full is per-payable and exact. */
const materialFull = d.querySelector('[data-pay-full="payGrnMaterial"]');
const expensesFull = d.querySelector('[data-pay-full="payGrnExpenses"]');
materialFull.click();
check("Pay full fills the stock payable only", d.getElementById("payGrnMaterial").value === "150000.00");
check("the expense box is untouched", d.getElementById("payGrnExpenses").value === "");
check("entered total shows stock only", d.getElementById("payGrnEntered").textContent === "Rs. 150,000.00");
expensesFull.click();
check("Pay full fills the expense payable separately", d.getElementById("payGrnExpenses").value === "6000.00");
check("entered total adds both payables", d.getElementById("payGrnEntered").textContent === "Rs. 156,000.00");
check("both submit cleanly", !submit().defaultPrevented);

/* 2. An expense amount above its own payable is flagged. */
input("payGrnExpenses", "7000");
check("over-expense is flagged on the input",
    d.getElementById("payGrnExpenses").classList.contains("is-invalid"));
check("stock stays valid",
    !d.getElementById("payGrnMaterial").classList.contains("is-invalid"));
const blocked = submit();
check("overpaying one payable is blocked", blocked.defaultPrevented);
check("the reason is shown", !d.getElementById("payGrnStatus").classList.contains("d-none"));

/* 3. Partial amounts are allowed and total correctly. */
input("payGrnMaterial", "50000");
input("payGrnExpenses", "1000");
check("partial total", d.getElementById("payGrnEntered").textContent === "Rs. 51,000.00");
check("partial submit passes", !submit().defaultPrevented);

/* 4. An empty submit is refused. */
input("payGrnMaterial", "");
input("payGrnExpenses", "");
check("empty total", d.getElementById("payGrnEntered").textContent === "Rs. 0.00");
check("empty submit blocked", submit().defaultPrevented);
check("the submit button is disabled when nothing is entered",
    d.getElementById("payGrnSubmit").disabled === true);

/* 5. Stock alone is a normal, valid payment. */
input("payGrnMaterial", "150000");
check("stock-only submit passes", !submit().defaultPrevented);
check("the submit button is enabled", d.getElementById("payGrnSubmit").disabled === false);
check("expenses alone still show as due server-side",
    d.querySelector('[data-pay-block="EXPENSES"]').getAttribute("data-remaining") === "6000.00");

/* 6. Zero-remaining blocks cannot be filled. */
d.querySelector('[data-pay-block="EXPENSES"]').setAttribute("data-remaining", "0.00");
d.getElementById("payGrnExpenses").disabled = true;
expensesFull.click();
check("Pay full does nothing on a settled payable", d.getElementById("payGrnExpenses").value === "");

/* 7. An expense not added to the supplier ledger has its own payable box. */
const chargeFull = d.querySelector('[data-pay-full="payGrnCharge31"]');
chargeFull.click();
check("own-recipient expense Pay full uses its own due",
    d.getElementById("payGrnCharge31").value === "500.00");
check("entered total includes off-ledger expenses",
    d.getElementById("payGrnEntered").textContent === "Rs. 150,500.00");
input("payGrnCharge31", "600");
check("own-recipient expense overpayment is flagged",
    d.getElementById("payGrnCharge31").classList.contains("is-invalid"));
check("own-recipient expense overpayment is blocked", submit().defaultPrevented);

if (fail) {
    console.log("\n" + fail + " check(s) failed; " + pass + " passed.");
    process.exit(1);
}
console.log("\n" + pass + " checks passed.");
