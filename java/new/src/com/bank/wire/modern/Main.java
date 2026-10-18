package com.bank.wire.modern;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;

/**
 * Batch wire protocol, identical to the legacy service: one flat JSON
 * request per stdin line, one JSON response per stdout line, same order.
 */
public class Main {
    public static void main(String[] args) throws Exception {
        var in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        var out = new PrintStream(System.out, false, StandardCharsets.UTF_8);
        var processor = new WirePaymentProcessor();
        String line;
        while ((line = in.readLine()) != null) {
            if (line.isBlank()) continue;
            String response;
            try {
                response = processor.process(Json.parseFlat(line));
            } catch (RuntimeException e) {
                response = "{\"paymentId\":\"\",\"status\":\"RJCT\",\"reasonCode\":\"NARR\","
                        + "\"reasonText\":" + Json.quote("Unhandled: " + e.getClass().getSimpleName())
                        + ",\"uetr\":\"\",\"workflow\":{\"finalState\":\"REJECTED\",\"history\":[]},\"pacs008\":\"\"}";
            }
            out.println(response);
        }
        out.flush();
    }
}
