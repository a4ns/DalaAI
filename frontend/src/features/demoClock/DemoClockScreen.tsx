import { useEffect, useState, useSyncExternalStore } from 'react';
import type { ApiClient } from '../../shared/api/client';
import type { DemoClockChange } from '../../shared/api/demoClockProtocol';
import { DemoClockController } from './controller';
import { DemoClockView } from './DemoClockView';
import './demoClock.css';
export function parseClockInteger(value:string,min:number,max:number):number {if(!/^\d+$/.test(value)||!Number.isSafeInteger(Number(value))||Number(value)<min||Number(value)>max)throw new Error(`Введите целое число от ${min} до ${max}.`);return Number(value);}
export function DemoClockScreen({client,isAuthReady,disabled,onConfirmed}:{client:ApiClient;isAuthReady:()=>boolean;disabled:boolean;onConfirmed:()=>void}){
  const [controller]=useState(()=>new DemoClockController(client,isAuthReady));const state=useSyncExternalStore(controller.subscribe,controller.getSnapshot);useEffect(()=>controller.attach(),[controller]);
  const [scale,setScale]=useState('1'),[seconds,setSeconds]=useState('60'),[error,setError]=useState<string|null>(null);
  useEffect(()=>{if(!['pending','unknown'].includes(state.operation))return;const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[state.operation]);
  async function act(change:DemoClockChange){setError(null);if(await controller.change(change))onConfirmed();}
  function numeric(action:'set_scale'|'advance'){try{void act(action==='set_scale'?{action,scale:parseClockInteger(scale,1,60)}:{action,seconds:parseClockInteger(seconds,1,3600)});}catch(e){setError(e instanceof Error?e.message:'Проверьте целое значение.');}}
  return <DemoClockView state={state} disabled={disabled} scale={scale} seconds={seconds} onScale={setScale} onSeconds={setSeconds} onRefresh={()=>void controller.refresh()} onPause={()=>void act({action:'set_scale',scale:0})} onResume={()=>void act({action:'set_scale',scale:1})} onSetScale={()=>numeric('set_scale')} onAdvance={()=>numeric('advance')} onResolve={controller.resolveConflict} inputError={error}/>;
}
