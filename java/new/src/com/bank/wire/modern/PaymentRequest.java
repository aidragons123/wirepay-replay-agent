package com.bank.wire.modern;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.Map;

/** Immutable inbound request (Java 16+ record). */
public record PaymentRequest(
        String requestId,
        String debtorName,
        String debtorAccount,
        String creditorName,
        String creditorAccount,
        String creditorBic,
        String amount,
        String currency,
        String valueDate,
        String chargeBearer,
        String remittanceInfo,
        LocalDate processingDate) {

    public static PaymentRequest from(Map<String, String> m) {
        return new PaymentRequest(
                t(m.get("requestId")),
                t(m.get("debtorName")),
                t(m.get("debtorAccount")),
                t(m.get("creditorName")),
                t(m.get("creditorAccount")),
                t(m.get("creditorBic")),
                t(m.get("amount")),
                t(m.get("currency")),
                t(m.get("valueDate")),
                t(m.get("chargeBearer")),
                t(m.get("remittanceInfo")),
                date(m.get("processingDate")));
    }

    public boolean hasAllMandatory() {
        return !(requestId.isEmpty() || debtorName.isEmpty() || debtorAccount.isEmpty()
                || creditorName.isEmpty() || creditorAccount.isEmpty() || creditorBic.isEmpty()
                || amount.isEmpty() || currency.isEmpty() || valueDate.isEmpty());
    }

    private static String t(String s) {
        return s == null ? "" : s.trim();
    }

    private static LocalDate date(String s) {
        try {
            return (s == null || s.isBlank()) ? LocalDate.now() : LocalDate.parse(s.trim());
        } catch (DateTimeParseException e) {
            return LocalDate.now();
        }
    }
}
