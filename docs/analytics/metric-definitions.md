# Метрики v1: время, когорты и отсутствующие данные

## 1. Статус и источники

Эта версия предлагает точные правила будущей аналитики и её приёмки. Она не
меняет API/БД, не утверждает наличие runtime-агрегаций и не утверждает принятие
формулы рейтинга. Проверенный исходный срез:
`f3b3ffd00d8bb59e55d539e2321196bf18c30d7d`.

Принятый узкий контракт: `1.0.0-proposal.2`,
`coord/proposals/a6-contract-v1/contracts/openapi.yaml`, SHA-256
`b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97`.
Старые надписи PROPOSED в подготовительных документах не отменяют последующее
[принятие A0](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6044529856).
Это принятие ядра не добавляет отсутствующие analytics/report endpoints.

| Источник в указанном SHA | Подтверждает |
|---|---|
| [CONTRACT.md, Clock/events, submissions](../../coord/proposals/a6-contract-v1/CONTRACT.md) | Два события submit, один committed `ai_review`; immutable attempt; unscored human score; UTC и overdue |
| [OpenAPI: Submission, Review, Assessment, OrderEvent, OrderPage](../../coord/proposals/a6-contract-v1/contracts/openapi.yaml) | Доступные поля, nullable score, отдельные сущности; нет аналитических маршрутов |
| [orders/models.py](../../backend/app/orders/models.py), [rules.py: prepare_new_command/is_overdue](../../backend/app/orders/rules.py) | Реальные поля и переходы, `now > due_at`, человеческое close/rework, новые assignment revisions |
| [persistence/postgres.py: persist_submission/persist_review/persist_events](../../backend/app/persistence/postgres.py) | Сохранение attempt/review, order-local sequence; `recorded_at` берётся из real clock |
| [persistence/service.py: get_submission](../../backend/app/persistence/service.py) | Отдельные массивы assessments и reviews, загрузка неизменяемой попытки |
| [persistence/http.py](../../backend/app/persistence/http.py) | В этом срезе opt-in vertical-slice router, не доказательство полного API или deployment |
| [ai/models.py: Assessment.to_wire](../../backend/app/ai/models.py) | Реальная rules-fallback структура: `score=null`, а не измеренная модельная оценка |
| [AGENTS.md §§7–10](../../AGENTS.md), [R03b/R06a/R06b](../REQUIREMENTS.md) | Требования/командные ограничения аналитики; сама карта не evidence выполнения |

Дополнительные принятые уточнения:
[списки/сессии A0-0004](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6044401325),
[словари A0-0006](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6044550997).
Они ограничивают трактовку данных; описанные ниже новые формулы являются
предложением C3, не дополнительным решением A0.

## 2. Обязательные координаты каждого результата

Результат содержит `metric_id`, версию определения, единицу, фильтры и текущую
разрешённую область, `start`, `end`, `domain_as_of`, `captured_at_real`, идентификатор
и hash входного набора, code SHA, synthetic/demo marker, status, value,
numerator/denominator (если применимы), eligible/missing/excluded counts, источники
order/submission/review/event IDs и причину каждого исключения. Формат здесь
описательный, не новый wire contract. Маленький checker проверяет числовое ядро;
он не реализует весь этот отчётный envelope.

- Период **[start, end)**: начало включено, конец исключён. Все входные timestamps
  имеют зону, нормализуются в UTC. Смещение не выбрасывается перед сравнением
- Отображение: **UTC+5** с подписью. Например, смена 2 октября 2026, 00:00–24:00
  UTC+5 соответствует `[2026-10-01T19:00:00Z, 2026-10-02T19:00:00Z)`
- `domain_as_of` — момент состояния производства/демо; события состояния с
  временем `<= domain_as_of` включены. Не подставлять время запуска отчёта вместо
  зафиксированного demo clock. В завершённом отчёте `start < end <= domain_as_of`
- `captured_at_real` — когда получен неизменяемый набор. `occurred_at`, issued_at,
  submitted_at и review.created_at — доменные времена; `recorded_at` события —
  реальное время сохранения. В ускоренном demo эти две шкалы несопоставимы
- Отчёт о незавершённой смене явно имеет `effective_end=min(end, domain_as_of)`
  и статус provisional. Нельзя выдать его за весь первоначально выбранный период
- История «что было известно тогда» дополнительно требует реального knowledge
  cutoff, полного versioned capture и поздно пришедших записей. Одного
  occurred_at или сегодняшнего snapshot для этого недостаточно. Полный
  bitemporal отчёт в этом пакете **не реализован**

### Полнота и разрешения

Точные сводные итоги требуют согласованного неизменяемого capture всех
разрешённых фактов за период плюс исторических связей, на которые они ссылаются.
Capture фиксирует область, полноту, clock, source hash и момент извлечения.
Current object authorization действует и для старых попыток; история не
разрешает раскрывать бывшему исполнителю наряд после переназначения.

Обычный обход `GET /orders` с `next_cursor` **не гарантирует snapshot/total между
страницами**. Устранение дублей не возвращает пропущенные при перемещении строк
данные. Такой обход маркируется live/partial, без «точного итога» или
авторитетного рейтинга. Не объявлять пустую/недоступную страницу нулевой нагрузкой.
Отдельного consistent-export механизма в принятом ядре нет; DB-backed реализация
и её доступ/изоляция требуют последующей отдельной работы.

## 3. Событие, попытка, состояние и автор решения

1. Единица наряда — order.id. Выдача — первоначальный issued_at / `order.created`,
   а не каждое возвращение snapshot в `issued` при переназначении
2. Единица отправки результата — submission.id; естественный ключ
   `(order_id, assignment_revision, attempt_number)`. Submit создаёт
   `order.done` и `order.ai_review_requested` с одним submission_id и одним
   order_version; committed snapshot сразу `ai_review`. Два события не дают
   две отправки. `status == done` не является счётчиком выполненных работ
3. Event.id устраняет повтор доставки; порядок в пределах одного наряда —
   `sequence`, не order_version и не уникальность timestamp. Несколько событий
   законно имеют одну версию/одинаковое время. Разные payload одного ID — ошибка,
   не разрешение выбрать последний. Пробелы sequence требуют проверки полноты
4. `Review.decision=close|rework` — факт решения мастера;
   `Assessment.recommendation` — рекомендация. AI score не является human
   final_score, вероятностью безопасного ремонта или фактом закрытия
5. `assessments=[]` означает «нет assessment в capture». Это не pending,
   failed, timeout, disabled или доказательство отсутствия AI job. Эти состояния
   требуют отдельного авторитетного источника. Assessment.mode и stale сохраняются
6. Для конкретного human decision показывается review с его submission_id,
   score и временем, а рядом исходные рекомендации. Stale AI старой revision
   не заменяет assessment новой попытки. Сравнение рекомендации с решением
   допускает только ту же попытку и recommendation, доступную к моменту решения;
   поздний assessment нельзя выдавать за совет, который видел мастер
7. Атрибуция исполнения — submission.submitted_by и assignment_revision в момент
   попытки. Сегодняшний orders.assignment не переписывает чужую старую работу.
   Группа бригады требует подтверждённого состава/assignment на момент работы,
   не только сегодняшнего employees.brigade_id. При отсутствии этого — unknown

## 4. Минимальные показатели

Все множества ограничены разрешённой областью и полным capture.
Счётчики не складываются в единую воронку, пока явно не выбран общий cohort.

| ID / подпись | Точное правило и единица | Источники / оговорки |
|---|---|---|
| issued_orders / Выдано | Число distinct order.id с issued_at в [start,end) | Сверка с первоначальным order.created; reassign не новая выдача |
| submitted_orders / Нарядов с отправленным результатом | Distinct order.id с хотя бы одной submission.submitted_at в периоде | Включает incomplete/rework attempts; не обещает принятие |
| submission_attempts / Отправок результата | Число distinct submission.id с submitted_at в периоде | Отдельно от submitted_orders; включает все revisions и повторные попытки |
| closed_orders / Принято мастером | Distinct order.id, связанный с Review.decision=close и Review.created_at в периоде | В MVP closed terminal; два close на наряд — нарушение, не тихий dedupe |
| rework_decisions / Возвращено на доработку | Число Review.id с decision=rework и created_at в периоде | Дополнительно distinct order.id; несколько возвратов одного наряда видны отдельно |
| awaiting_review / На проверке сейчас | Число snapshot.status=ai_review на domain_as_of | Stock, не число отправок периода; нет вывода о состоянии модели |
| overdue_active / Просрочено сейчас | Число snapshot на domain_as_of с due_at < domain_as_of и статусом issued/queued/accepted/rejected/in_progress/paused/rework | done/ai_review/closed/cancelled исключены; точное равенство сроку не просрочка |

`overdue_active` не считает исторически опоздавшие уже закрытые наряды. Для
исторического as_of нужен snapshot именно этого момента либо проверенная
полная реконструкция событий и полей; сегодняшняя строка не подходит. Ни
отрицательная, ни нулевая длительность просрочки не подставляется при unknown.

### Единая основная когорта качества и своевременности

**C = закрытые в периоде наряды** по правилу closed_orders выше. Для каждого
берём единственный close-review и его submission, даже если submission была
до start. Это cohort принятой работы, а не всех выданных или всех отправок.
Показывать также issued/submitted/awaiting_review, чтобы не скрыть незавершённую
работу. Незакрытые наряды не становятся ни успехами, ни провалами этой когорты.

- **Q / средняя оценка мастера:** сумма review.final_score / число non-null
  final_score в C, единица баллы 0–100. Нормированная Q при необходимости = Q/100.
  Показывать `scored_n`, `unscored_n`, `closed_n`. Score=0 — валидное наблюдение;
  null — unscored. В этом MVP нет редактируемой «последней оценки»: review
  immutable, один на submission. Не брать максимальный AI или human score
- **T / доля принятых работ, отправленных в срок:** число C с
  close-linked submission.done_late=false / число C с известным boolean
  done_late. Показывать numerator/denominator и missing. `done_late` зафиксирован
  при отправке сравнением `submitted_at > due_at`; равенство в срок. Не считать
  по review.created_at, текущему due_at или состоянию is_overdue
- **Rw_closed / принятые работы с доработкой той же assignment revision:**
  число C, где до close была хотя бы одна human rework-review на более ранней
  попытке **того же order_id и assignment_revision**, / число C с полной
  историей этой revision. Порядок подтверждён sequence/attempt identity,
  а не строгим неравенством timestamp: команды demo clock могут совпасть по времени.
  Наряд учитывается максимум один раз. Возврат прежнему
  исполнителю до переназначения не штрафует следующего. Это явно отдельная
  метрика от `rework_decisions` и повторной неисправности оборудования

Для Rw нужна история до начала периода и её полнота; ограничить вход только
reviews внутри периода нельзя. Дополнительно допустима **attempt_on_time**:
все отправки в периоде с done_late=false / отправки с известным done_late.
Её заголовок и denominator обязаны отличаться от T; повторные попытки меняют
её вес. Первую попытку нельзя молча подставить вместо close-linked final attempt.

### Ноль, отсутствие и малая выборка

- Точный count пустого **полного** набора = 0. Это измеренный ноль
- Ratio/mean при eligible=0: value=null, denominator=0, status=no_cohort
- Eligible>0, но ни одного наблюдаемого значения: value=null,
  denominator=0, status=missing, missing_count=eligible. Это не 0%
- Часть значений есть: value рассчитано по наблюдаемому denominator,
  status=partial, все missing/excluded counts видны; не выдавать partial mean
  за оценку всей группы. Для полной наблюдаемой когорты status=ok
- Для partial capture или отсутствующего поля, которое требуется всем строкам,
  авторитетное значение unavailable; observed-only диагностический результат
  можно показать отдельно с явным названием. Ошибочные ссылки/дубли не пропускаются
- n<5: флаг small_sample с фактическим n. Число не становится устойчивым
  рейтингом; автоматического сглаживания, заполнения нулями и сортировки людей
  по такому числу в данном пакете нет
- Excluded задаётся с причиной и от явно названного universe. Для Q это не
  количество всех незакрытых нарядов; missing_score — часть eligible C

## 5. Повторная неисправность, downtime и рейтинг

### 7-дневная повторная неисправность: пока unsupported

В ядре есть equipment_id, type, description и work_code_id, но нет
подтверждённых repair episode, fault classification, restoration time и связи
«повтор той же неисправности». Два unplanned наряда одной единицы — только
proxy «повторное обращение по оборудованию», не доказательство рецидива,
вины сотрудника или плохого ремонта. Rework той же попытки не новый отказ.

Предлагаемое правило **после появления авторитетных данных**:

- Index episode = подтверждённо восстановленная единица с repair_end в [start,end),
  equipment_id, fault_code и ответственным; follow-up заканчивается в
  `repair_end + 7*24h`, а не в конце отчётной смены
- Repeat = новый distinct failure episode той же единицы и того же согласованного
  fault_code в `(repair_end, repair_end + 7d]`. Дубли/продолжение того же episode,
  planned work и ordinary rework исключены
- Denominator = index episodes с известными required fields и непрерывным
  наблюдением **всех семи дней**, включая события после end. Numerator = число
  этих index episodes хотя бы с одним repeat; несколько repeats не увеличивают
  numerator одного index episode
- Молодые episodes и потерянное наблюдение — right-censored, отдельные counts.
  Не записывать «нет рецидива», когда прошло три дня. В этой простой mature-cohort
  версии **даже ранний замеченный repeat у незрелого episode исключён из ratio**:
  нельзя включать ранние успехи детектора, исключая незрелые отрицательные
- Если позже применяется survival estimator, это новая версия формулы; нельзя
  смешивать его denominator с описанным mature-cohort rate

Пример только для математики: as_of=10 октября 00:00Z. A восстановлен 1 октября,
repeat 5 октября; B восстановлен 2 октября, repeat нет, наблюдение полное;
C восстановлен 7 октября, repeat 8 октября, ещё незрелый. Rate=1/2=50%,
right_censored=1. D восстановлен 1 октября, но наблюдение прервано 3 октября:
тоже censored, не добавляет «здоровую» единицу. Fault code отсутствует → missing.
Эти поля **не объявляются существующими полями API**.

### Простой оборудования: пока unsupported

Pause отражает остановку работы исполнителя; это не автоматически downtime
оборудования. `norm_minutes` — норматив, не реальное время, не простой и не
признанный коэффициент сложности. Не выводить downtime из разницы issued/close,
числа paused нарядов, текста причины или просрочки.

Если появятся подтверждённые интервалы `[down_start, restored_at)` с equipment_id,
клипировать каждый к [start,end) и domain_as_of, объединять пересечения и касания
**внутри каждой единицы**, затем суммировать union length. Открытый подтверждённый
интервал считается до as_of с маркировкой ongoing; пропущенная граница не
становится нулевой. Интервалы разных единиц не объединяются: итог —
equipment-minutes, а не wall-clock минута остановки всего предприятия.

Математический пример: E1 [10:00,10:30), [10:20,10:50) → 50 минут;
E2 [10:10,10:20) → 10 минут. Всего 60 equipment-minutes, не 70 и не 50.
Для availability rate дополнительно требуется полный exposure/calendar;
«60 минут» без denominator не превращается в процент доступности.

### Рейтинг: никакой выдуманной полноты

AGENTS.md описывает кандидат `100*(0.35Q+0.25T+0.20*(1-Rw)+0.15V+0.05*(1-Rf))`
с неподтверждёнными компонентами. Данный пакет его **не внедряет и не вычисляет**.
Rw_closed выше намеренно не смешивает rework с repeat fault. Для их общего
компонента потребуются единый mature cohort и union по идентичности, чтобы один
наряд не штрафовался дважды; это отдельное принимаемое решение.

Отсутствуют принятые difficulty weights/normalization/exposure для V,
структурированное human adjudication «неуважительный отказ» для Rf и repeat-fault
факты. Причина reject не доказывает вину. Поэтому composite rating=null,
status=unsupported_inputs; missing components перечислены. Не менять веса,
не перенормировать известные компоненты и не подставлять AI score без отдельного
решения. До этого можно показывать прозрачные отдельные Q/T/counts с n,
не автоматическую оценку допуска, безопасности, трудоустройства или наказания.

## 6. Загрузка и другие неподтверждённые выводы

`active_order_id` — lowest-number представитель видимых assigned
in_progress/paused, не гарантия одного активного наряда. `queue_count` — только
queued, не полный backlog и не доступность. 0 queued не означает свободен.
Master/manager catalogues scoped, executor видит себя, admin не получает workload
rows по умолчанию. Не строить общий company total из этих ограниченных списков.

Материалы суммируются в единицах справочника по material_id и distinct
submission_id; kg и pieces не складываются. Повторный submit может повторно
заявлять тот же материал: без авторитетного правила инкрементального списания/
исправлений сумма payload — только «заявлено в отправках», не складской расход.
Ни обнаруженная корреляция, ни synthetic pattern не доказывают причинность,
промышленную точность, экономию или фактическое внедрение.
