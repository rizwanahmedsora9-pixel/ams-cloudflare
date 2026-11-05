/* =========================================================================
   Pay GRN Expenses — per-expense payment calculator ("one amount each").

   GRN expenses have their own payment system: every vehicle fare / loading /
   unloading / other expense the operator entered on the GRN gets its own money
   field.  This controller only:

     1. lets "Pay full" fill exactly what that ONE expense still owes;
     2. totals what the operator has entered across the expense boxes;
     3. flags an amount larger than that expense still owes;
     4. refuses an empty submit.

   It never posts anything, never invents a figure, and never touches the
   supplier bill: that is a separate payment system rendered by the same page
   in its own mode (the supplier amount field is not even on screen while the
   expenses section is open).
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

    function boxes(form) {
        return Array.prototype.slice.call(form.querySelectorAll("[data-expense-box]"));
    }

    function inputsOf(form) {
        return Array.prototype.slice.call(form.querySelectorAll('input[name="expense_amount[]"]'));
    }

    function remainingOf(box) {
        return box ? number(box.getAttribute("data-remaining")) : 0;
    }

    function refresh() {
        if (!state) return null;
        var entered = 0;
        var overpayment = 0;
        var filled = 0;
        inputsOf(state.form).forEach(function (input) {
            var box = input.closest ? input.closest("[data-expense-box]") : null;
            var remaining = remainingOf(box);
            var value = number(input.value);
            if (input.disabled) {
                value = 0;
            }
            entered += value;
            if (value > 0) filled += 1;
            var over = value - remaining;
            if (over > 0.004) {
                overpayment += over;
            }
            input.classList.toggle("is-invalid", over > 0.004);
            input.setAttribute("title", over > 0.004
                ? "More than the " + money(remaining) + " this expense still owes"
                : "");
        });
        if (state.total) state.total.textContent = money(entered);
        state.entered = entered;
        state.filled = filled;
        state.overpayment = overpayment;
        var submit = state.form.querySelector("#grnExpenseSubmit");
        if (submit) submit.disabled = state.readonly || entered <= 0;
        if (state.status && entered <= 0) {
            state.status.classList.add("d-none");
        }
        return { entered: entered, overpayment: overpayment, filled: filled };
    }

    function payFull(inputId) {
        if (!state || !inputId) return false;
        var input = state.form.querySelector("#" + inputId)
            || document.getElementById(inputId);
        if (!input) return false;
        var box = input.closest ? input.closest("[data-expense-box]") : null;
        var remaining = remainingOf(box);
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
                state.status.textContent = "Enter the amount next to at least one GRN expense.";
                state.status.classList.remove("d-none");
            }
            return false;
        }
        if (result.overpayment > 0.004) {
            event.preventDefault();
            if (state.status) {
                state.status.textContent = "One amount is more than that expense still owes. "
                    + "Each expense is paid on its own — reduce it or use Pay full.";
                state.status.classList.remove("d-none");
            }
            return false;
        }
        return true;
    }

    function init(root) {
        var scope = root || document;
        var form = scope.id === "grnExpenseForm"
            ? scope
            : (scope.querySelector ? scope.querySelector("#grnExpenseForm") : null);
        if (!form) return false;
        if (state && state.form === form) return state;

        state = {
            form: form,
            total: form.querySelector("#grnExpenseEntered"),
            status: form.querySelector("#grnExpenseStatus"),
            entered: 0,
            filled: 0,
            overpayment: 0,
            readonly: false
        };
        var submit = form.querySelector("#grnExpenseSubmit");
        var canEdit = (submit && submit.getAttribute("data-can-edit"))
            || form.getAttribute("data-can-edit") || "1";
        // The server decides permissions; never re-enable a disabled button.
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

    window.FBMGrnExpensePayments = {
        init: init,
        refresh: refresh,
        payFull: payFull,
        formatMoney: money,
        boxes: function () { return state ? boxes(state.form) : []; },
        getState: function () { return state; }
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { init(document); });
    } else {
        init(document);
    }
})();
