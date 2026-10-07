"""Exact event projection; uses the existing schema without migrations."""
from app.core.auth_policy import OrderScope
from app.persistence.postgres import sid


class EventRepository:
    def __init__(self,db):self.db=db

    def load_scope(self,order_id):
        row=self.db.execute('''SELECT id,section_id,executor_id,assignment_revision
            FROM orders WHERE id=%s FOR SHARE''',(order_id,)).fetchone()
        if row is None:return None
        return OrderScope(sid(row['id']),sid(row['section_id']),sid(row['executor_id']),row['assignment_revision'])

    def read_page(self,order_id,query):
        # Do not SELECT *: future internal audit/provider fields are not public.
        return self.db.execute('''SELECT id,order_id,sequence,order_version,assignment_revision,
            scheduling_revision,reason,details,kind,actor_id,operation_id,from_status,to_status,
            submission_id,occurred_at,recorded_at FROM order_events
            WHERE order_id=%s AND sequence>%s ORDER BY sequence ASC LIMIT %s''',
            (order_id,query.after_sequence,query.limit+1)).fetchall()
