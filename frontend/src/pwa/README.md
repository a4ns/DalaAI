# Local photo preparation (B-105)

`PhotoPicker` is a controlled Russian-language selector, not a transport. Props: `contextKey`, `phase: 'before' | 'after'`, `value: readonly PreparedPhoto[]`, `onChange(photos)`, optional `disabled`, `maxPhotos` (clamped to 1–5), and `required` (informational only). Import `PreparedPhoto` from `photoPreparation.ts`.

- Change `contextKey` for account, order/draft, assignment revision, or section changes. The selector remounts and cancels pending preparation. The parent must clear its own controlled value on these context changes and account exit; the picker never owns server records.
- Accepted input: actual JPEG, PNG, still-WebP signatures and valid dimensions, at most 8 MiB and 20,000,000 pixels. Header checks happen before decoding, then actual decoded dimensions are checked. Animated WebP is rejected. The browser still must decode the image. Server content validation and limits are independent and mandatory.
- Output: JPEG canvas re-encoding, aspect ratio preserved, long edge at most 1920 px, no upscaling. A 1.5 MB encoded target is best-effort; the hard encoded limit is 8 MiB. JPEG encoding replaces incoming container metadata but does not remove identifying information visible in the image. Transparency is flattened onto white. Neither EXIF nor `preparedAt` proves capture time.
- `PreparedPhoto.file` is the prepared immutable `File`. Keep that same file and the same operation identity on a retry. Do not call `preparePhoto` again for a transport retry. Local preparation never yields a server photo ID. The adapter must distinguish pending, unknown outcome, rejected and confirmed upload.
- Uploads for the after phase must bind to the wire contract's order, assignment revision and section. The server owns staged-upload expiration (proposed 24 h); the local component does not promise that a selected photo remains valid on the server.
- No fetch, service worker, offline outbox, persistent photo cache or push permission request. `navigator.onLine` is a browser hint, never server truth. A selected file is not a successful upload. Closing/reloading the tab may lose the parent's memory-only selections.
- The camera input merely hints `capture="environment"`; a separate ordinary file picker is available. Physical Android capture, permission denial and installation are device gates.

The manifest references only local SVG icons; B4 owns the HTML manifest link. Manifest metadata alone is not evidence of installability or offline operation.

## Focused checks

```sh
node --experimental-strip-types --test frontend/src/pwa/photoPreparation.test.ts
```

Header fixtures include a real synthetic PNG and deliberately malformed headers. Tests labelled “simulated browser” substitute decoder/canvas to exercise control flow and cleanup; they are not evidence of actual browser decoding, image quality, compression ratio or upload timing. Run the frontend lint/typecheck/build after integration. B6 independently owns browser acceptance.

## Device/browser gates

Actual browser image decode/compression and visual layout: BLOCKED in this execution environment (Chromium OS socket/ptrace launch failures were independently reproduced by B6; not retried here).

Real Android camera permission/capture, installation, actual network upload ≤10 seconds and server upload enforcement: NOT_RUN in this package. Nothing in these components marks those gates as passed.
