"""One human-reviewed synthetic dataset policy; no key, network or auto-approval.

Human/operator supplies a reviewed fixture manifest and explicitly runs setup.
Runtime reads the resulting policy only in a trusted isolated synthetic-demo
context. Arbitrary uploads cannot acquire provenance by setting a client flag.
"""
from dataclasses import dataclass
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import re

from .image_derivation import derive_model_png,MAX_SOURCE_BYTES
from .model_adapter import (EgressApproval,SyntheticDemoContext,content_fingerprint,
                            strict_json,InputValidationError)
from .openai_runtime import openai_demo_settings,openai_demo_budget,DEFAULT_DEMO_POLICY_EXPIRES_AT,NIGHT_ENDS_AT

POLICY_SCHEMA='synthetic-demo-egress-1'


@dataclass(frozen=True,slots=True)
class _ContentImage:
    purpose:str
    data:bytes


def build_demo_policy(manifest,*,fixture_root,expires_at,settings=None):
    """Offline helper, not user consent. Call only after human fixture approval.

    Input paths must remain within the explicit fixture root; reads are bounded
    and hashes must match. Image bytes pass the same A2 upload sanitizer before
    model derivation, so repeated uploads of the approved original fixture get
    the same outbound content even though runtime IDs are newly generated.
    """
    from app.photos.validation import decode_raster
    if (type(manifest) is not dict or set(manifest)!={'schema_version','dataset_id','dataset_version','cases'}
            or manifest['schema_version']!='1' or type(manifest['cases']) is not list
            or not 1<=len(manifest['cases'])<=100):
        raise InputValidationError('DEMO_FIXTURE_MANIFEST_INVALID')
    context=SyntheticDemoContext(manifest['dataset_id'],manifest['dataset_version'])
    if not isinstance(expires_at,datetime) or expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise InputValidationError('DEMO_POLICY_EXPIRY_REQUIRED')
    root=Path(fixture_root).resolve(strict=True)
    hashes,provenance=[],[]
    for case in manifest['cases']:
        if (type(case) is not dict or set(case)!={'problem_text','work_text','before','after'}
                or type(case['problem_text']) is not str or len(case['problem_text'])>2000
                or type(case['work_text']) is not str or not 1<=len(case['work_text'])<=6000):
            raise InputValidationError('DEMO_FIXTURE_CASE_INVALID')
        images,sources=[],[]
        for purpose in ('before','after'):
            item=case[purpose]
            if item is None:continue
            if (type(item) is not dict or set(item)!={'path','sha256'} or type(item['path']) is not str
                    or type(item['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}',item['sha256'])):
                raise InputValidationError('DEMO_FIXTURE_IMAGE_INVALID')
            path=(root/item['path']).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise InputValidationError('DEMO_FIXTURE_PATH_OUTSIDE_ROOT')
            with path.open('rb') as stream:raw=stream.read(MAX_SOURCE_BYTES+1)
            if len(raw)>MAX_SOURCE_BYTES or sha256(raw).hexdigest()!=item['sha256']:
                raise InputValidationError('DEMO_FIXTURE_DIGEST_MISMATCH')
            uploaded=decode_raster(raw)
            # A hashing-only placeholder identifies no real order/photo binding.
            # No fake before submission or assignment enters runtime evidence.
            png,proof=derive_model_png(uploaded.data,photo_id='00000000-0000-4000-8000-000000000001',
                                       source_mime=uploaded.mime_type,source_sha256=uploaded.sha256)
            images.append(_ContentImage(purpose,png))
            sources.append({'purpose':purpose,'fixture_sha256':item['sha256'],
                            'stored_source_sha256':uploaded.sha256,'derived_sha256':proof.derived_sha256})
        digest=content_fingerprint(case['problem_text'],case['work_text'],tuple(images))
        hashes.append(digest);provenance.append({'content_sha256':digest,'sources':sources})
    settings=settings or openai_demo_settings();budget=openai_demo_budget()
    return {'schema_version':POLICY_SCHEMA,'approval_id':budget.approval_id,
        'dataset_id':context.dataset_id,'dataset_version':context.dataset_version,
        'settings_fingerprint':settings.fingerprint,
        'expires_at':expires_at.astimezone(timezone.utc).isoformat().replace('+00:00','Z'),
        'image_egress':any(case['sources'] for case in provenance),
        'content_hashes':sorted(set(hashes)),'fixture_provenance':provenance,
        'total_microusd':budget.total_microusd,'period_microusd':budget.period_microusd,
        'night_ends_at':NIGHT_ENDS_AT.isoformat().replace('+00:00','Z')}


def load_demo_policy(policy,*,settings,ledger,demo_context):
    """Trusted host passes the actual current demo context, never user input."""
    keys={'schema_version','approval_id','dataset_id','dataset_version','settings_fingerprint',
          'expires_at','image_egress','content_hashes','fixture_provenance','total_microusd','period_microusd','night_ends_at'}
    if (type(policy) is not dict or set(policy)!=keys or policy['schema_version']!=POLICY_SCHEMA
            or type(demo_context) is not SyntheticDemoContext
            or policy['dataset_id']!=demo_context.dataset_id or policy['dataset_version']!=demo_context.dataset_version
            or policy['approval_id']!=ledger.policy.approval_id
            or policy['settings_fingerprint']!=settings.fingerprint
            or type(policy['image_egress']) is not bool
            or type(policy['content_hashes']) is not list or not 1<=len(policy['content_hashes'])<=100
            or any(type(h) is not str or not re.fullmatch('[a-f0-9]{64}',h) for h in policy['content_hashes'])
            or type(policy['total_microusd']) is not int or type(policy['period_microusd']) is not int
            or policy['total_microusd']!=ledger.policy.total_microusd
            or policy['period_microusd']!=ledger.policy.period_microusd
            or policy['total_microusd']>50_000_000 or policy['period_microusd']>10_000_000
            or ledger.policy.per_call_microusd<openai_demo_budget().per_call_microusd
            or ledger.policy.period_ends_at!=NIGHT_ENDS_AT.timestamp()
            or policy['night_ends_at']!=NIGHT_ENDS_AT.isoformat().replace('+00:00','Z')):
        raise InputValidationError('DEMO_POLICY_CONTEXT_OR_LIMIT_INVALID')
    try:
        expiry=datetime.fromisoformat(policy['expires_at'].replace('Z','+00:00'))
        if expiry.tzinfo is None or expiry.utcoffset() is None:raise ValueError
    except (AttributeError,TypeError,ValueError):
        raise InputValidationError('DEMO_POLICY_EXPIRY_INVALID') from None
    return EgressApproval(policy['approval_id'],policy['settings_fingerprint'],frozenset(),expiry,
        policy['image_egress'],frozenset(policy['content_hashes']),policy['dataset_id'],policy['dataset_version'])


def read_demo_policy(path):
    with Path(path).open('rb') as stream:raw=stream.read(1_048_577)
    return strict_json(raw,cap=1_048_576)

INTERACTIVE_SCHEMA='authorized-demo-processing-1'
INTERACTIVE_PURPOSE='closure_text_and_before_after_images'
INTERACTIVE_REPORTS_PURPOSE='closure_text_before_after_images_and_grounded_reports'
PROCESSING_DISCLOSURE=(
    'Текст результата и выбранные фото демонстрационного наряда отправляются в OpenAI '
    'для проверки соответствия и сравнения до/после. Синтетичность содержимого загрузок '
    'не подтверждена автоматически. Модель рекомендует; решение принимает мастер.')
REPORTS_PROCESSING_DISCLOSURE=(PROCESSING_DISCLOSURE+
    ' По отдельному запросу мастера в OpenAI также передаются доступные ему факты '
    'демонстрационного отчёта для краткой сводки. Сводка модели не изменяет наряды '
    'и не подтверждает качество или безопасность работ.')


def build_interactive_demo_policy(*,project_id,instance_id,expires_at=DEFAULT_DEMO_POLICY_EXPIRES_AT,settings=None,
                                  include_grounded_reports=False):
    """Human/operator setup within owner's approved interactive demo scope.

    No per-order/content approval is required after this explicit bounded policy.
    This builder itself is not permission: operator must possess the owner's
    authorization and establish this is the named isolated demo, not production.
    """
    from .model_adapter import DemoProjectContext
    if type(include_grounded_reports) is not bool:
        raise InputValidationError('DEMO_POLICY_PURPOSE_INVALID')
    project=DemoProjectContext(project_id,instance_id)
    if not isinstance(expires_at,datetime) or expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise InputValidationError('DEMO_POLICY_EXPIRY_REQUIRED')
    settings=settings or openai_demo_settings();budget=openai_demo_budget()
    return {'schema_version':INTERACTIVE_SCHEMA,'approval_id':budget.approval_id,
        'project_id':project.project_id,'instance_id':project.instance_id,
        'settings_fingerprint':settings.fingerprint,
        'expires_at':expires_at.astimezone(timezone.utc).isoformat().replace('+00:00','Z'),
        'purpose':INTERACTIVE_REPORTS_PURPOSE if include_grounded_reports else INTERACTIVE_PURPOSE,
        'authenticated_submissions_only':True,
        'image_egress':True,'source_provenance':'authenticated_demo_submission_content_unverified',
        'processing_disclosure':REPORTS_PROCESSING_DISCLOSURE if include_grounded_reports else PROCESSING_DISCLOSURE,
        'total_microusd':budget.total_microusd,'period_microusd':budget.period_microusd,
        'night_ends_at':NIGHT_ENDS_AT.isoformat().replace('+00:00','Z')}


def load_interactive_demo_policy(policy,*,settings,ledger,project_context,runtime_mode):
    """Call from trusted host config; runtime_mode must be actual demo mode."""
    from .model_adapter import DemoProjectContext
    keys={'schema_version','approval_id','project_id','instance_id','settings_fingerprint','expires_at',
          'purpose','authenticated_submissions_only','image_egress','source_provenance',
          'processing_disclosure','total_microusd','period_microusd','night_ends_at'}
    if (type(policy) is not dict or set(policy)!=keys or policy['schema_version']!=INTERACTIVE_SCHEMA
            or runtime_mode!='demo' or type(project_context) is not DemoProjectContext
            or policy['project_id']!=project_context.project_id or policy['instance_id']!=project_context.instance_id
            or policy['approval_id']!=ledger.policy.approval_id or policy['settings_fingerprint']!=settings.fingerprint
            or policy['purpose'] not in (INTERACTIVE_PURPOSE,INTERACTIVE_REPORTS_PURPOSE)
            or policy['authenticated_submissions_only'] is not True or policy['image_egress'] is not True
            or policy['source_provenance']!='authenticated_demo_submission_content_unverified'
            or policy['processing_disclosure']!=(REPORTS_PROCESSING_DISCLOSURE
                if policy['purpose']==INTERACTIVE_REPORTS_PURPOSE else PROCESSING_DISCLOSURE)
            or type(policy['total_microusd']) is not int or type(policy['period_microusd']) is not int
            or policy['total_microusd']!=ledger.policy.total_microusd or policy['total_microusd']>50_000_000
            or policy['period_microusd']!=ledger.policy.period_microusd or policy['period_microusd']>10_000_000
            or ledger.policy.per_call_microusd<openai_demo_budget().per_call_microusd
            or ledger.policy.period_ends_at!=NIGHT_ENDS_AT.timestamp()
            or policy['night_ends_at']!=NIGHT_ENDS_AT.isoformat().replace('+00:00','Z')):
        raise InputValidationError('INTERACTIVE_DEMO_POLICY_SCOPE_INVALID')
    try:
        expiry=datetime.fromisoformat(policy['expires_at'].replace('Z','+00:00'))
        if expiry.tzinfo is None or expiry.utcoffset() is None:raise ValueError
    except (AttributeError,TypeError,ValueError):
        raise InputValidationError('DEMO_POLICY_EXPIRY_INVALID') from None
    return EgressApproval(policy['approval_id'],policy['settings_fingerprint'],frozenset(),expiry,True,
        interactive_project_id=policy['project_id'],interactive_instance_id=policy['instance_id'],
        allow_authenticated_demo_submissions=True)
