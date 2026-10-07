import type { ReactNode } from 'react';
import type { MutationOutcome, ResourceState } from '../../shared/ui/types';

/** View models only. The shared adapter owns DTO conversion, credentials and receipts. */
export interface MasterOption { id: string; label: string }
export interface MasterEquipment extends MasterOption { sectionId: string }
export interface MasterExecutor extends MasterOption {
  sectionIds: string[];
  brigadeId: string | null;
  onShift: boolean;
  activeOrderId: string | null;
  queueCount: number;
}
export interface MasterDictionaries {
  sections: MasterOption[];
  equipment: MasterEquipment[];
  brigades: MasterOption[];
  executors: MasterExecutor[];
}
export interface MasterCreateDraft {
  type: 'planned' | 'unplanned';
  description: string;
  sectionId: string;
  equipmentId: string;
  executorId: string;
  brigadeId: string;
  /** Wall-clock value from datetime-local, interpreted only as UTC+5. */
  dueLocal: string;
  normMinutes: string;
  priority: 'normal' | 'high' | 'emergency';
  comment: string;
  beforePhotoIds: string[];
}
export interface MasterReviewDraft { reason: string; finalScore: string }
export type MasterOrderStatus = 'issued' | 'queued' | 'accepted' | 'rejected' | 'in_progress' | 'paused' | 'done' | 'ai_review' | 'rework' | 'closed' | 'cancelled';
export interface MasterAssessmentVM {
  mode: 'model' | 'rules_fallback' | 'manual';
  recommendation: 'satisfactory' | 'rework_recommended' | 'needs_master_review';
  score: number | null;
  reasons: string[];
  stale: boolean;
  fallbackReason: string | null;
}
export interface MasterSubmissionVM {
  id: string;
  assignmentRevision: number;
  attemptNumber: number;
  workDescription: string;
  workCodeLabel: string | null;
  materials: { label: string; quantity: string; unit: string }[];
  afterPhotoCount: number;
  comment: string;
  completeness: 'complete' | 'incomplete' | 'unknown';
  missingEvidence: string[];
  /** Null is not a positive assessment. Pending/failed AI does not prohibit manual review. */
  assessment: MasterAssessmentVM | null;
}
export interface MasterOrderVM {
  id: string;
  number: string;
  version: number;
  assignmentRevision: number;
  status: MasterOrderStatus;
  type: 'planned' | 'unplanned';
  description: string;
  equipmentLabel: string;
  executorLabel: string;
  dueAt: string;
  isOverdue: boolean;
  /** Null means submission details have not been loaded; never infer completeness. */
  submission: MasterSubmissionVM | null;
}
export interface MasterReviewIntent {
  orderId: string;
  expectedVersion: number;
  submissionId: string;
  decision: 'close' | 'rework';
  reason: string;
  finalScore: number | null;
}
export interface MasterPhotoControlProps {
  disabled: boolean;
  sectionId: string;
  photoIds: string[];
  onPhotoIdsChange: (photoIds: string[]) => void;
}
export interface MasterScreenProps {
  dictionaries: ResourceState<MasterDictionaries>;
  orders: ResourceState<MasterOrderVM[]>;
  createDraft: MasterCreateDraft;
  onCreateDraftChange: (draft: MasterCreateDraft) => void;
  reviewDrafts: Record<string, MasterReviewDraft>;
  onReviewDraftChange: (orderId: string, draft: MasterReviewDraft) => void;
  online: boolean;
  /** Omit until server domain time is known; browser time is not substituted. */
  domainNow?: string | null;
  onCreate: (draft: MasterCreateDraft) => Promise<MutationOutcome>;
  onReview: (intent: MasterReviewIntent) => Promise<MutationOutcome>;
  /** These replay the adapter's captured operation ID + exact body, never a new intent. */
  onRetryCreate?: () => Promise<MutationOutcome>;
  onRetryReview?: (orderId: string) => Promise<MutationOutcome>;
  onReload: () => Promise<void>;
  /** True while any selected before-photo is still processing/staging. */
  beforePhotosBusy?: boolean;
  renderBeforePhotos?: (props: MasterPhotoControlProps) => ReactNode;
  renderAfterPhotos?: (order: MasterOrderVM) => ReactNode;
}
export const emptyMasterCreateDraft = (): MasterCreateDraft => ({
  type: 'unplanned', description: '', sectionId: '', equipmentId: '', executorId: '',
  brigadeId: '', dueLocal: '', normMinutes: '', priority: 'normal', comment: '', beforePhotoIds: [],
});
export const emptyMasterReviewDraft = (): MasterReviewDraft => ({ reason: '', finalScore: '' });
