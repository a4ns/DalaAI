# НарядAI демонстрация проверенных runtime этапов

Срез **2026-10-07 23:07 UTC** для владельца демонстрации. Есть проверенный
ручной UI/API/PostgreSQL цикл в Android-эмуляции и более новый runtime с
историей и защищёнными отчётами. Это **два отдельных SHA**, не общий PASS
финального кандидата. C-106 сверил исходники, публичные CI-метаданные и
разрешённый count-only артефакт; сам приложение, БД и браузер не запускал.

Этот документ дополняет исторические [f3 runbook](README.md) и
[dfe9 source-срез](CURRENT_RUNTIME_RU.md). [Offline runner](OFFLINE_RUN_RU.md)
остаётся отдельным воспроизводимым synthetic evidence; его результаты
не объявляются runtime, моделью или физическим Android.

## Что можно утверждать

1. **Ручной мобильный цикл:** backend
   `ab632c0cf411b7670c1a03fe7aa97419950019a2`, frontend
   `ca320bf692c01d89dd79496fe18d1bc2742052df`, C110
   `23a135348a0e8ad9a140a36ca60e8440704b7893`.
   [mobile-core PASS](https://github.com/a4ns/DalaAI/actions/runs/37697793713/job/113053699040):
   1 тест, 6 этапов, 11 committed команд, 13 persisted событий, 0 skips.
   Два независимых Chromium-сеанса Pixel 7 Android emulation, настоящие
   UI/API/БД; успешные бизнес-ответы не подменены. AI/delivery/provider workers
   выключены. Это ручная приёмка мастером, **не проверка rules fallback**.
2. **История и mounted отчёты:** backend
   `f101e4320b59b0a7dc81bdcb8b28c73849d4a747`.
   [history-demo PASS](https://github.com/a4ns/DalaAI/actions/runs/37698758395/job/113056852691):
   10 actual PostgreSQL history/live/report cases, 0 skips.
   [postgres PASS](https://github.com/a4ns/DalaAI/actions/runs/37698758299/job/113056852440)
   включает report gates: 8 author + 8 restricted LOGIN + 1 actual `app.main`.
   Исходники C108 `711e2fbd69598d06f43da9ff47de60d2c569634c`,
   C109 `e999232014be8b16717058c6d9b70b41dec75c89` и
   C111 `2945e3d3b6ba187a510cfb715e22d9feb70c4408` в этом runtime сверены
   по Git blob. Это не доказательство готового frontend analytics экрана.

Все три run проверены как `push/main`, `completed/success` на указанных SHA.
Сохранены [проверенные метаданные и границы](../evidence/run/runtime-f101-milestones.json)
и [неизменённый public mobile summary](../evidence/run/mobile-ab632c0-summary.json).
Summary прямо фиксирует `full_cycle_green=false`. Его upstream ZIP SHA-256:
`c86c34a52994bc405a6ccb9f8b0fbc0ef154169aafd80df5990d9d21cd6addf0`;
GitHub artifact expires `2026-10-14T22:43:55Z`.

## Короткий показ до трёх минут

Это предлагаемый порядок, **не измеренная репетиция**. До показа оператор
получает от A0 точный собранный SHA, рабочий origin, подготовленную изолированную
синтетическую БД и два разрешённых сеанса. Этот документ не создаёт эти условия
и не содержит login-секретов. Новый SHA требует новой проверки сборки.

1. **0:00–0:20.** Назвать проблему и показать «Синтетические данные».
   Объяснить: исполнитель сообщает результат, окончательное решение у мастера.
2. **0:20–1:00.** Мастер создаёт свежий внеплановый наряд штатной RU-формой;
   исполнитель принимает и начинает. Короткий показ сокращает реплики,
   а не выдаёт заранее внесённую запись за только что выполненную команду.
3. **1:00–1:50.** Показать неполный результат и невозможность закрыть его;
   мастер возвращает на доработку. Исполнитель добавляет работы, шифр,
   материал и разрешённое synthetic PNG через настоящий upload. Мастер
   закрывает вручную; отсутствующая human score остаётся «не оценено».
   Отсутствующий AI assessment означает отсутствие оценки, а не её успех.
4. **1:50–2:25.** Показать историю действий. Отдельно открыть защищённый
   runtime-отчёт только если этот конкретный demo instance уже подготовлен
   и проверен. Иначе показать приведённое CI evidence с явным названием SHA,
   не обещая доступный UI-экран или отчёт на прежнем manual-core SHA.
5. **2:25–3:00.** Назвать ограничения: эмуляция, synthetic PNG, синтетическая
   история; модель, физический телефон, доставка и экспорт требуют своих gates.

Для расширенного показа сохранить весь подтверждённый порядок:
создать → очередь → принять → начать → пауза с причиной → продолжить →
неполный результат → доработка → повторная работа и upload → ручное закрытие →
история. Точные действия и границы:
[C110 сценарий на проверенном source SHA](https://github.com/a4ns/DalaAI/blob/23a135348a0e8ad9a140a36ca60e8440704b7893/tests/e2e/c110_README.md).
Synthetic PNG не является снимком камеры или доказательством ремонта.

## Как показывать историю и отчёт

На **f101e4320b59b0a7dc81bdcb8b28c73849d4a747** смонтированы GET
`/api/v1/analytics/shift`, `/api/v1/reports/shift` и
`/api/v1/reports/orders/{order_id}`. Для всех нужны `start` и `end` с зоной;
период полуоткрытый `[start,end)`, не позднее server domain time, максимум
93 дня. Отчёты поддерживают `format=json` и `format=html`; HTML инертный,
русский. Это не PDF/XLSX и не гарантия наличия кнопки в frontend.
Источник: [принятый runtime HTTP контракт](https://github.com/a4ns/DalaAI/blob/f101e4320b59b0a7dc81bdcb8b28c73849d4a747/docs/analytics/runtime-http.md).

Для проверенной полной истории использовать master scope всех четырёх участков
и период `[2026-07-01T00:00:00Z, 2026-10-01T00:00:00Z)`:
**540 выданных synthetic нарядов, 568 попыток результата, 444 недоступные
исторические after-photo ссылки**. Это metadata-only история без импортированных
image rows/bytes. Видимые признаки:
`synthetic_historical_evidence_unavailable`, `physical_evidence_verified=false`,
`historical_completeness_is_verified_evidence=false`.
Меньший разрешённый scope не обязан давать эти общие числа.

Не подменять `issued` числом `closed`, количество попыток числом нарядов,
AI score человеческой оценкой, историческую полноту успешным live close.
Сегодняшняя смена не должна считать июль–сентябрь сегодняшней выдачей.
Исторические неактивные исполнители не становятся live-аккаунтами;
свежий наряд создаётся с текущим временем штатным API/UI.
Источник: [проверенный history/live пакет](https://github.com/a4ns/DalaAI/blob/f101e4320b59b0a7dc81bdcb8b28c73849d4a747/ops/provision/HISTORY_DEMO.md).

## Существующие команды проверки для A5

Ни одна команда ниже не исполнялась C-106. Это ссылки на существующие gates,
**не новые инструкции настройки**. Их запускает уполномоченный A5 в своей
одноразовой среде с уже разрешёнными inputs; C-106 не читает PIN/secret files,
не создаёт доступы и не подключается к БД. Нельзя запускать их в рабочей БД.

| Проверяемый source SHA | Существующая команда и источник | Граница |
|---|---|---|
| `ab632c0cf411b7670c1a03fe7aa97419950019a2` | `python ops/ci/run_mobile.py --report mobile-ci-summary.json` — [CI runbook](https://github.com/a4ns/DalaAI/blob/ab632c0cf411b7670c1a03fe7aa97419950019a2/ops/ci/README.md) | Требует точного frontend reference, disposable Compose и fresh secrecy preflight; ручной core |
| `f101e4320b59b0a7dc81bdcb8b28c73849d4a747` | `python ops/run_history_demo_tests.py --with-reports` — [runner](https://github.com/a4ns/DalaAI/blob/f101e4320b59b0a7dc81bdcb8b28c73849d4a747/ops/run_history_demo_tests.py) | 10 PG cases; history/live/report, не готовый browser demo |
| `f101e4320b59b0a7dc81bdcb8b28c73849d4a747` | `python ops/run_report_runtime_tests.py` — [runner](https://github.com/a4ns/DalaAI/blob/f101e4320b59b0a7dc81bdcb8b28c73849d4a747/ops/run_report_runtime_tests.py) | 8+8+1 report cases; не физическое устройство и не экспорт |

## Чеклист перед передачей владельцу

- [ ] A0 зафиксировал окончательный runtime/frontend/harness SHA и exact CI
  этого кандидата; прежний PASS не перенесён на новую сборку
- [ ] Подготовленный origin, доверенный HTTPS и два сеанса проверены оператором;
  пароли/PIN передаются отдельно, не попадают в запись, Git или отчёт
- [ ] Новый optional B3/C110 real-core прогон имеет собственный результат;
  более новый source сам по себе не закрывает этот пункт
- [ ] Frontend analytics и fresh-history one-command Compose проверены отдельно;
  на этом срезе они pending, helper и PG gate их не заменяют
- [ ] PDF/XLSX, timed rehearsal и видео имеют реальные артефакты либо явно NOT_RUN
- [ ] Физический Android, камера, upload SLA, phone push и реальная модель
  предъявлены только со своими evidence; ручной core не даёт им PASS

Если условия показа отсутствуют, использовать явно названные CI-доказательства
или отдельный offline synthetic пакет. Не делать скрытый reset, fake success,
обход TLS/прав, запуск provider/уведомлений или деплой. Публикация этой
документации не означает release, подачу или готовность всех требований.
