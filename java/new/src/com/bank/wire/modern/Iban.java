package com.bank.wire.modern;

import java.util.regex.Pattern;

/** NEW FEATURE N-001: IBAN mod-97 checksum validation (old service only checked the shape). */
public final class Iban {
    private static final Pattern SHAPE = Pattern.compile("^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$");
    private static final Pattern DOMESTIC = Pattern.compile("^[0-9]{6,17}$");

    private Iban() {
    }

    public static boolean looksLikeIban(String a) {
        return SHAPE.matcher(a).matches();
    }

    public static boolean isDomestic(String a) {
        return DOMESTIC.matcher(a).matches();
    }

    public static boolean checksumValid(String iban) {
        String r = iban.substring(4) + iban.substring(0, 4);
        int rem = 0;
        for (int i = 0; i < r.length(); i++) {
            char c = r.charAt(i);
            if (c >= '0' && c <= '9') {
                rem = (rem * 10 + (c - '0')) % 97;
            } else {
                rem = (rem * 100 + (c - 'A' + 10)) % 97;
            }
        }
        return rem == 1;
    }

    /** Account is acceptable if it is a domestic number or an IBAN with a valid checksum. */
    public static boolean acceptable(String a) {
        if (looksLikeIban(a)) {
            return checksumValid(a);
        }
        return isDomestic(a);
    }
}
