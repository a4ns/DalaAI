# Panel reset-focus native browser acceptance

Product `ff6784a399132e29958cfa615e733270627706c1`; exact three-file test child
`25edea72dce27e597ba2c54b6f3404d8f73dfdb8`. Author archive SHA256
`8f3c92c8fe0cab76e81fcdfc0df5ce76079981145088d6c75ac7ce041934b969`.
Three fixture/test files and thirteen product/toolchain dependencies are pinned.
Only `validation/panel-focus-browser-20261008` triggers this isolated workflow.

One Chromium project executes six cases at each authored viewport:320×800,
390×844 and768×1024. The cases use the actual PanelScreen under React StrictMode
with synthetic props. A pass-through native focus observer verifies one owned
keyboard Reset restoration, preventScroll and focusin; ordinary polls, unfocused
Reset, newer focus, lost access and navigation must not replay the request.
Fixture scroll anchoring is disabled to isolate native focus-induced scrolling.

The fixture HTML is served by loopback Vite dev; it is not part of the production
bundle. These results do not establish real App routing, backend authorization,
physical Android, screen-reader or provider behavior. The exact viewport matrix
comes from the unchanged authored test.use configuration. The runner uses desktop
Chromium, DPR1 and no touch, without browser-warning bypasses.

All18 unique cases must pass once with zero skips/retries. Source and dependency
hashes are checked before and after execution. Live inputs and overrides are
filtered; raw runner errors, captures and generated files remain private and are
removed. Only fixed per-viewport counts, failure categories/source lines and exact
source identities are uploaded. Unrun cases are never labelled observed failures.
The original C gates and the canonical-export reproduction are separate evidence.

```sh
python ops/ci/panel_focus_tests.py
python ops/ci/panel_focus_gate.py --source .ci-panel-focus --check-inputs
python ops/ci/panel_focus_gate.py --source .ci-panel-focus
```
