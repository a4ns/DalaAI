from base64 import urlsafe_b64encode
import json
import unittest
from app.orders.models import DomainError
from app.discovery.cursor import Cursor,OrderFilters,parse_query,MAX_BIGINT

ACTOR="00000000-0000-4000-8000-000000000001"
OTHER="00000000-0000-4000-8000-000000000002"


class CursorTests(unittest.TestCase):
    def token(self,**changes):
        value={"v":1,"actor":ACTOR,"filters":OrderFilters().fingerprint,"upper":120,"last":90}
        value.update(changes)
        return urlsafe_b64encode(json.dumps(value,separators=(",",":")).encode()).rstrip(b"=").decode()

    def test_roundtrip_and_opaque_length(self):
        cursor=Cursor(ACTOR,OrderFilters().fingerprint,120,90)
        self.assertEqual(Cursor.decode(cursor.encode(),actor_id=ACTOR,filters=OrderFilters()),cursor)
        self.assertLessEqual(len(cursor.encode()),512)

    def test_cursor_is_actor_bound(self):
        with self.assertRaises(DomainError) as error:
            Cursor.decode(self.token(),actor_id=OTHER,filters=OrderFilters())
        self.assertEqual(error.exception.code,"INVALID_REQUEST")

    def test_cursor_is_filter_bound(self):
        with self.assertRaises(DomainError):
            Cursor.decode(self.token(),actor_id=ACTOR,filters=OrderFilters(status="queued"))

    def test_version_unknown_fields_and_number_bounds_rejected(self):
        for changes in ({"v":2},{"v":True},{"extra":1},{"upper":0},{"last":121},{"last":-1},
                        {"last":True},{"last":1.0},{"upper":MAX_BIGINT+1}):
            with self.subTest(changes=changes),self.assertRaises(DomainError) as error:
                Cursor.decode(self.token(**changes),actor_id=ACTOR,filters=OrderFilters())
            self.assertEqual(error.exception.code,"INVALID_REQUEST")

    def test_malformed_oversized_and_noncanonical_base64_rejected(self):
        for token in ("", "x"*513,"aa=", "not a cursor", "!", "a", "é"):
            with self.subTest(token=token),self.assertRaises(DomainError):
                Cursor.decode(token,actor_id=ACTOR,filters=OrderFilters())

    def test_duplicate_cursor_json_keys_rejected(self):
        raw='{"v":1,"v":2}'
        token=urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()
        with self.assertRaises(DomainError):
            Cursor.decode(token,actor_id=ACTOR,filters=OrderFilters())

    def test_limit_changes_do_not_change_filter_binding(self):
        a=parse_query({"limit":"1","status":"queued"})
        b=parse_query({"limit":"100","status":"queued"})
        self.assertEqual(a.filters.fingerprint,b.filters.fingerprint)
        token=Cursor(ACTOR,a.filters.fingerprint,100,90).encode()
        self.assertEqual(Cursor.decode(token,actor_id=ACTOR,filters=b.filters).last_number,90)

    def test_filters_normalize_uuid_case_and_object_order(self):
        lower="aabbccdd-aabb-4abb-8abb-aabbccddeeff"
        a=parse_query([("status","issued"),("section_id",lower.upper())])
        b=parse_query([("section_id",lower),("status","issued")])
        self.assertEqual(a.filters,b.filters)
        self.assertEqual(a.filters.fingerprint,b.filters.fingerprint)

    def test_default_limit_and_empty_filters(self):
        query=parse_query({})
        self.assertEqual(query.limit,50)
        self.assertEqual(query.filters,OrderFilters())
        self.assertIsNone(query.cursor_token)

    def test_invalid_limits_rejected(self):
        for value in ("0","101","01","-1","1.0"," 1","true","", "1000000000"):
            with self.subTest(value=value),self.assertRaises(DomainError) as error:
                parse_query({"limit":value})
            self.assertEqual(error.exception.code,"VALIDATION_FAILED")

    def test_unknown_duplicate_and_nonstring_query_rejected(self):
        for pairs in ([('sort','newest')],[('status','issued'),('status','queued')],[('limit',1)]):
            with self.subTest(pairs=pairs),self.assertRaises(DomainError) as error:
                parse_query(pairs)
            self.assertEqual(error.exception.code,"INVALID_REQUEST")

    def test_invalid_status_or_uuid_rejected(self):
        for pairs in ({"status":"busy"},{"section_id":"123"},{"executor_id":"*"}):
            with self.subTest(pairs=pairs),self.assertRaises(DomainError):
                parse_query(pairs)


if __name__=="__main__":
    unittest.main()
