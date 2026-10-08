import { ApiClient, ApiError, SessionChangedError } from '../../shared/api/client';
import type { AnalyticsFacts, OrderReport, PeriodRequest, ShiftReport } from '../../shared/api/analyticsProtocol';
export type LoadState<T>={status:'idle'|'loading'|'ready'|'error';data:T|null;error:string|null};
export interface AnalyticsState { facts:LoadState<AnalyticsFacts>; report:LoadState<ShiftReport|OrderReport>; period:PeriodRequest|null }
const empty=<T>():LoadState<T>=>({status:'idle',data:null,error:null});
const initial=():AnalyticsState=>({facts:empty(),report:empty(),period:null});
export function analyticsError(error:unknown):string {
  if (error instanceof ApiError) {
    if(error.status===401)return 'Сессия завершена. Войдите снова.';
    if(error.status===403)return 'Доступ к отчётам не подтверждён. Нужна активная сессия мастера с разрешённым участком.';
    if(error.status===404)return 'Наряд недоступен или отсутствует. Прежний отчёт скрыт.';
    if(error.problem?.code==='REPORT_LIMIT_EXCEEDED')return 'Превышен предел объёма отчёта. Это не пустая выборка. Сократите период; если ошибка сохраняется, размер полной истории требует проверки оператором.';
    if(error.status===422)return 'Сервер отклонил период или параметры. Проверьте даты, предел 93 суток и доменное время.';
    if(error.status===503||error.status===429)return 'Отчёт временно недоступен. Полная выборка не подтверждена; повторите позже с учётом задержки сервера.';
  }
  return 'Не удалось получить подтверждённый отчёт. Данные не считаются пустыми; проверьте соединение и повторите запрос.';
}
/** One session and latest requested period. No local persistence, polling or automatic retry. */
export class AnalyticsController {
  #client:ApiClient; #epoch:number; #state=initial(); #listeners=new Set<()=>void>(); #run=0; #reportRun=0; #alive=true;
  #abort:AbortController|null=null; #reportAbort:AbortController|null=null;
  constructor(client:ApiClient){this.#client=client;this.#epoch=client.epoch;}
  getSnapshot=():AnalyticsState=>this.#state;
  subscribe=(listener:()=>void):(()=>void)=>{this.#listeners.add(listener);return()=>{this.#listeners.delete(listener);};};
  #set(state:AnalyticsState){this.#state=state;this.#listeners.forEach(l=>l());}
  #current(){return this.#alive&&this.#client.epoch===this.#epoch;}
  attach=():(()=>void)=>{this.#alive=true;const off=this.#client.subscribe(()=>{if(this.#client.epoch!==this.#epoch){this.#invalidate();this.#set(initial());}});return()=>{off();this.#alive=false;this.#invalidate();};};
  #invalidate(){this.#run++;this.#reportRun++;this.#abort?.abort();this.#reportAbort?.abort();}
  async load(period:PeriodRequest):Promise<void>{
    if(!this.#current())return;
    this.#invalidate();const run=this.#run;const captured=Object.freeze({...period});this.#abort=new AbortController();
    this.#set({facts:{status:'loading',data:null,error:null},report:empty(),period:captured});
    try{const facts=await this.#client.getShiftAnalytics(captured,this.#abort.signal);if(!this.#current()||run!==this.#run)return;this.#set({...this.#state,facts:{status:'ready',data:facts,error:null}});}
    catch(error){if(!this.#current()||run!==this.#run||error instanceof SessionChangedError)return;this.#set({...this.#state,facts:{status:'error',data:null,error:analyticsError(error)},report:empty()});}
  }
  reportAccessLost(error:ApiError,report:ShiftReport|OrderReport):void {
    if(!this.#current()||this.#state.report.data!==report||![401,403,404].includes(error.status))return;
    this.#invalidate();this.#set({...this.#state,facts:empty(),report:{status:'error',data:null,error:analyticsError(error)}});
  }
  async openReport(orderId:string|null):Promise<void>{
    if(!this.#current()||this.#state.facts.status!=='ready'||!this.#state.period)return;
    if(orderId&&!this.#state.facts.data?.orders.some(row=>row.order.id===orderId))return;
    const run=++this.#reportRun;const queryRun=this.#run;const period=this.#state.period;this.#reportAbort?.abort();this.#reportAbort=new AbortController();
    this.#set({...this.#state,report:{status:'loading',data:null,error:null}});
    try{const report=orderId?await this.#client.getOrderReport(orderId,period,this.#reportAbort.signal):await this.#client.getShiftReport(period,this.#reportAbort.signal);if(!this.#current()||run!==this.#reportRun||queryRun!==this.#run)return;this.#set({...this.#state,report:{status:'ready',data:report,error:null}});}
    catch(error){if(!this.#current()||run!==this.#reportRun||queryRun!==this.#run||error instanceof SessionChangedError)return;const denied=error instanceof ApiError&&[401,403,404].includes(error.status);this.#set({...this.#state,facts:denied?empty():this.#state.facts,report:{status:'error',data:null,error:analyticsError(error)}});}
  }
}
