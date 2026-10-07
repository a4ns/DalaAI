import { ApiError } from '../shared/api/client';

/** A retry failure cannot turn a previously unconfirmed effect into a known failure. */
export function mutationFailureState(error: unknown, previouslyUnknown: boolean): 'unknown_result' | 'conflict' | 'failed' {
  if (previouslyUnknown || (error instanceof ApiError && error.outcomeUnknown)) return 'unknown_result';
  return error instanceof ApiError && error.status === 409 ? 'conflict' : 'failed';
}
