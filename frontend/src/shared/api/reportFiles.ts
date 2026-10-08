/** Accepted C5 fixed binary routes; no renderer or arbitrary URL/filename support. */
export type ReportFileFormat = 'pdf' | 'xlsx';
export type ReportFileKind = 'shift' | {orderId:string};
export interface ReportFile { blob:Blob;filename:string }
export const REPORT_FILE_LIMIT=8*1024*1024;
export const REPORT_FILE_MIME={pdf:'application/pdf',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'} as const;
export async function readReportFile(response:Response,format:ReportFileFormat,filename:string,assertCurrent:()=>void):Promise<ReportFile>{
  const mime=response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase();
  if(mime!==REPORT_FILE_MIME[format]||response.headers.get('Content-Disposition')!==`attachment; filename="${filename}"`)throw new Error('Invalid report headers');
  const length=response.headers.get('Content-Length');
  if(length!==null&&(!/^\d+$/.test(length)||!Number.isSafeInteger(Number(length))||Number(length)>REPORT_FILE_LIMIT))throw new Error('Report exceeds byte limit');
  if(!response.body)throw new Error('Missing report body');
  const reader=response.body.getReader();const chunks:Uint8Array<ArrayBuffer>[]=[];let size=0;
  try{for(;;){const item=await reader.read();assertCurrent();if(item.done)break;size+=item.value.byteLength;if(size>REPORT_FILE_LIMIT)throw new Error('Report exceeds byte limit');chunks.push(new Uint8Array(item.value));}}
  catch(error){void reader.cancel().catch(()=>undefined);throw error;}
  finally{reader.releaseLock();}
  if(size===0)throw new Error('Empty report');
  // The network body is complete. Inspect its owned bytes without another async
  // Blob read that could leave the request deadline active after EOF.
  const head=new Uint8Array(Math.min(size,5));let copied=0;
  for(const chunk of chunks){const prefix=chunk.subarray(0,head.length-copied);head.set(prefix,copied);copied+=prefix.length;if(copied===head.length)break;}
  assertCurrent();
  const valid=format==='pdf'?head.length===5&&head[0]===37&&head[1]===80&&head[2]===68&&head[3]===70&&head[4]===45:head.length>=4&&head[0]===80&&head[1]===75&&head[2]===3&&head[3]===4;
  if(!valid)throw new Error('Invalid report signature');
  return {blob:new Blob(chunks,{type:mime}),filename};
}
