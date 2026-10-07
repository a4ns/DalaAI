import type { ResourceState } from '../shared/ui/types';

/** Presentation models, not wire DTOs. B4 owns all server adapters. */
export interface PanelOrder {
  id: string;
  number: string;
  title: string;
  sectionLabel: string;
  equipmentLabel: string;
  executorLabel: string;
  status: string;
  priority: string;
  dueAt: string;
  isOverdue: boolean;
  version: number;
}

export interface PanelEmployee {
  id: string;
  label: string;
  onShift: boolean;
  /** A representative active order only, never a full list or workload count. */
  activeOrderId: string | null;
  /** Only orders whose status is queued. Zero does not establish availability. */
  queueCount: number;
}

export interface PanelEvent {
  id: string;
  sequence: number;
  occurredAt: string;
  kind: string;
  actorLabel: string;
  reason: string | null;
  fromStatus: string | null;
  toStatus: string;
}

export interface PanelHistory {
  orderId: string;
  events: readonly PanelEvent[];
}

export interface PanelScreenProps {
  orders: ResourceState<readonly PanelOrder[]>;
  employees?: ResourceState<readonly PanelEmployee[]>;
  selectedOrderId: string | null;
  history?: ResourceState<PanelHistory>;
  onSelectOrder: (orderId: string) => void;
  onRefresh?: () => void;
  onRefreshHistory?: (orderId: string) => void;
  /** Immediately hide every previous snapshot when authorization is lost. */
  access?: 'allowed' | 'unauthenticated' | 'forbidden';
  dataOrigin?: 'api' | 'synthetic';
}
