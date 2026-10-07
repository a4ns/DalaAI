import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { json } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as Failure from '../../src/app/mutationFailure';
const { ApiClient, ApiError, LoginError, safeErrorMessage } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { mutationFailureState } = sourceModule<typeof Failure>('src/app/mutationFailure.ts');
const credentials = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };

test('rejected login credentials get corrective copy distinct from expiry of an authenticated session', async () => {
  const client = new ApiClient({ online: () => true, fetch: async () => json({}, 401) });
  const failure = await client.login(credentials).catch(error => error as unknown);
  expect(failure).toBeInstanceOf(LoginError);
  expect(failure).toMatchObject({ loginOutcome: 'rejected', outcomeUnknown: false, status: 401 });
  expect(safeErrorMessage(failure)).toContain('табельный код и PIN');
  expect(safeErrorMessage(failure)).not.toContain('Сессия завершена');
  expect(safeErrorMessage(new ApiError('Synthetic authenticated expiry', 401))).toContain('Сессия завершена');
});

test('login post-send losses and malformed successes remain unknown without domain-operation semantics or auto retries', async () => {
  for (const kind of ['network', '503', 'malformed-200', 'wrong-201'] as const) {
    let sends = 0;
    const client = new ApiClient({ online: () => true, fetch: async () => {
      sends += 1;
      if (kind === 'network') throw new TypeError('Synthetic post-send loss');
      return json({}, kind === '503' ? 503 : kind === 'wrong-201' ? 201 : 200);
    } });
    const failure = await client.login(credentials).catch(error => error as unknown);
    expect(failure).toBeInstanceOf(LoginError);
    expect(failure).toMatchObject({ loginOutcome: 'unknown', outcomeUnknown: false });
    expect(safeErrorMessage(failure)).toContain('запрос входа не подтверждён');
    expect(safeErrorMessage(failure)).not.toContain(credentials.pin);
    expect(safeErrorMessage(failure)).not.toContain('тот же запрос');
    expect(client.session).toBeNull();
    expect(sends).toBe(1);
  }
});

test('known offline login says not sent and performs no fetch', async () => {
  let sends = 0;
  const client = new ApiClient({ online: () => false, fetch: async () => { sends += 1; return json({}); } });
  const failure = await client.login(credentials).catch(error => error as unknown);
  expect(failure).toMatchObject({ loginOutcome: 'rejected', status: 0, transportInterrupted: false });
  expect(safeErrorMessage(failure)).toContain('Запрос входа не отправлен');
  expect(sends).toBe(0);
});

test('incomplete submission copy explains missing evidence while preserving any earlier unresolved outcome', () => {
  const problem = { code: 'INCOMPLETE_SUBMISSION' as const, message: 'Synthetic incomplete result', request_id: 'synthetic-request', retryable: false, current_version: null, field_errors: [] };
  const known = new ApiError('Synthetic server refusal', 409, problem);
  expect(safeErrorMessage(known)).toContain('обязательных доказательств');
  expect(safeErrorMessage(known)).not.toContain('Данные изменились');
  expect(mutationFailureState(known, false)).toBe('failed');
  expect(mutationFailureState(known, true)).toBe('unknown_result');
  const unknown = new ApiError('Synthetic uncertain request', 409, problem, true);
  expect(safeErrorMessage(unknown)).toContain('Результат операции не подтверждён');
  expect(mutationFailureState(unknown, false)).toBe('unknown_result');
});
