package com.bank.wire.legacy;

import java.util.LinkedHashMap;
import java.util.Map;

/** Minimal flat-JSON reader/writer (Java 8, no external libraries). */
final class Json {

    private Json() {
    }

    static Map<String, String> parseFlat(String s) {
        Map<String, String> m = new LinkedHashMap<String, String>();
        int i = skipWs(s, 0);
        if (i >= s.length() || s.charAt(i) != '{') {
            throw new IllegalArgumentException("not a JSON object");
        }
        i++;
        while (true) {
            i = skipWs(s, i);
            if (i >= s.length()) {
                throw new IllegalArgumentException("unterminated object");
            }
            char c = s.charAt(i);
            if (c == '}') {
                break;
            }
            if (c == ',') {
                i++;
                continue;
            }
            int[] pos = {i};
            String key = readString(s, pos);
            i = skipWs(s, pos[0]);
            if (s.charAt(i) != ':') {
                throw new IllegalArgumentException("expected ':' at " + i);
            }
            i = skipWs(s, i + 1);
            String val;
            if (s.charAt(i) == '"') {
                pos[0] = i;
                val = readString(s, pos);
                i = pos[0];
            } else {
                int j = i;
                while (j < s.length() && ",}".indexOf(s.charAt(j)) < 0) {
                    j++;
                }
                val = s.substring(i, j).trim();
                if (val.equals("null")) {
                    val = "";
                }
                i = j;
            }
            m.put(key, val);
        }
        return m;
    }

    static String writeFlat(Map<String, String> m) {
        StringBuilder sb = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, String> e : m.entrySet()) {
            if (!first) {
                sb.append(',');
            }
            first = false;
            sb.append(quote(e.getKey())).append(':').append(quote(e.getValue() == null ? "" : e.getValue()));
        }
        return sb.append('}').toString();
    }

    static String quote(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':
                    sb.append("\\\"");
                    break;
                case '\\':
                    sb.append("\\\\");
                    break;
                case '\n':
                    sb.append("\\n");
                    break;
                case '\r':
                    sb.append("\\r");
                    break;
                case '\t':
                    sb.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        return sb.append('"').toString();
    }

    private static int skipWs(String s, int i) {
        while (i < s.length() && Character.isWhitespace(s.charAt(i))) {
            i++;
        }
        return i;
    }

    private static String readString(String s, int[] pos) {
        int i = pos[0];
        if (s.charAt(i) != '"') {
            throw new IllegalArgumentException("expected string at " + i);
        }
        i++;
        StringBuilder sb = new StringBuilder();
        while (i < s.length()) {
            char c = s.charAt(i++);
            if (c == '"') {
                pos[0] = i;
                return sb.toString();
            }
            if (c == '\\') {
                char n = s.charAt(i++);
                switch (n) {
                    case 'n':
                        sb.append('\n');
                        break;
                    case 'r':
                        sb.append('\r');
                        break;
                    case 't':
                        sb.append('\t');
                        break;
                    case 'b':
                        sb.append('\b');
                        break;
                    case 'f':
                        sb.append('\f');
                        break;
                    case 'u':
                        sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                        i += 4;
                        break;
                    default:
                        sb.append(n);
                }
            } else {
                sb.append(c);
            }
        }
        throw new IllegalArgumentException("unterminated string");
    }
}
