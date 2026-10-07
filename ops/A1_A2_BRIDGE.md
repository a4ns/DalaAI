# A1/A2: локальный интеграционный срез

Статус: review-only, stacked на PR #3, base
`43896ad58644768e86dbc22feaa0e9b9b585cfe4`. Эта база ещё не является принятым
`main`; контракт `1.0.0-proposal.2` остаётся PROPOSED_NOT_FROZEN.

Включены проверенные чистые A1 order rules, A2 session/RBAC policy и явный
`app.integration.principal_bridge.actor_from_auth_context`. Новых dependencies,
HTTP endpoints, database adapters или миграций нет. Health API остаётся прежним.

## Порядок использования будущим adapter

1. В каждом запросе вызвать A2 `authenticate_session` с настоящими серверными
   session/principal stores и real clock. Загружать актуальные active/role/sections;
   не переносить AuthContext между запросами и не создавать его из request JSON
2. Выполнить Origin/CSRF проверки для изменяющего запроса
3. Передать проверенный AuthContext в `actor_from_auth_context`. Bridge проверяет
   типы, active, identity match и revoked, преобразует `user_id` в A1 `Actor.id`,
   явно переводит role и сохраняет неизменяемый набор текущих sections
4. Прочитать актуальный объект и выполнить A2 authorization до receipt lookup.
   Для create используется `require_create_order`, не выдуманный OrderAction.CREATE
5. Для нового operation выполнить A1 планирование и атомарный CAS/receipt/events/
   delivery jobs в одной DB-транзакции. Replays должны возвращать сохранённый
   результат после текущей object authorization; bridge этого не реализует

Bridge не является способом проверки произвольно созданного AuthContext.
Сессии, expiry и текущее состояние аккаунта проверяет A2 authentication boundary
в каждом запросе. Bridge не принимает body/actor/role из HTTP payload и не
создаёт сессии или credentials.

## Обязательные gates перед включением domain HTTP

- Реальные session/PIN/rate-limit stores, cookie/CSRF/Origin adapter
- Receipt uniqueness/CAS/concurrent retry и транзакционность всего MutationPlan
- Атомарное одноразовое присоединение staged photos с owner/section/revision
- При human CLOSE повторно проверить DB-backed attached-photo/material evidence
  под блокировкой той же транзакции либо через обязательный trusted port
- Для CLOSE одних сохранённых photo IDs/completeness/AI score недостаточно.
  A4 deterministic `closure_permitted` должен использовать текущие доверенные
  DB facts; stage TTL и клиентские флаги не заменяют проверку прикреплённого файла
- Никакого автоматического close/rework по результату модели

Этот срез не подтверждает end-to-end закрытие наряда, долговечность данных,
авторизацию HTTP маршрутов, уведомления или работу на телефонах.

## Проверка

`make check` выполняет source/bridge/backend tests и offline contract fixtures.
Новые bridge tests проверяют explicit role mapping, inactive/malformed contexts,
session identity/revocation, запрет request-JSON context, сохранение sections,
отсутствие повышения manager/admin до master и перечитывание principal на новом
запросе. Отдельный независимый reviewer suite проверяется на интегрированном дереве.

При смене базы PR #3 требуется повторное согласование base SHA и aggregate.
