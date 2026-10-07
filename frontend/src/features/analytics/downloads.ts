import { ApiClient, ApiError, SessionChangedError } from '../../shared/api/client';
import type { ReportFileFormat } from '../../shared/api/reportFiles';
import type { OrderReport, ShiftReport } from '../../shared/api/analyticsProtocol';
import { analyticsError } from './controller';
export interface DownloadPort { createUrl:(blob:Blob)=>string;revokeUrl:(url:string)=>void;save:(url:string,filename:string)=>void;schedule:(callback:()=>void,ms:number)=>(()=>void) }
export const browserDownloadPort:DownloadPort={
  createUrl:blob=>URL.createObjectURL(blob),revokeUrl:url=>URL.revokeObjectURL(url),
  save(url,filename){const link=document.createElement('a');link.href=url;link.download=filename;link.rel='noopener';document.body.append(link);try{link.click();}finally{link.remove();}},
  schedule(callback,ms){const timer=setTimeout(callback,ms);return()=>clearTimeout(timer);},
};
export interface DownloadState {status:'idle'|'loading'|'ready'|'handed_off'|'expired'|'error';format:ReportFileFormat|null;error:string|null}
/** Memory-only binary staging. Saving is a separate explicit gesture; no automatic resend. */
export class ReportDownloadController {
  #client:ApiClient;#epoch:number;#report:ShiftReport|OrderReport;#isCurrent:()=>boolean;#onAccessLost:(error:ApiError)=>void;#port:DownloadPort;
  #state:DownloadState={status:'idle',format:null,error:null};#listeners=new Set<()=>void>();#run=0;#alive=true;#abort:AbortController|null=null;#url:string|null=null;#filename:string|null=null;#timer:(()=>void)|null=null;#readyUntil=0;
  constructor(client:ApiClient,report:ShiftReport|OrderReport,isCurrent:()=>boolean,onAccessLost:(error:ApiError)=>void,port:DownloadPort=browserDownloadPort){this.#client=client;this.#epoch=client.epoch;this.#report=report;this.#isCurrent=isCurrent;this.#onAccessLost=onAccessLost;this.#port=port;}
  getSnapshot=():DownloadState=>this.#state;
  subscribe=(listener:()=>void):(()=>void)=>{this.#listeners.add(listener);return()=>{this.#listeners.delete(listener);};};
  #set(state:DownloadState){this.#state=state;this.#listeners.forEach(l=>l());}
  #current(){const session=this.#client.session;return this.#alive&&this.#epoch===this.#client.epoch&&Boolean(session?.principal.active&&session.principal.role==='master'&&Date.parse(session.expires_at)>Date.now())&&this.#isCurrent();}
  #release(){this.#timer?.();this.#timer=null;if(this.#url)this.#port.revokeUrl(this.#url);this.#url=null;this.#filename=null;this.#readyUntil=0;}
  cancel=():void=>{this.#run++;this.#abort?.abort();this.#abort=null;this.#release();this.#set({status:'idle',format:null,error:null});};
  attach=():(()=>void)=>{this.#alive=true;const off=this.#client.subscribe(()=>{if(!this.#current())this.cancel();});return()=>{off();this.#alive=false;this.cancel();};};
  async prepare(format:ReportFileFormat):Promise<void>{
    if(!this.#current()){this.cancel();return;}
    if(this.#state.status==='loading'&&this.#state.format===format)return;
    this.cancel();const run=this.#run;this.#abort=new AbortController();this.#set({status:'loading',format,error:null});
    try{
      const kind=this.#report.report_kind==='shift'?'shift':{orderId:this.#report.order.order.id};
      const file=await this.#client.getReportFile(kind,format,this.#report.period,this.#abort.signal);
      if(!this.#current()||run!==this.#run)return;
      this.#url=this.#port.createUrl(file.blob);this.#filename=file.filename;this.#readyUntil=Date.now()+60000;
      this.#timer=this.#port.schedule(()=>{this.#release();this.#set({status:'expired',format,error:null});},60000);this.#set({status:'ready',format,error:null});
    }catch(error){
      if(!this.#current()||run!==this.#run||error instanceof SessionChangedError)return;
      this.#release();this.#set({status:'error',format,error:analyticsError(error)});
      if(error instanceof ApiError&&[401,403,404].includes(error.status))this.#onAccessLost(error);
    }
  }
  save=():void=>{
    if(!this.#current()){this.cancel();return;}
    if(this.#state.status!=='ready'||!this.#url||!this.#filename)return;
    const format=this.#state.format;
    if(Date.now()>=this.#readyUntil){this.#release();this.#set({status:'expired',format,error:null});return;}
    try{this.#port.save(this.#url,this.#filename);this.#timer?.();this.#timer=this.#port.schedule(()=>this.#release(),1000);this.#set({status:'handed_off',format,error:null});}
    catch{this.#release();this.#set({status:'error',format,error:'Браузер не подтвердил передачу файла на сохранение. Попробуйте получить файл заново.'});}
  };
}
