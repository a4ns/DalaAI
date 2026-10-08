'use strict';
/* Self-contained page preload. Never import product code or collect other bodies.
 * The app keeps native promises/Response/reader/chunks. Extra observer reactions
 * and copies still perturb timing. Attaching rejection observers marks selected
 * promises handled for host unhandled-rejection reporting; original app-facing
 * rejection values remain unchanged. This is INSTRUMENTED_DIAGNOSTIC_ONLY. */
function installReaderTap(config) {
  'use strict';
  const KEY = '__DALA_BODY_CAPTURE_PROBE__';
  const MAX = 8 * 1024 * 1024;
  const EXACT = 'https://localhost:18443/api/v1/reports/shift.pdf?start=2026-07-01T00%3A00%3A00Z&end=2026-10-01T00%3A00%3A00Z';
  if (!config || Object.keys(config).sort().join(',') !== 'nonce,runId,sourceSha' ||
      !/^[0-9a-f]{64}$/.test(config.nonce || '') || !/^bcp-[a-z0-9-]{8,58}$/.test(config.runId || '') ||
      !/^[0-9a-f]{40}$/.test(config.sourceSha || '') || Object.hasOwn(globalThis, KEY)) {
    throw new Error('BODY_PROBE_INSTALL_BLOCKED');
  }
  let nonce = config.nonce;
  const sourceSha = config.sourceSha, runId = config.runId;
  const targetPath = EXACT.slice('https://localhost:18443'.length);
  const nativeFetch = globalThis.fetch;
  const nativeThen = Promise.prototype.then;
  const nativeDigest = crypto.subtle.digest.bind(crypto.subtle);
  const restores = [];
  let state = 'IDLE', reason = 'NOT_ARMED', comparable = false, armed = false, disposed = false;
  let generation = 0, buffer = null, timer = null, digestTimer = null, outstanding = 0;
  let fetches = 0, readers = 0, reads = 0, bytes = 0, declared = 0, eof = false, hash = null;
  let sourceResponse = null, sourceReader = null;
  const clearTimers = () => { clearTimeout(timer); clearTimeout(digestTimer); timer = null; digestTimer = null; };
  const dropBytes = () => { try { if (buffer) buffer.fill(0); } finally { buffer = null; } };
  const restoreOwned = () => {
    let clean = true;
    for (const restore of restores.reverse()) { try { restore(); } catch { clean = false; } }
    restores.length = 0; sourceResponse = null; sourceReader = null;
    return clean;
  };
  const invalidate = code => {
    if (disposed) return;
    state = 'NOT_COMPARABLE'; reason = code; comparable = false; hash = null;
    generation++; try { clearTimers(); } catch {} try { dropBytes(); } catch {}
    if (!restoreOwned()) reason = 'RESTORE_FAILED';
  };
  const guarded = (callback, gen) => value => {
    if (disposed || gen !== generation) return;
    try { callback(value); } catch { invalidate('OBSERVER_FAILED'); }
  };
  const observe = (promise, success, failure, gen) => {
    try { Reflect.apply(nativeThen, promise, [guarded(success, gen), guarded(failure, gen)]); }
    catch { invalidate('OBSERVER_FAILED'); }
  };
  const install = (object, key, wrapper) => {
    const before = Object.getOwnPropertyDescriptor(object, key);
    const descriptor = { value: wrapper, configurable: true, enumerable: false, writable: true };
    Object.defineProperty(object, key, descriptor);
    restores.push(() => {
      const current = Object.getOwnPropertyDescriptor(object, key);
      if (current && current.value === wrapper && current.configurable === true && current.writable === true && current.enumerable === false) {
        if (before) Object.defineProperty(object, key, before); else delete object[key];
      }
    });
  };
  const finish = gen => {
    if (bytes !== declared || bytes === 0) return invalidate('TRUNCATED');
    eof = true; state = 'HASHING'; reason = 'DIGEST_PENDING'; clearTimeout(timer); timer = null;
    let digest;
    try { digest = nativeDigest('SHA-256', buffer); } catch { return invalidate('DIGEST_FAILED'); }
    digestTimer = setTimeout(() => invalidate('DIGEST_TIMEOUT'), 5000);
    observe(digest, value => {
      if (!(value instanceof ArrayBuffer) || value.byteLength !== 32) return invalidate('DIGEST_FAILED');
      hash = Array.from(new Uint8Array(value), x => x.toString(16).padStart(2, '0')).join('');
      comparable = true; state = 'COMPLETE'; reason = 'EOF_EXACT_LENGTH';
      clearTimers(); dropBytes();
    }, () => invalidate('DIGEST_FAILED'), gen);
  };
  const bindReader = reader => {
    sourceReader = reader;
    const nativeRead = reader.read, nativeCancel = reader.cancel;
    install(reader, 'read', function (...args) {
      let promise;
      try { promise = Reflect.apply(nativeRead, this, args); }
      catch (error) { invalidate('READ_THROW'); throw error; }
      if (this !== sourceReader || args.length !== 0 || state !== 'READING') {
        invalidate('UNSUPPORTED_READ'); return promise;
      }
      reads++;
      if (++outstanding !== 1) { invalidate('CONCURRENT_READ'); return promise; }
      const gen = generation;
      observe(promise, item => {
        outstanding--;
        if (!item || typeof item.done !== 'boolean') return invalidate('INVALID_READ_RESULT');
        if (item.done) return finish(gen);
        if (!(item.value instanceof Uint8Array)) return invalidate('INVALID_CHUNK');
        const size = item.value.byteLength;
        if (size > MAX || bytes + size > declared || bytes + size > MAX) return invalidate('OVERFLOW');
        buffer.set(item.value, bytes); bytes += size;
      }, () => { outstanding--; invalidate('READ_REJECTED'); }, gen);
      return promise;
    });
    install(reader, 'cancel', function (...args) {
      let promise;
      try { promise = Reflect.apply(nativeCancel, this, args); }
      catch (error) { invalidate('CANCEL_THROW'); throw error; }
      invalidate('CLIENT_CANCELLED');
      return promise;
    });
  };
  const bindResponse = response => {
    if (!(response instanceof Response) || response.url !== EXACT || response.redirected || response.status !== 200 ||
        response.type !== 'basic' || response.bodyUsed || !response.body || response.body.locked) return invalidate('RESPONSE_BINDING_FAILED');
    const h = response.headers, length = h.get('content-length'), encoding = h.get('content-encoding');
    if (h.get('content-type') !== 'application/pdf' || h.get('content-disposition') !== 'attachment; filename="naryadai-shift.pdf"' ||
        !/(?:^|,)\s*private(?:,|$)/i.test(h.get('cache-control') || '') || !/no-store/i.test(h.get('cache-control') || '') ||
        !/(?:^|,)\s*cookie\s*(?:,|$)/i.test(h.get('vary') || '') || h.get('x-content-type-options') !== 'nosniff' ||
        h.get('content-security-policy') !== "default-src 'none'; sandbox" ||
        (encoding !== null && encoding.trim().toLowerCase() !== 'identity') ||
        !/^[0-9]+$/.test(length || '') || !Number.isSafeInteger(Number(length)) || Number(length) < 1 || Number(length) > MAX) return invalidate('HEADERS_OR_LENGTH_FAILED');
    declared = Number(length); buffer = new Uint8Array(declared); sourceResponse = response;
    state = 'READING'; reason = 'AWAITING_CLIENT_READER';
    const stream = response.body, nativeGetReader = stream.getReader;
    install(stream, 'getReader', function (...args) {
      let reader;
      try { reader = Reflect.apply(nativeGetReader, this, args); }
      catch (error) { invalidate('READER_THROW'); throw error; }
      if (this !== stream || args.length !== 0 || ++readers !== 1 || state !== 'READING') {
        invalidate('UNSUPPORTED_READER'); return reader;
      }
      try { bindReader(reader); } catch { invalidate('OBSERVER_FAILED'); }
      return reader;
    });
  };
  const wrapper = function (...args) {
    const input = args[0], init = args[1];
    const related = typeof input === 'string' && (input.startsWith('/api/v1/reports/shift.pdf') || input.startsWith('https://localhost:18443/api/v1/reports/shift.pdf'));
    let selected = false;
    try { if (!disposed && related) {
      if (!armed || state === 'IDLE') invalidate('UNARMED_REQUEST');
      else if (++fetches !== 1) invalidate('DUPLICATE_REQUEST');
      else if ((input !== targetPath && input !== EXACT) || !init || init.method !== 'GET' || init.credentials !== 'same-origin' ||
          init.mode !== 'same-origin' || init.cache !== 'no-store' || init.redirect !== 'error' || init.body !== undefined || !init.signal) invalidate('REQUEST_BINDING_FAILED');
      else if (state === 'ARMED') { selected = true; state = 'FETCHING'; reason = 'AWAITING_ORIGINAL_RESPONSE'; }
    }
    } catch { invalidate('OBSERVER_FAILED'); }
    let promise;
    try { promise = Reflect.apply(nativeFetch, this, args); }
    catch (error) { if (selected) invalidate('FETCH_THROW'); throw error; }
    if (selected) observe(promise, bindResponse, () => invalidate('FETCH_REJECTED'), generation);
    return promise;
  };
  install(globalThis, 'fetch', wrapper);
  const check = capability => { if (disposed || capability !== nonce) { invalidate('CAPABILITY_REJECTED'); throw new Error('BODY_PROBE_CAPABILITY_REJECTED'); } };
  const snapshot = () => ({ scope: 'INSTRUMENTED_DIAGNOSTIC_ONLY', source_sha: sourceSha, run_id: runId,
    state, reason, comparability: comparable ? 'COMPARABLE' : 'NOT_COMPARABLE',
    fetches, readers, reads, declared_bytes: declared, observed_bytes: bytes, eof, sha256: hash,
    retained_capture_bytes: buffer ? buffer.byteLength : 0, disposed });
  const api = Object.freeze({
    arm(capability) {
      check(capability);
      if (armed || state !== 'IDLE') { invalidate('ARM_REPLAY'); throw new Error('BODY_PROBE_ARM_REJECTED'); }
      armed = true; state = 'ARMED'; reason = 'AWAITING_EXACT_REQUEST';
      timer = setTimeout(() => invalidate('READ_TIMEOUT'), 20000);
    },
    snapshot(capability) { check(capability); return snapshot(); },
    dispose(capability) {
      check(capability); clearTimers(); dropBytes(); generation++; disposed = true;
      if (!restoreOwned()) { comparable = false; state = 'NOT_COMPARABLE'; reason = 'RESTORE_FAILED'; hash = null; }
      nonce = null;
      const value = snapshot();
      if (globalThis[KEY] === api) delete globalThis[KEY];
      return value;
    },
  });
  Object.defineProperty(globalThis, KEY, { value: api, configurable: true, enumerable: false, writable: false });
}
module.exports = { installReaderTap };
