import { useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react';
import type { ApiError } from '../../shared/api/client';
import type { AssistanceSession } from '../aiReports/session';
import { assigneeContextKey, AssigneeRecommendationsController } from './controller';
import type { AssigneeContext, AssigneeTransport, EligibleExecutor } from './controller';
import { AssigneeRecommendationsView } from './AssigneeRecommendationsView';

/** Mount inside the existing create form. All buttons are type=button. */
export function AssigneeRecommendations(props: {
  client: AssistanceSession; context: AssigneeContext | null; executors: readonly EligibleExecutor[];
  request: AssigneeTransport; isAuthReady: () => boolean; isDraftCurrent: () => boolean; disabled: boolean;
  onChoose: (id: string) => void; onAccessLost?: (error: ApiError) => void;
}) {
  const [controller] = useState(() => new AssigneeRecommendationsController(props.client, props.request, () => props.context, () => props.executors, () => props.isAuthReady() && props.isDraftCurrent() && !props.disabled, props.onAccessLost));
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const key = assigneeContextKey(props.context);
  useLayoutEffect(() => { controller.updatePorts(props.request, () => props.context, () => props.executors, () => props.isAuthReady() && props.isDraftCurrent() && !props.disabled, error => props.onAccessLost?.(error)); controller.synchronize(); }, [props, controller, key]);
  useEffect(() => controller.attach(), [controller]);
  const visible = !props.disabled && props.isAuthReady() && props.isDraftCurrent() && controller.current() && state.contextKey === key;
  return <AssigneeRecommendationsView state={visible ? state : { status: 'idle', contextKey: key, data: null, error: null }} context={props.context} executors={props.executors} disabled={!visible} onLoad={() => { void controller.load(); }} onChoose={id => { const chosen = controller.choose(id); if (chosen !== null) props.onChoose(chosen); }}/>
}
