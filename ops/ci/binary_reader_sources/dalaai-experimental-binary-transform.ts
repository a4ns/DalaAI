/** Public diagnostic candidate only. Not product code or a validated transport repair. */
const TRANSFORM_REPORT_LIMIT = 8 * 1024 * 1024;
const TRANSFORM_REPORT_MIME = { pdf: 'application/pdf', xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' } as const;
export async function readReportFileTransformed(response: Response, format: 'pdf' | 'xlsx', filename: string, assertCurrent: () => void): Promise<{ blob: Blob; filename: string }> {
  const mime = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase();
  if (mime !== TRANSFORM_REPORT_MIME[format] || response.headers.get('Content-Disposition') !== `attachment; filename="${filename}"`) throw new Error('Invalid report headers');
  const length = response.headers.get('Content-Length');
  if (length !== null && (!/^\d+$/.test(length) || !Number.isSafeInteger(Number(length)) || Number(length) > TRANSFORM_REPORT_LIMIT)) throw new Error('Report exceeds byte limit');
  if (!response.body) throw new Error('Missing report body');
  assertCurrent();
  let size = 0; let copied = 0; const head = new Uint8Array(5);
  const limiter = new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      assertCurrent();
      if (!(chunk instanceof Uint8Array) || size + chunk.byteLength > TRANSFORM_REPORT_LIMIT) throw new Error('Report exceeds byte limit');
      size += chunk.byteLength;
      // Own accepted bytes before passing them to the native Blob consumer.
      const owned = new Uint8Array(chunk);
      const prefix = owned.subarray(0, head.length - copied); head.set(prefix, copied); copied += prefix.length;
      controller.enqueue(owned);
    },
    flush() { assertCurrent(); },
  }, { highWaterMark: 1 }, { highWaterMark: 0 });
  // One original-body consumer: no clone, tee, second fetch, or unbounded fallback.
  const bounded = response.body.pipeThrough(limiter);
  const blob = await new Response(bounded, { headers: { 'Content-Type': mime } }).blob();
  assertCurrent();
  if (size === 0 || blob.size !== size || size > TRANSFORM_REPORT_LIMIT) throw new Error('Invalid report size');
  const valid = format === 'pdf' ? size >= 5 && head[0] === 37 && head[1] === 80 && head[2] === 68 && head[3] === 70 && head[4] === 45 : size >= 4 && head[0] === 80 && head[1] === 75 && head[2] === 3 && head[3] === 4;
  if (!valid) throw new Error('Invalid report signature');
  return { blob, filename };
}
