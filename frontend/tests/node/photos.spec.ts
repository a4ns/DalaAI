import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import type * as Photo from '../../src/pwa/photoPreparation';
import type * as Connectivity from '../../src/pwa/useConnectivity';
const photo = sourceModule<typeof Photo>('src/pwa/photoPreparation.ts');
const connectivity = sourceModule<typeof Connectivity>('src/pwa/useConnectivity.ts');

function png(width: number, height: number): Uint8Array {
  const bytes = new Uint8Array(24);
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10]);
  const view = new DataView(bytes.buffer);
  view.setUint32(8, 13); bytes.set([73, 72, 68, 82], 12); view.setUint32(16, width); view.setUint32(20, height);
  return bytes;
}

test('photos: header preflight rejects zero and decompression-bomb dimensions before decoding', () => {
  expect(photo.inspectImageHeader(png(4000, 3000))).toEqual({ mime: 'image/png', width: 4000, height: 3000 });
  for (const [width, height] of [[0, 10], [10, 0], [5000, 5000], [0xffffffff, 0xffffffff]]) expect(() => photo.inspectImageHeader(png(width, height))).toThrow(photo.PhotoPreparationError);
});

test('photos: spoofed MIME, SVG content and truncated bytes are not accepted as a decoded image', async () => {
  for (const bytes of [new Uint8Array(), new TextEncoder().encode('<svg><script/></svg>'), new Uint8Array([0xff, 0xd8, 0xff])]) expect(() => photo.inspectImageHeader(bytes)).toThrow(photo.PhotoPreparationError);
  const forged = new File(['<svg/>'], 'forged.jpg', { type: 'image/jpeg' });
  await expect(photo.preparePhoto(forged)).rejects.toMatchObject({ code: 'format' });
});

test('photos: file size and cancellation are checked before unsupported browser access', async () => {
  await expect(photo.preparePhoto(new File([], 'empty.png'))).rejects.toMatchObject({ code: 'empty' });
  await expect(photo.preparePhoto(new File([new Uint8Array(photo.PHOTO_LIMITS.maxFileBytes + 1)], 'large.png'))).rejects.toMatchObject({ code: 'too_large' });
  const abort = new AbortController(); abort.abort();
  await expect(photo.preparePhoto(new File(['bytes'], 'aborted.png'), abort.signal)).rejects.toMatchObject({ name: 'AbortError' });
});

test('photos: target size does not enlarge small images or exceed1920 on either orientation', () => {
  expect(photo.outputDimensions(4000, 3000)).toEqual({ width: 1920, height: 1440 });
  expect(photo.outputDimensions(3000, 4000)).toEqual({ width: 1440, height: 1920 });
  expect(photo.outputDimensions(100, 50)).toEqual({ width: 100, height: 50 });
});

test('photos: online hint and prepared selection never claim delivery', () => {
  expect(connectivity.connectivityMessage('online')).toContain('подтверждаются отдельно');
  expect(connectivity.connectivityMessage('offline')).toContain('Автоматической отправки нет');
  expect(connectivity.connectivityMessage('unknown')).toContain('только ответом сервера');
});

test('photos: preparation busy is synchronous and releases exactly once after any finish/cancel sequence', () => {
  const { beginPhotoPreparation } = sourceModule<typeof import('../../src/pwa/preparationActivity')>('src/pwa/preparationActivity.ts');
  for (const actions of [['finish', 'finish', 'cancel'], ['cancel', 'finish', 'cancel']] as const) {
    const states: boolean[] = [];
    const activity = beginPhotoPreparation(value => states.push(value));
    expect(states).toEqual([true]);
    for (const action of actions) activity[action]();
    expect(states).toEqual([true, false]);
    expect(activity.signal.aborted).toBe(true);
  }
});

test('photos: completion from a canceled context cannot release a new preparation batch', () => {
  const { beginPhotoPreparation } = sourceModule<typeof import('../../src/pwa/preparationActivity')>('src/pwa/preparationActivity.ts');
  let busy = false;
  const old = beginPhotoPreparation(value => { busy = value; });
  old.cancel();
  const current = beginPhotoPreparation(value => { busy = value; });
  old.finish(); old.cancel();
  expect(busy).toBe(true);
  expect(current.signal.aborted).toBe(false);
  current.finish();
  expect(busy).toBe(false);
});
