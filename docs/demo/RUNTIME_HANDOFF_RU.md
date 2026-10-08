# НарядAI демонстрация проверенных runtime этапов

Примечание интеграции: [исходный C106 handoff](https://github.com/a4ns/DalaAI/blob/ed6b0808de964f5c8898f3c4db96216c9c19c0bd/docs/demo/RUNTIME_HANDOFF_RU.md)
сохранён в указанном коммите. Здесь только ссылки на отсутствующие в main
исторические документы заменены ссылками на их неизменяемые исходники.
Текущая инструкция запуска — [утренний handoff](../../ops/demo/MORNING_HANDOFF_RU.md).

Срез **2026-10-08 03:17 UTC (08:17 UTC+5)** для владельца демонстрации.
Проверены ручной UI/API/PostgreSQL цикл в Android-эмуляции, серверные
history/rules/export/clock gates и отдельный packaged-image/restart gate.
Final B `faef5d` на runtime `77ea58ff` теперь имеет собственные **C110/C112
PASS**, восемь зелёных main workflow и отдельный managed PASS того же SHA.
Новый C113 на `34df71ec` имеет **два отдельно проверенных PASS attempts**;
все десять workflow этого SHA зелёные на момент проверки.
Предыдущий `e548c948` сохраняет **PASS, затем FAIL на повторе того же SHA**;
причина не установлена, гарантии надёжности нет.
Прежний `43cd9ca` с частичным clock UI и полным FAIL остаётся необъяснённым.
Прежний
`2471afde` с locator timeout сохранён как исторический FAIL. Это
**не подтверждение всех device/provider/release gates**.

C-106 сверил публичные исходники и CI-метаданные; подробности отдельных
этапов ниже явно приписаны bounded-отчётам A0. В этом обновлении raw runtime
logs, приватные artifacts и приватные файлы паролей/PIN/DSN/сеансов не открывались.
Приложение, БД и браузер C-106 не запускал; фото/видео не создавал.

Этот документ дополняет исторические [f3 runbook](https://github.com/a4ns/DalaAI/blob/ed6b0808de964f5c8898f3c4db96216c9c19c0bd/docs/demo/README.md) и
[dfe9 source-срез](https://github.com/a4ns/DalaAI/blob/ed6b0808de964f5c8898f3c4db96216c9c19c0bd/docs/demo/CURRENT_RUNTIME_RU.md). [Offline runner](https://github.com/a4ns/DalaAI/blob/ed6b0808de964f5c8898f3c4db96216c9c19c0bd/docs/demo/OFFLINE_RUN_RU.md)
остаётся отдельным воспроизводимым synthetic evidence; его результаты
не объявляются runtime, моделью или физическим Android.

## Новые проверенные этапы: не переносить PASS между сборками

**Final B: свежие core и analytics PASS.** Runtime
`77ea58ff89d0f52853e7b4069b138f2577fa11b4`, frontend
`faef5d3d8b4c640fae013dbfa78074382e512e8f`:

- [C110 run 37715211318](https://github.com/a4ns/DalaAI/actions/runs/37715211318/job/113110152016),
  harness `afeef803d01d7e056b7ad87e0cd4b1a437092db3`:
  real-core UI/API/PostgreSQL job и его acceptance step завершились успешно.
- [C112 run 37715211417](https://github.com/a4ns/DalaAI/actions/runs/37715211417/job/113110005346),
  harness `118b81580cc658150eeca62e1b994e44ff015c6d`:
  fresh proof/history read-only journey прошёл на final frontend.
- [Managed image run 37715240438](https://github.com/a4ns/DalaAI/actions/runs/37715240438/job/113110094909)
  прошёл на том же exact SHA через отдельную validation-ветку; hosted
  deployment из этого не следует.

Точные frontend/harness pins проверены в
[C110 manifest](https://github.com/a4ns/DalaAI/blob/77ea58ff89d0f52853e7b4069b138f2577fa11b4/ops/ci/scenarios.json)
и [C112 manifest](https://github.com/a4ns/DalaAI/blob/77ea58ff89d0f52853e7b4069b138f2577fa11b4/ops/ci/history_contract.json).
Все восемь main workflow этого SHA и отдельный managed run — terminal
`success`. По [bounded-отчёту A0 именно для `77ea58ff`](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6050616164):
C110 — 6 этапов / 11 команд / 13 событий; C112 — 7 этапов / 3 protected
observations / 3 executor denials, 540/568/444 и неизменные business rows.
Оба с fresh proof, trusted TLS, zero skips и cleanup. Это атрибуция нового
run, а не перенос чисел из прежнего SHA; runtime artifacts не открывались.
Download/save и полная приёмка UI demo-clock остаются отдельным C113.

### C113: два новых PASS attempts, прежние сбои не объявлены исправленными

`34df71ec2aa49e98e7c17baf90f41789a6cb1176`, тот же frontend `faef5d`, C113
`0d2ac5e95dcd99b11b144b7871152ed9c0033697`:
[run 37721429331, attempt 1](https://github.com/a4ns/DalaAI/actions/runs/37721429331/job/113129722640)
и [свежий attempt 2](https://github.com/a4ns/DalaAI/actions/runs/37721429331/job/113130793896)
завершились success; у обоих source/setup и fresh-proof/actual clock/four-files
acceptance step прошли. Attempt 2 завершён в 03:16:46 UTC и проверен через
отдельный endpoint попытки, не подменяющий первый результат. Все десять
workflow exact SHA на этом срезе завершились успешно.
Source pins проверены в [controls manifest](https://github.com/a4ns/DalaAI/blob/34df71ec2aa49e98e7c17baf90f41789a6cb1176/ops/ci/controls_contract.json).
Числа отдельных действий из прежнего run на этот не перенесены.

[Новая диагностика](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6051298502)
коррелирует exact request completion с фиксированным состоянием клиента,
сохраняя byte/hash/content predicates; C0 сообщил 76 Node + 13 Python source
checks. **Это два успешных attempts, не доказанная причина или починка прежних
сбоев.** История PASS/FAIL ниже и ограничение надёжности остаются видимыми.

### Предыдущий C113: actual PASS и неуспешный повтор того же SHA

`e548c9482277f0b19e82f9959be6d25df92b5e97`, frontend `faef5d`, C113
`e92f80bac8011fef917dfa0685470475e67ea151`:
[run 37718867179, attempt 1](https://github.com/a4ns/DalaAI/actions/runs/37718867179/job/113121626731)
завершился success, включая fresh-proof/clock/four-files step. По
[bounded-отчёту A0](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6051088147):
8 этапов, 6 clock observations, ровно 3 master UI mutations (version 0→3),
4 browser-saved/content-inspected PDF/XLSX, 6 executor denials, неизменные
business rows, zero skips, fresh proof, normal TLS и cleanup.

Это actual Android-emulated UI/API/БД и файлы Chromium. Физический телефон,
native Excel, hosted deployment и live providers этим не проверены.
Изменение было diagnostics-only с прежними acceptance predicates.
Все девять остальных workflow `e548c948` завершились успешно, однако
отдельный свежий повтор того же SHA
[attempt 2, job 113123763239](https://github.com/a4ns/DalaAI/actions/runs/37718867179/job/113123763239)
завершился **FAIL**. По [bounded-отчёту A0](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6051171178):
`SHIFT_PDF → READ_RESPONSE_BYTES`, HTTP 200, identity encoding, bounded
Content-Length и protected MIME/disposition/CSP checks прошли; Playwright
`response.body()` не завершился успешно. До Save и inspector выполнение не
дошло, сохранённого файла нет; cleanup прошёл.

Это нерешённый intermittent capture/transfer boundary. Сбой инструмента
браузерной проверки и реальное прерывание ответа пока не различены.
**Первый PASS действителен только для своего attempt; он не отменяет FAIL
повтора и не доказывает надёжный экспорт.** Причина прежнего `43cd9ca`
failure также не установлена. Не убирать byte/hash/content checks ради PASS.

### Предыдущий C113: partial clock UI, полный FAIL сохранён

На `43cd9ca5823b02eb27e59e3af252f894dcefa2f6`, том же final B `faef5d`,
с harness `80e59f8a802d4e6bf78e6f7e08355d394ea782db`
[run 37716832135](https://github.com/a4ns/DalaAI/actions/runs/37716832135/job/113115120902)
завершился failure. Остальные девять workflow этого SHA — success;
это не скрывает непройденный C113 и не меняет стабильный baseline `77ea58ff`.

По [bounded-отчёту A0](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6050913081),
пройдены 4 этапа, включая 6 проверенных clock observations и выбор истории;
completed download rows = 0, выполненные C113 restrictions = 0. Fresh proof,
TLS, inspector import, service inventory и cleanup прошли. Этап 5 упал.
[Уточнение границы](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6050919978):
этот этап сначала открывает/проверяет shift JSON report, затем вызывает
Prepare/Save/inspection PDF/XLSX. Поэтому wrapper location не доказывает
даже вход в download helper, а отсутствие completed row не доказывает,
что bytes не пришли. Внутренняя причина этим run не установлена.

Это partial actual Android-emulated clock UI evidence, **не PASS четырёх
сохранённых файлов или полного clock/download сценария**. Защищённые
server exports и C112 restrictions сохраняют свои отдельные доказательства.
Новый [v3 snapshot](../evidence/run/runtime-20261008-v3.json) дополняет,
а не переписывает [стабильный v2](https://github.com/a4ns/DalaAI/blob/ed6b0808de964f5c8898f3c4db96216c9c19c0bd/docs/evidence/run/runtime-20261008-v2.json).

### Предыдущая полная аналитика B9a

**Полная аналитика UI/API/БД PASS:**
`347119c47b9a0ec70cd30cbc8bce2a2774a439e0`, frontend
`9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c`, C112
`d34455d877f9d3853421cad4cf6d3f92056254f7`.
[Fresh C112 run 37712740639](https://github.com/a4ns/DalaAI/actions/runs/37712740639/job/113102167252)
и все восемь workflow exact SHA завершились успешно. По
[bounded-отчёту A0](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6050279185):
7 этапов, 3 protected analytics/report observations, 3 запрета исполнителю,
540 нарядов / 568 попыток / 444 недоступные фото, неизменные business rows
и cleanup. Это Android-эмуляция с реальными UI/API/PostgreSQL, включая
защищённые отчёты смены и выбранного наряда. Artifact не открывался;
числа приписаны A0, terminal status проверен отдельно.

Предыдущий exact runtime, оставленный для истории и детализации server gates:
`2471afde7b8442f3c66a3fe56d21df5b332b81d1`, frontend
`9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c`.

- **Ручной core PASS:** [run 37710664244, mobile-core](https://github.com/a4ns/DalaAI/actions/runs/37710664244/job/113095586907).
  Реальные UI/API/PostgreSQL в Android-эмуляции; source binding — C110
  `d674d8a1cc261760c89b04b555123ca775f3c845`.
  [Manifest точного runtime](https://github.com/a4ns/DalaAI/blob/2471afde7b8442f3c66a3fe56d21df5b332b81d1/ops/ci/scenarios.json).
  Старые числа команд/событий не приписываются этому run без его summary.
- **History Compose PASS:** [history, clock=false](https://github.com/a4ns/DalaAI/actions/runs/37710664219/job/113095586617).
  Trusted HTTPS, настоящий photo upload → persisted `rules_fallback` →
  решение мастера → четыре защищённых PDF/XLSX ответа, повторный startup.
  [Minimal counterpart](https://github.com/a4ns/DalaAI/actions/runs/37710664219/job/113095586344)
  прошёл отдельно. Это серверный HTTP smoke, не сохранение файла браузером.
- **Clock API PASS:** [minimal, clock=true](https://github.com/a4ns/DalaAI/actions/runs/37710664219/job/113095586713).
  Shared pause/forward advance, CAS и доступ мастера проверены серверным
  сценарием; это не приёмка новых UI-кнопок времени. Matrix данного run
  не включает `history + clock=true`.
- **History/live/report fixture PASS:** [run 37710664408](https://github.com/a4ns/DalaAI/actions/runs/37710664408/job/113095587122).
  10 actual PostgreSQL cases, zero skips; отдельно пройден fixture-mode
  binding/completion barrier. Это не полный C112.
- **C112 частично, полный gate FAIL:** [run 37710664206](https://github.com/a4ns/DalaAI/actions/runs/37710664206/job/113095586236),
  C112 `edd109d2111e798db0440c7d3050e7e4fca80e42`.
  По [bounded-отчёту A0](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6050036426),
  пройдены четыре этапа и две проверенные API observations `HTTP_OK`,
  включая date fill, историческую аналитику и защищённый отчёт смены.
  Этап 5, `selectOption` в `c112_analytics.spec.cjs:213`, завершился
  `LOCATOR_TIMEOUT`; cleanup прошёл. Отчёт выбранного наряда и оставшийся
  конец сценария этим запуском не подтверждены.

У `2471afde` семь workflow имеют `completed/success`, один C112 —
`completed/failure`. Зелёный core/Compose не скрывает этот failure.

**Отдельная managed-image/restart приёмка PASS:**
`2d1a40796881eace63378c9ef83886b0a0bda95d`, ветка
`validation/managed-image-20261008`,
[run 37712260125](https://github.com/a4ns/DalaAI/actions/runs/37712260125/job/113100631476).
Статус exact job проверен. По [bounded-отчёту A0](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6050216105),
реальный образ прошёл trusted HTTPS/auth, combined history/clock/photo/rules/
human close/four exports; restart сохранил записи, файл фото и offline
test-ledger reservation, cleanup прошёл. «Файл фото» здесь не означает
нативную камеру или доказательство реального ремонта. Это disposable CI,
не hosted deployment и не проверка физического телефона/live provider.

### Граница source, synthetic и runtime evidence

- Final B `faef5d3d8b4c640fae013dbfa78074382e512e8f` —
  [source handoff](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6049790608):
  download controls и «Демо-время», 153 source cases/lint/types/build по B0.
  [Отдельный CI source/synthetic PASS](https://github.com/a4ns/DalaAI/actions/runs/37712552373/job/113101574022)
  на validation SHA `e2a6e67c1f314bb1b1a5224d73faf2ea85cc9289`:
  153 source + 13 Pixel9 synthetic cases. Это не реальный API/БД gate.
  Его C110/C112 runtime теперь подтверждён отдельно выше. Native save и
  реальные UI clock actions source/synthetic suite не проверяет.
- Отдельный
  [C113 downloads/demo-clock](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6050284514)
  должен проверить существующие download/time controls. Его
  [source handoff](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6050602139)
  `80e59f8a802d4e6bf78e6f7e08355d394ea782db` имеет сообщённые C0 70 Node +
  12 Python source checks. Его actual run `43cd9ca` завершился частичным
  результатом и полным FAIL, подробно выше. Отдельный diagnosis-only
  [handoff `e92f80ba`](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6050952523)
  имеет 71 Node + 13 Python source checks; на `e548c948` actual attempt 1
  PASS, attempt 2 FAIL. После следующей диагностики `0d2ac5e9` новый
  `34df71ec` attempts 1 и 2 PASS; root cause прежних сбоев остаётся неустановленным.

Новые [метаданные, source bindings и границы](https://github.com/a4ns/DalaAI/blob/ed6b0808de964f5c8898f3c4db96216c9c19c0bd/docs/evidence/run/runtime-20261008-v2.json)
сохранены отдельно от исторического JSON. Ни один старый failure не переписан.

## Исторические этапы, сохранённые без переатрибуции

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

Эти три исторических run проверены как `push/main`, `completed/success`
на указанных SHA.
Сохранены [проверенные метаданные и границы](https://github.com/a4ns/DalaAI/blob/ed6b0808de964f5c8898f3c4db96216c9c19c0bd/docs/evidence/run/runtime-f101-milestones.json)
и [неизменённый public mobile summary](https://github.com/a4ns/DalaAI/blob/ed6b0808de964f5c8898f3c4db96216c9c19c0bd/docs/evidence/run/mobile-ab632c0-summary.json).
Summary прямо фиксирует `full_cycle_green=false`. Его upstream ZIP SHA-256:
`c86c34a52994bc405a6ccb9f8b0fbc0ef154169aafd80df5990d9d21cd6addf0`;
GitHub artifact expires `2026-10-14T22:43:55Z`.

Следующий исторический baseline —
`4d38c71164a56b0eeefa9eb0430eb9100bcd7a3d`, B
`3ef269bba80dbd6eafaff0d5e557da21f2d96244`, C110
`67496c1c38051b9c45d960caa3242ff0a37edaa4`:
[real core PASS](https://github.com/a4ns/DalaAI/actions/runs/37701995224/job/113067379559)
и [history Compose PASS](https://github.com/a4ns/DalaAI/actions/runs/37701995307/job/113067380277).
Все семь workflows на этом SHA завершились успешно. Числа 6 этапов /
11 команд / 13 событий / 0 skips —
[атрибутированный отчёт A0](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6048937824),
не новый запуск C-106 и не результат более позднего frontend.

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
4. **1:50–2:25.** Показать историю действий и проверенную аналитику/отчёт
   смены на подготовленном exact instance. Для синтетической истории назвать
   540 нарядов / 568 попыток / 444 недоступные after-photo ссылки, явно
   отличая metadata от фото. Если instance не подготовлен, показать exact CI
   evidence. Order-report UI имеет собственный gate на `77ea58ff/faef5d`;
   другой собранный кандидат требует своей проверки.
5. **2:25–3:00.** Назвать ограничения: эмуляция, synthetic PNG и история;
   rules fallback не оценивает смысл ремонта моделью. Server PDF/XLSX
   проверены отдельно; Chromium save/inspection имеют новый PASS и историю
   неуспешного повтора. Live-экспорт добавлять только после успешной
   операторской проверки текущего экземпляра, раскрывая этот риск.
   Если проверка не прошла, убрать live-экспорт и показать явно названное
   exact CI или offline synthetic evidence; не обещать сохранённые файлы
   и не скрывать failure.
   Физические телефоны, live model
   и доставка требуют своих gates.

Для расширенного показа сохранить весь подтверждённый порядок:
создать → очередь → принять → начать → пауза с причиной → продолжить →
неполный результат → доработка → повторная работа и upload → ручное закрытие →
история. Точные действия и границы:
[C110 сценарий на проверенном source SHA](https://github.com/a4ns/DalaAI/blob/23a135348a0e8ad9a140a36ca60e8440704b7893/tests/e2e/c110_README.md).
Synthetic PNG не является снимком камеры или доказательством ремонта.

Расширенный порядок до семи минут, также пока **не timed rehearsal**:
0:00–0:30 контекст и synthetic label; 0:30–2:00 создание/очередь/принятие;
2:00–3:15 работа/пауза/продолжение; 3:15–5:15 неполный результат/доработка/
upload/ручное закрытие; 5:15–6:30 история/аналитика/отчёт смены;
6:30–7:00 границы и следующий пилотный шаг. Экспорт, UI demo-clock и
отчёт выбранного наряда показывать только в пределах приёмки конкретного
собранного кандидата; старое CI evidence показывать как старое.

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

### Более новый серверный PDF/XLSX

На `2471afde` отдельно проверены защищённые GET
`/api/v1/reports/shift.pdf`, `/api/v1/reports/shift.xlsx`,
`/api/v1/reports/orders/{order_id}.pdf` и `.xlsx` с теми же timezone-aware
`start`/`end` и текущей cookie-сессией. Это fixed suffix, не `format=pdf`.
Источник: [exact export contract](https://github.com/a4ns/DalaAI/blob/2471afde7b8442f3c66a3fe56d21df5b332b81d1/docs/reports/exports.md)
и History Compose gate выше. Успешный серверный binary response не
подтверждает нажатие Save, сохранение/открытие файла на телефоне или
приёмку новых download controls `faef5d`.

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
- [ ] Не смешаны historical core, `2471afde/B9a` core, серверные Compose gates
  и отдельный managed image; финальный B имеет собственную приёмку
- [ ] Оператор использует именно проверенный `77ea58ff/faef5d` либо
  следующий кандидат с собственными C110/C112; старые PASS не перенесены
- [ ] Оператор повторил экспорт на своём exact instance; новый `34df71ec`
  PASS не выдан за объяснение/починку прежних `e548c948` PASS/FAIL
- [ ] Timed rehearsal и видео имеют реальные артефакты либо явно NOT_RUN
- [ ] Физический Android, камера, upload SLA, phone push и реальная модель
  предъявлены только со своими evidence; ручной core не даёт им PASS

Если условия показа отсутствуют, использовать явно названные CI-доказательства
или отдельный offline synthetic пакет. Не делать скрытый reset, fake success,
обход TLS/прав, запуск provider/уведомлений или деплой. Публикация этой
документации не означает release, подачу или готовность всех требований.
