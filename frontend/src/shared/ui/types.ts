/** UI state only. Feature view models and wire DTOs remain separate. */
export type Freshness = 'never' | 'fresh' | 'stale';
export type LoadStatus = 'idle' | 'loading' | 'ready' | 'error' | 'offline' | 'unavailable';
export interface ResourceState<T> {
  snapshot: T | null;
  freshness: Freshness;
  loadStatus: LoadStatus;
  error: string | null;
  lastConfirmedAt: string | null;
  incomplete: boolean;
}
export type MutationStatus = 'idle' | 'pending' | 'confirmed' | 'unknown_result' | 'conflict' | 'failed';
export interface MutationState {
  status: MutationStatus;
  error: string | null;
}
export interface UnavailableCapability {
  available: false;
  reason: string;
}
export function initialResource<T>(): ResourceState<T> {
  return { snapshot: null, freshness: 'never', loadStatus: 'idle', error: null, lastConfirmedAt: null, incomplete: false };
}
export type MutationOutcome =
  | { kind: 'confirmed'; message?: string }
  | { kind: 'rejected' | 'conflict' | 'unknown'; message: string };
