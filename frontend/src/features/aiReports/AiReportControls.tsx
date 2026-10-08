import { useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react';
import type { ApiError } from '../../shared/api/client';
import { AiReportController } from './controller';
import type { AiReportTransport } from './controller';
import { aiReportSelectionKey } from './protocol';
import type { AiReportSelection } from './protocol';
import type { AssistanceSession } from './session';
import { AiReportView } from './AiReportView';

/** Mount with the authenticated session key. Transport is supplied by the shared client. */
export function AiReportControls(props: {
  client: AssistanceSession; selection: AiReportSelection | null; request: AiReportTransport;
  isAuthReady: () => boolean; isSelectionCurrent: () => boolean; disabled: boolean;
  onAccessLost?: (error: ApiError) => void;
}) {
  const [controller] = useState(() => new AiReportController(props.client, props.request, () => props.isAuthReady() && props.isSelectionCurrent() && !props.disabled, props.onAccessLost));
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const selectionKey = aiReportSelectionKey(props.selection);
  useLayoutEffect(() => { controller.updatePorts(props.request, () => props.isAuthReady() && props.isSelectionCurrent() && !props.disabled, error => props.onAccessLost?.(error)); controller.setSelection(props.selection); if (props.disabled || !props.isAuthReady() || !props.isSelectionCurrent()) controller.clear(); }, [props, controller, selectionKey]);
  useEffect(() => controller.attach(), [controller]);
  const visible = !props.disabled && props.isAuthReady() && props.isSelectionCurrent() && controller.current() && state.selectionKey === selectionKey;
  return <AiReportView state={visible ? state : { status: 'idle', selectionKey, data: null, error: null }} selection={props.selection} disabled={!visible || !props.selection} onGenerate={kind => { void controller.generate(kind); }} onRetry={() => { void controller.retry(); }}/>
}
