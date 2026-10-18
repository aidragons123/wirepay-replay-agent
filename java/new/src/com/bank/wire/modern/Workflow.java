package com.bank.wire.modern;

import java.util.ArrayList;
import java.util.List;

/**
 * NEW MODEL: an explicit payment workflow with guarded transitions and an
 * audit trail. The old service just overwrote a status string.
 */
public final class Workflow {

    public enum State {
        RECEIVED, VALIDATED, ENRICHED, ACCEPTED, REJECTED;

        boolean canGoTo(State next) {
            return switch (this) {
                case RECEIVED -> next == VALIDATED || next == REJECTED;
                case VALIDATED -> next == ENRICHED || next == REJECTED;
                case ENRICHED -> next == ACCEPTED || next == REJECTED;
                case ACCEPTED, REJECTED -> false;
            };
        }
    }

    public record Step(int seq, State state, String detail) {
    }

    private final List<Step> history = new ArrayList<>();

    public Workflow(String detail) {
        history.add(new Step(1, State.RECEIVED, detail));
    }

    public State current() {
        return history.get(history.size() - 1).state();
    }

    public void advance(State next, String detail) {
        if (!current().canGoTo(next)) {
            throw new IllegalStateException("illegal transition " + current() + " -> " + next);
        }
        history.add(new Step(history.size() + 1, next, detail));
    }

    public List<Step> history() {
        return List.copyOf(history);
    }
}
