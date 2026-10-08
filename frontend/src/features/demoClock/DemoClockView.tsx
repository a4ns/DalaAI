import type { DemoClockState } from './controller';
import { showTime } from '../analytics/model';
export interface DemoClockViewProps {state:DemoClockState;disabled?:boolean;scale:string;seconds:string;onScale:(value:string)=>void;onSeconds:(value:string)=>void;onRefresh:()=>void;onPause:()=>void;onResume:()=>void;onSetScale:()=>void;onAdvance:()=>void;onResolve:()=>void;inputError:string|null}
export function DemoClockView({state,disabled=false,scale,seconds,onScale,onSeconds,onRefresh,onPause,onResume,onSetScale,onAdvance,onResolve,inputError}:DemoClockViewProps){
  const snapshot=state.snapshot;const blocked=disabled||state.readStatus!=='ready'||!snapshot||snapshot.version>=2147483647||['pending','unknown','conflict'].includes(state.operation);
  return <section className="demo-clock card" aria-label="Синтетическое демо-время">
    <h3>Синтетическое демо-время</h3><p>Управление бизнес-временем изолированной демонстрации. Реальное время авторизации, сессий, хранения фото, таймаутов и бюджетов провайдера не меняется.</p>
    <button type="button" className="secondary" disabled={disabled||state.readStatus==='loading'} onClick={onRefresh}>{state.readStatus==='idle'?'Проверить доступ к демо-часам':'Обновить показание сервера'}</button>
    {state.readStatus==='idle'&&<p>Возможность управления пока не подтверждена сервером.</p>}
    {state.readStatus==='loading'&&<p role="status">Читаем текущее серверное состояние…</p>}
    {state.readError&&<p className="error" role="alert">{state.readError}</p>}
    {snapshot&&<>
      <p><strong>Бизнес-время снимка: {showTime(snapshot.domain_now)}</strong></p><p>Реальное время этого ответа: {showTime(snapshot.real_now)}.</p>
      <p>Версия: {snapshot.version}. Скорость: {snapshot.scale}× {snapshot.scale===0?'(пауза)':''}. Предел бизнес-времени: {showTime(snapshot.domain_limit)}.</p>
      <p className="hint">Показано последнее подтверждённое значение. Часы в интерфейсе не продвигаются по времени устройства. {state.readStatus!=='ready'?'Свежесть показания не подтверждена; изменения недоступны.':''}</p>
      <p>{snapshot.storage==='postgres_shared'?'Общее серверное состояние.':'Временное состояние одного процесса; перезапуск может заменить экземпляр часов.'}</p>
      <div className="analytics-actions"><button type="button" disabled={blocked||snapshot.scale===0} onClick={onPause}>Пауза (0×)</button><button type="button" disabled={blocked||snapshot.scale!==0} onClick={onResume}>Продолжить (1×)</button></div>
      <form onSubmit={event=>{event.preventDefault();onSetScale();}}><label>Скорость от 1 до {snapshot.limits.max_scale}×<input type="number" min="1" max={snapshot.limits.max_scale} step="1" value={scale} onChange={event=>onScale(event.target.value)} disabled={blocked}/></label><button type="submit" disabled={blocked}>Изменить скорость</button></form>
      <form onSubmit={event=>{event.preventDefault();onAdvance();}}><label>Продвинуть вперёд на секунды (1–{snapshot.limits.max_advance_seconds})<input type="number" min="1" max={snapshot.limits.max_advance_seconds} step="1" value={seconds} onChange={event=>onSeconds(event.target.value)} disabled={blocked}/></label><button type="submit" disabled={blocked}>Продвинуть бизнес-время вперёд</button></form>
      <p>Продвижение вперёд может изменить сроки и просрочку нарядов. Обратного хода и сброса здесь нет.</p>
    </>}
    {inputError&&<p className="error" role="alert">{inputError}</p>}
    {state.operation==='pending'&&<p role="status">Действие отправлено один раз. Ожидаем подтверждение сервера…</p>}
    {state.operation==='confirmed'&&<p role="status">Ответ на исходное действие подтверждён сервером. Показание выше — из последнего подтверждённого снимка.</p>}
    {state.operationError&&<p className="error" role="alert">{state.operationError}</p>}
    {state.operation==='unknown'&&<p>Оригинальный запрос сохранён в памяти этой сессии. Новое чтение может показать текущее состояние, но не докажет исход прежнего действия. Автоматического или ручного повтора POST нет. Оператору нужно отдельно проверить исход.</p>}
    {state.operation==='conflict'&&<button type="button" disabled={disabled||!state.canResolveConflict} onClick={onResolve}>Проверил обновлённое состояние — разрешить новое действие</button>}
  </section>;
}
