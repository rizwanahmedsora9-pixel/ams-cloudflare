/* =========================================================================
   Delivery Rent — expandable delivery-person summary.

   Owner rule: the screen shows ONE line per delivery person (rent earned, paid,
   remaining) and the trips sit behind an arrow.  A hundred rows a day is not a
   report, it is noise.

   Pinned behaviour:

     * the summary row is the only thing that toggles; pressing Pay / Ledger /
       Delete inside the action cell never expands the row;
     * the detail is rendered inline for a small period and fetched once from
       ``/delivery_rents/group/<key>`` for a busy one — after that it is cached
       in the DOM, so re-opening is instant and fires no request;
     * a failed fetch says so and offers a retry instead of showing an empty
       list (an empty list would read as "this driver owes nothing");
     * forms that arrive after the first paint still get the session CSRF
       token, and the account list still follows the payment method;
     * every money value comes from the server; this file never computes a
       balance, it only fills in the amount the operator is about to settle.

   All configuration arrives through data attributes on ``#rentGroupTable``.
   ========================================================================= */
(function () {
    "use strict";

    var table = document.getElementById("rentGroupTable");
    if (!table) { return; }

    var config = table.dataset || {};
    var csrfToken = config.csrfToken || "";
    var baseUrl = config.baseUrl || "/delivery_rents";
    var currency = config.currency || "";

    var entryForm = document.getElementById("rentEntryPayForm");
    var entryModalEl = document.getElementById("rentEntryPayModal");
    var driverForm = document.getElementById("rentDriverPayForm");
    var driverModalEl = document.getElementById("rentDriverPayModal");

    function modal(el) {
        if (!el || typeof window.bootstrap === "undefined" || !window.bootstrap.Modal) { return null; }
        return window.bootstrap.Modal.getOrCreateInstance(el);
    }

    function formatMoney(value) {
        var n = Number(value) || 0;
        return currency + n.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    function text(id, value) {
        var el = document.getElementById(id);
        if (el) { el.textContent = value === undefined || value === null ? "—" : value; }
    }

    function setPaidInput(form, due) {
        if (!form) { return; }
        var input = form.querySelector('input[name="paid_amount"]');
        if (input) { input.value = due > 0 ? due.toFixed(2) : "0"; }
    }

    /* ---- detail loading ------------------------------------------------ */
    function detailOf(row) {
        return document.getElementById(row.getAttribute("data-target"));
    }

    function detailBody(detail) {
        if (!detail) { return null; }
        var cell = detail.querySelector("td");
        return cell ? cell.querySelector(".rent-detail-wrap") : null;
    }

    function setOpen(row, detail, open) {
        row.classList.toggle("is-open", open);
        row.setAttribute("aria-expanded", open ? "true" : "false");
        if (detail) { detail.hidden = !open; }
    }

    function groupUrl(key) {
        return baseUrl + "/group/" + encodeURIComponent(key);
    }

    function loadDetail(row, detail) {
        var wrap = detailBody(detail);
        if (!wrap || row.getAttribute("data-loaded") === "1" || row.getAttribute("data-loading") === "1") {
            return;
        }
        row.setAttribute("data-loading", "1");
        wrap.innerHTML = '<div class="rent-detail-loading">' +
            '<span class="spinner-border spinner-border-sm me-2"></span>Loading trips…</div>';

        window.fetch(groupUrl(row.getAttribute("data-group-key")) + window.location.search, {
            credentials: "same-origin",
            headers: { "Accept": "application/json" }
        }).then(function (response) {
            if (!response.ok) { throw new Error("HTTP " + response.status); }
            return response.json();
        }).then(function (data) {
            if (!data || !data.ok || typeof data.html !== "string") { throw new Error("bad payload"); }
            wrap.innerHTML = data.html;
            row.setAttribute("data-loaded", "1");
            row.removeAttribute("data-loading");
            bindDynamic(wrap);
        }).catch(function () {
            row.removeAttribute("data-loading");
            wrap.innerHTML = '<div class="rent-detail-empty text-warning">' +
                '<i class="bi bi-exclamation-triangle me-1"></i>Could not load the trips. ' +
                '<a href="#" class="rent-bill-link rent-retry">Try again</a></div>';
            var retry = wrap.querySelector(".rent-retry");
            if (retry) {
                retry.addEventListener("click", function (event) {
                    event.preventDefault();
                    row.setAttribute("data-loaded", "0");
                    loadDetail(row, detail);
                });
            }
        });
    }

    function toggle(row) {
        var detail = detailOf(row);
        if (!detail) { return; }
        var open = !row.classList.contains("is-open");
        if (open) { loadDetail(row, detail); }
        setOpen(row, detail, open);
    }

    /* ---- forms that arrive later --------------------------------------- */
    function syncMethod(method) {
        var form = method.closest ? method.closest("form") : null;
        var account = form ? form.querySelector(".rent-account") : null;
        if (!account) { return; }
        var want = method.value === "Cash" ? "cash" : "bank";
        Array.prototype.forEach.call(account.options, function (opt) {
            if (!opt.value) { return; }
            var ok = opt.dataset.category === want;
            opt.hidden = !ok;
            opt.disabled = !ok;
        });
        var selected = account.selectedOptions[0];
        if (selected && selected.value && selected.disabled) { account.value = ""; }
    }

    function addCsrf(form) {
        if (!csrfToken) { return; }
        var method = (form.getAttribute("method") || "GET").toUpperCase();
        if (["POST", "PUT", "PATCH", "DELETE"].indexOf(method) === -1) { return; }
        if (form.querySelector('input[name="_csrf_token"]')) { return; }
        var input = document.createElement("input");
        input.type = "hidden";
        input.name = "_csrf_token";
        input.value = csrfToken;
        form.appendChild(input);
    }

    function bindDynamic(scope) {
        if (!scope || !scope.querySelectorAll) { return; }
        Array.prototype.forEach.call(scope.querySelectorAll("form"), addCsrf);
        Array.prototype.forEach.call(scope.querySelectorAll(".rent-method"), function (method) {
            method.addEventListener("change", function () { syncMethod(method); });
            syncMethod(method);
        });
        Array.prototype.forEach.call(scope.querySelectorAll(".rent-pay-entry"), function (button) {
            button.addEventListener("click", function (event) {
                event.stopPropagation();
                openEntryPay(button);
            });
        });
    }

    /* ---- settle one trip ----------------------------------------------- */
    function openEntryPay(button) {
        var instance = modal(entryModalEl);
        if (!entryForm || !instance) { return; }
        var due = parseFloat(button.getAttribute("data-due") || "0") || 0;
        entryForm.action = baseUrl + "/pay/" + encodeURIComponent(button.getAttribute("data-entry-id"));
        text("rentEntryPayPerson", button.getAttribute("data-person"));
        text("rentEntryPayBill", button.getAttribute("data-bill"));
        text("rentEntryPayDue", formatMoney(due));
        setPaidInput(entryForm, due);
        instance.show();
    }

    /* ---- settle a whole delivery person -------------------------------- */
    function openDriverPay(button) {
        var instance = modal(driverModalEl);
        if (!driverForm || !instance) { return; }
        var due = parseFloat(button.getAttribute("data-due") || "0") || 0;
        var trips = button.getAttribute("data-trips") || "0";
        driverForm.action = baseUrl + "/pay_driver/" + encodeURIComponent(button.getAttribute("data-person-id"));
        text("rentDriverPayPerson", button.getAttribute("data-person"));
        text("rentDriverPayDue", formatMoney(due));
        text("rentDriverPayTrips", trips);
        text("rentDriverPayTripPlural", trips === "1" ? "" : "s");
        setPaidInput(driverForm, due);
        instance.show();
    }

    /* ---- wiring -------------------------------------------------------- */
    table.addEventListener("click", function (event) {
        var target = event.target;
        var payDriver = target.closest ? target.closest(".rent-pay-driver") : null;
        if (payDriver) {
            event.stopPropagation();
            openDriverPay(payDriver);
            return;
        }
        var row = target.closest ? target.closest(".rent-group-row") : null;
        if (!row) { return; }
        if (target.closest("a, button, form, input, select, label")) { return; }
        toggle(row);
    });

    table.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") { return; }
        var row = event.target.closest ? event.target.closest(".rent-group-row") : null;
        if (!row || event.target !== row) { return; }
        event.preventDefault();
        toggle(row);
    });

    // Keyboard users get the same affordance as a click.
    Array.prototype.forEach.call(table.querySelectorAll(".rent-group-row"), function (row) {
        row.setAttribute("aria-expanded", "false");
        row.addEventListener("keydown", function (event) {
            if (event.key !== "Enter" && event.key !== " " ) { return; }
            event.preventDefault();
            toggle(row);
        });
    });

    document.querySelectorAll(".rent-method").forEach(function (method) {
        method.addEventListener("change", function () { syncMethod(method); });
        syncMethod(method);
    });

    document.querySelectorAll("form").forEach(function (form) {
        form.addEventListener("submit", function () {
            var button = form.querySelector('button[type="submit"]');
            if (button) { setTimeout(function () { button.disabled = true; }, 0); }
        });
    });

    bindDynamic(table);

    window.DeliveryRents = {
        toggle: toggle,
        formatMoney: formatMoney,
        syncMethod: syncMethod
    };
})();
