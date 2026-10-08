import { ApiClient, ApiError, SessionChangedError } from '../../shared/api/client';
import type { PreparedDemoClock } from '../../shared/api/client';
import { mergeDemoClock } from '../../shared/api/demoClockProtocol';
import type { DemoClockChange, DemoClockSnapshot } from '../../shared/api/demoClockProtocol';
export interface DemoClockState {snapshot:DemoClockSnapshot|null;readStatus:'idle'|'loading'|'ready'|'unavailable'|'error';readError:string|null;operation:'idle'|'pending'|'confirmed'|'unknown'|'conflict'|'failed';operationError:string|null;canResolveConflict:boolean}
const initial=():DemoClockState=>({snapshot:null,readStatus:'idle',readError:null,operation:'idle',operationError:null,canResolveConflict:false});
export function clockError(error:unknown):string {
  if(error instanceof ApiError){if(error.status===401)return 'Сессия завершена. Войдите снова.';if(error.status===403)return 'Сервер не разрешил управление демо-временем этой учётной записи.';if(error.status===404)return 'Демо-часы отсутствуют или отключены в этом профиле.';if(error.status===409)return 'Версия демо-времени изменилась. Обновите показание и явно подтвердите новое состояние перед следующим действием.';if(error.status===422)return 'Сервер отклонил величину или предел демо-времени. Проверьте значение и обновите показание.';}
  return 'Не удалось подтвердить демо-время. Проверьте соединение и выполните отдельное чтение состояния.';
}
/** Session-local CAS controls. Unknown effects remain locked, even after successful reads. */
export class DemoClockController {
  #client:ApiClient;#epoch:number;#allowed:()=>boolean;#alive=true;#state=initial();#listeners=new Set<()=>void>();#readRun=0;#writeRun=0;#freshRead=0;#conflictRead=0;#abort:AbortController|null=null;#pending:PreparedDemoClock|null=null;
  constructor(client:ApiClient,isAuthReady:()=>boolean=()=>true){this.#client=client;this.#epoch=client.epoch;this.#allowed=isAuthReady;}
  getSnapshot=():DemoClockState=>this.#state;
  subscribe=(listener:()=>void):(()=>void)=>{this.#listeners.add(listener);return()=>{this.#listeners.delete(listener);};};
  #set(next:DemoClockState){this.#state=next;this.#listeners.forEach(l=>l());}
  #current(){const s=this.#client.session;return this.#alive&&this.#epoch===this.#client.epoch&&this.#allowed()&&Boolean(s?.principal.active&&s.principal.role==='master'&&Date.parse(s.expires_at)>Date.now());}
  #requireCurrent():boolean {
    if(this.#current())return true;
    const session=this.#client.session;
    if(this.#alive&&this.#epoch===this.#client.epoch&&(!session?.principal.active||session.principal.role!=='master'||!(Date.parse(session.expires_at)>Date.now()))){
      this.#readRun++;this.#writeRun++;this.#abort?.abort();
      const pending=this.#state.operation==='pending';
      this.#set({...this.#state,snapshot:null,readStatus:'unavailable',readError:'Сессия или разрешение на управление больше не действуют. Войдите снова.',operation:pending?'unknown':this.#state.operation,operationError:pending?'Сессия завершилась до подтверждения исходного действия. Его результат неизвестен; повтор не выполняется.':this.#state.operationError,canResolveConflict:false});
    }
    return false;
  }
  attach=():(()=>void)=>{this.#alive=true;const off=this.#client.subscribe(()=>{if(this.#client.epoch!==this.#epoch){this.#readRun++;this.#writeRun++;this.#abort?.abort();this.#pending=null;this.#set(initial());}});return()=>{off();this.#alive=false;this.#readRun++;this.#writeRun++;this.#abort?.abort();};};
  async refresh():Promise<void>{
    if(!this.#requireCurrent())return;
    const run=++this.#readRun,write=this.#writeRun;this.#abort?.abort();this.#abort=new AbortController();this.#set({...this.#state,readStatus:'loading',readError:null,canResolveConflict:false});
    try{const snapshot=await this.#client.getDemoClock(this.#abort.signal);if(!this.#current()||run!==this.#readRun||write!==this.#writeRun)return;this.#freshRead=run;this.#set({...this.#state,snapshot:mergeDemoClock(this.#state.snapshot,snapshot),readStatus:'ready',readError:null,canResolveConflict:this.#state.operation==='conflict'&&run>this.#conflictRead});}
    catch(error){if(!this.#current()||run!==this.#readRun||write!==this.#writeRun||error instanceof SessionChangedError)return;const denied=error instanceof ApiError&&[401,403,404].includes(error.status);this.#set({...this.#state,snapshot:denied?null:this.#state.snapshot,readStatus:denied?'unavailable':'error',readError:clockError(error),canResolveConflict:false});}
  }
  resolveConflict=():void=>{if(!this.#requireCurrent()||this.#state.operation!=='conflict'||!this.#state.canResolveConflict||this.#freshRead<=this.#conflictRead)return;this.#pending=null;this.#set({...this.#state,operation:'idle',operationError:null,canResolveConflict:false});};
  async change(change:DemoClockChange):Promise<boolean>{
    if(!this.#requireCurrent())return false;
    if(['pending','unknown','conflict'].includes(this.#state.operation))return false;
    if(!this.#current()||this.#state.readStatus!=='ready'||!this.#state.snapshot)return false;
    const original=this.#state.snapshot;let token:PreparedDemoClock;
    try{token=this.#client.prepareDemoClock(original,change);}catch(error){this.#set({...this.#state,operation:'failed',operationError:clockError(error)});return false;}
    this.#pending=token;const run=++this.#writeRun;this.#readRun++;this.#abort?.abort();this.#set({...this.#state,operation:'pending',operationError:null,canResolveConflict:false});
    try{const receipt=await this.#client.executeDemoClock(token);if(!this.#current()||run!==this.#writeRun||this.#pending!==token)return false;const current=this.#state.snapshot;this.#set({...this.#state,snapshot:current&&current.instance_id!==original.instance_id?current:mergeDemoClock(current,receipt),readStatus:'ready',operation:'confirmed',operationError:null});return true;}
    catch(error){if(!this.#current()||run!==this.#writeRun||error instanceof SessionChangedError)return false;const unknown=!(error instanceof ApiError)||error.outcomeUnknown;const conflict=error instanceof ApiError&&error.status===409&&!unknown;const denied=error instanceof ApiError&&[401,403,404].includes(error.status);if(conflict)this.#conflictRead=this.#readRun;this.#set({...this.#state,snapshot:denied?null:this.#state.snapshot,readStatus:denied?'unavailable':this.#state.readStatus,operation:unknown?'unknown':conflict?'conflict':'failed',operationError:unknown?'Исход отправленного действия неизвестен. Повтор и новые изменения заблокированы. Чтение текущего состояния не устанавливает исход этой попытки.':clockError(error),canResolveConflict:false});return false;}
  }
}
