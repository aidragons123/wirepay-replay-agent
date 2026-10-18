package com.bank.wire.modern;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * STAND-IN for the new (Java 18) wire payment service: explicit workflow,
 * ISO 20022 pacs.008 output, plus three new features
 * (IBAN checksum, TARGET2 holiday-aware settlement, UETR).
 *
 * Two deliberate parity gaps are planted so the agents have something real
 * to find. They are marked PARITY-GAP-n and switched off by the JVM flag
 * -Dwirepay.parityFix=true.
 */
public final class WirePaymentProcessor {

    static final boolean PARITY_FIX = Boolean.getBoolean("wirepay.parityFix");
    static final String INSTRUCTING_BIC = "BANKUS33XXX";

    private static final Set<String> CURRENCIES = Set.of("USD", "EUR", "GBP", "JPY", "INR", "CHF");
    private static final BigDecimal LIMIT = new BigDecimal("1000000.00");
    private static final BigDecimal FEE_RATE = new BigDecimal("0.001");
    private static final BigDecimal FEE_MIN = new BigDecimal("15.00");
    private static final BigDecimal FEE_MAX = new BigDecimal("75.00");
    private static final BigDecimal OUR_SURCHARGE = new BigDecimal("10.00");
    private static final int NAME_MAX = 140;
    private static final int REMITTANCE_MAX = 140;
    private static final Pattern BIC = Pattern.compile("^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$");

    /** Processes one request and returns the JSON response line. */
    public String process(Map<String, String> in) {
        var req = PaymentRequest.from(in);
        var paymentId = "WP-" + req.requestId();
        var wf = new Workflow("request received");

        var outcome = validate(req);
        if (outcome instanceof Outcome.Invalid inv) {
            wf.advance(Workflow.State.REJECTED, inv.reason().code() + " " + inv.reason().text());
            return rejectJson(paymentId, inv.reason(), wf);
        }
        var ok = (Outcome.Valid) outcome;
        wf.advance(Workflow.State.VALIDATED, "all checks passed");

        // PARITY-GAP-1: banker's rounding on the fee. The old service rounds HALF_UP.
        var feeMode = PARITY_FIX ? RoundingMode.HALF_UP : RoundingMode.HALF_EVEN;
        var fee = ok.amount().multiply(FEE_RATE).setScale(2, feeMode);
        if (fee.compareTo(FEE_MIN) < 0) fee = FEE_MIN;
        if (fee.compareTo(FEE_MAX) > 0) fee = FEE_MAX;
        if (ok.chargeBearer().equals("OUR")) fee = fee.add(OUR_SURCHARGE);

        var settlement = TargetCalendar.settlementDate(ok.valueDate(), req.currency());
        var uetr = uetrFor(paymentId);
        wf.advance(Workflow.State.ENRICHED, "fee=" + fee.toPlainString() + " settlement=" + settlement + " uetr=" + uetr);

        var chargeBearerIso = switch (ok.chargeBearer()) {
            case "OUR" -> "DEBT";
            case "BEN" -> "CRED";
            default -> "SHAR";
        };

        var xml = Pacs008.build(new Pacs008.Data(
                paymentId, uetr, req.processingDate().toString(),
                ok.amount().toPlainString(), req.currency(), settlement.toString(), chargeBearerIso,
                fee.toPlainString(), INSTRUCTING_BIC,
                cut(req.debtorName(), NAME_MAX), req.debtorAccount(), req.creditorBic(),
                cut(req.creditorName(), NAME_MAX), req.creditorAccount(),
                cut(req.remittanceInfo(), REMITTANCE_MAX)));
        wf.advance(Workflow.State.ACCEPTED, "pacs.008 generated");
        return acceptJson(paymentId, uetr, xml, wf);
    }

    Outcome validate(PaymentRequest r) {
        if (!r.hasAllMandatory()) return new Outcome.Invalid(Outcome.Reason.MISSING_FIELD);

        BigDecimal amount;
        try {
            amount = new BigDecimal(r.amount()).setScale(2, RoundingMode.HALF_UP);
        } catch (NumberFormatException e) {
            return new Outcome.Invalid(Outcome.Reason.AMOUNT_INVALID);
        }
        if (amount.signum() <= 0) return new Outcome.Invalid(Outcome.Reason.AMOUNT_INVALID);
        if (amount.compareTo(LIMIT) > 0) return new Outcome.Invalid(Outcome.Reason.AMOUNT_LIMIT);
        if (!CURRENCIES.contains(r.currency())) return new Outcome.Invalid(Outcome.Reason.CURRENCY);
        if (!BIC.matcher(r.creditorBic()).matches()) return new Outcome.Invalid(Outcome.Reason.CREDITOR_BIC);

        LocalDate valueDate;
        try {
            valueDate = LocalDate.parse(r.valueDate());
        } catch (DateTimeParseException e) {
            return new Outcome.Invalid(Outcome.Reason.VALUE_DATE);
        }
        // PARITY-GAP-2: off-by-one. A value date equal to the processing date is valid
        // (same-day payment) in the old service, which only rejects dates strictly in the past.
        boolean past = PARITY_FIX ? valueDate.isBefore(r.processingDate()) : !valueDate.isAfter(r.processingDate());
        if (past) return new Outcome.Invalid(Outcome.Reason.VALUE_DATE);

        // NEW FEATURE N-001: IBAN checksum, not just shape.
        if (!Iban.acceptable(r.debtorAccount()) || !Iban.acceptable(r.creditorAccount())) {
            return new Outcome.Invalid(Outcome.Reason.ACCOUNT);
        }

        var cb = r.chargeBearer();
        if (!(cb.equals("OUR") || cb.equals("BEN"))) cb = "SHA";
        return new Outcome.Valid(amount, valueDate, cb);
    }

    /** NEW FEATURE N-004: deterministic, UUIDv4-shaped UETR derived from the payment id. */
    static String uetrFor(String paymentId) {
        var u = UUID.nameUUIDFromBytes(paymentId.getBytes(StandardCharsets.UTF_8));
        long msb = (u.getMostSignificantBits() & ~0xF000L) | 0x4000L;
        long lsb = (u.getLeastSignificantBits() & 0x3FFFFFFFFFFFFFFFL) | 0x8000000000000000L;
        return new UUID(msb, lsb).toString();
    }

    private static String acceptJson(String paymentId, String uetr, String xml, Workflow wf) {
        return "{" + kv("paymentId", paymentId) + "," + kv("status", "ACCP") + ","
                + kv("reasonCode", "") + "," + kv("reasonText", "") + ","
                + kv("uetr", uetr) + "," + workflowJson(wf) + "," + kv("pacs008", xml) + "}";
    }

    private static String rejectJson(String paymentId, Outcome.Reason reason, Workflow wf) {
        return "{" + kv("paymentId", paymentId) + "," + kv("status", "RJCT") + ","
                + kv("reasonCode", reason.code()) + "," + kv("reasonText", reason.text()) + ","
                + kv("uetr", "") + "," + workflowJson(wf) + "," + kv("pacs008", "") + "}";
    }

    private static String workflowJson(Workflow wf) {
        List<Workflow.Step> steps = wf.history();
        var sb = new StringBuilder("\"workflow\":{");
        sb.append(kv("finalState", wf.current().name())).append(",\"history\":[");
        for (int i = 0; i < steps.size(); i++) {
            var s = steps.get(i);
            if (i > 0) sb.append(',');
            sb.append("{\"seq\":").append(s.seq()).append(',').append(kv("state", s.state().name()))
                    .append(',').append(kv("detail", s.detail())).append('}');
        }
        return sb.append("]}").toString();
    }

    private static String kv(String k, String v) {
        return Json.quote(k) + ":" + Json.quote(v);
    }

    private static String cut(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max);
    }
}
