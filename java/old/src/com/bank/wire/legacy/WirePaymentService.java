package com.bank.wire.legacy;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * STAND-IN for the legacy (Java 8) wire payment creation service.
 *
 * Procedural, validate-then-fill-a-bean. There is no workflow: the status
 * is overwritten in place and nothing records how the payment got there.
 * Replace this with your real deployed service by pointing the agent's
 * "old" adapter at it (see agent.yaml).
 */
public class WirePaymentService {

    static final Set<String> CURRENCIES =
            new HashSet<String>(Arrays.asList("USD", "EUR", "GBP", "JPY", "INR", "CHF"));
    static final BigDecimal LIMIT = new BigDecimal("1000000.00");
    static final BigDecimal FEE_RATE = new BigDecimal("0.001");
    static final BigDecimal FEE_MIN = new BigDecimal("15.00");
    static final BigDecimal FEE_MAX = new BigDecimal("75.00");
    static final BigDecimal OUR_SURCHARGE = new BigDecimal("10.00");
    static final int NAME_MAX = 35;
    static final int REMITTANCE_MAX = 140;

    static final Pattern BIC = Pattern.compile("^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$");
    static final Pattern IBAN_SHAPE = Pattern.compile("^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$");
    static final Pattern DOMESTIC = Pattern.compile("^[0-9]{6,17}$");

    public Map<String, String> process(Map<String, String> in) {
        LegacyPayment p = new LegacyPayment();
        LocalDate processing = parseDate(in.get("processingDate"), LocalDate.now());

        String requestId = t(in.get("requestId"));
        String debtorName = t(in.get("debtorName"));
        String debtorAccount = t(in.get("debtorAccount"));
        String creditorName = t(in.get("creditorName"));
        String creditorAccount = t(in.get("creditorAccount"));
        String creditorBic = t(in.get("creditorBic"));
        String amountStr = t(in.get("amount"));
        String currency = t(in.get("currency"));
        String valueDateStr = t(in.get("valueDate"));
        String chargeBearer = t(in.get("chargeBearer"));
        String remittance = t(in.get("remittanceInfo"));

        p.setPaymentId("WP-" + requestId);
        p.setStatus("REJECTED");

        if (blank(requestId) || blank(debtorName) || blank(debtorAccount) || blank(creditorName)
                || blank(creditorAccount) || blank(creditorBic) || blank(amountStr)
                || blank(currency) || blank(valueDateStr)) {
            return reject(p, "E001", "Mandatory field missing");
        }

        BigDecimal amount;
        try {
            amount = new BigDecimal(amountStr).setScale(2, RoundingMode.HALF_UP);
        } catch (NumberFormatException e) {
            return reject(p, "E002", "Amount is not numeric");
        }
        if (amount.signum() <= 0) {
            return reject(p, "E002", "Amount must be positive");
        }
        if (amount.compareTo(LIMIT) > 0) {
            return reject(p, "E007", "Amount exceeds single-payment limit");
        }
        if (!CURRENCIES.contains(currency)) {
            return reject(p, "E003", "Currency not supported");
        }
        if (!BIC.matcher(creditorBic).matches()) {
            return reject(p, "E004", "Creditor BIC invalid");
        }

        LocalDate valueDate;
        try {
            valueDate = LocalDate.parse(valueDateStr);
        } catch (DateTimeParseException e) {
            return reject(p, "E005", "Value date invalid");
        }
        if (valueDate.isBefore(processing)) {
            return reject(p, "E005", "Value date in the past");
        }
        if (!validAccount(debtorAccount) || !validAccount(creditorAccount)) {
            return reject(p, "E006", "Account number format invalid");
        }

        if (blank(chargeBearer) || !(chargeBearer.equals("OUR") || chargeBearer.equals("BEN"))) {
            chargeBearer = "SHA";
        }

        BigDecimal fee = amount.multiply(FEE_RATE).setScale(2, RoundingMode.HALF_UP);
        if (fee.compareTo(FEE_MIN) < 0) {
            fee = FEE_MIN;
        }
        if (fee.compareTo(FEE_MAX) > 0) {
            fee = FEE_MAX;
        }
        if (chargeBearer.equals("OUR")) {
            fee = fee.add(OUR_SURCHARGE);
        }

        LocalDate settlement = valueDate;
        while (settlement.getDayOfWeek() == DayOfWeek.SATURDAY
                || settlement.getDayOfWeek() == DayOfWeek.SUNDAY) {
            settlement = settlement.plusDays(1);
        }

        p.setStatus("ACCEPTED");
        p.setDebtorName(cut(debtorName, NAME_MAX));
        p.setDebtorAccount(debtorAccount);
        p.setCreditorName(cut(creditorName, NAME_MAX));
        p.setCreditorAccount(creditorAccount);
        p.setCreditorBic(creditorBic);
        p.setAmount(amount);
        p.setCurrency(currency);
        p.setFee(fee);
        p.setSettlementDate(settlement);
        p.setChargeBearer(chargeBearer);
        p.setRemittanceInfo(cut(remittance, REMITTANCE_MAX));
        return toMap(p);
    }

    private static boolean validAccount(String a) {
        return IBAN_SHAPE.matcher(a).matches() || DOMESTIC.matcher(a).matches();
    }

    private static Map<String, String> reject(LegacyPayment p, String code, String msg) {
        p.setStatus("REJECTED");
        p.setErrorCode(code);
        p.setErrorMessage(msg);
        return toMap(p);
    }

    private static Map<String, String> toMap(LegacyPayment p) {
        Map<String, String> m = new LinkedHashMap<String, String>();
        m.put("paymentId", p.getPaymentId());
        m.put("status", p.getStatus());
        m.put("errorCode", p.getErrorCode());
        m.put("errorMessage", p.getErrorMessage());
        m.put("debtorName", p.getDebtorName());
        m.put("debtorAccount", p.getDebtorAccount());
        m.put("creditorName", p.getCreditorName());
        m.put("creditorAccount", p.getCreditorAccount());
        m.put("creditorBic", p.getCreditorBic());
        m.put("amount", p.getAmount() == null ? "" : p.getAmount().toPlainString());
        m.put("currency", p.getCurrency());
        m.put("fee", p.getFee() == null ? "" : p.getFee().toPlainString());
        m.put("settlementDate", p.getSettlementDate() == null ? "" : p.getSettlementDate().toString());
        m.put("chargeBearer", p.getChargeBearer());
        m.put("remittanceInfo", p.getRemittanceInfo());
        return m;
    }

    private static LocalDate parseDate(String s, LocalDate fallback) {
        try {
            return (s == null || s.trim().isEmpty()) ? fallback : LocalDate.parse(s.trim());
        } catch (DateTimeParseException e) {
            return fallback;
        }
    }

    private static String t(String s) {
        return s == null ? "" : s.trim();
    }

    private static boolean blank(String s) {
        return s == null || s.trim().isEmpty();
    }

    private static String cut(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max);
    }
}
