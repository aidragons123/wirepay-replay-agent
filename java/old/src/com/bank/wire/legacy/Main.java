package com.bank.wire.legacy;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Batch wire protocol: one flat JSON request per stdin line, one flat JSON
 * response per stdout line, same order. This is what lets the agents drive
 * 1000 payments through a single JVM start-up.
 */
public class Main {
    public static void main(String[] args) throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
        PrintStream out = new PrintStream(System.out, false, "UTF-8");
        WirePaymentService service = new WirePaymentService();
        String line;
        while ((line = in.readLine()) != null) {
            if (line.trim().isEmpty()) {
                continue;
            }
            Map<String, String> response;
            try {
                response = service.process(Json.parseFlat(line));
            } catch (RuntimeException e) {
                response = new LinkedHashMap<String, String>();
                response.put("status", "REJECTED");
                response.put("errorCode", "E999");
                response.put("errorMessage", "Unhandled: " + e.getClass().getSimpleName());
            }
            out.println(Json.writeFlat(response));
        }
        out.flush();
    }
}
