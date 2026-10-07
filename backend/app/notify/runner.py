"""Injected bounded worker tick. A5 owns process/config/secret supervision."""
from dataclasses import dataclass

from .models import DispatchResult
from .reconcile import ReconcilePage


@dataclass(frozen=True, slots=True)
class NotificationTick:
    reconciliation: ReconcilePage
    dispatch: tuple[DispatchResult, ...]


class NotificationRunner:
    """No threads, clocks, environment reads or activity on construction.

    The page cursor is an optimization, never a durable truth marker. A process
    restart starts a fresh sweep and existing outbox keys prevent duplicate work.
    When a sweep ends the next tick starts at the first currently active order.
    """
    def __init__(self, *, reconciler, dispatcher):
        if reconciler.channel != dispatcher.channel:
            raise ValueError('Reconciliation and dispatch must use one configured channel')
        self.reconciler, self.dispatcher = reconciler, dispatcher
        self.channel = reconciler.channel
        self._after_id = None

    def tick(self, *, reconcile_limit=100, dispatch_limit=20):
        # Failure propagates; never report a healthy/successful tick after a DB
        # error. Any prior order transactions remain durable and deduplicated.
        page = self.reconciler.scan_once(limit=reconcile_limit,after_id=self._after_id)
        self._after_id = page.next_after_id
        results = self.dispatcher.run_batch(limit=dispatch_limit)
        return NotificationTick(page,results)
