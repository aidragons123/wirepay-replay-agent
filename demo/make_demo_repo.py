#!/usr/bin/env python3
"""Create a small local Git repo that holds the bundled stand-in services on separate branches.

    python3 demo/make_demo_repo.py /tmp/wire-demo.git-work

Branches:  legacy        the old flat Java 8 service         main class com.bank.wire.legacy.Main
           modern        the new workflow / pacs.008 service  main class com.bank.wire.modern.Main   (two planted gaps)
           modern-fixed  the same service with both gaps fixed (the "after the fix" commit)

Use it in the app: Settings -> Services under test -> Git repository, repo = the path printed at the end.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
dest = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/wire-demo-repo").resolve()
if dest.exists():
    shutil.rmtree(dest)
dest.mkdir(parents=True)


def git(*a):
    subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", *a], cwd=dest, check=True,
                   capture_output=True)


def put(side):
    if (dest / "src").exists():
        shutil.rmtree(dest / "src")
    shutil.copytree(ROOT / "java" / side / "src", dest / "src")


git("init", "-q", "-b", "legacy")
put("old"); git("add", "-A"); git("commit", "-qm", "Legacy wire payment service (Java 8)")
git("checkout", "-q", "-b", "modern")
put("new"); git("add", "-A"); git("commit", "-qm", "ISO 20022 workflow service (Java 18)")
git("checkout", "-q", "-b", "modern-fixed")
f = dest / "src/com/bank/wire/modern/WirePaymentProcessor.java"
f.write_text(f.read_text().replace('Boolean.getBoolean("wirepay.parityFix")', 'true'))
git("add", "-A"); git("commit", "-qm", "Fix fee rounding and same-day value date")
git("checkout", "-q", "legacy")
print(dest)
