# C4: проверяемые определения отчётов наряда и смены

Задача C-104, generation 1. **Документация и автономные синтетические примеры**, не новый API, не серверный модуль и не свидетельство готового отчёта в приложении. Требования R06a/R06b остаются непроверенными на живом контуре. Все данные примеров вымышлены; реальные люди, фотографии, уведомления и модель не использованы.

## 1. Зафиксированные основания

Исследованный код: `f3b3ffd00d8bb59e55d539e2321196bf18c30d7d`. Принятый узкий core: `coord/proposals/a6-contract-v1/contracts/openapi.yaml`, версия `1.0.0-proposal.2`, SHA-256 `b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97`. Слово PROPOSED в старом заголовке файла не расширяет и не отменяет последующее принятие узкого core; отчёты этим принятием не добавлены.

| Источник | Что именно подтверждает |
|---|---|
| [Принятие A0-0005](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6044529856) | Принятый core и handshake |
| [A0-0004](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6044401325), [A0-0006](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6044550997) | Scoped keyset pages без межстраничного snapshot/total; область справочников; семантика загрузки |
| [OpenAPI точного base](https://github.com/a4ns/DalaAI/blob/f3b3ffd00d8bb59e55d539e2321196bf18c30d7d/coord/proposals/a6-contract-v1/contracts/openapi.yaml) | Order, Submission, Review, Assessment, MaterialItem, OrderEvent; обязательные поля и null |
| [Core semantics](https://github.com/a4ns/DalaAI/blob/f3b3ffd00d8bb59e55d539e2321196bf18c30d7d/coord/proposals/a6-contract-v1/CONTRACT.md) | Нет report API; attempts/revisions; clocks; immutable done_late; запрет auto-close |
| [Orders rules](https://github.com/a4ns/DalaAI/blob/f3b3ffd00d8bb59e55d539e2321196bf18c30d7d/backend/app/orders/rules.py) | Submit даёт done → ai_review в одной команде; review привязан к текущей попытке; overdue исключает done/ai_review/closed/cancelled |
| [Persistence service](https://github.com/a4ns/DalaAI/blob/f3b3ffd00d8bb59e55d539e2321196bf18c30d7d/backend/app/persistence/service.py) | Имеются transactional commands, get_order/get_submission и загрузка assessments/reviews; это не готовый report query |
| [AI values](https://github.com/a4ns/DalaAI/blob/f3b3ffd00d8bb59e55d539e2321196bf18c30d7d/backend/app/ai/models.py) | Реальный rules_fallback wire result сохраняет mode и null score/model; AI-код уже существует |
| [Карта требований](https://github.com/a4ns/DalaAI/blob/f3b3ffd00d8bb59e55d539e2321196bf18c30d7d/docs/REQUIREMENTS.md) | R06a/R06b, case §6.4/6.6/7; это карта, не результаты приёмки |

Точные следующие решения API перечислены в разделе 7. Этот пакет не меняет контракт, SQL, backend, dependency/lockfiles или статус чужих требований.

## 2. Отчёт отдельного наряда

Каждая строка имеет первичный ID и происхождение. Человекочитаемое обозначение не заменяет ID. Код сотрудника допустим только из разрешённого справочника; при отсутствии справочника показывать UUID и «код недоступен», не угадывать имя.

| Раздел | Поля и смысл | Источник |
|---|---|---|
| Заголовок | number/id, версия snapshot, section_id, equipment_id, type/priority/status, описание, комментарий | Order |
| Ответственные | текущие executor_id/brigade_id; мастер created_by; автор каждой исторической попытки отдельно | Order.assignment, created_by; Submission.submitted_by |
| Время | issued_at, неизменённый due_at, norm_minutes; domain_now снимка и отдельно время построения | Order; report metadata |
| Попытки | order_id, submission_id, assignment_revision, attempt_number, submitted_at, done_late, completeness/missing_evidence | Submission |
| Работы | полный work_description/comment, work_code_id и доступный справочный код | Submission.payload |
| Материалы | material_id, количество Decimal, unit из связанного MaterialItem, submission_id | payload.materials + разрешённый справочник |
| Доказательства | before/after photo IDs, связь с нарядом/попыткой; только защищённое чтение | Order.before_photo_ids, payload.after_photo_ids |
| Рекомендация | assessment ID, submission/revision, schema_version, mode, model/version, score или «не оценено», reasons, evidence_ids, fallback_reason, stale, created_at | Assessment |
| Решение мастера | review ID, submission ID, reviewer ID, close/rework, причина, final_score или «не оценено», created_at | Review |
| Хронология | ordered events: id, sequence, occurred_at, recorded_at, actor, from/to, revisions, submission_id; attempts/reviews сохраняются | OrderEvent + Submission + Review |

Ключ попытки: `(order_id, assignment_revision, attempt_number)`. После переназначения attempt_number начинается в новой revision; нельзя объединять «попытка 1» разных назначений. Одна immutable submission имеет не более одного Review; второй Review с новым ID тоже ошибка целостности. Повтор строки с тем же ID в capture — ошибка целостности, не дополнительная работа. Изменённая копия с тем же ID — ошибка, не «последняя победила». Переназначение не переписывает автора старой работы. Последняя AI-оценка другой попытки, stale=true либо другой revision не становится текущей рекомендацией.

Рекомендация `satisfactory` не означает человеческое `close`; `rules_fallback` не называется «модель проверила». Даже mode=manual в Assessment не заменяет Review. Пустой assessments означает **«оценок в источнике нет; состояние задания AI неизвестно»**, не «проверка идёт»/«ошибка». Пустой reviews — «решения мастера нет». Null final_score — отсутствие числовой оценки; число 0 — реальная нулевая оценка. Не переносить AI score в final_score. Причина решения сохраняется даже при совпадении с рекомендацией.

Материалы в submit — **заявленные материалы этой попытки**, не доказанное складское списание. Нельзя складывать все попытки и называть результат фактическим расходом: повторная попытка может повторять прежний ввод. Отдельный итог «материалы закрытых попыток» берёт только submission, на который ссылается человеческий close выбранной когорты. Разные material_id не объединяются по label; разные единицы не суммируются. Смена единицы требует исторической версии справочника/снимка; текущая unit не доказывает историческую. В примерах справочник заморожен вместе с фактами.

Норма не равна фактической длительности. `submitted_at - issued_at` можно явно назвать календарным временем от выдачи до результата, но не рабочим временем и не простоем оборудования. Для рабочего времени нужны полные start/pause/resume/reassign events и согласованная формула. Простой без явных интервалов недоступен. Фото-ID подтверждает только ссылку, не содержание/качество/безопасность ремонта. До/после без before-фото — «не применимо».

## 3. Отчёт смены: период, когорта, источники

Предлагаемая однозначная семантика потребителя, не расширение API: полуинтервал `[start, end)`, обе границы с зоной, `start < end`, отображение UTC+5 (`Asia/Almaty` для этих дат). Пример: `2026-10-06T19:00:00Z` — `2026-10-07T07:00:00Z`, то есть 7 октября 00:00–12:00 UTC+5. Событие ровно start входит; ровно end не входит. `as_of` — доменное время состояния, отдельно от реального `generated_at`. В примере as_of=end; snapshot включает известное состояние на эту точку. Исторический as_of нельзя получить фильтрацией сегодняшнего статуса.

| Показатель | Когорта / правило | Обязательное происхождение |
|---|---|---|
| Выдано | distinct Order.id с issued_at в периоде; переназначение не новая выдача | order IDs |
| Отправлено результатов | distinct orders с Submission.submitted_at в периоде; рядом число distinct submission IDs | order + submission IDs |
| Закрыто мастером | distinct orders с Review.decision=close и Review.created_at в периоде | order + submission + review IDs |
| Возвраты | число human rework review в периоде; отдельно distinct orders | review + submission + order IDs |
| Просрочено на as_of | due_at < as_of и статус issued/queued/accepted/rejected/in_progress/paused/rework на as_of | order IDs, version, due_at, snapshot time |
| Оценка закрытых | arithmetic mean только numeric final_score close reviews; scored n, unscored n, cohort n отдельно | review IDs; это не общий рейтинг |
| В срок среди закрытых | close-linked Submission.done_late=false; число timely / все close-linked submissions | close review + submission IDs |
| Материалы закрытых | строки material_id/unit/Decimal quantity из close-linked submissions периода | material + submission + review + order IDs |

Все источники проходят один scope. Исполнитель видит только разрешённые сейчас наряды; master/manager ограничены участками; admin не получает производственные строки по роли. Историческая принадлежность сотрудника не даёт текущего доступа. Конечный сервер должен проверять доступ и при генерации, и при последующем скачивании.

Close в периоде может ссылаться на submission до периода; такой submission входит в закрытую когорту, но не в счётчик «отправлено в периоде». Две попытки одного наряда дают один submitted order и две attempts. Технические done + ai_review events не дают два выполненных наряда. Rework и повторная неисправность — разные факты. Рейтинг, простои, повторные неисправности, сложность и обоснованность отказов не выводятся из этих полей; нужны отдельные согласованные определения C3/A0.

Пустая известная когорта: counts=0, mean/rate=null («недостаточно данных»), sample n=0. Неполная/неизвестная когорта: total=null с причиной, а не 0. Для n<5 показывать малую выборку. Процент рядом с numerator/denominator; при denominator=0 никакого 0%. `queue_count=0` не доказывает свободу человека, а active_order_id — только lowest-number представитель видимых in_progress/paused, не единственный активный наряд. Эти поля не заменяют метрики смены.

## 4. Полнота данных и пагинация

`GET /orders` даёт разрешённые текущие страницы без стабильного total/snapshot. Даже drain до next_cursor=null не создаёт транзакционно согласованный исторический capture. Запрет: число текущей страницы / сумма страниц / число видимых строк как «всего за смену».

- Полный автономный synthetic fixture имеет собственную метку `frozen_complete_synthetic`; этого достаточно только для проверки примера
- API pages, прерванная загрузка, несовпавшие scope/as_of или неизвестное покрытие: summary=null, явная причина; разрешён список наблюдённых строк с временем чтения, без итогов
- Для authoritative отчёта нужен согласованный серверный snapshot/query/export manifest с capture ID, scope, временными границами, версией схемы и доказуемой полнотой orders/submissions/reviews/events/dictionaries
- Полный capture не означает разрешение на публикацию данных. Внешняя передача требует отдельного разрешения

## 5. Автономный пример и независимо заданный oracle

Файлы в этой папке:

- `c4-report-cases.json`: один небольшой замороженный synthetic capture с полными wire Order/Submission/Assessment/Review полями и отдельными report metadata; не импорт в DB
- `c4-report-expected.json`: вручную заданные ожидаемые IDs, количества и Decimal итоги; не генерируется renderer
- `c4_report_examples.py`: stdlib-only валидатор узких инвариантов capture, расчёт примера и HTML-представление; не полный OpenAPI validator и не production код
- `test_c4_report_examples.py`: позитивные и негативные данные/render assertions; никакого mock/API/DB/модели/телефона

Запуск из root: `python -m unittest discover -s docs/reports -p 'test_c4_report_examples.py' -v`.

Построение примеров: `python docs/reports/c4_report_examples.py --output-dir /tmp/c4-report-preview`. В output появляются `order.html`, `shift.html`, `summary.json`. Каждый HTML содержит source base SHA, contract SHA-256, normalized_input_sha256 (sorted compact UTF-8 JSON, Decimal как строки) и реальное generated_at UTC. На каждом HTML видна надпись «СИНТЕТИЧЕСКИЙ АВТОНОМНЫЙ ПРИМЕР». HTML не содержит внешних ресурсов, скриптов или фотографий. Проверка строк/DOM не является визуальной проверкой PDF/печати, Android или живого отчёта. Полная lifecycle-хронология не изображается: fixture содержит только attempts/reviews, не полный OrderEvent журнал.

Ручная арифметика: выдано 3; отправлено 2 наряда / 4 попытки; close 2 наряда; rework 1; overdue на as_of 1. Close scores `[null, 0]` → среднее 0, scored n=1, unscored n=1. Close-linked on-time `[true, false]` → 1/2. Материалы closed submissions: 2,25 кг одного material_id и 1 шт другого; 1,125 кг из rework attempt не добавляются. Поздняя AI-оценка revision 1 сохраняется как stale история, не рекомендация revision 2.

## 6. Приёмка данных и представления

| ID | Проверка | Ожидаемый результат |
|---|---|---|
| C4-D01 | Сверить summary с независимым expected JSON | Точные counts, Decimal quantity, источники и denominator |
| C4-D02 | start/end, close с предшествующим submission, due_at=as_of | Границы без двойного учёта; равный срок ещё не overdue |
| C4-D03 | Две assignment revisions с attempt_number=1 | Разные попытки; stale оценка остаётся у своего submission |
| C4-D04 | final_score null и 0; AI score=91 при human null | Null не превращается в 0/91; 0 входит в human sample |
| C4-D05 | assessments=[]; reviews=[]; materials=[] | Отсутствие, неизвестное состояние AI, явный пустой список; не fabricated progress |
| C4-D06 | Partial keyset / drained moving keyset capture | Нет авторитетных totals и rates |
| C4-D07 | Неизвестный material, плохая unit, quantity≤0/NaN/>3 decimals | Отклонение capture; не подставлять quantity=0 или unit «шт» |
| C4-D08 | Duplicate IDs / неверный cross-order/revision join / пропущенное required поле | Отклонение с field-level кодом, не тихий пропуск |
| C4-R01 | HTML в description/reason/labels и кавычки в IDs, если бы прошли validation | Только escaped text; UUID строго проверяются; никакого script/img/event handler |
| C4-R02 | Длинный русский work_description до 6000 и comment до 2000, переводы строк | Полный текст сохранён, CSS wrap/pre-wrap; overflow/печать требуют visual check |
| C4-R03 | Decimal 1.125, 2.250; даты UTC+5 | 1,125; 2,25; зона явная; никакого float drift |
| C4-R04 | Sources и synthetic label на обоих HTML | Видны source IDs; ни «реальная БД», ни «модель вызвана» |
| C4-F01 | Будущий CSV/XLSX export с `=`, `+`, `-`, `@`, tab/CR в text cells | Отдельная защита spreadsheet formulas, typed numeric cells; здесь NOT_RUN, CSV/XLSX не реализованы |

Формат report input намеренно не подменяет OpenAPI: metadata/coverage принадлежат только synthetic примеру. UUID, связи, decimal, обязательное присутствие collections/null, score и timestamps проверяются локально. Полное бизнес-состояние, upload ownership, RBAC, права на unit/name, сортировка полного event feed и возможности печати остаются отдельными runtime gates.

## 7. Точные решения, необходимые от A0/A6 перед runtime-отчётом

1. **Поверхность**: принять конкретные report routes/operation IDs, order/shift input filters, response schema/version и выбранный формат HTML/PDF/Excel. Core сейчас таких маршрутов не имеет
2. **Snapshot**: определить transaction/export consistency, capture ID, as_of, period/filter binding, max window/limits, полноту history/dictionaries и поведение при concurrent mutation; moving keyset не годится как доказательство total
3. **Scope и выдача**: кто получает order/shift, scoped master/manager и executor-self; отсутствие admin workload; повторная авторизация скачивания, private/no-store, TTL и отзыв доступа; никакой постоянной публичной ссылки
4. **История**: механизм полного перечня submissions и всех revisions/events (сейчас historical submission читается по уже известному ID); join/ordering, mapping reviews↔event IDs, гарантии occurred_at/recorded_at и отрезания после as_of
5. **Материалы**: declaration versus authoritative writeoff; повторные попытки cumulative/delta; исторические unit/label/version и правила объединения. Пока показывать per-attempt declaration либо явно close-linked declaration
6. **Время и итоговые метрики**: подтвердить half-open window, display zone, shift identifier/расписание, as_of reconstruction, sample/denominator conventions и отдельные C3 definitions. Не называть паузу простоем
7. **AI job state**: принять отдельный status/absence/failure interface, если UI должен показывать pending/failed; selection current assessment и сохранение stale history; человеческий Review всегда отдельно
8. **Экспорт и безопасность**: допустимые размеры/long text/page breaks, нейтрализация HTML/CSV formulas, protected photo attachment, redaction/retention, файл-name/MIME и проверяемые Unicode fonts для PDF
9. **Реализация и evidence**: выделить точный backend/frontend scope, isolated DB query/HTTP tests, device/print validation, code/capture hashes и independent review. C4 docs PASS не закрывает R06a/R06b на живом сервисе

Следующий безопасный шаг: A0 выбирает минимальный DB-backed order report seam и snapshot semantics; затем новый GRANT на реализацию/интеграционные проверки. Исторический synthetic capture не посылается через live POST и не требует ослаблять live deadline validation.
