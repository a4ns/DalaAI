import type { CommandResult, Session } from '../../src/shared/api/wire';

/** Synthetic test identities only. These are not accounts or credentials. */
export const ids = {
  first: '10000000-0000-4000-8000-000000000001',
  second: '10000000-0000-4000-8000-000000000002',
  section: '10000000-0000-4000-8000-000000000003',
  equipment: '10000000-0000-4000-8000-000000000004',
  order: '10000000-0000-4000-8000-000000000005',
  event: '10000000-0000-4000-8000-000000000006',
};
export function session(userId = ids.first): Session {
  return {
    principal: { user_id: userId, active: true, employee_code: 'SYNTHETIC-UI-TEST', role: 'master', section_ids: [ids.section], on_shift: true },
    csrf_token: 'synthetic-test-value-not-a-credential', expires_at: '2099-01-01T00:00:00Z',
  };
}
export function result(): CommandResult {
  return {
    order: {
      id: ids.order, number: 'SYNTHETIC-001', version: 2, assignment_revision: 1, scheduling_revision: 1,
      status: 'accepted', type: 'unplanned', description: 'Синтетический наряд для UI-теста', section_id: ids.section,
      equipment_id: ids.equipment, assignment: { executor_id: ids.second, brigade_id: null }, created_by: ids.first,
      issued_at: '2026-10-07T19:00:00Z', due_at: '2026-10-08T04:00:00Z', norm_minutes: 30, priority: 'normal',
      comment: '', before_photo_ids: [], current_submission_id: null, is_overdue: false,
      domain_now: '2026-10-07T19:01:00Z', updated_at: '2026-10-07T19:01:00Z',
    }, event_ids: [ids.event], submission_id: null,
  };
}
export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, refuse) => { resolve = accept; reject = refuse; });
  return { promise, resolve, reject };
}
