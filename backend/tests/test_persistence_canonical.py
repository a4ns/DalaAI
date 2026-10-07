import copy
from decimal import Decimal
import unittest

from app.orders.models import DomainError
from app.orders.validation import parse_command
from app.persistence.canonical import canonical_json, command_hash, decode_json


def uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def create_command():
    return {"operation_id":uid(11),"expected_version":0,"action":"create","payload":{
        "type":"unplanned","description":"Проверить ремень","section_id":uid(1),"equipment_id":uid(2),
        "assignment":{"executor_id":uid(3),"brigade_id":None},"due_at":"2026-10-07T18:00:00Z",
        "norm_minutes":30,"priority":"normal","comment":"","before_photo_ids":[]}}


class CanonicalTests(unittest.TestCase):
    def test_order_of_object_keys_is_not_significant(self):
        a = create_command()
        b = dict(reversed(list(a.items())))
        b["payload"] = dict(reversed(list(a["payload"].items())))
        self.assertEqual(command_hash(parse_command(a),None),command_hash(parse_command(b),None))

    def test_uuid_case_and_timestamp_offsets_normalize(self):
        a = create_command()
        a["operation_id"] = "aabbccdd-aabb-4abb-8abb-aabbccddeeff"
        b = copy.deepcopy(a)
        b["operation_id"] = b["operation_id"].upper()
        b["payload"]["due_at"] = "2026-10-07T23:00:00.000000+05:00"
        self.assertEqual(command_hash(parse_command(a),None),command_hash(parse_command(b),None))

    def test_decimal_normalizes_without_binary_float(self):
        self.assertEqual(canonical_json({"q":Decimal("1.230"),"zero":Decimal("-0")}),'{"q":1.23,"zero":0}')
        raw = decode_json('{"q":123456789.123}')
        self.assertIsInstance(raw["q"],Decimal)
        self.assertEqual(raw["q"],Decimal("123456789.123"))

    def test_route_expected_version_and_payload_are_bound(self):
        a = {"operation_id":uid(11),"expected_version":1,"action":"accept","payload":{}}
        baseline = command_hash(parse_command(a),uid(30))
        self.assertNotEqual(baseline,command_hash(parse_command(a),uid(31)))
        a["expected_version"] = 2
        self.assertNotEqual(baseline,command_hash(parse_command(a),uid(30)))
        b = create_command()
        before = command_hash(parse_command(b),None)
        b["payload"]["comment"] = "different"
        self.assertNotEqual(before,command_hash(parse_command(b),None))

    def test_duplicate_keys_and_nonfinite_are_rejected(self):
        for raw in ('{"a":1,"a":2}','{"a":{"b":1,"b":2}}','{"a":NaN}','{"a":Infinity}','{"a":-Infinity}',b'\xff'):
            with self.subTest(raw=raw),self.assertRaises(DomainError) as caught:
                decode_json(raw)
            self.assertEqual(caught.exception.code,"INVALID_REQUEST")

    def test_no_float_fallback_in_canonical_encoder(self):
        with self.assertRaises(ValueError):
            canonical_json(0.1)

    def test_route_cannot_change_create_or_action_semantics(self):
        with self.assertRaises(DomainError):
            command_hash(parse_command(create_command()),uid(30))
        with self.assertRaises(DomainError):
            command_hash(parse_command({"operation_id":uid(11),"expected_version":1,"action":"accept","payload":{}}),None)

    def test_lone_unicode_surrogate_rejected(self):
        raw = create_command()
        raw["payload"]["comment"] = "\ud800"
        with self.assertRaises(DomainError) as error:
            command_hash(parse_command(raw),None)
        self.assertEqual(error.exception.code,"INVALID_REQUEST")

    def test_nul_text_rejected_before_postgres(self):
        raw = {"operation_id":uid(11),"expected_version":3,"action":"pause",
               "payload":{"reason":"abc\x00def"}}
        with self.assertRaises(DomainError) as error:
            command_hash(parse_command(raw),uid(30))
        self.assertEqual(error.exception.code,"VALIDATION_FAILED")

    def test_golden_vector(self):
        self.assertEqual(command_hash(parse_command(create_command()),None),
                         "6e6ca4d93b76d2fc74262e63faaa212ad7b5d91e1f17ec53a3e803639cffe321")


if __name__ == "__main__":
    unittest.main()
