import re


def parse_log(log: str) -> dict[str, str]:
    """Parse test runner output into per-test results.

    Args:
        log: Full stdout+stderr output of `bash run_test.sh 2>&1`.

    Returns:
        Dict mapping test_id to status.
        - test_id: pytest native format (e.g. "tests/test_basic.py::BasicTestCase::test_func")
        - status: one of "PASSED", "FAILED", "SKIPPED", "ERROR"
    """
    results = {}
    # Strip ANSI escape codes
    log = re.sub(r'\x1b\[[0-9;]*m', '', log)

    for line in log.splitlines():
        line = line.strip()
        # Match pytest verbose output: "tests/test_basic.py::Class::test PASSED [ 5%]"
        m = re.match(
            r'^(\S+::\S+.*?)\s+(PASSED|FAILED|SKIPPED|ERROR)\s+\[\s*\d+%\]',
            line,
        )
        if m:
            test_id = m.group(1).strip()
            status = m.group(2)
            results[test_id] = status
            continue

        # Match collection errors: "ERROR tests/foo.py" (no ::)
        m = re.match(r'^ERROR\s+(tests/\S+\.py)$', line)
        if m:
            results[m.group(1)] = "ERROR"

    return results

