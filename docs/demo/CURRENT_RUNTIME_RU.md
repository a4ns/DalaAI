# НарядAI: актуализация выбранной runtime-версии

Срез сведений: **2026-10-07 20:20 UTC**. Выбранный принятый backend:
`dfe9d8f7772b1a1c44f5a506c03e26c55fb5e1ca`.
Это конкретный снимок исправленной factory, **не утверждение о latest main**.
Исходный пакет C6 `3708866f48b5e885db586f2e8c213be45ef0dad4` и его проверки
на коде f3 сохраняются историческими; эта актуализация не переписывает их.

C6 прочитал source и журнал, но **не запускал** на dfe9 приложение, PostgreSQL,
новые backend suites, браузер, модель или устройство. Машиночитаемое разделение
собственных и внешних сведений: [runtime-dfe9.json](../evidence/run/runtime-dfe9.json).

## Что изменилось по сравнению с f3

Сверено непосредственно с `backend/app/main.py` и `backend/app/runtime.py`
на указанном SHA:

- `DALA_API_MODE=health` остаётся режимом по умолчанию: только health/readiness
- Явный `DALA_API_MODE=demo` теперь монтирует реальные session, command и
  discovery routers. Называть весь этот backend «health-only» уже неверно
- Session routes: POST `/api/v1/auth/login`, GET `/api/v1/me`, POST `/api/v1/auth/logout`
- Command/read routes: POST `/api/v1/orders`, POST `/api/v1/orders/{order_id}/commands`,
  GET `/api/v1/orders/{order_id}`, GET `/api/v1/orders/{order_id}/submissions/{submission_id}`
- Discovery routes: GET `/api/v1/orders`, GET `/api/v1/dicts`
- Demo lifespan проверяет настоящую БД: отдельный restricted LOGIN, необходимые
  таблицы/колонки/триггеры и точные разрешения. Owner/superuser и опасные grants
  не являются запасным способом запуска
- В demo mode readiness проверяет эти prerequisites, а не только `SELECT 1`.
  Неуспешная runtime readiness закрывает доступ к API до исправления и перезапуска;
  до завершения startup API также не принимается
- `UnavailablePhotoReferences` намеренно заменяет persisted `file_valid` на unknown.
  Флаг в БД не доказывает физическую целостность фото. Не обещать успешное закрытие
  результата с photo evidence до принятого blob/upload adapter

Миграции, использованные runtime acceptance, находятся в
`backend/db/migrations/{001_vertical_slice,002_trusted_evidence,004_immutable_reference_keys}.sql`
и `backend/db/proposals/003_auth_rate_limits.sql`. C6 **не применял** их.
Текст старых README может описывать прежний candidate; authoritative здесь —
точный код и отдельно атрибутированные результаты, а не заголовок документа.

## Минимальная команда запуска явного demo API

Это исходниково подтверждённая команда процесса, **ещё не one-command demo**.
Исполнять только в checkout выбранного backend SHA, с установленными его
зависимостями и после подготовки владельцем изолированной БД/синтетических ролей.
Ветка исторических C6-документов сама по себе этот backend не содержит.

Предварительно должны быть безопасно предоставлены:

1. `DATABASE_URL` для уже созданного restricted runtime LOGIN; C6 не создаёт,
   не читает и не выводит DSN/пароль, не подставляет owner connection
2. `DALA_DATABASE_SCHEMA` для уже применённой и подготовленной схемы (default
   `public` не означает, что подходящая схема существует)
3. `DALA_ALLOWED_ORIGIN` — один **реально предоставленный** точный HTTPS-origin
   без path/query/credentials/wildcard; Host и same-origin защита остаются включены
4. Согласованный HTTPS reverse proxy/serving seam, когда требуется настоящий
   браузерный login с Secure host-only cookie. Локальный upstream HTTP ниже
   сам по себе этого не создаёт; публичный URL в этом пакете отсутствует

```sh
DALA_API_MODE=demo PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18606 \
  --no-proxy-headers --no-access-log
```

Флаги `--no-proxy-headers --no-access-log` следуют `ops/MOUNTED_RUNTIME.md`
этого SHA: forwarded headers не считаются доверенными до принятой настройки
ingress, access logs не включаются неявно.

Не копировать вымышленные учётные записи или значения origin. Не открывать
секретные файлы без разрешения. Команда не применяет миграции, не создаёт роли,
не делает seed и не включает модель/доставку. Если предпосылок нет — остановиться
с точной причиной; не отключать startup/Host/origin/CSRF проверки.

Для отдельной process-only диагностики доступен явный health mode:

```sh
env -u DATABASE_URL DALA_API_MODE=health PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 18606 --no-proxy-headers --no-access-log
make smoke-unready BASE_URL=http://127.0.0.1:18606
```

Это две команды для двух терминалов; остановить только свой процесс.
**C6 не исполнял их на dfe9**. Исторический smoke на f3 не переносится сюда.
`make dev` на dfe9 всё ещё использует старый Compose с owner-style локальной БД
и без demo-переменных; его успешный запуск нельзя назвать готовым demo runtime.
Не включать demo mode поверх owner DSN для обхода подготовки.

## Что подтверждено кем

| Доказательство | Источник и предел |
|---|---|
| Исправленная mounted factory и 275 aggregate, real factory lifecycle | A0 сообщил PASS в [A0-0026](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6045765569), branch CI 37677929971. C6 не повторял тесты и не проверял exact CI head; свежий main CI в том сообщении pending |
| Published C2 `936e4327337b1aa3683021d3fd12dc9c987363ee` | [C0-0008](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6045230484): exact published rerun — 22 tests, 48 authored synthetic episodes. Исторический сохранённый report измеряет `10c8e4d859190c3ad6b6241388aace7e00b69884`, а не новый backend |
| Границы C2 eval | 24 dev + 24 holdout; mandatory expectations 24/24 в каждом, critical false permits 0/18 в каждом. Semantic abstention 24/24 в каждом. Это synthetic rules conformance, не semantic AI accuracy; model NOT_RUN, cost null |
| B shell `633beec6de954b45160361c2ea2bc41c1e99fae6` | C5 artifact `a9a8ee59e26c20e271277ff446889ccee5b45665`: locked install/build/type/lint и локальный HTTP200; не собранный пользовательский путь. C6 ранее проверил hash/source evidence |
| Реальный cloud-browser render | У C5 navigation к локальному origin: `net::ERR_BLOCKED_BY_CLIENT`. RU/console/390px/focus/no-fake-mutation — NOT_RUN. Доступность blank-tab и HTTP200 не заменяют рендер и не разрешают обход ограничения |
| Более новая B assembly | [B0-0029](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6045981387) сообщает WIP `b51d6577b0e3b0a10dd063f1a1c946e804633c07`; это не final integration/runtime acceptance и C6 его не запускал |

C2 опубликован в `eval/**`. Отсутствие `backend/eval/` в старой таблице не
означает, что eval-пакета вообще нет. Наличие отдельной frontend ветки не
означает, что она уже включена в выбранный backend SHA или проверена с ним.

## Исправление короткого питча без выдуманного live-успеха

Сохранить регламент **3:00 питч + отдельно 3:00 вопросы** и отдельную длинную
device-репетицию. Для свежего выступления заменить исторический блок
«пользовательский маршрут не подключён» следующими репликами:

«В принятой версии backend есть явный demo-режим: login, команды нарядов и
каталоги подключены к application factory с проверкой ограниченной роли БД.
Команда A сообщила об успешном реальном API/БД lifecycle. Мы отделяем этот
результат от пока не проверенного здесь browser/phone пути».

«Наш опубликованный offline eval проверяет обязательные правила на 48
синтетических примерах. В вопросах смысла работ правила воздерживаются от
оценки. Это не испытание внешней модели и не промышленная точность».

«Фото, новый assembled UI, реальная модель и физическая доставка должны иметь
собственные evidence на совпадающем кандидате. Неизвестный результат остаётся
неизвестным; финальное решение принимает мастер».

Не демонстрировать fake login, не показывать shell как законченный мобильный
цикл и не переносить старые синтетические оценки в human score.

## Следующие точные пробелы

- От A0/A5: фактический authorized same-origin serving seam, изолированная
  подготовленная схема и безопасный operator login/bootstrap; не выдуманные URL/PIN
- Принятый frontend assembly + этот backend в одном проверяемом кандидате,
  затем повтор C5 browser journey; отсутствие browser доступа остаётся явным
- В выбранном dfe9 не смонтированы GET `/api/v1/orders/{order_id}/events`,
  POST `/api/v1/photos/stage` и GET `/api/v1/photos/{photo_id}`. B0 UI уже
  обращается к history/photo seam; API более нового SHA требует новой сверки
- Реальный upload/private blob validation и подключение для close; действующая
  проблема фото не скрывается DB-флагом или mock-success
- История 500+ за ≥3 месяца: воспроизводимый synthetic export отдельно от
  безопасного DB importer; historical dates не отправляются live POST
- Отчёты/аналитика, модель, push, Android камера/доставка и timings — отдельные
  модули и проверки, без подразумеваемого PASS от API или unit tests

Последний прочитанный приоритет [A0-0027](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6045948478)
отменяет предыдущую цель ночного деплоя и делает WebPush основным направлением,
Telegram выключенным. Это план команды A, не подтверждение реализации,
публикации или разрешение C на расходы/секреты/доставку. C сохраняет собственный
hard stop `2026-10-08T04:00:00Z`; эта документация ничего не развёртывает и не отправляет.
