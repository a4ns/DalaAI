import type * as Protocol from '../../src/shared/api/demoClockProtocol';
/** Synthetic shape from backend ClockSnapshot.wire at d4a2932; never a live clock observation. */
export function clock(patch: Partial<Protocol.DemoClockSnapshot> = {}): Protocol.DemoClockSnapshot {
  return { mode: 'synthetic_demo', label: 'Синтетическое демо-время', instance_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', version: 3, scale: 1,
    real_now: '2026-10-08T00:00:00Z', domain_now: '2026-10-09T00:00:00Z', real_anchor: '2026-10-08T00:00:00Z', domain_anchor: '2026-10-09T00:00:00Z', domain_limit: '2026-10-15T00:00:00Z', storage: 'postgres_shared', reset_supported: false, limits: { max_scale: 60, max_advance_seconds: 3600 }, ...patch };
}
