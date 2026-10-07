from datetime import datetime,timedelta,timezone
import hashlib,json,os
from pathlib import Path
import unittest
from uuid import UUID
from app.orders.models import DomainError
from app.order_events.query import parse_query,MAX_SEQUENCE,MAX_JS_SAFE_INTEGER
from app.order_events.serialization import event_wire,EVENT_FIELDS

NOW=datetime(2026,10,7,17,tzinfo=timezone.utc)
def uid(n):return f'00000000-0000-4000-8000-{n:012d}'
ORDER=uid(1)


def event(sequence=1,**changes):
    row={'id':UUID(uid(sequence if sequence<1000 else 999)),'order_id':UUID(ORDER),'sequence':sequence,
         'order_version':4,'assignment_revision':1,'scheduling_revision':1,'reason':None,'details':{},
         'kind':'order.ai_review_requested','actor_id':None,'operation_id':UUID(uid(10)),
         'from_status':'done','to_status':'ai_review','submission_id':UUID(uid(11)),
         'occurred_at':NOW,'recorded_at':NOW+timedelta(seconds=2)}
    row.update(changes);return row


class QueryTests(unittest.TestCase):
    def test_defaults_and_bounds(self):
        self.assertEqual(parse_query({}).after_sequence,0)
        self.assertEqual(parse_query({}).limit,100)
        query=parse_query({'after_sequence':str(MAX_SEQUENCE),'limit':'200'})
        self.assertEqual(query.after_sequence,MAX_SEQUENCE);self.assertEqual(query.limit,200)

    def test_noncanonical_sequence_rejected(self):
        for value in ('-1','+1',' 1','1 ','01','00','1.0','1e3','true','',str(MAX_SEQUENCE+1),'9'*1000):
            with self.subTest(value=value),self.assertRaises(DomainError) as error:
                parse_query({'after_sequence':value})
            self.assertEqual(error.exception.code,'VALIDATION_FAILED')

    def test_limit_errors(self):
        for value in ('0','201','01','+1',' 1','-1','1.0',''):
            with self.subTest(value=value),self.assertRaises(DomainError):parse_query({'limit':value})

    def test_unknown_duplicate_and_nonstrings_rejected(self):
        for query in ([('cursor','abc')],[('after_sequence','1'),('after_sequence','2')],[('limit',1)]):
            with self.subTest(query=query),self.assertRaises(DomainError) as error:parse_query(query)
            self.assertEqual(error.exception.code,'INVALID_REQUEST')

    def test_js_unsafe_integer_remains_exact_backend_integer(self):
        value=MAX_JS_SAFE_INTEGER+2
        self.assertEqual(parse_query({'after_sequence':str(value)}).after_sequence,value)
        self.assertEqual(parse_query({'after_sequence':str(MAX_JS_SAFE_INTEGER)}).after_sequence,MAX_JS_SAFE_INTEGER)


class EventSerializationTests(unittest.TestCase):
    def test_exact_fields_nullable_system_actor_and_two_clocks(self):
        row=event(extra_private_field='not exposed')
        body=event_wire(row,order_id=ORDER)
        self.assertEqual(set(body),set(EVENT_FIELDS));self.assertIsNone(body['actor_id'])
        self.assertEqual(body['recorded_at'],'2026-10-07T17:00:02.000000Z')
        self.assertEqual(body['occurred_at'],'2026-10-07T17:00:00.000000Z')
        self.assertNotIn('extra_private_field',body)

    def test_fractional_details_and_human_reason_preserved(self):
        details={'coverage':0.75,'reason_codes':['X'],'nested':{'value':2}}
        row=event(kind='order.reviewed',actor_id=UUID(uid(5)),reason='Проверено мастером',details=details,to_status='closed')
        body=event_wire(row,order_id=ORDER)
        self.assertEqual(body['details'],details);self.assertEqual(body['reason'],'Проверено мастером')

    def test_background_event_nullable_operation_and_submission(self):
        body=event_wire(event(operation_id=None,submission_id=None,from_status=None),order_id=ORDER)
        self.assertIsNone(body['operation_id']);self.assertIsNone(body['submission_id']);self.assertIsNone(body['from_status'])

    def test_foreign_or_invalid_stored_event_fails_closed(self):
        for changes in ({'order_id':UUID(uid(2))},{'sequence':0},{'sequence':True},{'order_version':-1},
                        {'kind':'internal.secret'},{'kind':[]},{'to_status':'fake'},{'details':[]},
                        {'details':{'bad':float('nan')}},{'actor_id':'bad'},{'recorded_at':NOW.replace(tzinfo=None)}):
            with self.subTest(changes=changes),self.assertRaises(DomainError) as error:
                event_wire(event(**changes),order_id=ORDER)
            self.assertEqual(error.exception.code,'TEMPORARILY_UNAVAILABLE')

    def test_missing_stored_field_fails_closed(self):
        row=event();del row['reason']
        with self.assertRaises(DomainError):event_wire(row,order_id=ORDER)

    def test_bigint_json_has_exact_digits_no_string_coercion_or_rounding(self):
        for value in (MAX_JS_SAFE_INTEGER,MAX_JS_SAFE_INTEGER+2,MAX_SEQUENCE):
            body=event_wire(event(value),order_id=ORDER)
            encoded=json.dumps(body,separators=(',',':'))
            self.assertIn(f'"sequence":{value}',encoded)
            self.assertEqual(json.loads(encoded)['sequence'],value)
            self.assertIsInstance(body['sequence'],int)

    def test_page_validates_against_exact_accepted_contract(self):
        import yaml,jsonschema
        root=Path(__file__).resolve().parents[2]
        candidates=[Path(os.environ['DALA_CONTRACT_FILE'])] if os.environ.get('DALA_CONTRACT_FILE') else [
            root/'contracts/openapi.yaml',root/'coord/proposals/a6-contract-v1/contracts/openapi.yaml',
            root.parent/'dalaai-a6-contract/contracts/openapi.yaml']
        path=next((candidate for candidate in candidates if candidate.is_file()),None)
        self.assertIsNotNone(path,'Set DALA_CONTRACT_FILE to the accepted proposal.2 OpenAPI')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         'b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97')
        document=yaml.safe_load(path.read_text())
        schema={'$ref':'#/components/schemas/EventPage','components':document['components']}
        validator=jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker())
        validator.validate({'items':[event_wire(event(),order_id=ORDER)],'next_after_sequence':1,'has_more':False})
        validator.validate({'items':[],'next_after_sequence':MAX_SEQUENCE,'has_more':False})
