package com.bank.wire.modern;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.Month;

/** NEW FEATURE N-002: TARGET2 closing days are skipped when settling EUR payments. */
public final class TargetCalendar {
    private TargetCalendar() {
    }

    public static LocalDate easterSunday(int y) {
        int a = y % 19;
        int b = y / 100;
        int c = y % 100;
        int d = b / 4;
        int e = b % 4;
        int f = (b + 8) / 25;
        int g = (b - f + 1) / 3;
        int h = (19 * a + b - d - g + 15) % 30;
        int i = c / 4;
        int k = c % 4;
        int l = (32 + 2 * e + 2 * i - h - k) % 7;
        int m = (a + 11 * h + 22 * l) / 451;
        int month = (h + l - 7 * m + 114) / 31;
        int day = ((h + l - 7 * m + 114) % 31) + 1;
        return LocalDate.of(y, month, day);
    }

    public static boolean isHoliday(LocalDate d) {
        if (d.getMonth() == Month.JANUARY && d.getDayOfMonth() == 1) return true;
        if (d.getMonth() == Month.MAY && d.getDayOfMonth() == 1) return true;
        if (d.getMonth() == Month.DECEMBER && (d.getDayOfMonth() == 25 || d.getDayOfMonth() == 26)) return true;
        LocalDate easter = easterSunday(d.getYear());
        return d.equals(easter.minusDays(2)) || d.equals(easter.plusDays(1));
    }

    public static LocalDate settlementDate(LocalDate valueDate, String currency) {
        var d = valueDate;
        while (isWeekend(d) || ("EUR".equals(currency) && isHoliday(d))) {
            d = d.plusDays(1);
        }
        return d;
    }

    private static boolean isWeekend(LocalDate d) {
        return d.getDayOfWeek() == DayOfWeek.SATURDAY || d.getDayOfWeek() == DayOfWeek.SUNDAY;
    }
}
