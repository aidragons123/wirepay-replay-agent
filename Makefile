.PHONY: setup sample replay replay-fixed ui test clean
PYTHON ?= python3

setup:
	$(PYTHON) -m pip install --break-system-packages -r requirements.txt
	@which javac >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y default-jdk)

# (Demo only) regenerate the recorded "production day" from the stand-in old service.
sample:
	$(PYTHON) run_replay.py sample --n 1000

# Replay the recorded day through the new code and write out/report.*
replay:
	$(PYTHON) run_replay.py replay

# Same, with the stand-in's planted parity gaps fixed: should be 0 mismatches.
replay-fixed:
	$(PYTHON) run_replay.py replay --parity-fix --no-fail

ui:
	$(PYTHON) -m streamlit run streamlit_app.py

test:
	$(PYTHON) -m pytest tests -v

clean:
	rm -rf build out .pytest_cache
	find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
