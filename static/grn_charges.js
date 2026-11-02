/* =========================================================================
   GRN charge grid — operator-driven, never pre-filled.

   Owner rule: a charge line exists ONLY because the operator pressed
   "Add charge" (or because it is already saved on the GRN being edited).
   The screen must never invent Vehicle Fare / Loading / Unloading / Other
   rows on its own.  So:

     * the server renders zero rows for a new GRN;
     * "Add charge" clones the inert <template id="grnChargeRowTemplate">,
       never a visible row, so a new line starts blank;
     * every row is removable, including the last one — an empty grid is a
       valid GRN whose cost is the supplier material only;
     * an empty grid still posts ``charge_grid_present`` so the server can
       tell "no charges" from "this form has no charge grid".

   This module owns the rows only.  All money arithmetic still comes from
   app/services/grn_costing.py on the server; the live figure here is a
   preview built from the same rule (INVENTORY charges, minus the ones
   declared Not Applicable) and is replaced by the server's numbers on save.
   ========================================================================= */
(function () {
    "use strict";

    var TABLE_SELECTOR = "#grnChargesTable";
    var ROW_SELECTOR = "tr.grn-charge-row";
    var BODY_ID = "grnChargesBody";
    var TEMPLATE_ID = "grnChargeRowTemplate";
    var WRAP_ID = "grnChargesWrap";
    var EMPTY_ID = "grnChargesEmpty";
    var ADD_BTN_ID = "addGrnChargeBtn";

    /* Mirrors DEFAULT_RECIPIENT_BY_CHARGE in app/services/grn_costing.py. */
    var RECIPIENT_BY_CHARGE = {
        VEHICLE_FARE: "TRANSPORTER",
        TRANSPORT: "TRANSPORTER",
        LOADING: "LABOUR",
        UNLOADING: "LABOUR",
        OTHER: "OTHER"
    };

    var onChange = null;
    var notifyEnabled = true;

    function byId(id) {
        return document.getElementById(id);
    }

    function body() {
        return byId(BODY_ID) || document.querySelector(TABLE_SELECTOR + " tbody");
    }

    function rows() {
        var host = body();
        if (!host) return [];
        return Array.prototype.slice.call(host.querySelectorAll(ROW_SELECTOR));
    }

    function rowCount() {
        return rows().length;
    }

    function field(row, name) {
        return row.querySelector('[name="' + name + '"]');
    }

    function valueOf(row, name) {
        var el = field(row, name);
        return el ? String(el.value === undefined || el.value === null ? "" : el.value).trim() : "";
    }

    function recipientForCharge(chargeType) {
        return RECIPIENT_BY_CHARGE[chargeType] || "OTHER";
    }

    function num(value) {
        var parsed = parseFloat(String(value === undefined || value === null ? "" : value).replace(/,/g, ""));
        return isFinite(parsed) ? parsed : 0;
    }

    function notify() {
        if (notifyEnabled && typeof onChange === "function") onChange();
    }

    /* The table is on screen only while it has rows.  With no charges the
       operator reads one sentence instead of staring at an empty grid. */
    function syncVisibility() {
        var hasRows = rowCount() > 0;
        var wrap = byId(WRAP_ID);
        var empty = byId(EMPTY_ID);
        if (wrap) wrap.hidden = !hasRows;
        if (empty) empty.hidden = hasRows;
        return hasRows;
    }

    /* Capitalised preview: material-cost charges only, and a charge declared
       Not Applicable never contributes.  Paid/unpaid never changes the cost. */
    function capitalisedTotal() {
        var total = 0;
        rows().forEach(function (row) {
            var amount = num(valueOf(row, "charge_amount[]"));
            if (!amount) return;
            var treatment = valueOf(row, "charge_treatment[]") || "INVENTORY";
            var status = valueOf(row, "charge_status[]");
            if (treatment === "INVENTORY" && status !== "NOT_APPLICABLE") total += amount;
        });
        return total;
    }

    function bindRow(row) {
        Array.prototype.forEach.call(row.querySelectorAll("input, select"), function (el) {
            if (el.dataset.grnChargeBound) return;
            el.dataset.grnChargeBound = "1";
            el.addEventListener("input", notify);
            el.addEventListener("change", notify);
        });

        /* Choosing the charge fills the matching recipient type on that same
           row, unless the operator already picked one.  It fills a field on a
           row the operator added; it never adds a row. */
        var typeSel = field(row, "charge_type[]");
        var recSel = field(row, "charge_recipient_type[]");
        if (recSel && !recSel.dataset.grnChargeRecipientBound) {
            recSel.dataset.grnChargeRecipientBound = "1";
            if (recSel.value) recSel.dataset.grnChargeRecipientChosen = "1";
            recSel.addEventListener("change", function () {
                recSel.dataset.grnChargeRecipientChosen = "1";
            });
        }
        if (typeSel && recSel && !typeSel.dataset.grnChargeRecipientBound) {
            typeSel.dataset.grnChargeRecipientBound = "1";
            typeSel.addEventListener("change", function () {
                if (recSel.dataset.grnChargeRecipientChosen) return;
                recSel.value = recipientForCharge(typeSel.value);
            });
        }

        var remove = row.querySelector(".grn-charge-remove");
        if (remove && !remove.dataset.grnChargeBound) {
            remove.dataset.grnChargeBound = "1";
            remove.addEventListener("click", function () {
                removeRow(row);
            });
        }
    }

    function bindRows() {
        rows().forEach(bindRow);
    }

    function addRow() {
        var host = body();
        var blueprint = byId(TEMPLATE_ID);
        if (!host || !blueprint || !blueprint.content) return null;
        var source = blueprint.content.querySelector(ROW_SELECTOR);
        if (!source) return null;
        var clone = source.cloneNode(true);
        /* The blueprint is inert, but be explicit: a newly added line carries
           no stored id and no values from any other charge. */
        Array.prototype.forEach.call(clone.querySelectorAll("input"), function (el) {
            if (el.type !== "checkbox" && el.type !== "radio") el.value = el.defaultValue || "";
            el.removeAttribute("data-grn-charge-bound");
        });
        var idField = field(clone, "charge_id[]");
        if (idField) idField.value = "";
        Array.prototype.forEach.call(clone.querySelectorAll("select"), function (sel) {
            sel.removeAttribute("data-grn-charge-bound");
            sel.removeAttribute("data-grn-charge-recipient-bound");
            sel.removeAttribute("data-grn-charge-recipient-chosen");
        });
        var removeBtn = clone.querySelector(".grn-charge-remove");
        if (removeBtn) removeBtn.removeAttribute("data-grn-charge-bound");
        host.appendChild(clone);
        bindRow(clone);
        syncVisibility();
        notify();
        var first = field(clone, "charge_type[]");
        if (first && typeof first.focus === "function") first.focus();
        return clone;
    }

    function removeRow(row) {
        if (!row) return false;
        row.remove();
        syncVisibility();
        notify();
        return true;
    }

    function isBlank(row) {
        return !valueOf(row, "charge_type[]")
            && !valueOf(row, "charge_label[]")
            && !valueOf(row, "charge_recipient[]")
            && !valueOf(row, "charge_amount[]");
    }

    /* Runs on save.  Untouched blank rows are dropped instead of stored; a row
       that means something must say which charge it is and what it costs.
       ``alertFn`` is injectable so the DOM test can assert the refusals. */
    function validate(alertFn) {
        var warn = typeof alertFn === "function" ? alertFn : function (message) { window.alert(message); };
        var dropped = 0;
        rows().forEach(function (row) {
            if (isBlank(row) && !valueOf(row, "charge_id[]")) {
                row.remove();
                dropped += 1;
            }
        });
        if (dropped) syncVisibility();

        var live = rows();
        for (var i = 0; i < live.length; i += 1) {
            var row = live[i];
            var id = valueOf(row, "charge_id[]");
            var type = valueOf(row, "charge_type[]");
            var amountRaw = valueOf(row, "charge_amount[]");
            var status = valueOf(row, "charge_status[]");
            if (!type) {
                warn("Charge row " + (i + 1) + ": select the charge (Vehicle Fare, Transportation, Loading, Unloading, Other Expenses), or remove the row.");
                var sel = field(row, "charge_type[]");
                if (sel) sel.focus();
                return false;
            }
            if (!amountRaw || num(amountRaw) <= 0) {
                /* A stored charge may legitimately be zeroed / marked Not
                   Applicable; a brand-new row may not be saved costless. */
                if (status !== "NOT_APPLICABLE" && !id) {
                    warn("Charge row " + (i + 1) + ": enter the amount, or remove the row.");
                    var amt = field(row, "charge_amount[]");
                    if (amt) amt.focus();
                    return false;
                }
            }
            var recSel = field(row, "charge_recipient_type[]");
            if (recSel && !recSel.value) recSel.value = recipientForCharge(type);
        }
        syncVisibility();
        notify();
        return true;
    }

    function init(options) {
        options = options || {};
        if (typeof options.onChange === "function") onChange = options.onChange;
        var host = body();
        if (!host) return false;
        bindRows();
        var addBtn = byId(ADD_BTN_ID);
        if (addBtn && !addBtn.dataset.grnChargeBound) {
            addBtn.dataset.grnChargeBound = "1";
            addBtn.addEventListener("click", function () { addRow(); });
        }
        syncVisibility();
        return true;
    }

    window.FBMGrnCharges = {
        init: init,
        addRow: addRow,
        removeRow: removeRow,
        bindRows: bindRows,
        rows: rows,
        rowCount: rowCount,
        capitalisedTotal: capitalisedTotal,
        recipientForCharge: recipientForCharge,
        syncVisibility: syncVisibility,
        validate: validate
    };
})();
