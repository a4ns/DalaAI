# In-app notice mounted browser gate

Product and authored test source are exact
`8e8087103821b6334ba8d5de0a40c91ee58276f9`, based on main
`348b82683b95e4bd20ce2ecbbf980d761e72ae3a`. The six changed product/test files
and thirteen unchanged dependency/toolchain inputs are pinned in the contract.
Only `validation/in-app-notices-browser-20261008` triggers this workflow.

The required checks build the production App before loopback-only Vite preview.
One official Chromium project selects exactly eleven in-app notice scenarios and
seven existing polling-command scenarios. All eighteen must pass once; skips,
retries, duplicate titles, extra cases and unrun cases cannot pass the gate.
Default viewport is 390×844 with desktop mode, DPR1 and no touch. The authored
notice layout/reduced-motion case explicitly changes its viewport to 360×732.
This is browser rendering with synthetic intercepted HTTP and a controlled clock.
It does not establish physical Android/iPhone, backend authorization, WebPush,
OS notifications, background delivery or original C110/C112/C113 acceptance.

Notice cases cover a silent initial snapshot, duplicate suppression, pause and
resume of the eight-second lifetime on hover/focus, three-item display limit,
no delayed backlog, retention of a focused existing notice during a new burst,
preserved draft/focus/scroll/navigation, suppression of
duplicate own-action messages, failed/partial recovery, and logout/access/account
invalidation. The seven unchanged command cases preserve their exact one-POST
and invalid-state refusal assertions. No tests or product paths are modified.

The runner filters live inputs and launch overrides, disables automatic traces,
video and screenshots, and keeps raw output in a disposable private directory.
The one explicit synthetic screenshot authored by B also stays in that directory
and is deleted afterward. Only the fixed counts and bounded failure categories,
known case names and source lines are published. Failed and unrun cases remain
distinct; no failure is relabeled as a completed behavior check.

```sh
python ops/ci/in_app_notice_tests.py
python ops/ci/in_app_notice_gate.py --source .ci-in-app-notices --check-inputs
python ops/ci/in_app_notice_gate.py --source .ci-in-app-notices
```

The previously canceled request-Origin publication is separate and remains held.
This candidate's parent is 348b and contains no request-Origin policy change.
