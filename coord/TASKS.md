# Общая очередь DalaAI / НарядAI

Автор состояния: A0. Снимок подготовки ночи 8 октября 2026, 00:00–09:00 UTC+5; не live-реестр. Текущие назначения, lease и статусы — новые комментарии A0 в https://github.com/a4ns/DalaAI/issues/2 для run `DalaAI-20261008-night` по `NIGHT_RUN.md`. Прежнее «всё не создано» больше не описывает состояние A. Для B/C отсутствие проверенного результата означает UNKNOWN, а не отсутствие работы.

Текущий main на момент снимка: `131188156fd789dee30a66bdd96c3c27da6935fe`. Предшествующий кодовый SHA `be1d1bc9442e4a91a747cebdfb6916b1ca9c9065`: успешный [main/push CI](https://github.com/a4ns/DalaAI/actions/runs/37664427210), включая PostgreSQL readiness/outage/recovery. Это не доказательство business HTTP, frontend, реальных телефонов или будущего SHA. В RUN_OPEN A0 заново фиксирует base и состояние checks.

| ID | Результат | Владелец | Состояние подготовки | Evidence / что осталось |
|---|---|---|---|---|
| BOOT-01 | Активные pod на одном run/base/контракте | A0 | PARTIAL | A работает; B/C collaborator write подтверждён; их подключение, READY, cloud/wake и обмен через issue ещё требуют проверки; не заявлять 21 активный агент |
| A-001 | Контракт, схема, примеры ошибок/событий | A6 | PROPOSED_NOT_FROZEN | `coord/proposals/a6-contract-v1/`, proposal.2; включено в main как предложение; нужны принятие и точный contract hash |
| A-002 | Запуск/health/CI | A5 | FOUNDATION_IN_MAIN | Health/API+PostgreSQL scaffold и CI; business HTTP и frontend этим не подтверждены |
| A-003 | Auth и объектные права | A2 | PURE_MODULES_IN_MAIN | `backend/app/core/`; требуется реальная HTTP/session/CSRF/store-интеграция |
| A-004 | Жизненный цикл, version/operation ID | A1 | PURE_MODULES_IN_MAIN | `backend/app/orders/` и `backend/app/integration/principal_bridge.py`; транзакционные adapters/API ещё не подтверждены |
| A-005 | Сроки/очередь/уведомления | A3 | PACKAGE_PENDING_INTEGRATION | Локальный пакет подготовлен; публикация и реальная доставка не подтверждены; новая внешняя отправка требует разрешения |
| A-006 | Проверка закрытия, AI/rules fallback | A4 | PACKAGE_PENDING_INTEGRATION | Локальный пакет подготовлен; production HTTP/DB и реальный provider/eval не считаются подтверждёнными |
| A-007 | Persistence/миграции/транзакции | A6 | NOT_INTEGRATED | Требуются проверенные adapters, CAS/receipts/events и актуальные DB-backed evidence при CLOSE |
| B-001 | Shared клиент и fixtures | B4 | UNKNOWN | Запросить B0 ветку/result SHA; не считать mock живой интеграцией |
| B-002 | Мастер: выдать наряд | B1 | UNKNOWN | Запросить B0 фактическое состояние и проверки |
| B-003 | Исполнитель: принять/начать/отправить результат | B2 | UNKNOWN | Запросить B0 фактическое состояние и проверки |
| B-004 | Панель смены и reconnect | B3 | UNKNOWN | Запросить B0 фактическое состояние и проверки |
| B-005 | Фото/PWA/сеть | B5 | UNKNOWN | Запросить B0 фактическое состояние и проверки |
| B-006 | Android/UX | B6 | NOT_VERIFIED | Проверка на реальном устройстве отдельно от браузерной симуляции |
| C-001 | Детерминированный synthetic seed | C1 | UNKNOWN | Запросить C0 ветку/result SHA и воспроизводимость |
| C-002 | Независимый eval и rules baseline | C2 | UNKNOWN | Запросить C0 фактический report/условия/ограничения |
| C-003 | Рейтинг и факты аналитики | C3 | UNKNOWN | Запросить C0; backend-пути только по точному GRANT |
| C-004 | Отчёт по наряду/смене | C4 | UNKNOWN | Запросить C0; числа из реальной согласованной БД, не шаблон |
| C-005 | Сквозной e2e/security | C5 | NOT_VERIFIED | Нужен реальный прогон на точном интегрированном SHA |
| C-006 | README/сценарий/комплект | C6 | UNKNOWN | Запросить C0; официальная подача не разрешена этим планом |

Перед RUNNING A0 назначает точные пути/base/contract/branch/generation/lease/reviewer и hard stop `2026-10-08T04:00:00Z`. Сначала один реальный вертикальный путь; отдельные unit/contract passes не закрывают весь пакет. Нет READY одного pod — работать подтверждённым составом; пропускать отсутствующее одобрение нельзя. Обновляет этот снимок только A0 по фактическим событиям журнала.
