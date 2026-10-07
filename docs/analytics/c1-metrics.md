# C3: метрики на зафиксированном экспорте C1

**Офлайн, только синтетика.** Это применение [определений C3](metric-definitions.md)
к immutable C1, не API/БД-отчёт, оценка работников или доказательство качества
модели. Исходный C3 commit `2a65c80b94d92bd15112dd95d9498998431eb00c`
сохранён; этот пакет добавляется отдельно.

## Вход и воспроизводимость

- Исторический C1 checkpoint: `5775d6f6aa8e1bbf8796e7ba36c9ada6f1edd6e7`,
  прежний путь `data/synthetic/v1/history.json`; только provenance, **не зависимость запуска**
- Опубликованный generator C1: `8af3897f03aa2f41f0af07ec74ec2c807a4a535a`
- Стандартный вход: `data/synthetic/generated/v1/history.json`
- SHA-256 точных bytes:
  `7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1`
- Область: все четыре синтетических участка этого export; это **не проверка
  текущего доступа пользователя**
- Полный период: `[2026-06-30T19:00:00Z,2026-09-30T19:00:00Z)`, то есть
  июль–сентябрь 2026 UTC+5. Месяцы тоже полуоткрытые, границы записаны в manifest
- Единственный используемый snapshot: `2026-09-30T19:00:00Z`. Ежемесячные flow
  не выдают нынешнее closed-состояние за исторические month-end stocks

```sh
# Сначала воспроизвести полный источник опубликованным C1 generator
PYTHONDONTWRITEBYTECODE=1 python3 scripts/synthetic/generate.py --output data/synthetic/generated/v1/history.json
PYTHONDONTWRITEBYTECODE=1 python3 docs/analytics/c1_metrics.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s docs/analytics -p 'test_c1_metrics.py' -v
python3 docs/analytics/c1_metrics.py --trace full/human_score
python3 docs/analytics/c1_metrics.py --trace all > /tmp/c3-c1-source-traces.json
```

По умолчанию calculator читает стандартный **локальный generated файл**.
Git, `.git`, сеть и старый unpublished checkpoint не требуются. Если вход ещё не
создан, выдаётся ошибка с командой generation; скрипт не подменяет полный источник
маленьким illustrative example. Для другого расположения того же файла:
`python3 docs/analytics/c1_metrics.py --history <generated-history.json> --check`.
Для tests с внешним файлом можно установить `C3_HISTORY_PATH=<generated-history.json>`;
без него они читают стандартный generated путь. В обоих режимах принимаются
только bytes с указанным SHA-256. Другой dataset требует новой явной версии,
а не обновления expected values. Calculator не запускает generator, не читает
evaluator truth и не пишет в C1. Source-only distribution должен содержать
публичные scripts/synthetic для шага generation либо уже полученный canonical файл.

[Manifest](c1-metrics-manifest.json) содержит supported/unsupported metrics,
точные числители/знаменатели, missing/eligible counts, status, полные границы,
два UUID-примера и hash полного списка UUID для каждой метрики. `--trace` выдаёт
**все** source IDs соответствующего source_table. Samples не являются полным
списком. Полный trace воспроизводим и связан global hash; в репозитории не
дублируется большой массив уже опубликованной истории.

Для human_score trace содержит **все eligible close-review IDs**, включая null.
Observed denominator выбирается как final_score!=null; missing — противоположное
условие. Для T trace содержит close-linked submission IDs; numerator выбирается
как done_late=false. Для Rw_closed trace содержит closed order IDs; lower attempt
той же assignment revision должен иметь human rework. Правила доступны в исходной
спецификации и calculator. `excluded_from_eligible=0` означает отсутствие тихо
отброшенных строк уже выбранной когорты; строки вне неё не входят в этот счётчик.
Count denominator=null означает «не доля», а не отсутствие известного количества.

Value хранится decimal-строкой с округлением half-even до 12 знаков; точный
numerator/denominator имеет приоритет. Нельзя усреднить три месячных mean без
весов: quarter Q считается из суммы баллов/суммы scored, не mean of means.

## Полученные значения

| Период UTC+5 | Закрыто | Попыток | Возвратов | Human score sum/scored; unscored | В срок среди закрытых |
|---|---:|---:|---:|---|---|
| Июль–сентябрь | 540 | 568 | 28 | 41859/486; 54 | 492/540 |
| Июль | 182 | 192 | 10 | 14141/163; 19 | 182/182 |
| Август | 182 | 191 | 9 | 14138/164; 18 | 182/182 |
| Сентябрь | 176 | 185 | 9 | 13580/159; 17 | 128/176 |

За полный период issued=540 и distinct submitted=540. Attempt-on-time=520/568;
Rw_closed=28/540. На **конечный as_of** overdue_active=0 и awaiting_review=0,
потому что в этом C1 corpus все 540 итоговых snapshots closed. Это не отсутствие
исторических опозданий: 48 close-linked submissions поздние. Не выводить из нуля
настоящую доступность работников или успех runtime deadline monitor.

Q имеет status=partial из-за 54 unscored закрытий. Все оценки вымышленные.
AI assessments отсутствуют; AI quality=null/no_assessment, состояние AI jobs
неизвестно. Downtime, seven-day repeat fault, composite rating и исторические
month-end stocks остаются null с разными явными причинами.

## Проверки и ограничения

Восемь новых stdlib checks: воспроизведение manifest; зафиксированные суммы;
отдельная прямая сверка close-review/late фактов; принадлежность каждого trace ID
реальному source table и его hash; разбиение месяцев без потерь/пересечений;
null unsupported metrics; независимость от порядка входных строк; изменённый
canonical hash отвергается. Отдельный portability regression копирует только
calculator/manifest и canonical bytes в временный source-only каталог без `.git`,
обнуляет PATH и выполняет оба пути чтения (default и --history), а также отрицательный
случай missing file. Это доказывает отсутствие скрытого вызова Git. Дополнительно
исходные 15 oracle cases сохраняются.
Independent numeric review C4 относится к указанному result SHA в handoff.

Никакого production extractor, SQL, импорта, backend endpoint, auth/RBAC,
модельных вызовов, изображения, device или deployment здесь не проверено.
Source profile узкий и привязан hash; это не универсальный validator истории.
