import { ApiError } from '../shared/api/client';

/** A retry failure cannot turn a previously unconfirmed effect into a known failure. */
export function mutationFailureState(error: unknown, previouslyUnknown: boolean): 'unknown_result' | 'conflict' | 'failed' {
  if (previouslyUnknown || (error instanceof ApiError && error.outcomeUnknown)) return 'unknown_result';
  return error instanceof ApiError && error.status === 409 ? 'conflict' : 'failed';
}

export interface IntentLock { status: string; unresolved?: boolean }
export function isIntentUnresolved(intent: IntentLock | undefined): boolean {
  return Boolean(intent && (intent.unresolved || intent.status === 'pending' || intent.status === 'unknown_result'));
}

/** Run the lock check before validation, photo checks, token allocation or any other new-intent work. */
export function withNewIntentGuard(intent: IntentLock | undefined, begin: () => Promise<import('../shared/ui/types').MutationOutcome>): Promise<import('../shared/ui/types').MutationOutcome> {
  if (isIntentUnresolved(intent)) return Promise.resolve({ kind: 'unknown', message: 'Предыдущее действие ещё не подтверждено. Повторите исходную операцию.' });
  return begin();
}
export function canResolveIntent(intent: IntentLock | undefined, resource: { freshness: string; loadStatus: string; incomplete: boolean }): boolean {
  return !isIntentUnresolved(intent) && resource.freshness === 'fresh' && resource.loadStatus === 'ready' && !resource.incomplete;
}
