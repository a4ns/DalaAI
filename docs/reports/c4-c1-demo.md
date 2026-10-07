# C4: автономный отчёт из настоящего файла synthetic history C1

Статус: **offline synthetic report**, не импорт в БД и не отчёт приложения.
Сохранённые примеры ниже построены из исторического C1 export commit
`5775d6f6aa8e1bbf8796e7ba36c9ada6f1edd6e7`; этот большой объект не требуется
и может отсутствовать в fresh clone. Текущий builder читает локальный результат
публичного C1 generator `8af3897f03aa2f41f0af07ec74ec2c807a4a535a`, по умолчанию
`data/synthetic/generated/v1/history.json`, со строго тем же SHA-256
`7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1`.
Полный вход: 540 нарядов, 568 попыток/решений, четыре вымышленных участка.
Материалы и оценки также синтетические. Evaluator truth не читается.

## Проверяемый результат

- `c1-demo/order-521.html`: наряд 521, ID `a6ee1c96-9473-5998-bd83-476b161be6eb`, две попытки revision 1, возврат и последующее close с `final_score=null`. AI assessment в исходнике нет
- `c1-demo/period-september-27-30.html`: период 27 сентября 00:00 — 1 октября 00:00 UTC+5, то есть `[2026-09-26T19:00:00Z,2026-09-30T19:00:00Z)`. Это явно выбранный четырёхдневный период, не утверждённое расписание производственной смены
- `c1-demo/report-source-trace.json`: выбранный исходный order, все его attempts/reviews/materials, actor codes, события и photo placeholders; source IDs и точные значения сводки периода
- `c1-demo/manifest.json`: source/code SHA, входной hash/counts, настоящий момент построения, hashes/bytes файлов, компактная арифметика периода и полного квартала

Полный capture обрабатывается до выбора периода, поэтому ранние связанные
attempts/reviews не теряются. Stock overdue считается только на настоящем export
as_of `2026-09-30T19:00:00Z`, а не на угаданном историческом snapshot.
Область «все четыре synthetic участка» — граница вымышленного набора, **не
доказательство пользовательских прав**. Все snapshots здесь closed; overdue=0.

Период: выдано/отправлено/закрыто по 23 наряда, 25 attempts, 2 возврата;
human score сумма 1829 / scored n=21, unscored n=2; on-time 19/23.
Полный квартал: 540 выдано/отправлено/закрыто, 568 attempts, 28 возвратов;
human score сумма 41859 / scored n=486, unscored n=54; on-time 492/540.
Это точные результаты данного synthetic capture, не показатели предприятия.

## Явное сопоставление с существующим C4 facts schema

| C1 export | C4 facts | Правило |
|---|---|---|
| metadata.synthetic, window, as_of | synthetic, period, coverage | Проверенный source hash + manifest counts; выбранный период внутри окна, as_of только исходный |
| orders | orders | Все исходные поля сохраняются; derived domain_now=export as_of; is_overdue по accepted-core active status и due_at<as_of |
| submissions | submissions | Все исходные поля, work/material payload, ID/revision/attempt, done_late/completeness неизменны |
| reviews | nested submission.reviews | Join только по submission_id, без потери nullable final_score; максимум один immutable review |
| ai_assessments=[] | nested submission.assessments=[] | Никакого fake model/rules_fallback, pending или failed |
| materials | materials | IDs, labels и units сохраняются из замороженного справочника |
| material_writeoffs | не используются для общего складского итога | HTML считает только декларации close-linked final attempts; не смешивает с расходом rework attempts |
| employees | selected source trace actor codes | Не подставлять сегодняшнего ответственного как автора прежней попытки |
| order_events/photos | selected source trace | Подлинные строки synthetic файла; photos artifact_available=false, нет image bytes/валидации реального ремонта |

Существующий HTML renderer показывает attempts/reviews, а полный synthetic
OrderEvent trace выбранного наряда дан в JSON отдельно. Рендеринг raw IDs не
заменяет защищённое получение фото. Source `complete` означает полноту fictional
structure; оно не разрешает живое закрытие без реальных evidence gates.

## Воспроизведение и тесты

Из root source-пакета с публичным C1 generator, стандартный Python. Каталог `.git` не требуется:

```sh
python3 scripts/synthetic/generate.py --output data/synthetic/generated/v1/history.json
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s docs/reports -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python docs/reports/c4_c1_history_report.py --output-dir docs/reports/c1-demo
```

Повторная сборка сохраняет значения и source-ID trace, но меняет реальный
`generated_at` HTML/manifest, поэтому hashes заново построенных HTML закономерно
отличаются. Проверять output manifest своей сборки; не выдавать старый hash за
новый. Для иного расположения передать `--history <file>`; тесты принимают `C4_HISTORY=<file>`.
Adapter сверяет точный hash до projection; не вызывает Git, generator, сеть,
credentials, live POST, DB или модель. `--code-sha <40-hex>` необязателен:
без него code SHA=null с явной причиной, source SHA-256 обоих report-модулей
всегда записаны. Это поддерживает source-only архив и не выдумывает commit.

Сохранённые ранее HTML/JSON/manifest остаются неизменными с первоначальной
исторической provenance. Новая сборка указывает публичный generator commit и
свой момент построения. Manifest counts привязаны к точным разрешённым bytes,
а не читаются из необязательного соседнего файла; любой другой hash отклоняется.

Проверяются целостность pin, tamper rejection, counts, joins, source preservation,
полная когорта, null/AI absence, units, независимая арифметика и отсутствие мутации
источника. Существующие 19 C4 checks сохраняются. Визуальная проверка browser/
PDF/печати, runtime RBAC, API/DB и реальные устройства: **NOT_RUN**.
Независимая сверка C3 и точный implementation/artifact SHA фиксируются в handoff.
