package com.bank.wire.modern;

import java.math.BigDecimal;
import java.time.LocalDate;

/** Result of validation: either a clean, parsed payment or an ISO 20022 reason. */
public sealed interface Outcome permits Outcome.Valid, Outcome.Invalid {

    record Valid(BigDecimal amount, LocalDate valueDate, String chargeBearer) implements Outcome {
    }

    record Invalid(Reason reason) implements Outcome {
    }

    /** ISO 20022 external status reason codes used by this service. */
    enum Reason {
        MISSING_FIELD("FF01", "Mandatory field missing"),
        AMOUNT_INVALID("AM01", "Amount is not numeric or not positive"),
        AMOUNT_LIMIT("AM02", "Amount exceeds the single-payment limit"),
        CURRENCY("AM03", "Currency not supported"),
        CREDITOR_BIC("RC01", "Creditor agent BIC invalid"),
        VALUE_DATE("DT01", "Value date invalid or not allowed"),
        ACCOUNT("AC01", "Account number incorrect");

        private final String code;
        private final String text;

        Reason(String code, String text) {
            this.code = code;
            this.text = text;
        }

        public String code() {
            return code;
        }

        public String text() {
            return text;
        }
    }
}
