/// <reference types="node" />
import assert from 'node:assert/strict';
import test from 'node:test';
import { beginPhotoPreparation } from './preparationActivity.ts';
import { inspectImageHeader, outputDimensions, PHOTO_LIMITS, PhotoPreparationError, photoErrorMessage, preparePhoto } from './photoPreparation.ts';

// Real, synthetic 2x2 PNG bytes. Header tests alone do not prove browser decoding.
const PNG = new Uint8Array(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGOs2LKPgYGBiYGBgYGBAQAW3AHuIPb9IwAAAABJRU5ErkJggg==', 'base64'));
const rejectsCode = (code: string) => (error: unknown): boolean => error instanceof PhotoPreparationError && error.code === code;
function sizedPng(width: number, height: number): Uint8Array {
  const bytes = PNG.slice();
  const view = new DataView(bytes.buffer);
  view.setUint32(16, width); view.setUint32(20, height);
  return bytes; // Corrupted CRC is deliberate: no decoder acceptance is asserted.
}
function webp(chunk: string, payload: Uint8Array): Uint8Array {
  const bytes = new Uint8Array(20 + payload.length + (payload.length % 2));
  bytes.set(Buffer.from('RIFF')); bytes.set(Buffer.from('WEBP'), 8); bytes.set(Buffer.from(chunk), 12);
  const view = new DataView(bytes.buffer);
  view.setUint32(4, bytes.length - 8, true); view.setUint32(16, payload.length, true); bytes.set(payload, 20);
  return bytes;
}

test('real PNG signature and dimensions, independent of filename or MIME', () => {
  assert.deepEqual(inspectImageHeader(PNG), { mime: 'image/png', width: 2, height: 2 });
});
test('reject empty, renamed non-images, SVG and truncated headers', () => {
  for (const bytes of [new Uint8Array(), new Uint8Array(Buffer.from('<svg/>')), PNG.slice(0, 20), new Uint8Array([255, 216, 255, 192, 0])]) {
    assert.throws(() => inspectImageHeader(bytes), PhotoPreparationError);
  }
});
test('enforce 20MP before browser decode, including zero or oversized dimensions', () => {
  assert.equal(inspectImageHeader(sizedPng(5000, 4000)).width, 5000);
  for (const [width, height] of [[5001, 4000], [0, 12], [0xffffffff, 0xffffffff]]) {
    assert.throws(() => inspectImageHeader(sizedPng(width, height)), rejectsCode('dimensions'));
  }
});
test('JPEG SOF header, malformed segment and oversized dimensions', () => {
  const bytes = new Uint8Array([255, 216, 255, 224, 0, 4, 0, 0, 255, 192, 0, 8, 8, 1, 44, 2, 88, 0, 255, 217]);
  assert.deepEqual(inspectImageHeader(bytes), { mime: 'image/jpeg', width: 600, height: 300 });
  assert.throws(() => inspectImageHeader(new Uint8Array([255, 216, 255, 224, 255, 255])), rejectsCode('decode'));
  bytes[13] = 255; bytes[14] = 255; bytes[15] = 255; bytes[16] = 255;
  assert.throws(() => inspectImageHeader(bytes), rejectsCode('dimensions'));
});
test('WebP lossless/lossy/extended dimensions and corrupt chunks', () => {
  const lossy = new Uint8Array([0, 0, 0, 0x9d, 1, 0x2a, 44, 1, 200, 0]);
  assert.deepEqual(inspectImageHeader(webp('VP8 ', lossy)), { mime: 'image/webp', width: 300, height: 200 });
  const lossless = new Uint8Array(5); lossless[0] = 0x2f;
  new DataView(lossless.buffer).setUint32(1, 299 | (199 << 14), true);
  assert.deepEqual(inspectImageHeader(webp('VP8L', lossless)), { mime: 'image/webp', width: 300, height: 200 });
  const extended = new Uint8Array(10); extended[4] = 43; extended[5] = 1; extended[7] = 199;
  const extendedOnly = webp('VP8X', extended);
  assert.throws(() => inspectImageHeader(extendedOnly), rejectsCode('decode'));
  const withFrame = new Uint8Array(extendedOnly.length + 18);
  withFrame.set(extendedOnly); withFrame.set(webp('VP8 ', lossy).slice(12), extendedOnly.length);
  new DataView(withFrame.buffer).setUint32(4, withFrame.length - 8, true);
  assert.deepEqual(inspectImageHeader(withFrame), { mime: 'image/webp', width: 300, height: 200 });
  withFrame[24] = 12;
  assert.throws(() => inspectImageHeader(withFrame), rejectsCode('decode'));
  extended[0] = 2;
  assert.throws(() => inspectImageHeader(webp('VP8X', extended)), rejectsCode('format'));
  const bad = webp('VP8 ', lossy); new DataView(bad.buffer).setUint32(16, 40000, true);
  assert.throws(() => inspectImageHeader(bad), rejectsCode('decode'));
});
test('output preserves aspect ratio, does not upscale, caps long edge', () => {
  assert.deepEqual(outputDimensions(6000, 3000), { width: 1920, height: 960 });
  assert.deepEqual(outputDimensions(3000, 6000), { width: 960, height: 1920 });
  assert.deepEqual(outputDimensions(320, 240), { width: 320, height: 240 });
  assert.throws(() => outputDimensions(6000, 6000), rejectsCode('dimensions'));
});
test('empty and oversized file fail before touching a browser decoder', async () => {
  await assert.rejects(preparePhoto(new File([], 'empty.jpg')), rejectsCode('empty'));
  await assert.rejects(preparePhoto(new File([new Uint8Array(PHOTO_LIMITS.maxFileBytes + 1)], 'large.jpg')), rejectsCode('too_large'));
  await assert.rejects(preparePhoto(new File(['not a photo'], 'photo.jpg', { type: 'image/jpeg' })), rejectsCode('format'));
});
test('abort is respected before reading and does not return a prepared file', async () => {
  const controller = new AbortController(); controller.abort();
  await assert.rejects(preparePhoto(new File([PNG], 'small.png'), controller.signal), { name: 'AbortError' });
});
test('unknown decoder errors are displayed safely without raw exception text', () => {
  assert.equal(photoErrorMessage(new Error('secret/path?token=hidden')), 'Не удалось прочитать изображение. Файл может быть повреждён. Выберите другое фото.');
  assert.match(photoErrorMessage(new PhotoPreparationError('too_large')), /8 МиБ/);
});

interface BrowserStubOptions { decodeFails?: boolean; output?: Blob | null; width?: number; height?: number; onDecode?: () => void }
async function withSimulatedBrowser(options: BrowserStubOptions, run: (closed: () => number) => Promise<void>): Promise<void> {
  const previousBitmap = Object.getOwnPropertyDescriptor(globalThis, 'createImageBitmap');
  const previousDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  let closes = 0;
  Object.defineProperty(globalThis, 'createImageBitmap', { configurable: true, value: async () => {
    options.onDecode?.();
    if (options.decodeFails) throw new Error('private decoder failure');
    return { width: options.width ?? 2, height: options.height ?? 2, close: () => { closes++; } };
  } });
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { createElement: () => ({
    width: 0, height: 0,
    getContext: () => ({ fillStyle: '', fillRect: () => undefined, drawImage: () => undefined }),
    toBlob: (callback: BlobCallback) => callback(options.output === undefined ? new Blob(['synthetic JPEG encoder stand-in'], { type: 'image/jpeg' }) : options.output),
  }) } });
  try { await run(() => closes); }
  finally {
    if (previousBitmap) Object.defineProperty(globalThis, 'createImageBitmap', previousBitmap); else Reflect.deleteProperty(globalThis, 'createImageBitmap');
    if (previousDocument) Object.defineProperty(globalThis, 'document', previousDocument); else Reflect.deleteProperty(globalThis, 'document');
  }
}

test('simulated browser: decoder failure returns safe visible error', async () => {
  await withSimulatedBrowser({ decodeFails: true }, async () => {
    await assert.rejects(preparePhoto(new File([PNG], 'broken.png')), rejectsCode('decode'));
  });
});
test('simulated browser: null or wrong encoder output fails without a prepared file', async () => {
  for (const output of [null, new Blob(['x'], { type: 'image/png' })]) {
    await withSimulatedBrowser({ output }, async closed => {
      await assert.rejects(preparePhoto(new File([PNG], 'photo.png')), rejectsCode('encode'));
      assert.equal(closed(), 1);
    });
  }
});
test('simulated browser: output File retained unchanged across reads for transport retry', async () => {
  await withSimulatedBrowser({}, async closed => {
    const photo = await preparePhoto(new File([PNG], 'input with metadata.png', { type: 'application/octet-stream' }));
    assert.ok(Object.isFrozen(photo));
    assert.equal(photo.file.type, 'image/jpeg');
    assert.match(photo.file.name, /^photo-.+\.jpg$/);
    assert.equal(photo.originalName, 'input with metadata.png');
    const retryFile = photo.file;
    const first = new Uint8Array(await photo.file.arrayBuffer());
    const second = new Uint8Array(await retryFile.arrayBuffer());
    assert.equal(photo.file, retryFile);
    assert.deepEqual(first, second);
    assert.equal(closed(), 1);
  });
});
test('simulated browser: actual decoded dimensions are checked again', async () => {
  await withSimulatedBrowser({ width: 6000, height: 6000 }, async closed => {
    await assert.rejects(preparePhoto(new File([PNG], 'deceptive.png')), rejectsCode('dimensions'));
    assert.equal(closed(), 1);
  });
});
test('simulated browser: cancellation closes a late bitmap without yielding a file', async () => {
  const controller = new AbortController();
  await withSimulatedBrowser({ onDecode: () => controller.abort() }, async closed => {
    await assert.rejects(preparePhoto(new File([PNG], 'photo.png'), controller.signal), { name: 'AbortError' });
    assert.equal(closed(), 1);
  });
});


test('preparation busy seam: start synchronous, finish exactly once', () => {
  const states: boolean[] = [];
  const activity = beginPhotoPreparation(busy => states.push(busy));
  assert.deepEqual(states, [true]);
  assert.equal(activity.signal.aborted, false);
  activity.finish(); activity.finish();
  assert.deepEqual(states, [true, false]);
});
test('preparation busy seam: cancel/unmount releases busy and aborts work', () => {
  const states: boolean[] = [];
  const activity = beginPhotoPreparation(busy => states.push(busy));
  activity.cancel(); activity.cancel(); activity.finish();
  assert.equal(activity.signal.aborted, true);
  assert.deepEqual(states, [true, false]);
});
test('preparation busy seam: stale completion cannot clear a newer context batch', () => {
  const states: boolean[] = [];
  const onBusyChange = (busy: boolean): void => { states.push(busy); };
  const oldActivity = beginPhotoPreparation(onBusyChange);
  oldActivity.cancel();
  const newActivity = beginPhotoPreparation(onBusyChange);
  oldActivity.finish();
  assert.deepEqual(states, [true, false, true]);
  assert.equal(newActivity.signal.aborted, false);
  newActivity.finish();
  assert.deepEqual(states, [true, false, true, false]);
});
