/* =========================================================================
   Delivery Person Ledger — expandable daily summary rows.

   Each calendar day renders as ONE collapsed summary row showing that day's
   total debit, total credit, and running balance.  Clicking the row (or its
   arrow) expands the full chronological entries of that day; collapsing hides
   the detail and leaves only the day's totals.
   ========================================================================= */
(function () {
    "use strict";

    var table = document.getElementById("driverLedgerTable");
    if (!table) { return; }

    var toggleAllBtn = document.getElementById("driverLedgerToggleAll");

    function summaryRows() {
        return Array.prototype.slice.call(table.querySelectorAll(".driver-day-row"));
    }

    function detailOf(row) {
        if (!row) { return null; }
        var targetId = row.getAttribute("data-target");
        return targetId ? document.getElementById(targetId) : null;
    }

    function syncToggleAllBtn() {
        if (!toggleAllBtn) { return; }
        var rows = summaryRows();
        var allOpen = rows.length > 0 && rows.every(function (r) {
            return r.classList.contains("is-open");
        });
        toggleAllBtn.setAttribute("data-expanded", allOpen ? "1" : "0");
        toggleAllBtn.setAttribute("aria-expanded", allOpen ? "true" : "false");
        var icon = toggleAllBtn.querySelector("i");
        var label = toggleAllBtn.querySelector("span");
        if (icon) {
            icon.className = allOpen ? "bi bi-arrows-collapse me-1" : "bi bi-arrows-expand me-1";
        }
        if (label) {
            label.textContent = allOpen ? "Collapse all" : "Expand all";
        }
    }

    function setOpen(row, open) {
        if (!row) { return; }
        var detail = detailOf(row);
        var nextState = Boolean(open);
        row.classList.toggle("is-open", nextState);
        row.setAttribute("aria-expanded", nextState ? "true" : "false");
        if (detail) {
            detail.hidden = !nextState;
        }
        syncToggleAllBtn();
    }

    function toggle(row) {
        if (!row) { return; }
        setOpen(row, !row.classList.contains("is-open"));
    }

    function setAll(open) {
        summaryRows().forEach(function (row) {
            var detail = detailOf(row);
            var nextState = Boolean(open);
            row.classList.toggle("is-open", nextState);
            row.setAttribute("aria-expanded", nextState ? "true" : "false");
            if (detail) {
                detail.hidden = !nextState;
            }
        });
        syncToggleAllBtn();
    }

    function syncDayStars() {
        summaryRows().forEach(function (row) {
            var dot = row.querySelector(".driver-day-star-dot");
            if (!dot) { return; }
            var detail = detailOf(row);
            var hasStar = Boolean(detail && detail.querySelector(".row-star-btn.starred"));
            dot.hidden = !hasStar;
        });
    }

    table.addEventListener("click", function (event) {
        var target = event.target;
        if (!target || !target.closest) { return; }
        if (target.closest(".row-star-btn")) {
            setTimeout(syncDayStars, 0);
            return;
        }
        if (target.closest("a, button, form, input, select, textarea, label")) {
            return;
        }
        var row = target.closest(".driver-day-row");
        if (!row) { return; }
        toggle(row);
    });

    summaryRows().forEach(function (row) {
        row.setAttribute("aria-expanded", row.classList.contains("is-open") ? "true" : "false");
        row.addEventListener("keydown", function (event) {
            if (event.key !== "Enter" && event.key !== " ") { return; }
            if (event.target !== row) { return; }
            event.preventDefault();
            toggle(row);
        });
    });

    if (toggleAllBtn) {
        toggleAllBtn.addEventListener("click", function () {
            var rows = summaryRows();
            var allOpen = rows.length > 0 && rows.every(function (r) {
                return r.classList.contains("is-open");
            });
            setAll(!allOpen);
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        setTimeout(syncDayStars, 0);
    });
    syncToggleAllBtn();
    syncDayStars();

    window.DriverLedger = {
        toggle: toggle,
        setOpen: setOpen,
        setAll: setAll,
        syncDayStars: syncDayStars
    };
})();
