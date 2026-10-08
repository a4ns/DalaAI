import { Provenance } from '../analytics/Reports';
import { showTime } from '../analytics/model';
import type { AiReportState } from './controller';
import type { AiReportKind, AiReportSelection } from './protocol';
import './aiReports.css';

export function AiReportView({ state, selection, disabled, onGenerate, onRetry }: {
  state: AiReportState; selection: AiReportSelection | null; disabled: boolean;
  onGenerate: (kind: AiReportKind) => void; onRetry: () => void;
}) {
  const busy = state.status === 'loading'; const unresolved = state.status === 'unknown_result';
  const shiftAvailable = Boolean(selection && Date.parse(selection.end) - Date.parse(selection.start) <= 86400000);
  const data = state.data;
  return <section className="card ai-reports" aria-label="Сводка и анализ по фактам" aria-busy={busy}>
    <h3>Сводка и анализ по фактам</h3>
    <p>Запрос выполняется только по кнопке для выбранного периода. Сервер проверит доступ и получит новый снимок; его время может отличаться от таблицы.</p>
    {!selection && <p>Сначала загрузите разрешённый период аналитики.</p>}
    <div className="ai-reports-actions">
      <button type="button" disabled={disabled || !shiftAvailable || busy || unresolved} onClick={() => onGenerate('shift')}>Сводка смены</button>
      <button type="button" disabled={disabled || !selection || busy || unresolved} onClick={() => onGenerate('history')}>Анализ истории</button>
    </div>
    {selection && !shiftAvailable && <p>Сводка смены доступна для периода до 24 часов. Для этого периода используйте анализ истории.</p>}
    {busy && <p role="status">Готовим сводку. Режим и результат ещё не подтверждены…</p>}
    {state.error && <p role="alert">{state.error}</p>}
    {unresolved && <button type="button" disabled={disabled} onClick={onRetry}>Проверить тем же запросом</button>}
    {data && <>
      <h4>{data.report_kind === 'shift' ? 'Сводка смены' : 'Анализ истории'}</h4>
      <p><strong>{data.mode === 'openai' ? 'OpenAI выбрал факты и рекомендации; текст построен сервером' : data.mode === 'recorded_fixture' ? 'Записанный пример, без живого вызова модели' : 'Фактическая сводка по правилам, без ответа модели'}</strong></p>
      <p>{data.label}</p>
      {data.model && <p>Модель по ответу сервера: {data.model}</p>}
      {data.fallback_reason && <p>Причина резервного режима: {data.fallback_reason}</p>}
      <p>Сформировано (реальное время): {showTime(data.generated_at_real)}.</p>
      {data.reserved_upper_bound_microusd > 0 && <p>Зарезервированная верхняя граница стоимости: {data.reserved_upper_bound_microusd} микро-USD. Фактическое списание неизвестно.</p>}
      <Provenance source={data.provenance} period={data.period}/>
      <p className="ai-reports-text">{data.summary}</p>
      <h4>Факты и основания</h4>
      {data.highlights.length === 0 ? <p>Подтверждённые факты не представлены. Это не нулевой итог периода.</p> : data.highlights.map(fact => <article key={fact.fact_id} className="ai-reports-fact"><p>{fact.text}</p><details><summary>Основания факта {fact.fact_id}</summary><p>Таблица: {fact.source_table}. Записи: {fact.source_ids.join(', ') || 'Нет ссылок на записи'}.</p>{fact.equipment_id && <p>Оборудование: {fact.equipment_id}</p>}</details></article>)}
      <h4>Что проверить мастеру</h4>
      {data.recommendations.length === 0 ? <p>Дополнительные рекомендации не сформированы.</p> : <ul>{data.recommendations.map((item, index) => <li key={`${item.code}:${index}`}><p>{item.text}</p><p>Основания: {item.fact_ids.join(', ') || 'Не указаны'}.</p></li>)}</ul>}
      {(data.limitations.length > 0 || data.unavailable_reasons.length > 0) && <aside><h4>Ограничения</h4><ul>{[...data.limitations, ...data.unavailable_reasons].map((line, index) => <li key={index}>{line}</li>)}</ul></aside>}
      <p>Выводы требуют проверки мастером. Сводка не подтверждает исправность оборудования, допуски или безопасность работ. Фото этой сводкой не проверяются.</p>
    </>}
  </section>;
}
