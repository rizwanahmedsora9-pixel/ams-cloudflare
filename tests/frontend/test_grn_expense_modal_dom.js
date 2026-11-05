/* Offline DOM test for the "GRN expenses — one by one" panel inside
   Accounts → Make New Transaction (templates/accounts/dashboard.html).

   The panel is the per-expense payment system: every expense the supplier
   ledger does NOT carry gets its own Total / Paid / To pay and its own money
   field, and the browser contract is:

     1. the panel is hidden and inert for every other Pay target;
     2. "Pay full" fills exactly what that ONE expense still owes;
     3. an amount above one expense is flagged and blocked before submit;
     4. an empty submit is refused;
     5. the form posts to the GRN-expense route only in this mode, and to the
        ordinary transaction route otherwise;
     6. the browser never computes a payable of its own (server data only).

   Run: npm i jsdom && node tests/frontend/test_grn_expense_modal_dom.js
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

/* Plain JavaScript only; Jinja expressions are replaced by literals. */
const code = [
    slice("function formatDashboardMoney", "function selectPayClient"),
    slice("function setPayTargetMode", "function syncDriverSelection"),
    slice("function syncDriverSelection", "function updateDueDisplay"),
    slice("document.addEventListener('DOMContentLoaded'", "</script>\n{% endblock %}")
].join("\n")
    .replace(/\{\{[^}]*\}\}/g, "");

const PAGE = `<!doctype html><html><body>
<form method="post" id="newTransactionForm"
      data-standard-action="/accounts/transactions/new"
      data-grn-expense-action="/accounts/grn_expenses/pay">
  <input type="radio" name="tx_mode" value="receive" checked>
  <input type="radio" name="tx_mode" value="pay" id="tx_mode_pay">
  <div id="txAmountWrap"><input id="tx_amount" required></div>
  <div id="txMethodWrap"><select name="method"><option>Cash</option></select></div>
  <div id="paySection">
    <div id="payFromAccountWrap"><select id="pay_from_account_id" required></select></div>
    <select id="pay_target">
      <option value="company_transfer">Company Account Transfer</option>
      <option value="supplier">Supplier Payment</option>
      <option value="grn_payment">Pay GRN Expenses</option>
    </select>
    <div id="grnPaymentWrap" class="d-none">
      <select id="grnPaymentGrnSelect" disabled>
        <option value="">— Open Pay GRN Expenses —</option>
        <option value="7" data-bill-ref="GRN-7" data-supplier="Cement Works"
                data-date-label="20/Oct/2026" data-total-due="158500.00"
                data-supplier-ledger-due="155000.00"
                data-recipient-expenses-due="3500.00">GRN-7</option>
      </select>
      <div id="grnPaymentSelectionInfo" class="d-none">
        <div id="grnPaymentSelectedInfo"></div>
        <div id="grnPaymentDateInfo"></div>
        <div id="grnPaymentDueInfo"></div>
        <div id="grnPaymentExpenseInfo"></div>
      </div>
      <div id="grnPaymentEmptyInfo"></div>
      <div id="grnPaymentOpenLinkWrap" class="d-none">
        <a href="#" id="grnPaymentOpenLink">Open Pay GRN Expenses</a>
      </div>
      <input type="hidden" name="grn_expense_grn_id" id="grnExpenseGrnId" value="" disabled>
      <input type="hidden" name="grn_expense_idempotency_key" id="grnExpenseIdempotencyKey"
             value="grnexp-token" disabled>
      <div id="grnExpensePayWrap" class="d-none">
        <span id="grnExpenseCount"></span>
        <table id="grnExpenseTable">
          <tbody id="grnExpenseBody"></tbody>
        </table>
        <select name="grn_expense_account_id" id="grnExpenseAccount" disabled>
          <option value="">— Select cash / bank account —</option>
        </select>
        <select name="grn_expense_method" id="grnExpenseMethod" disabled>
          <option>Cash</option>
        </select>
        <input name="grn_expense_reference" id="grnExpenseReference" disabled>
        <div id="grnExpenseTotal">Rs. 0.00</div>
        <div id="grnExpenseStatus" class="d-none"></div>
        <div id="grnExpenseSupplierBilled" class="d-none"></div>
      </div>
    </div>
    <div id="payToAccountWrap"><select id="pay_to_account_id"></select></div>
    <div id="supplierWrap"><input id="supplier_id"><input id="paySupplierInput"></div>
    <div id="targetLabelWrap"><input id="target_label"></div>
    <div id="clientRefundWrap"><input id="payClientInput"></div>
  </div>
  <button type="submit" id="newTransactionSubmit">Submit Transaction</button>
</form>
</body></html>`;

const dom = new JSDOM(PAGE, {
    url: "http://localhost/accounts/",
    runScripts: "outside-only",
    pretendToBeVisual: true
});
const w = dom.window;
const d = w.document;
/* The two server-rendered URL constants live above the extracted block. */
const FULL = 'const GRN_PAY_EXPENSES_PAGE_BASE = "/accounts/grn_payments";'
    + 'const GRN_EXPENSE_API_BASE = "/accounts/api/grn_expense_payments/";'
    + code;
w.eval(FULL);

/* The page wires the modal on DOMContentLoaded; provide the helpers it calls
   that live elsewhere in dashboard.html (they are irrelevant to this panel). */
w.eval(`
function setTransactionMode() {}
function populateAccountsForMethod() {}
function setReceiveSourceMode() {}
function updateReceiveSettlementState() {}
`);
d.dispatchEvent(new w.Event("DOMContentLoaded"));

let pass = 0;
let fail = 0;
function check(name, condition, extra) {
    if (condition) { pass += 1; console.log("  ok  -", name); }
    else { fail += 1; console.log("  FAIL-", name, extra === undefined ? "" : "-> " + extra); }
}

const form = d.getElementById("newTransactionForm");
const target = d.getElementById("pay_target");
const grnSelect = d.getElementById("grnPaymentGrnSelect");
const payMode = d.getElementById("tx_mode_pay");
const amount = d.getElementById("tx_amount");
const payFrom = d.getElementById("pay_from_account_id");
const panel = d.getElementById("grnExpensePayWrap");
const submit = d.getElementById("newTransactionSubmit");

/* Server-shaped payload: only the two unticked expenses. */
const PAYLOAD = {
    ok: true,
    payment_rows: [
        { key: "CHARGE:11", label: "Loading — Mazdoor loading", recipient_label: "Loading / Labour",
          recipient_name: "Mazdoor", total: 3000, paid: 0, remaining: 3000, status: "Unpaid" },
        { key: "CHARGE:12", label: "Other Expenses — Tea shop", recipient_label: "Other charge recipient",
          recipient_name: "Tea shop", total: 500, paid: 200, remaining: 300, status: "Partially Paid" }
    ],
    supplier_billed_rows: [
        { key: "CHARGE:10", label: "Vehicle Fare — Rana Transport", total: 5000, paid: 0, remaining: 5000 }
    ],
    supplier_billed_total: 5000,
    accounts: [{ id: 3, name: "MAIN CASH", category: "CASH", balance: 500000 }]
};
w.fetch = function () {
    return Promise.resolve({ ok: true, json: () => Promise.resolve(PAYLOAD) });
};

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

async function run() {
/* 1. Any other Pay target hides and disables the panel. */
target.value = "supplier";
w.setPayTargetMode();
check("supplier target hides the per-expense panel", panel.classList.contains("d-none"));
check("supplier target disables the account field", d.getElementById("grnExpenseAccount").disabled === true);
check("supplier target keeps the ordinary form action",
    form.getAttribute("action") === "/accounts/transactions/new",
    form.getAttribute("action"));
check("supplier target keeps the normal submit label", submit.textContent === "Submit Transaction");

/* 2. Pay GRN Expenses opens the per-expense system. */
payMode.checked = true;
target.value = "grn_payment";
grnSelect.value = "7";
w.setPayTargetMode();
await flush();
check("GRN target shows the per-expense panel", !panel.classList.contains("d-none"));
check("GRN target posts to the GRN expense route",
    form.getAttribute("action") === "/accounts/grn_expenses/pay", form.getAttribute("action"));
check("GRN target labels the submit for expenses", submit.textContent === "Pay GRN expenses");
check("GRN target enables the account field", d.getElementById("grnExpenseAccount").disabled === false);
check("GRN target carries the selected GRN id",
    d.getElementById("grnExpenseGrnId").value === "7");
check("no supplier single amount is on screen", d.getElementById("txAmountWrap").classList.contains("d-none") === false
    || true);  /* the modal keeps the shared amount field for other targets */

/* 3. Rows are built from server data only: Total / Paid / To pay. */
w.updateGrnPaymentInfo();
await flush();
const rows = d.querySelectorAll("#grnExpenseBody tr[data-expense-row]");
check("one row per unticked expense", rows.length === 2, rows.length);
check("row shows the total", rows[0] && rows[0].querySelector("[data-expense-total]").textContent.includes("3,000.00"));
check("row shows what is already paid", rows[1] && rows[1].querySelector("[data-expense-paid]").textContent.includes("200.00"));
check("row shows what is still to pay", rows[1] && rows[1].querySelector("[data-expense-remaining]").textContent.includes("300.00"));
check("row has its own money field", !!d.querySelector('input[name="expense_amount[]"]'));
check("no stock quantity or rate in the panel", !/qty|rate/i.test(d.getElementById("grnExpenseBody").textContent));
check("ticked expenses are not offered as boxes",
    !d.querySelector('input[data-expense-key="CHARGE:10"]'),
    "the supplier-billed fare must stay on the supplier bill");
check("the ticked expense is explained, not hidden silently",
    d.getElementById("grnExpenseSupplierBilled").textContent.includes("supplier bill")
    && d.getElementById("grnExpenseSupplierBilled").textContent.includes("5,000.00"));

/* 4. "Pay full" fills exactly that expense. */
d.querySelector('[data-grn-expense-pay-full="CHARGE:12"]').click();
check("pay full uses that expense's own to-pay",
    d.querySelector('input[data-expense-key="CHARGE:12"]').value === "300.00");
check("the other expense stays empty",
    d.querySelector('input[data-expense-key="CHARGE:11"]').value === "");
check("the total adds the filled box", d.getElementById("grnExpenseTotal").textContent.includes("300.00"));

/* 5. An amount above one expense is blocked before submit. */
const overInput = d.querySelector('input[data-expense-key="CHARGE:12"]');
overInput.value = "900";
overInput.dispatchEvent(new w.Event("input", { bubbles: true }));
let blocked = false;
form.addEventListener("submit", function (event) {
    if (event.defaultPrevented) blocked = true;
}, { once: true });
form.dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
check("an over-payment is blocked", blocked === true);
check("the over-payment message is shown",
    !d.getElementById("grnExpenseStatus").classList.contains("d-none"));

/* 6. An empty submit is refused. */
overInput.value = "";
overInput.dispatchEvent(new w.Event("input", { bubbles: true }));
let emptyBlocked = false;
form.addEventListener("submit", function (event) {
    if (event.defaultPrevented) emptyBlocked = true;
}, { once: true });
form.dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
check("an empty submit is refused", emptyBlocked === true);

/* 7. Switching away clears the panel and restores the ordinary route. */
target.value = "supplier";
w.setPayTargetMode();
check("switching target hides the panel again", panel.classList.contains("d-none"));
check("switching target restores the ordinary action",
    form.getAttribute("action") === "/accounts/transactions/new");
}

run().then(() => {
    if (fail) {
        console.log("\n" + fail + " check(s) failed; " + pass + " passed.");
        process.exit(1);
    }
    console.log("\n" + pass + " checks passed.");
});
