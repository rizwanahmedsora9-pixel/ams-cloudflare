/* Offline DOM test for static/driver_ledger.js — expandable daily rows on the
   Delivery Person Ledger.

   Pinned behaviour:
     1. every day row starts collapsed (aria-expanded="false", detail hidden);
     2. clicking a day row (or its arrow) expands that day's detail row, and
        clicking again collapses it back to just the day's total;
     3. keyboard Enter / Space on a focused day row toggles it;
     4. Expand all / Collapse all toggles all days and stays in sync when
        individual rows are opened or closed;
     5. clicking bill links, Edit/Reverse buttons, forms, or star buttons inside
        an expanded detail row never toggles/collapses the day row;
     6. starring an entry inside a day lights up the star indicator dot on that
        day's collapsed summary row. */
const fs = require("fs");
const path = require("path");
let JSDOM;
try { JSDOM = require("jsdom").JSDOM; }
catch (_) { JSDOM = require("/tmp/node_modules/jsdom").JSDOM; }

const code = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "driver_ledger.js"),
    "utf8"
);

let pass = 0, fail = 0;
function check(name, cond, extra) {
    if (cond) { pass++; console.log("  ok  -", name); }
    else { fail++; console.log("  FAIL-", name, extra === undefined ? "" : "-> " + extra); }
}

const PAGE_HTML = `<!doctype html><html><body>
  <button type="button" id="driverLedgerToggleAll" data-expanded="0" aria-expanded="false">
    <i class="bi bi-arrows-expand me-1"></i><span>Expand all</span>
  </button>
  <table id="driverLedgerTable">
    <tbody>
      <tr class="driver-day-row" data-group-key="day:2026-10-05" data-target="driverDayDetail_1" tabindex="0" aria-expanded="false">
        <td>
          <span class="driver-day-chevron"><i class="bi bi-chevron-right"></i></span>
          <span class="driver-day-title">2026-10-05</span>
          <i class="bi bi-star-fill driver-day-star-dot" hidden></i>
        </td>
        <td><span class="badge">3 entries</span></td>
        <td class="text-end">Rs. 3,300.00</td>
        <td class="text-end">—</td>
        <td class="text-end">Rs. 3,800.00</td>
      </tr>
      <tr class="driver-day-detail-row" id="driverDayDetail_1" hidden>
        <td colspan="5">
          <table class="driver-day-detail-table">
            <tbody>
              <tr>
                <td><span class="row-star-btn" data-row-id="rent-1"><i class="bi bi-star"></i></span></td>
                <td>2026-10-05 10:00</td>
                <td>Delivery Rent</td>
                <td><a id="billLink1" href="/view_bill/MB-101">MB-101</a></td>
                <td>Delivery rent (CLIENT D1-1) · 25 bags</td>
                <td>—</td><td>—</td><td>1,000.00</td><td>—</td><td>1,500.00</td>
                <td>—</td>
              </tr>
            </tbody>
          </table>
        </td>
      </tr>

      <tr class="driver-day-row" data-group-key="day:2026-10-06" data-target="driverDayDetail_2" tabindex="0" aria-expanded="false">
        <td>
          <span class="driver-day-chevron"><i class="bi bi-chevron-right"></i></span>
          <span class="driver-day-title">2026-10-06</span>
          <i class="bi bi-star-fill driver-day-star-dot" hidden></i>
        </td>
        <td><span class="badge">4 entries</span></td>
        <td class="text-end">Rs. 1,500.00</td>
        <td class="text-end">Rs. 3,000.00</td>
        <td class="text-end">Rs. 2,300.00</td>
      </tr>
      <tr class="driver-day-detail-row" id="driverDayDetail_2" hidden>
        <td colspan="5">
          <table class="driver-day-detail-table">
            <tbody>
              <tr>
                <td><span class="row-star-btn" data-row-id="pay-1"><i class="bi bi-star"></i></span></td>
                <td>2026-10-06 15:00</td>
                <td>Payment</td>
                <td>VCH-77</td>
                <td>Driver service payment from LEDGER CASH · Bill MB-101</td>
                <td>LEDGER CASH</td><td>—</td><td>—</td><td>1,000.00</td><td>2,800.00</td>
                <td>
                  <button type="button" id="editBtn1">Edit</button>
                  <form method="POST" action="/delivery_person_payments/1/void" onsubmit="return false;">
                    <button type="submit" id="voidBtn1">Reverse</button>
                  </form>
                </td>
              </tr>
            </tbody>
          </table>
        </td>
      </tr>
    </tbody>
  </table>
</body></html>`;

const dom = new JSDOM(PAGE_HTML, { runScripts: "outside-only", url: "https://example.test/delivery_person_ledger/1" });
dom.window.eval(code);

const doc = dom.window.document;
const rows = doc.querySelectorAll(".driver-day-row");
const detail1 = doc.getElementById("driverDayDetail_1");
const detail2 = doc.getElementById("driverDayDetail_2");
const toggleAll = doc.getElementById("driverLedgerToggleAll");

check("two daily summary rows found", rows.length === 2, rows.length);
check("day 1 detail starts hidden", detail1.hidden === true);
check("day 2 detail starts hidden", detail2.hidden === true);
check("day 1 aria-expanded starts false", rows[0].getAttribute("aria-expanded") === "false");
check("toggle-all starts as Expand all", toggleAll.textContent.trim() === "Expand all");

// 1. Click chevron/row expands Day 1
rows[0].querySelector(".driver-day-chevron").dispatchEvent(
    new dom.window.MouseEvent("click", { bubbles: true })
);
check("click expands day 1", rows[0].classList.contains("is-open"));
check("day 1 detail becomes visible", detail1.hidden === false);
check("day 1 aria-expanded becomes true", rows[0].getAttribute("aria-expanded") === "true");
check("day 2 remains collapsed", detail2.hidden === true);
check("toggle-all stays Expand all while day 2 is closed", toggleAll.textContent.trim() === "Expand all");

// 2. Clicking bill link or star inside detail does NOT collapse Day 1
const billLink = doc.getElementById("billLink1");
billLink.addEventListener("click", function (e) { e.preventDefault(); });
billLink.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
check("clicking bill link keeps day 1 open", detail1.hidden === false && rows[0].classList.contains("is-open"));

// 3. Starring an entry updates the summary row star indicator dot
const star1 = detail1.querySelector(".row-star-btn");
star1.classList.add("starred");
dom.window.DriverLedger.syncDayStars();
check("starred detail entry lights day 1 star dot", rows[0].querySelector(".driver-day-star-dot").hidden === false);
check("unstarred day 2 star dot remains hidden", rows[1].querySelector(".driver-day-star-dot").hidden === true);

// 4. Second click on Day 1 collapses back to totals
rows[0].dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
check("second click collapses day 1", !rows[0].classList.contains("is-open") && detail1.hidden === true);
check("day 1 aria-expanded returns to false", rows[0].getAttribute("aria-expanded") === "false");
check("starred dot stays visible when collapsed", rows[0].querySelector(".driver-day-star-dot").hidden === false);

// 5. Keyboard Enter & Space toggle Day 2
rows[1].dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
check("Enter key opens day 2", detail2.hidden === false && rows[1].classList.contains("is-open"));

// Clicking Edit or Reverse inside Day 2 detail does NOT collapse Day 2
doc.getElementById("editBtn1").dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
doc.getElementById("voidBtn1").dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
check("Edit/Reverse buttons inside detail keep day 2 open", detail2.hidden === false);

rows[1].dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: " ", bubbles: true }));
check("Space key collapses day 2", detail2.hidden === true && !rows[1].classList.contains("is-open"));

// 6. Expand all / Collapse all button
toggleAll.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
check("Expand all opens both days", detail1.hidden === false && detail2.hidden === false);
check("toggle-all switches label to Collapse all", toggleAll.textContent.trim() === "Collapse all");

toggleAll.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
check("Collapse all closes both days", detail1.hidden === true && detail2.hidden === true);
check("toggle-all switches back to Expand all", toggleAll.textContent.trim() === "Expand all");

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) { process.exit(1); }
