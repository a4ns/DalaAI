"""Read-only PostgreSQL projections; all caller values are bound parameters."""
from app.core.auth_policy import Role
from app.orders.models import Assignment, Order, OrderType, Priority, Status
from app.persistence.postgres import sid


def order_from_row(row):
    return Order(sid(row["id"]),str(row["number"]),row["version"],row["assignment_revision"],
        row["scheduling_revision"],Status(row["status"]),OrderType(row["type"]),row["description"],
        sid(row["section_id"]),sid(row["equipment_id"]),
        Assignment(sid(row["executor_id"]),sid(row["brigade_id"])),sid(row["created_by"]),
        row["issued_at"],row["due_at"],row["norm_minutes"],Priority(row["priority"]),row["comment"],
        tuple(sid(value) for value in row["before_photo_ids"]),sid(row["current_submission_id"]),row["updated_at"])


class DiscoveryRepository:
    def __init__(self,db):
        self.db=db

    def list_orders(self,principal,query,cursor):
        clauses=["o.section_id=ANY(%s::uuid[])"]
        values=[sorted(principal.section_ids)]
        if principal.role == Role.EXECUTOR:
            clauses.append("o.executor_id=%s::uuid")
            values.append(principal.user_id)
        for name in ("status","section_id","equipment_id","executor_id"):
            value=getattr(query.filters,name)
            if value is not None:
                # name is a closed server-side tuple, never a client SQL token.
                clauses.append("o."+name+"=%s")
                values.append(value)
        if cursor is not None:
            clauses.extend(("o.number<=%s","o.number<%s"))
            values.extend((cursor.upper_number,cursor.last_number))
        values.append(query.limit+1)
        rows=self.db.execute("""SELECT o.*,COALESCE((SELECT array_agg(p.id ORDER BY p.id)
            FROM photos p WHERE p.order_id=o.id AND p.purpose='before'
            AND p.attached_at IS NOT NULL),'{}'::uuid[]) AS before_photo_ids
            FROM orders o WHERE """+" AND ".join(clauses)+"""
            ORDER BY o.number DESC LIMIT %s FOR SHARE OF o""",tuple(values)).fetchall()
        return [order_from_row(row) for row in rows]

    def dictionaries(self,principal,policy):
        sections=sorted(principal.section_ids)
        empty={"sections":[],"equipment":[],"brigades":[],"executors":[],"work_codes":[],"materials":[]}
        if not sections:
            return empty
        result={}
        result["sections"]=self.db.execute("SELECT id,code,label FROM sections WHERE id=ANY(%s::uuid[]) ORDER BY code COLLATE \"C\",id",(sections,)).fetchall()
        result["equipment"]=self.db.execute("SELECT id,code,label,section_id FROM equipment WHERE section_id=ANY(%s::uuid[]) ORDER BY code COLLATE \"C\",id FOR SHARE",(sections,)).fetchall()
        result["brigades"]=self.db.execute("SELECT id,code,label FROM brigades WHERE section_id=ANY(%s::uuid[]) ORDER BY code COLLATE \"C\",id FOR SHARE",(sections,)).fetchall()
        result["work_codes"]=self.db.execute("SELECT id,code,label FROM work_codes ORDER BY code COLLATE \"C\",id").fetchall()
        result["materials"]=self.db.execute("SELECT id,code,label,unit FROM materials ORDER BY code COLLATE \"C\",id").fetchall()
        result["executors"]=[]
        # Admin can inspect its catalogues without receiving forbidden order IDs
        # or implying that hidden workers have an empty workload.
        if principal.role == Role.ADMIN:
            return result
        self_clause=" AND e.id=%s::uuid" if principal.role == Role.EXECUTOR else ""
        params=(sections,principal.user_id) if self_clause else (sections,)
        employees=self.db.execute("""SELECT e.id,e.employee_code,e.brigade_id,e.on_shift
            FROM employees e WHERE e.active AND e.role='executor' AND EXISTS
            (SELECT 1 FROM employee_sections es WHERE es.employee_id=e.id AND es.section_id=ANY(%s::uuid[]))
            """+self_clause+" ORDER BY e.employee_code COLLATE \"C\",e.id FOR SHARE OF e",params).fetchall()
        employee_ids=[sid(row["id"]) for row in employees]
        if not employee_ids:
            return result
        memberships=self.db.execute("""SELECT employee_id,section_id FROM employee_sections
            WHERE employee_id=ANY(%s::uuid[]) AND section_id=ANY(%s::uuid[])
            ORDER BY employee_id,section_id FOR SHARE""",(employee_ids,sections)).fetchall()
        visible_members={employee_id:[] for employee_id in employee_ids}
        for row in memberships:
            visible_members[sid(row["employee_id"])].append(sid(row["section_id"]))
        # Only current assignments within the caller's object-read scope. Old
        # submission authors/history never become current workload recipients.
        orders=self.db.execute("""SELECT id,number,executor_id,section_id,status FROM orders
            WHERE executor_id=ANY(%s::uuid[]) AND section_id=ANY(%s::uuid[])
            AND status IN ('in_progress','paused','queued') ORDER BY number ASC FOR SHARE""",
            (employee_ids,sections)).fetchall()
        by_executor={employee_id:[] for employee_id in employee_ids}
        for order in orders:
            # The caller's scope above controls visibility. A master's active
            # assignment does not disappear just because an executor's separate
            # section membership was revoked while that order remains assigned.
            by_executor[sid(order["executor_id"])].append(order)
        brigades={sid(row["id"]) for row in result["brigades"]}
        for employee in employees:
            employee_id=sid(employee["id"])
            if not visible_members[employee_id]:
                continue
            brigade=sid(employee["brigade_id"])
            result["executors"].append({"id":employee_id,"employee_code":employee["employee_code"],
                "section_ids":visible_members[employee_id],"brigade_id":brigade if brigade in brigades else None,
                "on_shift":employee["on_shift"],**policy.summarize(by_executor[employee_id])})
        return result
