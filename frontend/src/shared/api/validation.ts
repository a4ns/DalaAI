import definitions from './wire-schema.json';

type Schema = { $ref?: string; type?: string; const?: unknown; enum?: unknown[]; anyOf?: Schema[]; oneOf?: Schema[]; properties?: Record<string, Schema>; required?: string[]; additionalProperties?: boolean; items?: Schema; minItems?: number; maxItems?: number; uniqueItems?: boolean; minLength?: number; maxLength?: number; pattern?: string; format?: string; minimum?: number; maximum?: number; exclusiveMinimum?: number };
const schemas = definitions as Record<string, Schema>;

/** Small validator for the JSON Schema vocabulary used by the hash-pinned contract. */
function matches(schema: Schema, value: unknown): boolean {
  if (schema.$ref) return matches(schemas[schema.$ref.split('/').at(-1)!], value);
  if ('const' in schema && value !== schema.const) return false;
  if (schema.enum && !schema.enum.includes(value)) return false;
  if (schema.anyOf) return schema.anyOf.some(s => matches(s, value));
  if (schema.oneOf) return schema.oneOf.filter(s => matches(s, value)).length === 1;
  if (schema.type === 'null') return value === null;
  if (schema.type === 'boolean') return typeof value === 'boolean';
  if (schema.type === 'string') {
    if (typeof value !== 'string') return false;
    if (schema.minLength !== undefined && [...value].length < schema.minLength) return false;
    if (schema.maxLength !== undefined && [...value].length > schema.maxLength) return false;
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) return false;
    if (schema.format === 'uuid' && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) return false;
    if (schema.format === 'date-time' && (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value) || !Number.isFinite(Date.parse(value)))) return false;
    return true;
  }
  if (schema.type === 'integer' || schema.type === 'number') {
    return typeof value === 'number' && Number.isFinite(value) && (schema.type !== 'integer' || Number.isSafeInteger(value))
      && (schema.minimum === undefined || value >= schema.minimum) && (schema.maximum === undefined || value <= schema.maximum)
      && (schema.exclusiveMinimum === undefined || value > schema.exclusiveMinimum);
  }
  if (schema.type === 'array') {
    return Array.isArray(value) && (schema.minItems === undefined || value.length >= schema.minItems)
      && (schema.maxItems === undefined || value.length <= schema.maxItems)
      && (!schema.uniqueItems || new Set(value.map(v => JSON.stringify(v))).size === value.length)
      && (!schema.items || value.every(v => matches(schema.items!, v)));
  }
  if (schema.type === 'object') {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
    const object = value as Record<string, unknown>;
    return (schema.required ?? []).every(k => Object.hasOwn(object, k))
      && Object.entries(object).every(([key, field]) => schema.properties?.[key] ? matches(schema.properties[key], field) : schema.additionalProperties !== false);
  }
  return true;
}

export function isWire<T>(name: keyof typeof definitions, value: unknown): value is T {
  return matches(schemas[name], value);
}
export function assertWire(name: keyof typeof definitions, value: unknown): void {
  if (!isWire(name, value)) throw new Error(`Invalid ${name} shape`);
}
