"""Actual independent processes sharing the same SQLite ledger, no network."""
import multiprocessing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.ai.model_budget import BudgetBlocked, BudgetPolicy, SqliteBudgetLedger


def reserve_in_process(path, event, queue):
    ledger=SqliteBudgetLedger(path,BudgetPolicy('process-test',100,100,60,4))
    event.wait(5)
    try:
        ledger.reserve(now=1)
        queue.put('reserved')
    except BudgetBlocked:
        queue.put('blocked')


class ProcessBudgetTests(unittest.TestCase):
    def test_atomic_spend_cap_across_independent_processes(self):
        with TemporaryDirectory() as directory:
            path=str(Path(directory)/'shared.sqlite')
            policy=BudgetPolicy('process-test',100,100,60,4)
            SqliteBudgetLedger(path,policy)
            ctx=multiprocessing.get_context('fork')
            queue,event=ctx.Queue(),ctx.Event()
            workers=[ctx.Process(target=reserve_in_process,args=(path,event,queue)) for _ in range(6)]
            try:
                for p in workers:p.start()
                event.set()
                result=[queue.get(timeout=5) for _ in workers]
                for p in workers:
                    p.join(timeout=5)
                    self.assertEqual(p.exitcode,0)
                self.assertEqual(result.count('reserved'),1)
                self.assertEqual(result.count('blocked'),5)
                self.assertEqual(SqliteBudgetLedger(path,policy).counters()['reserved_upper_bound_microusd'],100)
            finally:
                for p in workers:
                    if p.is_alive():p.terminate();p.join()
                queue.close()
