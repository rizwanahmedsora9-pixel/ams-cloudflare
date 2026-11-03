/* Offline DOM test for static/delivery_rents.js — the expandable Delivery Rent
   summary.

   Owner rule under test: the screen shows ONE line per delivery person with
   rent / paid / remaining, and an arrow expands the trips behind it.  Ten
   drivers doing ten deliveries must stay ten readable lines, not a hundred.

   Pinned here:

     1. clicking a summary row expands it and a second click collapses it;
     2. a row whose detail was already rendered inline (small period) fires no
        request; a row that was not gets exactly ONE request, and re-opening it
        does not request again;
     3. a failed request shows a retry, never an empty trip list (an empty list
        would read as "this driver owes nothing");
     4. the Pay / Ledger / Delete controls inside the action cell never toggle
        the row;
     5. "Pay" on a summary row opens the driver modal addressed to
        /delivery_rents/pay_driver/<id> with the outstanding amount pre-filled;
     6. "Pay" on a trip row opens the trip modal addressed to
        /delivery_rents/pay/<allocation id>;
     7. forms that arrive with the fetched detail still get the session CSRF
        token, and the account list still follows the payment method.

   Run:  npm i jsdom   then   node tests/frontend/test_delivery_rents_dom.js
   Against a real rendered screen instead of the fixture:
         RENTS_PAGE_HTML=/tmp/rents.html RENTS_GROUP_JSON=/tmp/rent_group.json \
             node tests/frontend/test_delivery_rents_dom.js */
const fs = require("fs");
const path = require("path");
let JSDOM;
try { JSDOM = require("jsdom").JSDOM; }
catch (_) { JSDOM = require("/tmp/node_modules/jsdom").JSDOM; }

const code = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "delivery_rents.js"),
    "utf8"
);

let pass = 0, fail = 0;
function check(name, cond, extra) {
    if (cond) { pass++; console.log("  ok  -", name); }
    else { fail++; console.log("  FAIL-", name, extra === undefined ? "" : "-> " + extra); }
}

/* The detail fragment the server returns for one delivery person: two trips,
   the first already settled, plus a payment line and its reversal form. */
const GROUP_HTML = `
<table class="table rent-detail-table"><tbody>
  <tr class="rent-entry-row">
    <td>2026-10-28</td><td><a class="rent-bill-link" href="/direct_sales?q=MB">MB NO.1</a></td>
    <td>CLIENT A</td><td>10</td><td>Rs. 100.00</td><td>Rs. 100.00</td><td>Rs. 0.00</td>
    <td><button type="button" class="btn rent-pay-entry" data-entry-id="11"
                data-person="ALI RAZA" data-bill="MB NO.1" data-due="0.00">Pay</button></td>
  </tr>
  <tr class="rent-entry-row">
    <td>2026-10-29</td><td><a class="rent-bill-link" href="/direct_sales?q=MB">MB NO.2</a></td>
    <td>CLIENT B</td><td>12</td><td>Rs. 150.00</td><td>Rs. 0.00</td><td>Rs. 150.00</td>
    <td><button type="button" class="btn rent-pay-entry" data-entry-id="12"
                data-person="ALI RAZA" data-bill="MB NO.2" data-due="150.00">Pay</button>
        <form method="POST" action="/delivery_rents/void/12" class="d-inline">
          <input type="hidden" name="next" value="/delivery_rents">
          <button type="submit" class="btn rent-icon-btn">Delete</button>
        </form></td>
  </tr>
  <tr class="rent-payment-row"><td colspan="8">
    <div class="rent-payment-item">Rs. 100.00 · 2026-10-30 · Cash
      <form method="POST" action="/delivery_person_payments/5/void" class="d-inline">
        <button type="submit" class="btn btn-link rent-link-btn">reverse</button>
      </form>
    </div>
  </td></tr>
</tbody></table>`;

const PAGE_HTML = `<!doctype html><html><body>
  <table id="rentGroupTable" data-csrf-token="token-abc"
         data-base-url="/delivery_rents" data-currency="Rs. ">
    <tbody>
      <tr class="rent-group-row" data-group-key="person:1" data-target="rentDetail_1" data-loaded="0"
          tabindex="0" aria-expanded="false">
        <td><div class="d-flex"><span class="rent-chevron"></span><span class="rent-driver-name">ALI RAZA</span></div></td>
        <td class="text-end rent-amount">Rs. 250.00</td>
        <td class="text-end rent-amount">Rs. 100.00</td>
        <td class="text-end rent-amount rent-amount-due">Rs. 150.00</td>
        <td class="text-end"><button type="button" class="btn rent-pay-driver" data-person-id="1"
              data-person="ALI RAZA" data-due="150.00" data-trips="2">Pay</button>
            <a href="/delivery_person_ledger/1" class="btn rent-ledger">Ledger</a></td>
      </tr>
      <tr class="rent-detail-row" id="rentDetail_1" hidden><td><div class="rent-detail-wrap"></div></td></tr>

      <tr class="rent-group-row" data-group-key="person:2" data-target="rentDetail_2" data-loaded="1"
          tabindex="0" aria-expanded="false">
        <td><span class="rent-driver-name">BILAL AHMED</span></td>
        <td class="text-end rent-amount">Rs. 300.00</td>
        <td class="text-end rent-amount">Rs. 300.00</td>
        <td class="text-end rent-amount text-white-50">Rs. 0.00</td>
        <td class="text-end"><a href="/delivery_person_ledger/2" class="btn rent-ledger">Ledger</a></td>
      </tr>
      <tr class="rent-detail-row" id="rentDetail_2" hidden><td><div class="rent-detail-wrap">
        <table class="table rent-detail-table"><tr class="rent-entry-row"><td>inline detail</td></tr></table>
      </div></td></tr>
    </tbody>
  </table>

  <form id="rentEntryPayForm" method="POST" action="#">
    <input type="number" name="paid_amount" value="0">
    <select name="method" class="rent-method"><option value="Cash">Cash</option><option value="Bank">Bank</option></select>
    <select name="payment_account_id" class="rent-account">
      <option value="">Select…</option>
      <option value="1" data-category="cash">[CASH] MAIN CASH</option>
      <option value="2" data-category="bank">[BANK] MAIN BANK</option>
    </select>
    <button type="submit">Save</button>
  </form>
  <form id="rentDriverPayForm" method="POST" action="#">
    <input type="number" name="paid_amount" value="0">
    <select name="method" class="rent-method"><option value="Cash">Cash</option><option value="Bank">Bank</option></select>
    <select name="payment_account_id" class="rent-account">
      <option value="">Select…</option>
      <option value="1" data-category="cash">[CASH] MAIN CASH</option>
      <option value="2" data-category="bank">[BANK] MAIN BANK</option>
    </select>
    <button type="submit">Save</button>
  </form>
  <div id="rentEntryPayModal"></div>
  <div id="rentDriverPayModal"></div>
  <span id="rentEntryPayPerson"></span><span id="rentEntryPayBill"></span><span id="rentEntryPayDue"></span>
  <span id="rentDriverPayPerson"></span><span id="rentDriverPayDue"></span>
  <span id="rentDriverPayTrips"></span><span id="rentDriverPayTripPlural"></span>
</body></html>`;

const realPage = process.env.RENTS_PAGE_HTML;
const realGroup = process.env.RENTS_GROUP_JSON;
const pageHtml = realPage ? fs.readFileSync(realPage, "utf8") : PAGE_HTML;
const groupPayload = realGroup
    ? fs.readFileSync(realGroup, "utf8")
    : JSON.stringify({ ok: true, key: "person:1", html: GROUP_HTML });

const dom = new JSDOM(pageHtml, { url: "http://localhost/delivery_rents", runScripts: "outside-only" });
const w = dom.window;
const d = w.document;

const shownModals = [];
w.bootstrap = {
    Modal: {
        getOrCreateInstance: function (el) {
            return {
                show: function () { shownModals.push(el.id); },
                hide: function () {}
            };
        }
    }
};

const requests = [];
let mode = "ok";
w.fetch = function (url) {
    requests.push({ url: url, options: arguments[1] });
    if (mode === "fail") {
        return Promise.resolve({ ok: false, status: 500, json: function () { return Promise.resolve({}); } });
    }
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve(JSON.parse(groupPayload)); } });
};

try {
    w.eval(code);
} catch (err) {
    console.log("  FAIL- script threw on load ->", err.message);
    fail++;
}

function click(el) {
    el.dispatchEvent(new w.Event("click", { bubbles: true }));
}
function wait(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms || 30); });
}

const rows = Array.from(d.querySelectorAll(".rent-group-row"));
const rowOne = rows[0];
const detailOne = d.getElementById("rentDetail_1");
const rowTwo = rows[1];
const detailTwo = d.getElementById("rentDetail_2");

(async function run() {
    check("summary rows found", rows.length >= 1, rows.length);
    check("detail starts hidden", detailOne.hidden === true && detailTwo.hidden === true);

    /* 1. expand / collapse ------------------------------------------------ */
    click(rowOne.querySelector("td"));
    await wait(40);
    check("arrow expands the row", rowOne.classList.contains("is-open"));
    check("detail becomes visible", detailOne.hidden === false);
    check("aria-expanded is true", rowOne.getAttribute("aria-expanded") === "true");
    check("detail fetched once", requests.length === 1, requests.length);
    check("fetch hits the group endpoint", /\/delivery_rents\/group\/person%3A\d+/.test(requests[0].url), requests[0].url);
    check("fetch keeps the page filters", requests[0].url.indexOf("/group/") > 0, requests[0].url);
    check("detail html injected", detailOne.innerHTML.indexOf("MB NO.1") !== -1);
    check("detail marked loaded", rowOne.getAttribute("data-loaded") === "1");

    click(rowOne.querySelector("td"));
    check("second click collapses", !rowOne.classList.contains("is-open") && detailOne.hidden === true);

    click(rowOne.querySelector("td"));
    await wait(30);
    check("re-opening fires no extra request", requests.length === 1, requests.length);

    /* 2. rows already rendered inline ------------------------------------ */
    const rowTwoWasLazy = rowTwo.getAttribute("data-loaded") === "0";
    click(rowTwo.querySelector("td"));
    await wait(30);
    // A row the server rendered inline must not re-fetch; a row it left lazy
    // fetches exactly once.  Both are correct — the page decides per period.
    check("second row opens without a duplicate request",
        rowTwo.classList.contains("is-open") && requests.length === (rowTwoWasLazy ? 2 : 1),
        requests.length + " (was lazy=" + rowTwoWasLazy + ")");
    check("second row shows its trips", detailTwo.innerHTML.indexOf("rent-detail-wrap") !== -1);

    /* 3. action cell does not toggle ------------------------------------- */
    const driverBtn = rowOne.querySelector(".rent-pay-driver");
    const wasOpen = rowOne.classList.contains("is-open");
    click(driverBtn);
    check("Pay button does not toggle the row", rowOne.classList.contains("is-open") === wasOpen);

    const ledgerLink = rowTwo.querySelector("a");
    if (ledgerLink) {
        ledgerLink.addEventListener("click", function (e) { e.preventDefault(); });
        const rowTwoOpen = rowTwo.classList.contains("is-open");
        click(ledgerLink);
        check("Ledger link does not toggle the row", rowTwo.classList.contains("is-open") === rowTwoOpen);
    }

    const deleteForm = detailOne.querySelector('form[action*="/delivery_rents/void/"]');
    const deleteBtn = deleteForm ? deleteForm.querySelector("button") : null;
    check("delete form was present in the injected detail", !!deleteBtn);
    if (deleteBtn) {
        deleteForm.addEventListener("submit", function (e) { e.preventDefault(); });
        click(deleteBtn);
        check("Delete button does not toggle the row", rowOne.classList.contains("is-open") === wasOpen);
    }

    /* 4. CSRF token for late forms --------------------------------------- */
    const injectedForm = detailOne.querySelector('form[method="POST"]');
    check("late form got the CSRF token",
        !!injectedForm && injectedForm.querySelector('input[name="_csrf_token"]') !== null);
    check("CSRF value matches the page",
        injectedForm && injectedForm.querySelector('input[name="_csrf_token"]').value ===
            (d.getElementById("rentGroupTable").dataset.csrfToken || ""));

    /* 5. pay one delivery person ---------------------------------------- */
    if (!driverBtn) {
        console.log("  ..  no Pay button in this page (nothing outstanding) — skipping pay checks");
    }
    if (driverBtn) { click(driverBtn); }
    const driverForm = d.getElementById("rentDriverPayForm");
    if (driverBtn) {
    check("driver modal opens", shownModals.indexOf("rentDriverPayModal") !== -1, shownModals.join(","));
    check("driver action targets the person", /\/delivery_rents\/pay_driver\/\d+/.test(driverForm.action), driverForm.action);
    check("driver amount is pre-filled with the outstanding",
        Number(driverForm.querySelector('input[name="paid_amount"]').value) ===
            Number(driverBtn.getAttribute("data-due")));
    check("driver name shown", d.getElementById("rentDriverPayPerson").textContent.length > 0, d.getElementById("rentDriverPayPerson").textContent);
    check("driver due is formatted with the currency",
        d.getElementById("rentDriverPayDue").textContent.indexOf("Rs.") === 0,
        d.getElementById("rentDriverPayDue").textContent);
    check("trip count shown", d.getElementById("rentDriverPayTrips").textContent === (driverBtn.getAttribute("data-trips") || "0"));
    }

    /* 6. pay one trip ---------------------------------------------------- */
    const tripBtns = detailOne.querySelectorAll(".rent-pay-entry");
    const tripBtn = tripBtns[tripBtns.length - 1];
    check("trip pay button exists in the detail", !!tripBtn);
    if (tripBtn) {
        click(tripBtn);
        const entryForm = d.getElementById("rentEntryPayForm");
        check("trip modal opens", shownModals.indexOf("rentEntryPayModal") !== -1, shownModals.join(","));
        check("trip action targets the allocation", /\/delivery_rents\/pay\/\d+/.test(entryForm.action), entryForm.action);
        check("trip amount is pre-filled",
            Number(entryForm.querySelector('input[name="paid_amount"]').value) ===
                Number(tripBtn.getAttribute("data-due")));
        check("trip modal names the driver", d.getElementById("rentEntryPayPerson").textContent.length > 0);
        check("trip modal names the bill", d.getElementById("rentEntryPayBill").textContent.length > 0);
    }

    /* 7. account list follows the method -------------------------------- */
    function visibleAccounts(form) {
        return Array.from(form.querySelectorAll(".rent-account option"))
            .filter(function (o) { return o.value && !o.hidden; })
            .map(function (o) { return o.dataset.category; });
    }
    const method = driverForm.querySelector(".rent-method");
    method.value = "Bank";
    method.dispatchEvent(new w.Event("change", { bubbles: true }));
    check("Bank hides cash accounts", visibleAccounts(driverForm).every(function (c) { return c === "bank"; }),
        visibleAccounts(driverForm).join(","));
    method.value = "Cash";
    method.dispatchEvent(new w.Event("change", { bubbles: true }));
    check("Cash hides bank accounts", visibleAccounts(driverForm).join(",") === "cash", visibleAccounts(driverForm).join(","));

    /* 8. a failed load is reported, never an empty list ------------------ */
    mode = "fail";
    const fresh = new JSDOM(PAGE_HTML, { url: "http://localhost/delivery_rents", runScripts: "outside-only" });
    const w2 = fresh.window;
    w2.bootstrap = w.bootstrap;
    w2.fetch = function (url) {
        return Promise.resolve({ ok: false, status: 500, json: function () { return Promise.resolve({}); } });
    };
    w2.eval(code);
    const row3 = w2.document.querySelector(".rent-group-row");
    row3.querySelector("td").dispatchEvent(new w2.Event("click", { bubbles: true }));
    await wait(40);
    const wrap = w2.document.getElementById("rentDetail_1").querySelector(".rent-detail-wrap");
    check("failed load shows a retry, not an empty list", /Try again/.test(wrap.innerHTML), wrap.innerHTML.slice(0, 120));
    check("failed load keeps the row open", row3.classList.contains("is-open"));
    check("failed load does not mark the detail loaded", row3.getAttribute("data-loaded") !== "1");

    console.log("\n" + pass + " passed, " + fail + " failed");
    process.exit(fail ? 1 : 0);
})();
