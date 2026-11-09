"""Let CI gate a deploy while two known backlogs are still being paid down.

CI has never passed. It died at Lint, so the test step never ran, which meant
nothing stopped a broken deploy and "deploy only after CI passes" could not be
agreed to. Lint is clean now, but mypy reports 1410 errors across 104 files
and the suite fails 30 tests. Neither is a week's work, and neither is a
reason to keep shipping ungated.

So those two are ratcheted instead of ignored. A recorded baseline says how
bad things are today; CI fails if they get worse and tells you to lower the
number when they get better. That catches the regression a deploy gate is
actually for, without pretending the backlog is gone.

    python scripts/ci_gate.py mypy
    python scripts/ci_gate.py tests

The baseline lives in ci_baseline.json beside this file. Lowering it is the
point; raising it should take a conversation, which is why the failure
message says so.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

BASELINE = pathlib.Path(__file__).with_name("ci_baseline.json")


def _baseline() -> dict:
    return json.loads(BASELINE.read_text())


def _save(data: dict) -> None:
    BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def check_mypy() -> int:
    """Fail if the type-error count has grown.

    A count rather than a list of errors, because mypy's messages move around
    when unrelated code changes and a list would be noise. The count is blunt
    but it is honest about direction, which is the only thing being gated.
    """
    allowed = _baseline()["mypy_errors"]
    result = subprocess.run([sys.executable, "-m", "mypy"], capture_output=True, text=True)
    found = re.search(r"Found (\d+) error", result.stdout)
    count = int(found.group(1)) if found else (0 if result.returncode == 0 else -1)
    if count < 0:
        print(result.stdout[-4000:])
        print("ci_gate: could not read an error count out of mypy")
        return 1

    print(f"mypy: {count} error(s), baseline {allowed}")
    if count > allowed:
        print(result.stdout[-8000:])
        print(
            f"\nci_gate: mypy errors went up, {allowed} -> {count}. Fix the new "
            "ones. If they are genuinely unavoidable, raising the baseline is a "
            "conversation, not a commit."
        )
        return 1
    if count < allowed:
        print(
            f"\nci_gate: mypy is down to {count}. Lower mypy_errors to {count} in "
            f"{BASELINE.name} so it cannot drift back up."
        )
        return 1
    return 0


def check_tests() -> int:
    """Fail on any failure that is not already a known one.

    By name, not by count, because thirty failures becoming a different thirty
    is exactly what a gate exists to catch. A known failure that starts
    passing also fails, so the list cannot quietly rot into a list of tests
    nobody has looked at since.
    """
    known = set(_baseline()["known_test_failures"])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            # Kept from the step this replaced, so the coverage figure does
            # not quietly disappear from the build log.
            "--cov=nevo",
            "--cov-report=term-missing",
        ],
        capture_output=True,
        text=True,
    )
    print(result.stdout[-6000:])
    failing = {
        line.removeprefix("FAILED ").split(" ", 1)[0].strip()
        for line in result.stdout.splitlines()
        if line.startswith("FAILED ")
    }

    new = sorted(failing - known)
    fixed = sorted(known - failing)
    print(f"tests: {len(failing)} failing, {len(known)} known")

    if new:
        print("\nci_gate: these tests are newly failing:")
        for name in new:
            print(f"  {name}")
        print("\nFix them, or say why they are acceptable and add them to")
        print(f"known_test_failures in {BASELINE.name}.")
    if fixed:
        print("\nci_gate: these known failures now pass, which is good news:")
        for name in fixed:
            print(f"  {name}")
        print(f"\nRemove them from known_test_failures in {BASELINE.name}.")
    if not new and not fixed:
        print("ci_gate: no new failures, and none of the known ones started passing")
    return 1 if (new or fixed) else 0


def record() -> int:
    """Rewrite the baseline from the current state.

    For the first commit and for a deliberate re-baseline. Never run in CI:
    a gate that records whatever it finds gates nothing.
    """
    data = _baseline() if BASELINE.exists() else {}
    mypy = subprocess.run([sys.executable, "-m", "mypy"], capture_output=True, text=True)
    found = re.search(r"Found (\d+) error", mypy.stdout)
    data["mypy_errors"] = int(found.group(1)) if found else 0
    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
    )
    data["known_test_failures"] = sorted(
        line.removeprefix("FAILED ").split(" ", 1)[0].strip()
        for line in tests.stdout.splitlines()
        if line.startswith("FAILED ")
    )
    _save(data)
    print(
        f"recorded {data['mypy_errors']} mypy error(s) and "
        f"{len(data['known_test_failures'])} known test failure(s)"
    )
    return 0


def main() -> int:
    actions = {"mypy": check_mypy, "tests": check_tests, "record": record}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        print(f"usage: {sys.argv[0]} {{{'|'.join(actions)}}}")
        return 2
    return actions[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
