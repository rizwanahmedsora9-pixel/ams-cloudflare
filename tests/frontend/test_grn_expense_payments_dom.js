/* Offline DOM test for static/grn_expense_payments.js (Pay GRN Expenses).

   The page is server-authoritative: every expense box carries its own
   `data-remaining` produced by app/services/grn_costing.py, and the supplier
   amount field is not rendered in this payment mode at all.  This test pins the
   browser-only contract:

     1. "Pay full" fills exactly what that ONE expense still owes;
     2. the entered total adds every expense box;
     3. an amount above one expense is flagged and blocked before submit;
     4. an empty submit is refused;
     5. the calculator never disables a permitted submit;
     6. a fully paid (disabled) box is ignored.

   Run: npm i jsdom && node tests/frontend/test_grn_expense_payments_dom.js
*/
const fs = require("fs");
const path = require("path");
let JSDOM;
try { JSDOM = require("jsdom").JSDOM; }
catch (_) { JSDOM = require("/tmp/node_modules/jsdom").JSDOM; }

const code = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "grn_expense_payments.js"),
    "utf8"
);

const PAGE = `<!doctype html><html><body>
<form id="grnExpenseForm" data-can-edit="1">
  <div class="grn-expense-box" id="expense-box-11" data-expense-box="CHARGE:11" data-remaining="5000.00">
    <input type="hidden" name="expense_key[]" value="CHARGE:11">
    <input type="number" name="expense_amount[]" id="expenseAmount11" value="">
    <button type="button" data-pay-full="expenseAmount11">Pay full</button>
  </div>
  <div class="grn-expense-box" id="expense-box-12" data-expense-box="CHARGE:12" data-remaining="3000.00">
    <input type="hidden" name="expense_key[]" value="CHARGE:12">
    <input type="number" name="expense_amount[]" id="expenseAmount12" value="">
    <button type="button" data-pay-full="expenseAmount12">Pay full</button>
  </div>
  <div class="grn-expense-box is-paid" id="expense-box-13" data-expense-box="CHARGE:13" data-remaining="0.00">
    <input type="hidden" name="expense_key[]" value="CHARGE:13">
    <input type="number" name="expense_amount[]" id="expenseAmount13" value="" disabled>
    <button type="button" data-pay-full="expenseAmount13" disabled>Pay full</button>
  </div>
  <b id="grnExpenseEntered">Rs. 0.00</b>
  <div class="d-none" id="grnExpenseStatus"></div>
  <button id="grnExpenseSubmit" data-can-edit="1">Save expense payment(s)</button>
</form>
</body></html>`;

const dom = new JSDOM(PAGE, { runScripts: "outside-only" });
const { window } = dom;
window.eval(code);
const d = window.document;
const form = d.getElementById("grnExpenseForm");
const api = window.FBMGrnExpensePayments;
// jsdom still reports `loading`, so DOMContentLoaded has not fired yet: wire the
// controller exactly as the page does after parse.
api.init(d);

let failures = 0;
function check(name, condition) {
    if (condition) { console.log("  ok  - " + name); }
    else { failures += 1; console.log("  FAIL- " + name); }
}

function setValue(input, value) {
    input.value = String(value);
    const event = new window.Event("input", { bubbles: true });
    input.dispatchEvent(event);
}

check("controller initialised", !!api && !!api.getState());
check("reads every expense box", api.boxes().length === 3);

// 1. Pay full fills only that expense.
d.querySelector('[data-pay-full="expenseAmount12"]').click();
check("pay full fills exactly that expense",
    d.getElementById("expenseAmount12").value === "3000.00");
check("the other expense stays empty",
    d.getElementById("expenseAmount11").value === "");
check("totals what was entered",
    d.getElementById("grnExpenseEntered").textContent === "Rs. 3,000.00");

// 2. Two expenses can be paid in one run.
setValue(d.getElementById("expenseAmount11"), "2000");
check("adds a second expense to the same run",
    d.getElementById("grnExpenseEntered").textContent === "Rs. 5,000.00");

// 3. Overpayment of ONE expense is flagged (supplier bill is not involved).
setValue(d.getElementById("expenseAmount12"), "4000");
check("amount above the expense is flagged",
    d.getElementById("expenseAmount12").classList.contains("is-invalid"));
let prevented = false;
form.dispatchEvent(new window.Event("submit", { cancelable: true }));
const submitEvent = new window.Event("submit", { cancelable: true });
form.dispatchEvent(submitEvent);
prevented = submitEvent.defaultPrevented;
check("overpayment blocks the submit", prevented);
check("status explains the refusal",
    d.getElementById("grnExpenseStatus").textContent.indexOf("more than that expense") !== -1);

// 4. A valid amount submits.
setValue(d.getElementById("expenseAmount12"), "3000");
const okEvent = new window.Event("submit", { cancelable: true });
form.dispatchEvent(okEvent);
check("valid amounts are allowed to submit", okEvent.defaultPrevented === false);

// 5. Empty submit refused.
setValue(d.getElementById("expenseAmount11"), "");
setValue(d.getElementById("expenseAmount12"), "");
const emptyEvent = new window.Event("submit", { cancelable: true });
form.dispatchEvent(emptyEvent);
check("empty submit is refused", emptyEvent.defaultPrevented === true);
check("status asks for an amount",
    d.getElementById("grnExpenseStatus").textContent.indexOf("at least one GRN expense") !== -1);
check("submit is disabled while nothing is entered",
    d.getElementById("grnExpenseSubmit").disabled === true);
setValue(d.getElementById("expenseAmount11"), "100");
check("entering money re-enables the submit",
    d.getElementById("grnExpenseSubmit").disabled === false);

// 6. Paid (disabled) box is ignored even if it somehow holds a value.
d.getElementById("expenseAmount13").value = "999";
api.refresh();
check("a settled expense is never counted",
    d.getElementById("grnExpenseEntered").textContent === "Rs. 100.00");

// 7. A permission-less render keeps the button disabled.
const locked = new JSDOM(PAGE.split('data-can-edit="1"').join('data-can-edit="0"'),
    { runScripts: "outside-only" });
locked.window.eval(code);
locked.window.FBMGrnExpensePayments.init(locked.window.document);
locked.window.document.getElementById("grnExpenseSubmit").disabled = false;
const lockedForm = locked.window.document.getElementById("grnExpenseForm");
const lockedInput = locked.window.document.getElementById("expenseAmount11");
lockedInput.value = "50";
lockedInput.dispatchEvent(new locked.window.Event("input", { bubbles: true }));
check("no permission = submit stays disabled",
    locked.window.document.getElementById("grnExpenseSubmit").disabled === true);

if (failures) {
    console.log(failures + " check(s) FAILED.");
    process.exit(1);
}
console.log("all checks passed.");
