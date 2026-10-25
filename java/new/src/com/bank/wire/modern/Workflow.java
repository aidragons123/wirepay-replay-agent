package com.bank.wire.modern;

import java.util.ArrayList;
import java.util.List;

/**
 * NEW MODEL: the payment is a workflow. Every processing stage is a named step with a status,
 * the whole path is kept as an audit trail, and a payment can PAUSE at a step (e.g. fraud
 * review) and later be RESUMED from exactly that step without re-running the earlier ones.
 * The old service ran the same checks inline and kept no record of how far a payment got.
 */
public final class Workflow {

    /** Stages in processing order, then the two end states. */
    public enum State {
        RECEIVED, BASIC_VALIDATION, DUPLICATE_CHECK, FRAUD_CHECK, BANK_DETAILS_CHECK, POSTING, COMPLETED, REJECTED;

        boolean canGoTo(State next) {
            if (this == COMPLETED || this == REJECTED) return false;
            return next == REJECTED || next.ordinal() == ordinal() + 1;
        }
    }

    /** DONE = ran and passed, FAILED = ran and failed, PAUSED = waiting for a person, RESTORED = done earlier, not re-run. */
    public enum Status { DONE, FAILED, PAUSED, RESTORED }

    public record Step(int seq, State state, Status status, String detail) {
    }

    private final List<Step> history = new ArrayList<>();

    public Workflow(Status status, String detail) {
        history.add(new Step(1, State.RECEIVED, status, detail));
    }

    public State current() {
        return history.get(history.size() - 1).state();
    }

    public boolean paused() {
        return history.get(history.size() - 1).status() == Status.PAUSED;
    }

    public void step(State next, Status status, String detail) {
        if (paused()) {
            throw new IllegalStateException("workflow is paused at " + current());
        }
        if (!current().canGoTo(next)) {
            throw new IllegalStateException("illegal transition " + current() + " -> " + next);
        }
        history.add(new Step(history.size() + 1, next, status, detail));
    }

    public List<Step> history() {
        return List.copyOf(history);
    }
}
