/* =========================================================================
   GRN payment calculator.

   The server renders the authoritative GRN obligations.  This controller only
   gives the operator immediate feedback while entering a payment:

     amount payable -> amount entered -> remaining GRN balance

   It never posts a payment or replaces the server-side validation.  The
   selected obligation carries its server-calculated values in data attributes
   so the browser cannot accidentally use the landed cost or a rounded label
   as a different payable figure.
   ========================================================================= */
(function () {
    "use strict";

    var state = null;
    var TONES = ["text-success", "text-warning", "text-danger", "text-muted", "text-info"];

    function number(value) {
        var parsed = parseFloat(String(value == null ? "" : value).replace(/,/g, ""));
        return isFinite(parsed) ? parsed : 0;
    }

    function money(value) {
        var amount = number(value);
        return "Rs. " + amount.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    function text(element, value) {
        if (element) element.textContent = value;
    }

    function tone(element, className) {
        if (!element) return;
        TONES.forEach(function (name) { element.classList.remove(name); });
        if (className) element.classList.add(className);
    }

    function attribute(element, name, fallback) {
        if (!element) return fallback;
        var value = element.getAttribute(name);
        return value === null || value === "" ? fallback : value;
    }

    function selectedOption() {
        if (!state || !state.obligation) return null;
        var index = state.obligation.selectedIndex;
        return index >= 0 ? state.obligation.options[index] : null;
    }

    function obligationValues() {
        var option = selectedOption();
        if (!option || !option.value) {
            return { option: null, original: 0, paid: 0, payable: 0, label: "" };
        }
        return {
            option: option,
            original: number(attribute(option, "data-original", 0)),
            paid: number(attribute(option, "data-paid", 0)),
            // `data-remaining` is generated from the same breakdown used by
            // the payment service.  `data-payable` is accepted for old cached
            // markup while deployments are rolling forward.
            payable: number(attribute(option, "data-remaining",
                attribute(option, "data-payable", 0))),
            label: attribute(option, "data-label", option.textContent || "")
        };
    }

    function accountBalance() {
        if (!state || !state.account) return null;
        var option = state.account.options[state.account.selectedIndex];
        if (!option || !option.value) return null;
        var raw = attribute(option, "data-balance", null);
        return raw === null ? null : number(raw);
    }

    function setStatus(message, className) {
        if (!state) return;
        text(state.status, message);
        tone(state.status, className || "text-muted");
        if (state.status) state.status.classList.toggle("d-none", !message);
    }

    function refresh() {
        if (!state) return null;

        var values = obligationValues();
        var enteredRaw = state.amount ? state.amount.value : "";
        var entered = number(enteredRaw);
        var hasAmount = String(enteredRaw || "").trim() !== "";
        var remaining = Math.max(0, values.payable - entered);
        var totalPayable = number(attribute(state.form, "data-total-remaining", 0));
        var totalRemaining = Math.max(0, totalPayable - entered);
        var overpayment = Math.max(0, entered - values.payable);
        var allowAdvance = !!(state.advance && state.advance.checked);

        text(state.payable, values.option ? money(values.payable) : "—");
        text(state.alreadyPaid, values.option ? money(values.paid) : "—");
        text(state.totalPayable, money(totalPayable));
        text(state.totalRemaining, money(totalRemaining));
        text(state.entered, hasAmount ? money(entered) : money(0));
        text(state.remaining, values.option ? money(remaining) : "—");
        tone(state.totalPayable, "text-warning");
        tone(state.totalRemaining, totalRemaining <= 0.005 ? "text-success" : "text-warning");
        text(state.overpayment, overpayment > 0 ? money(overpayment) : money(0));

        tone(state.payable, values.option ? "text-warning" : "text-muted");
        tone(state.alreadyPaid, values.option ? "text-info" : "text-muted");
        tone(state.entered, entered > 0 ? "text-info" : "text-muted");
        tone(state.remaining, !values.option ? "text-muted" : (remaining <= 0.005 ? "text-success" : "text-warning"));
        tone(state.overpayment, overpayment > 0 ? "text-danger" : "text-muted");

        if (state.overpaymentRow) {
            state.overpaymentRow.classList.toggle("d-none", overpayment <= 0);
        }

        if (!values.option) {
            setStatus("Select a GRN payment recipient to see the amount payable.", "text-muted");
        } else if (!hasAmount || entered <= 0) {
            if (values.payable <= 0.005) {
                setStatus("This obligation is already fully paid.", "text-success");
            } else {
                setStatus("Enter an amount. Remaining balance is " + money(values.payable) + ".", "text-muted");
            }
        } else if (overpayment > 0 && !allowAdvance) {
            setStatus("Entered amount is " + money(overpayment) + " above the payable. Reduce it or allow an advance.", "text-danger");
        } else if (overpayment > 0 && allowAdvance) {
            setStatus("The GRN balance will be zero. " + money(overpayment) + " will be recorded as an advance.", "text-warning");
        } else if (remaining <= 0.005) {
            setStatus("This payment will settle the selected obligation in full.", "text-success");
        } else {
            setStatus("Remaining balance after this payment: " + money(remaining) + ".", "text-warning");
        }

        var balance = accountBalance();
        if (balance === null) {
            text(state.accountAfter, "—");
            tone(state.accountAfter, "text-muted");
            setStatusAccount("");
        } else {
            var afterAccount = balance - entered;
            text(state.accountAfter, money(afterAccount));
            tone(state.accountAfter, afterAccount < -0.005 ? "text-danger" : "text-success");
            setStatusAccount(afterAccount < -0.005
                ? "Payment is greater than the selected account balance."
                : "Account balance after payment: " + money(afterAccount) + ".");
        }

        if (state.form) {
            state.form.dataset.amountPayable = values.payable.toFixed(2);
            state.form.dataset.amountEntered = entered.toFixed(2);
            state.form.dataset.remainingBalance = remaining.toFixed(2);
            state.form.dataset.overpayment = overpayment.toFixed(2);
        }

        return {
            original: values.original,
            paid: values.paid,
            payable: values.payable,
            totalPayable: totalPayable,
            totalRemaining: totalRemaining,
            entered: entered,
            remaining: remaining,
            overpayment: overpayment,
            allowAdvance: allowAdvance,
            accountBalance: balance,
            accountAfter: balance === null ? null : balance - entered
        };
    }

    function setStatusAccount(message) {
        if (!state || !state.accountStatus) return;
        text(state.accountStatus, message);
        state.accountStatus.classList.toggle("d-none", !message);
        tone(state.accountStatus, message.indexOf("greater") !== -1 ? "text-danger" : "text-muted");
    }

    function dispatchInput(element) {
        if (!element) return;
        var event;
        try {
            event = new Event("input", { bubbles: true });
        } catch (_) {
            event = document.createEvent("Event");
            event.initEvent("input", true, true);
        }
        element.dispatchEvent(event);
    }

    function payRemaining() {
        if (!state || !state.amount) return false;
        var values = obligationValues();
        if (!values.option) return false;
        state.amount.value = values.payable > 0 ? values.payable.toFixed(2) : "0.00";
        dispatchInput(state.amount);
        state.amount.focus();
        return true;
    }

    function submitGuard(event) {
        if (!state) return true;
        var values = obligationValues();
        var entered = number(state.amount ? state.amount.value : 0);
        var overpayment = Math.max(0, entered - values.payable);

        if (!values.option) {
            event.preventDefault();
            setStatus("Select a GRN payment recipient before saving.", "text-danger");
            if (state.obligation) state.obligation.focus();
            return false;
        }
        if (!(entered > 0)) {
            event.preventDefault();
            setStatus("Enter a payment amount greater than zero.", "text-danger");
            if (state.amount) state.amount.focus();
            return false;
        }
        if (overpayment > 0 && !(state.advance && state.advance.checked)) {
            event.preventDefault();
            setStatus("Reduce the payment or tick Allow overpayment as advance.", "text-danger");
            if (state.amount) state.amount.focus();
            return false;
        }
        return true;
    }

    function init(root) {
        var scope = root || document;
        var form = scope.id === "grnPaymentForm"
            ? scope
            : scope.querySelector
                ? scope.querySelector("#grnPaymentForm")
                : document.getElementById("grnPaymentForm");
        if (!form) return false;
        if (state && state.form === form) return state;

        state = {
            form: form,
            obligation: form.querySelector("#grnObligationSelect"),
            amount: form.querySelector("#grnPaymentAmount"),
            advance: form.querySelector("#grnAllowAdvance"),
            account: form.querySelector("#grnPaymentAccount"),
            payable: form.querySelector("#grnPaymentPayable"),
            alreadyPaid: form.querySelector("#grnPaymentAlreadyPaid"),
            totalPayable: form.querySelector("#grnTotalPayable"),
            totalRemaining: form.querySelector("#grnTotalRemaining"),
            entered: form.querySelector("#grnPaymentEntered"),
            remaining: form.querySelector("#grnPaymentRemaining"),
            overpayment: form.querySelector("#grnPaymentOverpayment"),
            overpaymentRow: form.querySelector("#grnPaymentOverpaymentRow"),
            status: form.querySelector("#grnPaymentStatus"),
            accountAfter: form.querySelector("#grnAccountBalanceAfter"),
            accountStatus: form.querySelector("#grnAccountStatus"),
            payRemainingButton: form.querySelector("#grnPayRemaining")
        };

        if (state.obligation) state.obligation.addEventListener("change", refresh);
        if (state.amount) {
            state.amount.addEventListener("input", refresh);
            state.amount.addEventListener("change", refresh);
        }
        if (state.advance) state.advance.addEventListener("change", refresh);
        if (state.account) state.account.addEventListener("change", refresh);
        if (state.payRemainingButton) state.payRemainingButton.addEventListener("click", payRemaining);
        form.addEventListener("submit", submitGuard);
        refresh();
        return state;
    }

    window.FBMGrnPayments = {
        init: init,
        refresh: refresh,
        payRemaining: payRemaining,
        formatMoney: money,
        getState: function () { return state; }
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { init(document); });
    } else {
        init(document);
    }
})();
