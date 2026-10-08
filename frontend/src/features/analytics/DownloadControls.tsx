import { useEffect, useState, useSyncExternalStore } from 'react';
import type { ApiClient } from '../../shared/api/client';
import type { OrderReport, ShiftReport } from '../../shared/api/analyticsProtocol';
import type { AnalyticsController } from './controller';
import { ReportDownloadController } from './downloads';
export function DownloadControls({client,report,analytics,isAuthReady,disabled}:{client:ApiClient;report:OrderReport|ShiftReport;analytics:AnalyticsController;isAuthReady:()=>boolean;disabled:boolean}) {
  const [download]=useState(()=>new ReportDownloadController(client,report,()=>isAuthReady()&&analytics.getSnapshot().report.data===report,error=>analytics.reportAccessLost(error,report)));
  const state=useSyncExternalStore(download.subscribe,download.getSnapshot);
  useEffect(()=>{const detach=download.attach();const off=analytics.subscribe(()=>{if(analytics.getSnapshot().report.data!==report)download.cancel();});return()=>{off();detach();};},[download,analytics,report]);
  useEffect(()=>{if(disabled)download.cancel();},[disabled,download]);
  return <section className="card" aria-label="Скачать выбранный отчёт"><h3>Скачать выбранный отчёт</h3><p>Файл формируется заново для периода и наряда показанного отчёта, с текущей проверкой доступа. Его время снимка может отличаться.</p>
    <div className="analytics-actions"><button type="button" disabled={disabled||state.status==='loading'} onClick={()=>void download.prepare('pdf')}>Подготовить PDF</button><button type="button" disabled={disabled||state.status==='loading'} onClick={()=>void download.prepare('xlsx')}>Подготовить XLSX</button></div>
    {state.status==='loading'&&<p role="status">Получаем {state.format?.toUpperCase()}… Сохранение ещё не начато.</p>}
    {state.status==='ready'&&<><p role="status">Файл получен. Ссылка для сохранения действует одну минуту.</p><button type="button" disabled={disabled} onClick={download.save}>Сохранить {state.format?.toUpperCase()}</button></>}
    {state.status==='handed_off'&&<p role="status">Запрос сохранения передан браузеру. Проверьте результат в загрузках.</p>}
    {state.status==='expired'&&<p role="status">Время сохранения истекло. Получите файл заново.</p>}
    {state.status==='error'&&<p className="error" role="alert">{state.error}</p>}
  </section>;
}
