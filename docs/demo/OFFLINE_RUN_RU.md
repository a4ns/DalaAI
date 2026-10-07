# Одна команда: автономные синтетические доказательства

**Это offline demo/evidence runner, не живой MVP.** Он не запускает API/БД,
браузер, модель, уведомления или деплой. HTML создаётся как инертный файл;
визуальная проверка и все product/device gates остаются `NOT_RUN`.

Нужен Python 3.12 со стандартной библиотекой и локальные, неизменённые файлы
четырёх опубликованных пакетов. Точные commits и SHA-256 каждого необходимого
файла находятся в [offline_sources.json](offline_sources.json):

- C1 `8af3897f03aa2f41f0af07ec74ec2c807a4a535a`: deterministic generator и fixtures
- C2 `936e4327337b1aa3683021d3fd12dc9c987363ee`: frozen rules eval и его AI-rule source
- C3 `c5984436da2b94bf33e61b8a62a2fe54f3657a60`: арифметика по canonical C1 history
- C4 `4a5184fd5caa3c1be35fea5ff55d534967c191bf`: автономные order/period reports

## Запуск

Из source tree, содержащего эти пакеты, выбрать **новый** output directory
с существующей родительской папкой:

```sh
python3 docs/demo/offline_runner.py --output-dir /tmp/naryadai-offline-demo
```

Если C-пакеты лежат в отдельном source-only каталоге без `.git`:

```sh
python3 docs/demo/offline_runner.py --source-root /path/to/source-only-packages \
  --output-dir /tmp/naryadai-offline-demo
```

Путь — локальный каталог пользователя, не предоставленный deployment.
Runner ничего не скачивает, не делает checkout/install, не читает `.env` или
credentials. Missing package или несовпадение pinned bytes дают `BLOCKED`
до исполнения чужого source. Существующий output не перезаписывается.
Выбор нового каталога для нового прогона сохраняет прежние evidence.

Коды выхода: `0` — выполнены только offline проверки; `1` — FAIL выполнения;
`2` — BLOCKED предпосылки. Наличие HTML после частичного сбоя не меняет FAIL.
Первым читать `offline-summary.json`, а не считать появление файлов успехом.

## Что выполняется

1. Проверить 63 pinned source files и скопировать неизменённые bytes во временную
   source-only assembly. Исходный checkout не изменяется; временная копия удаляется
2. C1: создать и проверить полные 540 нарядов с canonical hash; выполнить synthetic tests
3. C2: выполнить tests и отдельно `eval.predict` для dev/holdout, затем вызвать
   публичный `eval.metrics.score` с frozen labels. Это опубликованный two-stage
   seam; `eval.run` не используется, поскольку требует Git/output внутри repo.
   Labels не передаются predictor; C1 evaluator truth не входит в pipeline
4. C3: oracle tests, проверка manifest, JSON-метрики и focused tests на том же history
5. C4: synthetic tests и новые инертные HTML/trace/manifest, затем сверка C3/C4
   counts, null-score и on-time числителей/знаменателей. HTML guard допускает
   только инертные tags/attributes и точный статический CSS pinned renderer

Дочерние процессы получают ограниченный environment без credentials и пустой
`PATH`; используются текущий Python и проверенные offline scripts. Это не
универсальная security sandbox и не разрешение исполнять изменённые пакеты.
Source archive/runner не вызывают Git, сеть или установщики. Генерация не делает
DB import, а historical dates не отправляются live POST.

## Выходы и честные ограничения

- `offline-summary.json`: package SHAs/file hashes, фактически выполненные stages,
  test counts, ошибки и hashes артефактов. Нет вымышленного assembled Git SHA
- `c1/history.json` и manifest: вся canonical synthetic история; не данные предприятия
- `c2/report.json` и predictions: 24 dev + 24 holdout, обязательные gates отдельно
  от semantic abstention. Это не качество модели; model NOT_RUN, cost null
- `c3/metrics.json`: точная арифметика и provenance; все human scores вымышленные
- `c4/`: order/period HTML, исходные IDs и manifest новой сборки. Временные метки
  и HTML hashes могут отличаться между прогонами. Рендер браузером не выполняется
- `logs/`: отдельный log каждого выполненного stage, без частных source/output paths

Generated outputs могут занимать несколько мегабайт. Они остаются локальными;
не отправлять их через большой publication call и не добавлять автоматически в
Git. Скрипт ничего не публикует. После интеграции других versions требуется новый
pin/review, а не отключение проверки hash. Исторические local checkpoint IDs
в C3/C4 provenance не нужны для исполнения и не подменяют четыре public commits.

Проверки самого runner:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s docs/demo \
  -p 'test_offline_runner.py' -v
```

## Выполненная source-only проверка

На immutable runner `825966a6d8a3183b5c98cc62c5e56883848c3ab1`: все 13 stages
PASS; C1 25 + C2 22 + C3 15/8 + C4 33 = **103 package tests**, отдельно
**14 runner guard tests**. 540 orders, 568 submissions и 48 eval episodes;
C3/C4 quarter totals согласованы. Missing-package/no-overwrite CLI вернули
BLOCKED/exit 2. Это не application PASS. Подробности и hashes:
[компактная запись фактического прогона](../evidence/run/offline-825966a.json).
