export const object = (v: unknown): v is Record<string, unknown> => Boolean(v && typeof v === 'object' && !Array.isArray(v));
export const text = (v: unknown): v is string => typeof v === 'string' && v.length <= 20000;
export const uuid = (v: unknown): v is string => typeof v === 'string' && /^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(v);
export const integer = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
export const nullable = (check: (v: unknown) => boolean, v: unknown): boolean => v === null || check(v);
export const array = (v: unknown, check: (v: unknown) => boolean, max = 20000): boolean => Array.isArray(v) && v.length <= max && v.every(check);
export const texts = (v: unknown): v is string[] => array(v, text, 200);
export const ids = (v: unknown): v is string[] => array(v, uuid);
export const sameId = (a: string | null, b: string | null): boolean => a === null || b === null ? a === b : a.toLowerCase() === b.toLowerCase();
