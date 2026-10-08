import { showTime } from '../analytics/model';
import { sameId } from '../aiReports/validation';
import { eligibleExecutor } from './controller';
import type { AssigneeContext, AssigneeState, EligibleExecutor } from './controller';
import { limitationLabels, reasonLabels } from './protocol';
import './assigneeRecommendations.css';

export function AssigneeRecommendationsView({ state, context, executors, disabled, onLoad, onChoose }: {
  state: AssigneeState; context: AssigneeContext | null; executors: readonly EligibleExecutor[]; disabled: boolean;
  onLoad: () => void; onChoose: (id: string) => void;
}) {
  const data = state.data;
  const candidates = data?.candidates.filter(candidate => context && executors.some(executor => sameId(executor.id, candidate.executor_id) && eligibleExecutor(executor, context))) ?? [];
  return <section className="assignee-recommendations" aria-label="Подсказка по исполнителям" aria-busy={state.status === 'loading'}>
    <h3>Подсказка по исполнителям</h3>
    <p>Рекомендация по правилам: сначала видимая загрузка, затем активные работы и наблюдения по выбранному шифру. Модель ИИ не вызывается.</p>
    <p>Специальность, квалификация, допуски и пригодность к оборудованию неизвестны. Проверьте их перед назначением. Выбор и решение остаются за мастером.</p>
    <button type="button" disabled={disabled || !context || state.status === 'loading'} onClick={onLoad}>Предложить исполнителей</button>
    {!context && <p>Сначала выберите участок и загрузите актуальные справочники.</p>}
    {state.status === 'loading' && <p role="status">Получаем рекомендации для текущего участка…</p>}
    {state.status === 'expired' && <p role="status">Срок рекомендации истёк. Запросите свежий снимок перед выбором.</p>}
    {state.error && <p role="alert">{state.error}</p>}
    {data && <>
      <p><strong>{data.synthetic ? 'СИНТЕТИЧЕСКИЕ ДАННЫЕ — не история предприятия' : 'Данные разрешённой области'}</strong></p>
      <p>Снимок получен: {showTime(data.as_of)}. Действует до {showTime(data.expires_at)} (реальное время).</p>
      <p>Доменное время загрузки и истории: {showTime(data.domain_as_of)}.</p>
      <p>Доступных на участке: {data.eligible_count}. Сервер вернул: {data.returned_count}. {context?.brigadeId ? 'Ниже показаны только кандидаты выбранной бригады среди возвращённых рекомендаций.' : 'Одинаковый ранг означает равные условия сортировки.'}</p>
      {data.eligible_count === 1 && <p>Доступен один исполнитель. Сравнение с альтернативами невозможно.</p>}
      {data.eligible_count === 0 && <p>Доступных исполнителей на смене не найдено. Никто не назначен.</p>}
      {data.eligible_count > 0 && candidates.length === 0 && <p>Среди возвращённых рекомендаций нет исполнителя, подходящего текущему выбору бригады и справочникам.</p>}
      {candidates.map(candidate => {
        const executor = executors.find(row => sameId(row.id, candidate.executor_id))!;
        const h = candidate.history; const w = candidate.workload;
        return <article key={candidate.executor_id} className="assignee-recommendations-candidate">
          <h4>{executor.label} · ранг по правилам {candidate.rank}</h4>
          <p>Код: {candidate.employee_code}. На смене по данным снимка.</p>
          <p>Незавершённых: {w.outstanding_count}; в работе или на паузе: {w.active_count}; в очереди: {w.queued_count}; ожидают проверки: {w.awaiting_review_count}; просроченных: {w.overdue_count}.</p>
          <p>Сумма норм незавершённых работ: {w.norm_minutes_total} мин. Это не оставшееся время и не полная загрузка за пределами доступа мастера.</p>
          <ul>{candidate.reason_codes.map((code, index) => <li key={`${code}:${index}`}>{reasonLabels[code]}</li>)}</ul>
          <p>История закрытых работ: {showTime(h.window_start)} — {showTime(h.window_end)}, обе границы включены. Закрыто: {h.closed_count}.</p>
          {h.status === 'no_observations' && <p>Наблюдений нет. Качество и опыт неизвестны.</p>}
          <p>Средняя оценка мастера: {h.human_score_mean === null ? 'неизвестна' : h.human_score_mean}; оценок: {h.human_score_count}.</p>
          <p>Отправлено в срок среди закрытых: {h.on_time_rate === null ? 'нет наблюдений' : `${h.on_time_count} из ${h.closed_count}`}. Совпадений по шифру: {h.matching_work_code_count === null ? 'шифр не выбран' : h.matching_work_code_count}.</p>
          <details><summary>Основания и ссылки на записи</summary>
            <p>Текущая загрузка:</p>{w.evidence.length === 0 ? <p>В видимой области записей нет.</p> : <ul>{w.evidence.map(row => <li key={row.order_id}>Наряд {row.order_id}; статус {row.status}; срок {showTime(row.due_at)}; обновлён {showTime(row.updated_at)}</li>)}</ul>}
            {w.evidence_truncated && <p>Показаны не все ссылки загрузки.</p>}
            <p>История подтверждённых мастером закрытий:</p>{h.evidence.length === 0 ? <p>Исторических ссылок нет.</p> : <ul>{h.evidence.map(row => <li key={row.review_id}>Наряд {row.order_id}; результат {row.submission_id}; решение {row.review_id}. Отправлен {showTime(row.submitted_at)}; проверен {showTime(row.reviewed_at)}. Оценка мастера: {row.final_score === null ? 'не выставлена' : row.final_score}.</li>)}</ul>}
            {h.evidence_truncated && <p>Показаны не все исторические ссылки.</p>}
          </details>
          <button type="button" disabled={disabled} onClick={() => onChoose(candidate.executor_id)}>Выбрать {executor.label} в черновике</button>
        </article>;
      })}
      <ul>{data.limitations.map((code, index) => <li key={`${code}:${index}`}>{limitationLabels[code]}</li>)}</ul>
      <p>Выбор здесь меняет только черновик. При выдаче наряда сервер повторно проверит назначение. Подсказка не является кадровым решением или оценкой безопасности.</p>
    </>}
  </section>;
}
