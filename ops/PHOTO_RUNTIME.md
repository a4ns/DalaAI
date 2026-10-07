# Private photo runtime

Set DALA_PHOTO_STORAGE_ROOT to an existing absolute durable directory owned by
the API UID (10001 in the image), mode0700. The same PrivateFileStore instance
serves staging/retrieval and supplies physical integrity checks at human CLOSE.
No public/static mount exposes that directory. DALA_PHOTO_MAX_TOTAL_BYTES defaults
to1GiB and includes retained orphans and expired staged files. Each owner may
have at most20 live, unattached stages; the quota uses real time sampled after
the owner lock. At expires_at the stage stops consuming a slot, but its row,
receipt and private bytes remain unchanged. Expired stages cannot be read,
attached or replayed as a new upload. Attached evidence is outside this quota.
Disk reclamation remains a separate retention-policy task; expiry does not
free disk space or bypass the independent total-byte limit.
No cleanup/reset of final files is automatic, especially after uncertain COMMIT.

Only photo-enabled runtime permits/requires the extra INSERT privilege on photos.
It still rejects UPDATE(file_valid), DELETE, TRUNCATE, TRIGGER and ownership.
No new migration or external service is needed. Pillow12.3.0 and
python-multipart0.0.32 are pinned, with official registry versions verified.

Photos are decoded, metadata-stripped, re-encoded and atomically published before
the receipt/database transaction commits. HTTP bodies have a30-second deadline,
8MiB decoded file limit and20MP raster limit. One raster decoder and two upload
bodies per process bound concurrent memory; these are not latency/load guarantees.
Single-worker20MP local observations peaked around401MiB WebP and245MiB JPEG/PNG
before Argon2/application overhead. Budget at least1GiB as a starting envelope;
worst-case mixed load and real-phone network timing remain unverified.

CLOSE first holds the existing order/photo locks and reads trusted bound rows.
Persisted file_valid=true is insufficient: stored bytes must still match their
server-established length/hash. Known mismatch yields409 INCOMPLETE_SUBMISSION
with no review/receipt effects. Missing/unavailable private storage yields generic
retryable503; restore storage and retry the same operation. No verifier means
unknown photo validity and cannot close required-photo work. A matching hash is
storage integrity, not evidence that the pictured repair is semantically correct.

Exact-head CI runs20 real PostgreSQL photo cases,4 independent lock races,
20 actual restricted-login cases and4 actual app.main physical CLOSE flows,
plus all existing regression gates. The new full flow stages actual generated
image bytes through HTTP, submits, reviews and replays after an app restart;
negative flows inspect absence of DB effects. No live deployment, camera device,
notification delivery or model quality is implied.
