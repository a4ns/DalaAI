# C-105 independent-review correction

Supersedes the implementation selection in `checkpoint.md`; that file remains
historical evidence of the first checkpoint, not the current recommended code.

- Reviewer: C6
- Finding: configuration accepted mixed-case representations of the same UUID,
  then compared raw strings for distinct role identity and foreign-section scope
- Previous checkpoint: `d06b44fcd7135cac59e265a9ba5c1ef31f2cad54`
- Corrected implementation: `043d7bf8ba3423ea379f97bf815ecad8ad0c3e2c`
- Tested at: `2026-10-07T19:26:25Z`
- Fix: every user and section UUID must be canonical lowercase hyphenated form;
  zero UUID placeholders remain forbidden
- Added regression tests: differently cased duplicate user UUIDs; uppercase and
  unhyphenated section UUIDs that would otherwise defeat scope comparison

Checks on the exact corrected implementation:

- PASS: `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests/e2e -p 'test_*.py' -q`, 26 tests
- PASS: `PYTHONDONTWRITEBYTECODE=1 python -c "import sys; sys.path.insert(0,'tests/e2e'); import browser_evidence as h; h.verify_provenance(h.fingerprint())"`
- PASS: `git diff --check`; clean checkout after tests
- NOT_RUN: all 12 product browser/device journeys

The subsequent commit adds this record and a README format clarification only.
It does not change the corrected Python implementation, matrix or test cases.
C6 independently rechecks the corrected commit before the coordinator publishes.
No API/contract/dependency/root change, credentials, deployment or notification.
