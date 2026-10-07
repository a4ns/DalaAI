/** Local preparation only. The server still validates bytes, ownership and limits. */
export const PHOTO_LIMITS = Object.freeze({
  maxFileBytes: 8 * 1024 * 1024,
  maxPixels: 20_000_000,
  maxPhotos: 5,
  maxEdge: 1920,
  targetBytes: 1_500_000,
});

export type PhotoPhase = 'before' | 'after';
export interface PreparedPhoto {
  readonly id: string;
  /** Blob/File bytes are immutable. Keep this exact File for every transport retry. */
  readonly file: File;
  readonly originalName: string;
  readonly originalBytes: number;
  readonly width: number;
  readonly height: number;
  /** Local preparation time, never evidence of capture time. */
  readonly preparedAt: string;
}

export type PhotoErrorCode = 'empty' | 'too_large' | 'format' | 'dimensions' | 'decode' | 'encode' | 'unsupported';
const messages: Record<PhotoErrorCode, string> = {
  empty: 'Файл пустой. Выберите другое фото.',
  too_large: 'Фото больше 8 МиБ. Уменьшите размер файла или выберите другое фото.',
  format: 'Нужен настоящий файл JPEG, PNG или WebP. Переименование файла не меняет его формат.',
  dimensions: 'Фото превышает 20 мегапикселей или имеет неверные размеры. Выберите фото меньшего разрешения.',
  decode: 'Не удалось прочитать изображение. Файл может быть повреждён. Выберите другое фото.',
  encode: 'Не удалось подготовить фото. Выберите другое фото или попробуйте ещё раз.',
  unsupported: 'Этот браузер не поддерживает подготовку фото. Откройте приложение в современном браузере.',
};
export class PhotoPreparationError extends Error {
  readonly code: PhotoErrorCode;
  constructor(code: PhotoErrorCode) {
    super(messages[code]);
    this.name = 'PhotoPreparationError';
    this.code = code;
  }
}
export function photoErrorMessage(error: unknown): string {
  return error instanceof PhotoPreparationError ? error.message : messages.decode;
}

export interface ImageHeader { mime: 'image/jpeg' | 'image/png' | 'image/webp'; width: number; height: number }
const fail = (code: PhotoErrorCode): never => { throw new PhotoPreparationError(code); };
function checked(header: ImageHeader): ImageHeader {
  if (!Number.isSafeInteger(header.width) || !Number.isSafeInteger(header.height) ||
      header.width < 1 || header.height < 1 || header.width * header.height > PHOTO_LIMITS.maxPixels) {
    return fail('dimensions');
  }
  return header;
}

/** Reject oversized dimensions before handing compressed bytes to a browser decoder. */
export function inspectImageHeader(bytes: Uint8Array): ImageHeader {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const ascii = (offset: number, text: string): boolean => [...text].every((char, i) => bytes[offset + i] === char.charCodeAt(0));
  if (bytes.length >= 24 && bytes[0] === 137 && ascii(1, 'PNG\r\n\x1a\n')) {
    if (!ascii(12, 'IHDR') || view.getUint32(8) !== 13) return fail('decode');
    return checked({ mime: 'image/png', width: view.getUint32(16), height: view.getUint32(20) });
  }
  if (bytes.length >= 4 && bytes[0] === 0xff && bytes[1] === 0xd8) {
    let offset = 2;
    while (offset + 1 < bytes.length) {
      if (bytes[offset++] !== 0xff) return fail('decode');
      while (bytes[offset] === 0xff) offset++;
      const marker = bytes[offset++];
      if (marker === 0xd9 || marker === 0xda) break;
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
      if (offset + 2 > bytes.length) return fail('decode');
      const length = view.getUint16(offset);
      if (length < 2 || offset + length > bytes.length) return fail('decode');
      const startOfFrame = marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker);
      if (startOfFrame) {
        if (length < 8) return fail('decode');
        return checked({ mime: 'image/jpeg', height: view.getUint16(offset + 3), width: view.getUint16(offset + 5) });
      }
      offset += length;
    }
    return fail('decode');
  }
  if (bytes.length >= 20 && ascii(0, 'RIFF') && ascii(8, 'WEBP')) {
    // A WebP may contain metadata before its image chunk. Never trust MIME alone.
    let offset = 12;
    let canvasHeader: ImageHeader | undefined;
    while (offset + 8 <= bytes.length) {
      const length = view.getUint32(offset + 4, true);
      const data = offset + 8;
      if (data + length > bytes.length) return fail('decode');
      const uint24 = (at: number): number => bytes[at] + (bytes[at + 1] << 8) + (bytes[at + 2] << 16);
      if (ascii(offset, 'VP8X') && length >= 10) {
        // Animated WebP is not a still-photo input; avoid frame-decoder surprises.
        if (bytes[data] & 0x02) return fail('format');
        canvasHeader = checked({ mime: 'image/webp', width: 1 + uint24(data + 4), height: 1 + uint24(data + 7) });
      }
      if (ascii(offset, 'VP8 ') && length >= 10 && bytes[data + 3] === 0x9d && bytes[data + 4] === 1 && bytes[data + 5] === 0x2a) {
        const frame = checked({ mime: 'image/webp', width: view.getUint16(data + 6, true) & 0x3fff, height: view.getUint16(data + 8, true) & 0x3fff });
        if (canvasHeader && (canvasHeader.width !== frame.width || canvasHeader.height !== frame.height)) return fail('decode');
        return frame;
      }
      if (ascii(offset, 'VP8L') && length >= 5 && bytes[data] === 0x2f) {
        const packed = view.getUint32(data + 1, true);
        const frame = checked({ mime: 'image/webp', width: 1 + (packed & 0x3fff), height: 1 + ((packed >>> 14) & 0x3fff) });
        if (canvasHeader && (canvasHeader.width !== frame.width || canvasHeader.height !== frame.height)) return fail('decode');
        return frame;
      }
      offset = data + length + (length % 2);
    }
    return fail('decode');
  }
  return fail('format');
}

export function outputDimensions(width: number, height: number): { width: number; height: number } {
  checked({ mime: 'image/jpeg', width, height });
  const scale = Math.min(1, PHOTO_LIMITS.maxEdge / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

function checkAbort(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Подготовка отменена', 'AbortError');
}
interface DecodedImage { source: CanvasImageSource; width: number; height: number; close: () => void }
async function decode(file: Blob, signal?: AbortSignal): Promise<DecodedImage> {
  checkAbort(signal);
  if (typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
      if (signal?.aborted) { bitmap.close(); checkAbort(signal); }
      return { source: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close() };
    } catch (error) {
      checkAbort(signal);
      // The image-element path also covers browsers with partial bitmap support.
      if (typeof Image === 'undefined') throw error;
    }
  }
  if (typeof Image === 'undefined' || typeof URL.createObjectURL !== 'function') return fail('unsupported');
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    const clean = (): void => { signal?.removeEventListener('abort', abort); image.onload = null; image.onerror = null; URL.revokeObjectURL(url); };
    const abort = (): void => { clean(); image.src = ''; reject(new DOMException('Подготовка отменена', 'AbortError')); };
    image.onload = () => { clean(); resolve({ source: image, width: image.naturalWidth, height: image.naturalHeight, close: () => { image.src = ''; } }); };
    image.onerror = () => { clean(); reject(new PhotoPreparationError('decode')); };
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) { abort(); return; }
    image.src = url;
  });
}

function encode(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => blob && blob.size > 0 && blob.type === 'image/jpeg'
      ? resolve(blob) : reject(new PhotoPreparationError('encode')), 'image/jpeg', quality);
  });
}

export async function preparePhoto(file: File, signal?: AbortSignal): Promise<PreparedPhoto> {
  checkAbort(signal);
  if (file.size === 0) return fail('empty');
  if (file.size > PHOTO_LIMITS.maxFileBytes) return fail('too_large');
  const header = inspectImageHeader(new Uint8Array(await file.arrayBuffer()));
  checkAbort(signal);
  if (typeof document === 'undefined') return fail('unsupported');
  let decoded: DecodedImage;
  try {
    // Give decoder the verified format, not a forged user-provided MIME value.
    decoded = await decode(file.slice(0, file.size, header.mime), signal);
  } catch (error) { checkAbort(signal); if (error instanceof PhotoPreparationError) throw error; return fail('decode'); }
  const canvas = document.createElement('canvas');
  try {
    checkAbort(signal);
    const size = outputDimensions(decoded.width, decoded.height);
    canvas.width = size.width;
    canvas.height = size.height;
    const context = canvas.getContext('2d');
    if (!context) return fail('unsupported');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, size.width, size.height);
    context.drawImage(decoded.source, 0, 0, size.width, size.height);
    let blob = await encode(canvas, 0.84);
    for (const quality of [0.72, 0.6]) {
      checkAbort(signal);
      if (blob.size <= PHOTO_LIMITS.targetBytes) break;
      blob = await encode(canvas, quality);
    }
    checkAbort(signal);
    if (blob.size > PHOTO_LIMITS.maxFileBytes) return fail('too_large');
    const id = globalThis.crypto?.randomUUID?.() ?? `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return Object.freeze({ id, file: new File([blob], `photo-${id}.jpg`, { type: 'image/jpeg' }),
      originalName: file.name, originalBytes: file.size, ...size, preparedAt: new Date().toISOString() });
  } catch (error) {
    checkAbort(signal);
    if (error instanceof PhotoPreparationError) throw error;
    return fail('encode');
  } finally { decoded.close(); canvas.width = 0; canvas.height = 0; }
}
