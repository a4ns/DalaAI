import { useEffect, useState, useSyncExternalStore } from 'react';
import type { ApiClient } from '../../shared/api/client';
import { AnalyticsController } from './controller';
import { AnalyticsView } from './AnalyticsView';
import { instantToLocal, parsePeriod } from './model';
export function AnalyticsScreen({client,domainNow,onRefreshClock}:{client:ApiClient;domainNow:string|null;onRefreshClock:()=>void}) {
  const [controller]=useState(()=>new AnalyticsController(client));
  const state=useSyncExternalStore(controller.subscribe,controller.getSnapshot);
  useEffect(()=>controller.attach(),[controller]);
  const [draft,setDraft]=useState({start:'',end:''});const [error,setError]=useState<string|null>(null);const [selected,setSelected]=useState('');
  const clocks=[domainNow,state.facts.data?.provenance.domain_as_of,state.report.data?.provenance.domain_as_of].filter((v):v is string=>Boolean(v));
  const bound=clocks.sort((a,b)=>Date.parse(b)-Date.parse(a))[0]??null;
  function load(){try{const period=parsePeriod(draft.start,draft.end,bound);setError(null);setSelected('');void controller.load(period);}catch(e){setError(e instanceof Error?e.message:'Проверьте период.');}}
  return <AnalyticsView state={state} draft={draft} onDraftChange={next=>{setDraft(next);setError(null);}} onLoad={load} onOpenReport={id=>{void controller.openReport(id);}} domainNow={bound} onRefreshClock={onRefreshClock} validationError={error} selectedOrderId={selected} onSelectOrder={setSelected} onPreset={hours=>{if(bound){setDraft({start:instantToLocal(new Date(Date.parse(bound)-hours*3600000).toISOString()),end:instantToLocal(bound)});setError(null);}}}/>;
}
