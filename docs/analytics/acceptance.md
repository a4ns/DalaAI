# Минимальная приёмка C3

## Что этот пакет проверяет

Это **synthetic unit arithmetic**, не runtime-результат. Команда:

```sh
python3 docs/analytics/check_examples.py
```

Ожидаемый исход: 15 тестов, OK. Конкретный запуск, SHA и время фиксируются в
handoff после коммита; эта инструкция сама по себе не является PASS evidence.
Expected values находятся в worked-examples.json отдельно от вычислений.
Checker никогда их не перегенерирует. Ни один результат здесь не является
измерением модели, сотрудника, БД, телефона или экономии.

### Независимая ручная сверка основного примера

Период: 2 октября 2026, 00:00–24:00 **UTC+5**. UTC:
`[2026-10-01T19:00:00Z,2026-10-02T19:00:00Z)`; domain_as_of равен правой границе.
Все данные вымышленные, IDs символические, reduced schema специально не wire.

| Факт | Ожидаемый результат | Почему |
|---|---|---|
| Выдано | 6: A,C,D,E,H,J | A на start включён; F ровно на end исключён; остальные выданы ранее |
| Отправлено нарядов / попыток | 4 / 5 | A,B,C,I; у B две отправки; sG и sIold до start |
| Принято мастером | 4: A,B,G,I | rG ровно на start включён, хотя sG до start; C ещё на проверке |
| Возвратов в периоде | 1: rB1 | rIold произошёл до start |
| Ожидает проверки / просрочено сейчас | 1 / 2 | C в ai_review; D/E активны после срока; J ровно в срок, H cancelled |
| Средняя human score | (80+0+100)/3 = 60 | rB2 unscored; два AI score=99 ничего не заполняют; eligible=4, missing=1, partial |
| T: принятые, отправленные в срок | 3/4 = 75% | sA,sG,sInew вовремя; sB2 поздно; время решения мастера не используется |
| Rw_closed той же revision | 1/4 = 25% | B был возвращён; старый возврат I относился к worker-A/revision1, close — worker-B/revision2 |
| Attempt-on-time | 2/5 = 40% | sA,sInew вовремя; две поздние попытки B и поздняя sC учитываются отдельно |

Несколько правильных чисел (75% и 40%) описывают разные cohorts; подпись
«в срок» без denominator и правила выбора попытки недостаточна.

### Негативные и граничные примеры

- Пустой close cohort: count=0, mean/ratio=null, denominator=0, no_cohort
- Все human scores null: missing, eligible=4, denominator=0; AI не подставляется
- Валидные нулевые наблюдения: 0/2=0%, ok; human score=0 входит в среднее
- Один неизвестный done_late: наблюдаемое 2/3, missing=1, partial; не успех
- Неизвестная timezone, partial capture, неполная связанная история, неверный
  snapshot_as_of, дубли fact ID или чужой section: отклонение вычисления
- Submit: done + ai_review_requested с одной version дают одну попытку;
  точный повтор event ID dedupe, противоречивый повтор отвергается
- Review ровно на end исключён из flow, хотя уже влияет на состояние as_of
- Совпавшие доменные времена последовательных команд не стирают rework;
  отдельные attempt identities/sequence задают порядок
- `assessments=[]` не меняет human metrics и не порождает вымышленный job status
- Гипотетический repeat-fault пример: mature 2, repeat 1, censored 2, rate 50%;
  ранний repeat незрелого episode не попадает в denominator или numerator
- Гипотетические downtime intervals: union внутри оборудования =60
  equipment-minutes; clipping =30; открытый подтверждённый интервал до as_of =30

Эти проверки не являются полноценным validator всей domain/state machine.
В частности, checker принимает декларацию `capture_complete/history_complete`
как предусловие: он не доказывает работу extractor, права пользователя,
целостность всех event sequences или достоверность downtime/fault-классификации.
Защита RBAC должна быть в приложении; отказ toy-checker на чужой section —
проверка правила входа, не security acceptance приложения.

## Минимальный gate для будущего DB-backed отчёта

1. Pin точного code SHA, accepted contract/hash, schema/import adapter, input
   manifest/hash, clock, роли/области, output metric version и environment
2. В изолированной разрешённой БД получить согласованный capture и доказать
   его полноту/изоляцию. Не собирать точный total из moving keyset pages
3. Сверить перечисленные above source IDs и арифметику после реальных commands:
   повтор submit receipt, rework/new attempt, reassign, null/0 human score,
   deadline equality и close до/внутри/после периода
4. Сравнить с независимыми expected values; предъявить numerator/denominator,
   eligible/missing/excluded, small_sample и traceability всех агрегатов
5. Проверить неизменность исторического done_late, human/AI separation,
   current authorization старого submission, запрет межучасткового отчёта
6. Проверить внешний отчёт/экспорт отдельно: UTC+5 подпись, synthetic watermark,
   escaping недоверенного текста, отсутствие секретов и неизвестных нулей
7. Report deployment, real DB run, model invocation и physical phone gates
   отдельными результатами. Unit PASS не повышает их статус

## Известные границы

- **NOT_RUN:** DB-backed analytics, complete-export route, API/frontend reports,
  runtime authorization/restart/concurrency tests, deployment, model calls,
  physical Android, production data, pilot effect
- **BLOCKED для вычисления composite:** принятые rating weights/cohort policy,
  difficulty/exposure, unjustified-refusal adjudication и repeat-fault facts
- **BLOCKED для downtime/recurrence из ядра:** нужных авторитетных фактов нет;
  два маленьких расчёта проверяют лишь предлагаемую арифметику
- **NOT_RUN:** совместимость с полным export C1. Настоящий C1 input не загружается;
  отдельный adapter после фиксированного schema/SHA и grant
- **Не обещается:** восстановление произвольного исторического snapshot из
  сегодняшней строки, bitemporal knowledge history, общий total предприятия,
  confidence interval/industrial accuracy или финальное мнение мастера из AI

Scope: только docs/analytics/**. Нет изменений контракта, migrations,
dependencies, root config, backend, generated client или dataset C1.
Удаление этого документационного пакета не меняет состояние приложения;
rollback при необходимости — обычный reviewed revert соответствующего коммита.
