/* =========================================================================
   PAY GRN — stock / GRN-expense calculator (static module, DOM-testable).

   The server renders both payables with their authoritative remaining amounts
   in `data-remaining`.  This controller only:

     1. lets "Pay full" fill exactly what is due on ONE payable;
     2. totals what the operator has entered across both boxes;
     3. flags an amount larger than that payable (the server still decides);
     4. refuses an empty submit.

   It never posts anything and never invents a figure: stock and GRN expenses
   stay separate payables (owner rule A3).
   ========================================================================= */
(function () {
    "use strict";

    var state = null;

    function number(value) {
        var parsed = parseFloat(String(value == null ? "" : value).replace(/,/g, ""));
        return isFinite(parsed) ? parsed : 0;
    }

    function money(value) {
        return "Rs. " + number(value).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    function blocks(form) {
        return Array.prototype.slice.call(form.querySelectorAll("[data-pay-block]"));
    }

    function inputsOf(form) {
        return Array.prototype.slice.call(form.querySelectorAll('input[name="pay_amount[]"]'));
    }

    function remainingOf(block) {
        return block ? number(block.getAttribute("data-remaining")) : 0;
    }

    function refresh() {
        if (!state) return null;
        var entered = 0;
        var overpayment = 0;
        inputsOf(state.form).forEach(function (input) {
            var block = input.closest ? input.closest("[data-pay-block]") : null;
            var remaining = remainingOf(block);
            var value = number(input.value);
            var over = value - remaining;
            entered += value;
            if (over > 0.004) {
                overpayment += over;
            }
            input.classList.toggle("is-invalid", over > 0.004);
            input.setAttribute("title", over > 0.004
                ? "More than the " + money(remaining) + " due for this payable"
                : "");
        });
        if (state.total) state.total.textContent = money(entered);
        state.entered = entered;
        state.overpayment = overpayment;
        var submit = state.form.querySelector("#payGrnSubmit");
        if (submit) submit.disabled = state.readonly || entered <= 0;
        return { entered: entered, overpayment: overpayment };
    }

    function payFull(inputId) {
        if (!state || !inputId) return false;
        var input = state.form.querySelector("#" + inputId)
            || document.getElementById(inputId);
        if (!input) return false;
        var block = input.closest ? input.closest("[data-pay-block]") : null;
        var remaining = remainingOf(block);
        if (remaining <= 0.004 || input.disabled) return false;
        input.value = remaining.toFixed(2);
        refresh();
        return true;
    }

    function submitGuard(event) {
        if (!state) return true;
        var result = refresh();
        if (!result || result.entered <= 0) {
            event.preventDefault();
            if (state.status) {
                state.status.textContent = "Enter the stock amount, the GRN expenses amount, or both.";
                state.status.classList.remove("d-none");
            }
            return false;
        }
        if (result.overpayment > 0.004) {
            event.preventDefault();
            if (state.status) {
                state.status.textContent = "One of the amounts is more than that payable is due. "
                    + "Reduce it — stock and GRN expenses are paid separately.";
                state.status.classList.remove("d-none");
            }
            return false;
        }
        return true;
    }

    function init(root) {
        var scope = root || document;
        var form = scope.id === "payGrnForm"
            ? scope
            : (scope.querySelector ? scope.querySelector("#payGrnForm") : null);
        if (!form) return false;
        if (state && state.form === form) return state;

        state = {
            form: form,
            total: form.querySelector("#payGrnEntered"),
            status: form.querySelector("#payGrnStatus"),
            entered: 0,
            overpayment: 0,
            readonly: false
        };
        var submit = form.querySelector("#payGrnSubmit");
        var canEdit = (submit && submit.getAttribute("data-can-edit"))
            || form.getAttribute("data-can-edit") || "1";
        // Server-side permission is authoritative; the calculator must never
        // re-enable a submit button that the server disabled.
        state.readonly = canEdit === "0";

        form.addEventListener("input", refresh);
        form.addEventListener("change", refresh);
        Array.prototype.forEach.call(form.querySelectorAll("[data-pay-full]"), function (button) {
            button.addEventListener("click", function () {
                payFull(button.getAttribute("data-pay-full"));
            });
        });
        form.addEventListener("submit", submitGuard);
        refresh();
        return state;
    }

    window.FBMPayGrn = {
        init: init,
        refresh: refresh,
        payFull: payFull,
        formatMoney: money,
        getState: function () { return state; }
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { init(document); });
    } else {
        init(document);
    }
})();
