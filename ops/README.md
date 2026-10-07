# Локальный backend scaffold

Это инфраструктурная основа, не реализованный производственный сценарий.
Есть FastAPI, PostgreSQL Compose, health/readiness, тесты и CI-конфигурация.
Авторизации, нарядов, миграций, seed, AI и frontend в этом пакете ещё нет.
Health 200 не означает выполнение R01–R07.

## Запуск

Нужны Docker Engine с Compose v2 (`up --wait`) и Python 3.12.
Из корня репозитория:

```sh
make dev
make smoke
```

`make dev` создаёт `.env`, только если его ещё нет, генерирует отдельный
пароль локальной синтетической БД и не выводит его. Файл исключён из Git.
Если `.env` создаётся вручную из `.env.example`, пароль обязателен;
используйте URL-safe символы. Существующая конфигурация не перезаписывается.

API доступен только на `http://127.0.0.1:8000` хоста. PostgreSQL не публикует
порт хоста. Это локальная разработка: TLS, интернет-публикация, реальные
данные и production-права БД требуют отдельной реализации и проверки.
Пользователь БД из официального образа является владельцем локальной БД;
не переносите эти настройки в production.

```sh
make logs
make down
```

`make down` сохраняет PostgreSQL volume. Скрипта удаления/сброса данных нет.
Изменение пароля в `.env` не меняет пароль уже созданной БД в volume.
Не удаляйте volume ради исправления доступа без согласованного решения.

Для другого API-порта задайте `API_PORT` в `.env`, затем используйте, например,
`make smoke BASE_URL=http://127.0.0.1:8001`.

## Проверки без Docker

```sh
make install
make check
```

`make install` создаёт `.venv` и устанавливает точные версии; последующие
Make targets автоматически используют `.venv/bin/python`, если она есть.
`make check` проверяет Python/TOML/YAML syntax и запускает unittest во всём
`backend/tests`, затем проверяет manifest и offline schemas/fixtures A6 proposal.
`make contract-check` выполняет последний шаг отдельно, в временной копии,
не изменяя сохранённое evidence. Это не принятие контракта A0/B0/C0. YAML parsing не заменяет `make compose-check` и живой запуск.
Отдельные Ruff/mypy gates пока не настроены.

Для process-only проверки можно запустить:

```sh
PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1
make smoke-unready
```

Без `DATABASE_URL` `/readyz` обязан вернуть 503. Вне Compose задавайте
`DATABASE_URL` локально, не помещайте реальный пароль в историю shell.

## Значение probes

- `GET /healthz`: процесс отвечает, БД не запрашивается
- `GET /readyz`: 200 только после `SELECT 1`; нет конфигурации, ошибка,
  недоступный драйвер или timeout дают 503
- Readiness ограничен реальным временем: 3 секунды на probe, 2 секунды на
  соединение и SQL statement; это не domain clock
- Ответы не кешируются и не содержат DSN, SQL или exception text
- Readiness проверяет только доступность БД, пока не подтверждает миграции
- OpenAPI/docs отключены до интеграции согласованного доменного контракта

CI устанавливает зависимости заново, запускает unit/HTTP/syntax checks,
собирает образ, проверяет PostgreSQL readiness, выключение БД и восстановление.
Конфигурация CI сама по себе не является результатом успешного CI.

## Границы интеграции

Entrypoint: `app.main:app`; factory: `create_app()`. Импорты из `backend/app`
используют namespace `app`. `/healthz` и `/readyz` инфраструктурные;
доменный `/api/v1` принадлежит A6/A0. Здесь нет миграций и заглушек API,
возвращающих фиктивный успех. Миграции и least-privilege app role должны
появиться перед использованием реальных данных.

Python dependencies зафиксированы целиком для Linux/Python 3.12 в
`backend/requirements.lock` и `requirements-dev.lock`. Это exact-version
pins без supply-chain hashes, не universal cross-platform lock.
FastAPI/Uvicorn и их установленная dependency closure проверены в текущем
runtime; чистая установка всего lock, включая psycopg, требует CI.
Docker image tags фиксируют patch-версии, но не immutable image digest.

## Проверенные источники версий, 2026-10-07

- [FastAPI 0.141.1](https://pypi.org/project/fastapi/0.141.1/)
- [Uvicorn 0.52.1](https://pypi.org/project/uvicorn/0.52.1/)
- [psycopg 3.3.6](https://pypi.org/project/psycopg/3.3.6/)
- [psycopg-binary 3.3.6](https://pypi.org/project/psycopg-binary/3.3.6/)
- [HTTPX 0.28.1](https://pypi.org/project/httpx/0.28.1/)
- [PyYAML 6.0.3](https://pypi.org/project/PyYAML/6.0.3/)
- [Python official image](https://hub.docker.com/_/python): `3.12.15-slim-bookworm`
- [PostgreSQL official image](https://hub.docker.com/_/postgres): `17.11-bookworm`
- [PostgreSQL support](https://www.postgresql.org/support/versioning/)
- [Compose healthy startup](https://docs.docker.com/compose/how-tos/startup-order/)
- [psycopg async connection](https://www.psycopg.org/psycopg3/docs/advanced/async.html)
- [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)
- [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0)

GitHub Actions pinned на полные commit SHA из официальных tag refs.

Для offline проверки proposal дополнительно зафиксированы dev-only версии:
[jsonschema 4.26.0](https://pypi.org/project/jsonschema/4.26.0/),
[attrs 26.1.0](https://pypi.org/project/attrs/26.1.0/),
[jsonschema-specifications 2025.9.1](https://pypi.org/project/jsonschema-specifications/2025.9.1/),
[referencing 0.37.0](https://pypi.org/project/referencing/0.37.0/),
[rpds-py 2026.6.3](https://pypi.org/project/rpds-py/2026.6.3/).
