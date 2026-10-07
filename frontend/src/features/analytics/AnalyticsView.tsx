import type { AnalyticsState } from './controller';
import { FactTotals, OrderReportView, Provenance, ShiftReportView, Unavailable } from './Reports';
import { instantToLocal, showTime, statusLabels } from './model';
import './analytics.css';
export interface AnalyticsViewProps { state:AnalyticsState;draft:{start:string;end:string};onDraftChange:(draft:{start:string;end:string})=>void;onLoad:()=>void;onOpenReport:(orderId:string|null)=>void;domainNow:string|null;onRefreshClock:()=>void;validationError:string|null;selectedOrderId:string;onSelectOrder:(id:string)=>void;onPreset:(hours:number)=>void }
export function AnalyticsView({state,draft,onDraftChange,onLoad,onOpenReport,domainNow,onRefreshClock,validationError,selectedOrderId,onSelectOrder,onPreset}:AnalyticsViewProps) {
  const facts=state.facts.data;
  return <section className="analytics-view" aria-label="Аналитика и отчёты">
    <p>Факты разрешённых участков. Выберите смену или период до 93 суток. Все даты и время — UTC+5.</p>
    <form className="card analytics-period" onSubmit={event=>{event.preventDefault();onLoad();}}>
      <label>Начало периода<input type="datetime-local" step="1" required value={draft.start} onChange={e=>onDraftChange({...draft,start:e.target.value})}/></label>
      <label>Конец периода (не включён)<input type="datetime-local" step="1" required value={draft.end} max={domainNow?instantToLocal(domainNow):undefined} onChange={e=>onDraftChange({...draft,end:e.target.value})}/></label>
      <p>{domainNow?`Последнее подтверждённое доменное время: ${showTime(domainNow)}.`:'Доменное время пока неизвестно. Укажите явные даты; допустимый конец проверит сервер. Время устройства не используется.'}</p>
      <div className="analytics-actions"><button type="button" className="secondary" onClick={onRefreshClock}>Обновить время из нарядов</button><button type="button" className="secondary" disabled={!domainNow} onClick={()=>onPreset(12)}>12 часов до снимка</button><button type="button" className="secondary" disabled={!domainNow} onClick={()=>onPreset(24)}>24 часа до снимка</button></div>
      <p className="hint">Быстрые интервалы не задают официальный график смен. Конец ограничен временем последнего ответа сервера; часы здесь не продвигаются автоматически.</p>
      {validationError&&<p className="error" role="alert">{validationError}</p>}
      <button type="submit">{state.facts.status==='loading'?'Запросить другой период':'Показать факты'}</button>
    </form>
    {state.facts.status==='idle'&&state.report.status==='idle'&&<p>Период ещё не запрошен.</p>}
    {state.facts.status==='loading'&&<p role="status">Получаем согласованный снимок. Прежние результаты скрыты.</p>}
    {state.facts.status==='error'&&<p className="error" role="alert">{state.facts.error}</p>}
    {facts&&<>
      <Provenance source={facts.provenance} period={facts.period}/><FactTotals data={facts}/><Unavailable reasons={facts.unavailable_reasons}/>
      <section className="card"><h3>Защищённые отчёты</h3><p>Отчёт загружается отдельно с проверкой текущего доступа и собственным временем снимка. Выбранный период относится к итогам; список содержит все разрешённые наряды снимка.</p>
        <button type="button" onClick={()=>onOpenReport(null)}>Открыть отчёт смены / периода</button>
        {facts.orders.length===0?<p>В успешно полученном снимке нет доступных нарядов.</p>:<><label>Наряд для отчёта<select value={selectedOrderId} onChange={e=>onSelectOrder(e.target.value)}><option value="">Выберите наряд</option>{facts.orders.map(({order})=><option key={order.id} value={order.id}>№{order.number} · {statusLabels[order.status]??order.status} · {order.description.slice(0,80)}</option>)}</select></label><button type="button" disabled={!facts.orders.some(row=>row.order.id===selectedOrderId)} onClick={()=>onOpenReport(selectedOrderId)}>Открыть отчёт наряда</button></>}
      </section>
    </>}
    <section className="analytics-report" aria-label="Выбранный отчёт">
      {state.report.status==='loading'&&<p role="status">Загружаем защищённый отчёт…</p>}
      {state.report.status==='error'&&<p className="error" role="alert">{state.report.error}</p>}
      {state.report.data&&(state.report.data.report_kind==='order'?<OrderReportView data={state.report.data}/>:<ShiftReportView data={state.report.data}/>)}
    </section>
  </section>;
}
