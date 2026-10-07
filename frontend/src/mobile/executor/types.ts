import type { ReactNode } from 'react';
import type { MutationOutcome, MutationState, ResourceState } from '../../shared/ui/types';

/** Presentation models only. The shared client owns wire mapping and operation IDs. */
export type ExecutorOrderStatus = 'issued' | 'queued' | 'accepted' | 'rejected' | 'in_progress' | 'paused' | 'done' | 'ai_review' | 'rework' | 'closed' | 'cancelled';
export type ExecutorAction = 'queue' | 'accept' | 'reject' | 'start' | 'pause' | 'resume' | 'submit';
export interface ExecutorOrderViewModel {
  id: string;
  number: string;
  version: number;
  assignmentRevision: number;
  sectionId: string;
  equipmentLabel: string;
  sectionLabel: string;
  status: ExecutorOrderStatus;
  type: 'planned' | 'unplanned';
  priority: 'normal' | 'high' | 'emergency';
  description: string;
  comment: string;
  dueAt: string;
  isOverdue: boolean;
}
export interface ExecutorOption { id: string; code: string; label: string }
export interface ExecutorMaterialOption extends ExecutorOption { unit: string }
export interface ExecutorDictionaries {
  workCodes: ExecutorOption[];
  materials: ExecutorMaterialOption[];
}
export interface ExecutorMaterialDraft {
  /** UI row identity, never sent to the server. */
  rowId: string;
  materialId: string;
  quantity: string;
}
export interface ExecutorDraft {
  workDescription: string;
  workCodeId: string;
  materials: ExecutorMaterialDraft[];
  /** IDs from confirmed stage responses only; local files are not evidence. */
  afterPhotoIds: string[];
  comment: string;
  reason: string;
}
export interface ExecutorSubmitPayload {
  workDescription: string;
  workCodeId: string | null;
  materials: { materialId: string; quantity: number }[];
  afterPhotoIds: string[];
  comment: string;
}
export type ExecutorIntent = {
  orderId: string;
  expectedVersion: number;
  /** UI-only assignment fence; the shared mapper must not add it to the wire body. */
  expectedAssignmentRevision: number;
} & (
  | { action: 'queue' | 'accept' | 'start' | 'resume'; payload: Record<string, never> }
  | { action: 'reject' | 'pause'; payload: { reason: string } }
  | { action: 'submit'; payload: ExecutorSubmitPayload }
);
export interface ExecutorIntentSummary {
  orderId: string;
  expectedVersion: number;
  action: ExecutorAction;
}
export interface ExecutorPhotoContext {
  orderId: string;
  sectionId: string;
  assignmentRevision: number;
  disabled: boolean;
  confirmedPhotoIds: string[];
  onConfirmedPhotoIdsChange: (ids: string[]) => void;
}
export interface ExecutorScreenProps {
  /** Non-secret identity/session generation. Change on every login or identity reset. */
  sessionKey: string;
  /** Opt-in: existing mutation/intent/retry/resolve props belong to this opaque order/assignment scope. */
  operationScopeKey?: string;
  /** Retained inaccessible unknown operations. Only a generic notice is rendered. */
  quarantinedIntentCount?: number;
  orders: ResourceState<ExecutorOrderViewModel[]>;
  dictionaries: ResourceState<ExecutorDictionaries>;
  selectedOrderId: string | null;
  drafts: Record<string, ExecutorDraft>;
  mutation: MutationState;
  pendingIntent: ExecutorIntentSummary | null;
  onSelectOrder: (id: string) => void;
  onDraftChange: (orderId: string, draft: ExecutorDraft, assignmentRevision: number) => void;
  /** Parent must synchronously reserve one intent, then allocate one operation ID. */
  onIntent: (intent: ExecutorIntent) => Promise<MutationOutcome>;
  /** Replay parent's exact original operation ID/body, never current form values. */
  onRetry: () => Promise<MutationOutcome>;
  onRefresh: () => void;
  /** Called only after explicit conflict review; must not submit any command. */
  onResolveConflict: () => void;
  /** Selected-order preparation/staging/unresolved upload blocks result submission only. */
  photoBusy?: boolean;
  photoBusyReason?: string;
  renderPhotoPicker?: (context: ExecutorPhotoContext) => ReactNode;
  /** Optional read-only disclosure for the selected authorized result; no mode is inferred here. */
  resultAnalysisDisclosure?: ReactNode;
}
