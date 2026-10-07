"""Explicit provider job runner; no implicit startup, credentials or live calls.

Depends on accepted A3 claim/failure/lease SQL and A4 model adapter. These files
are not modified. This worker owns actual-mode persistence and event provenance.
"""
from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import UUID, uuid5

from app.ai.model_adapter import (DemoProjectContext, DemoSubmissionContext, BeforePhotoEvidence, ModelAdapter, ModelAssessment,
    ModelCandidate, SyntheticImage, finalize_candidate, prepare_input)
from app.ai.image_derivation import ImageDerivation, derive_model_png
from app.ai.models import ClosureInput, EvidenceContext, InputValidationError
from app.ai.order_adapter import from_order_snapshot
from app.jobs.models import LostLease, RunResult, assessment_event
from app.jobs.postgres import JobRepository
from app.jobs.worker import AssessmentWorker
from app.persistence.postgres import PostgresRepository, jsonb
from app.scheduler.clocks import utc


@dataclass(frozen=True, slots=True)
class ProviderAssets:
    """Trusted server-loaded model bytes and nullable-before bindings.

    No HTTP/client deserializer. An optional factory may perform bounded LOCAL
    physical reads only. It must verify bytes from the same private store used
    by CLOSE; stored file_valid=True alone is insufficient. In completion mode
    the factory must return fresh before-photo integrity facts, not old images.
    """
    images: tuple[SyntheticImage, ...] = ()
    before_photos: tuple[BeforePhotoEvidence, ...] = ()
    image_derivations: tuple[ImageDerivation, ...] = ()
    derivation_failed: bool = False

    def __post_init__(self):
        if (type(self.images) is not tuple or len(self.images) > 2
                or any(type(i) is not SyntheticImage for i in self.images)
                or type(self.before_photos) is not tuple or len(self.before_photos) > 5
                or any(type(p) is not BeforePhotoEvidence for p in self.before_photos)
                or type(self.image_derivations) is not tuple or len(self.image_derivations)>2
                or any(type(p) is not ImageDerivation for p in self.image_derivations)
                or type(self.derivation_failed) is not bool):
            raise InputValidationError('PROVIDER_ASSETS_INVALID')


class PrivatePngAssetsFactory:
    """Optional local byte loader for an explicitly selected synthetic demo pair.

    photo_reader must be the existing private store integrity verifier's read(row)
    method: it verifies current bytes/length/hash, not just a stored valid flag.
    selections maps immutable submission UUID -> (before UUID or None, after UUID
    or None). It is trusted host configuration, never an HTTP field. Only actual
    metadata-free PNG is supported. Text/image egress still requires exact A4
    payload approval; merely selecting a photo grants no external permission.
    """
    def __init__(self, photo_reader, *, selections):
        from app.ai.rules import _uuid
        if not callable(photo_reader) or type(selections) is not dict or len(selections)>1000:
            raise ValueError('TRUSTED_PNG_SELECTION_REQUIRED')
        self.photo_reader=photo_reader
        self.selections={}
        for submission_id,pair in selections.items():
            _uuid(submission_id,'selection_submission_id')
            if type(pair) is not tuple or len(pair)!=2:
                raise ValueError('PNG_PAIR_REQUIRED')
            for value in pair:
                if value is not None:_uuid(value,'selection_photo_id')
            self.selections[submission_id]=pair

    def _selected(self,order,submission):
        return self.selections.get(submission.id,(None,None))

    def _model_image(self,photo_id,purpose,row,raw):
        return SyntheticImage(photo_id,purpose,raw),None

    def __call__(self,repo,refs,order,submission,*,include_images):
        from app.persistence.postgres import sid
        selected=self._selected(order,submission)
        images,before,derivations=[],[],[]
        for purpose,photo_id in zip(('before','after'),selected):
            if photo_id is None:continue
            eligible=order.before_photo_ids if purpose=='before' else submission.payload.after_photo_ids
            if photo_id not in eligible:
                raise InputValidationError('SELECTED_MODEL_PHOTO_NOT_BOUND')
            row=repo.db.execute('SELECT * FROM photos WHERE id=%s FOR SHARE',(photo_id,)).fetchone()
            if (row is None or sid(row['order_id'])!=order.id or row['attached_at'] is None
                    or sid(row['section_id'])!=order.section_id or row['purpose']!=purpose):
                raise InputValidationError('SELECTED_MODEL_PHOTO_NOT_BOUND')
            if purpose=='after' and (sid(row['submission_id'])!=submission.id
                    or row['assignment_revision']!=submission.assignment_revision
                    or sid(row['owner_id'])!=submission.submitted_by):
                raise InputValidationError('SELECTED_MODEL_PHOTO_NOT_BOUND')
            if purpose=='before' and (row['submission_id'] is not None or row['assignment_revision'] is not None):
                raise InputValidationError('BEFORE_PHOTO_BINDING_INVALID')
            if row['file_valid'] is not True:
                if purpose=='before':before.append(BeforePhotoEvidence(photo_id,order.id,None))
                continue
            raw=self.photo_reader(row)  # Bounded local private read; no remote URL.
            image,proof=self._model_image(photo_id,purpose,row,raw)
            if proof is not None:derivations.append(proof)
            if purpose=='before':before.append(BeforePhotoEvidence(photo_id,order.id,True))
            if include_images:images.append(image)
        return ProviderAssets(tuple(images),tuple(before),tuple(derivations))


class CameraAssetsFactory(PrivatePngAssetsFactory):
    """Verified JPEG/WebP/PNG -> bounded in-memory model PNG, no original write.

    The inherited selection/binding checks and injected private verifier remain
    mandatory. Derivation failures produce explicit rules fallback, never a
    fabricated visual observation. Exact derived payload approval still applies.
    """
    def __init__(self,photo_reader,*,selections=None):
        self.auto_select_current=selections is None
        super().__init__(photo_reader,selections={} if selections is None else selections)

    def _selected(self,order,submission):
        if self.auto_select_current:
            before=order.before_photo_ids[0] if order.before_photo_ids else None
            after=submission.payload.after_photo_ids[0] if submission.payload.after_photo_ids else None
            return before,after
        return super()._selected(order,submission)

    def _model_image(self,photo_id,purpose,row,raw):
        png,proof=derive_model_png(raw,photo_id=photo_id,source_mime=row['mime_type'],
                                   source_sha256=row['sha256'])
        return SyntheticImage(photo_id,purpose,png),proof

    def __call__(self,*args,**kwargs):
        try:
            assets=super().__call__(*args,**kwargs)
            # A selected source which is unknown/invalid is not silently turned
            # into an approved text-only model call. Complete as rules fallback.
            submission=args[3]
            wanted=sum(p is not None for p in self._selected(args[2],submission))
            if len(assets.image_derivations)!=wanted:
                return replace(assets,derivation_failed=True)
            return assets
        except Exception:
            # No raw decoder/storage error is persisted. A DB transaction error
            # still aborts the enclosing transaction before any model request.
            return ProviderAssets(derivation_failed=True)


@dataclass(frozen=True, slots=True)
class PreparedAssessment:
    data: ClosureInput
    context: EvidenceContext
    assets: ProviderAssets
    request_context: DemoSubmissionContext | None = None


def no_model_images(repo, refs, order, submission, *, include_images):
    """Default text-only; no claim that before/after pixels were compared."""
    return ProviderAssets()


def provider_event(order, assessment, candidate, *, sequence, domain_now, real_now,
                   image_derivations=(), derivation_status='not_applicable'):
    # Reuse only stable identity/order-event shape, not its hardcoded rules mode.
    event = assessment_event(order, assessment, sequence=sequence,
                             domain_now=domain_now, real_now=real_now)
    event['details'] = {'assessment_id': assessment.id, 'mode': assessment.to_wire()['mode'],
                        'provider_provenance': candidate.provenance()}
    if image_derivations or derivation_status!='not_applicable':
        event['details']['image_derivations']=[p.to_audit() for p in image_derivations]
        event['details']['image_derivation_status']=derivation_status
    return event


class ProviderJobRepository(JobRepository):
    """Only finalized trusted types reach SQL. No shared table/schema change."""
    def persist_finalized(self, assessment):
        from app.ai.models import Assessment
        if type(assessment) not in (Assessment, ModelAssessment):
            raise InputValidationError('FINALIZED_ASSESSMENT_REQUIRED')
        w = assessment.to_wire()
        # It is impossible for this path to persist an arbitrary model score.
        if w['mode'] not in {'model', 'rules_fallback'} or w['score'] is not None:
            raise InputValidationError('PROVIDER_ASSESSMENT_MODE_INVALID')
        self.db.execute("""INSERT INTO ai_assessments
            (id,submission_id,assignment_revision,mode,schema_version,model,model_version,
             duration_ms,recommendation,score,reasons,evidence_ids,fallback_reason,stale,created_at)
            VALUES (%s,%s,%s,%s,'1',%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s)""",
            (assessment.id,assessment.submission_id,assessment.assignment_revision,
             w['mode'],w['model'],w['model_version'],assessment.duration_ms,
             assessment.recommendation,jsonb(list(assessment.reasons)),
             jsonb(list(assessment.evidence_ids)),w['fallback_reason'],assessment.stale,assessment.created_at))

    def publish_finalized(self, order, assessment, candidate, *, domain_now, real_now,
                          image_derivations=(), derivation_status='not_applicable'):
        count = self.db.execute("""UPDATE orders SET version=version+1,updated_at=%s
            WHERE id=%s AND version=%s AND assignment_revision=%s
            AND current_submission_id=%s AND status='ai_review'""",
            (domain_now,order.id,order.version,assessment.assignment_revision,assessment.submission_id)).rowcount
        if count != 1:
            raise RuntimeError('PROVIDER_CURRENT_FENCE_FAILED')
        sequence = self.db.execute('SELECT COALESCE(MAX(sequence),0)+1 AS n '
                                  'FROM order_events WHERE order_id=%s', (order.id,)).fetchone()['n']
        event = provider_event(order,assessment,candidate,sequence=sequence,
                               domain_now=domain_now,real_now=real_now,image_derivations=image_derivations,
                               derivation_status=derivation_status)
        event['details'] = jsonb(event['details'])
        self.db.execute("""INSERT INTO order_events
            (id,order_id,sequence,order_version,assignment_revision,scheduling_revision,kind,reason,
             details,actor_id,operation_id,from_status,to_status,submission_id,occurred_at,recorded_at)
            VALUES (%(id)s,%(order_id)s,%(sequence)s,%(order_version)s,%(assignment_revision)s,
                %(scheduling_revision)s,%(kind)s,%(reason)s,%(details)s,%(actor_id)s,%(operation_id)s,
                %(from_status)s,%(to_status)s,%(submission_id)s,%(occurred_at)s,%(recorded_at)s)""",event)


class ProviderAssessmentWorker(AssessmentWorker):
    """Host-owned async worker; no state transition beyond assessment event.

    Claim/preparation/completion each use separate committed transactions. Every
    network await runs between transactions. Runtime must inject the same trusted
    physical-evidence factory as human CLOSE, plus optional private PNG assets.
    With absent approval/key, existing ModelAdapter yields honest rules fallback.
    """
    def __init__(self, connect, *, adapter, domain_clock, real_clock=None, policy=None,
                 references_factory=None, assets_factory=None, demo_project=None):
        super().__init__(connect,domain_clock=domain_clock,real_clock=real_clock,
                         policy=policy,references_factory=references_factory)
        if type(adapter) is not ModelAdapter:
            raise ValueError('TYPED_MODEL_ADAPTER_REQUIRED')
        if self.policy.lease <= timedelta(seconds=adapter.settings.timeout_seconds + 2):
            raise ValueError('PROVIDER_TIMEOUT_EXCEEDS_LEASE_MARGIN')
        if demo_project is not None and type(demo_project) is not DemoProjectContext:
            raise ValueError('TRUSTED_DEMO_PROJECT_REQUIRED')
        self.demo_project=demo_project
        self.adapter = adapter
        self.assets_factory = assets_factory or no_model_images

    def _snapshot(self, db, claim, *, include_images):
        repo = PostgresRepository(db)
        sub = repo.load_submission(claim.submission_id)
        if sub is None or sub.assignment_revision != claim.assignment_revision:
            raise InputValidationError('JOB_SUBMISSION_MISMATCH')
        order = repo.load_order(sub.order_id,lock=True)
        if order is None:
            raise InputValidationError('JOB_ORDER_MISSING')
        # Prelock the entire candidate evidence set in one globally sorted photo
        # order, before either factory can reacquire its subsets. Same lock order
        # in preparation and completion; no external/provider network here.
        ids = sorted(set(order.before_photo_ids) | set(sub.payload.after_photo_ids))
        if len(ids) > 10:
            raise InputValidationError('PROVIDER_PHOTO_SET_TOO_LARGE')
        if ids:
            db.execute('SELECT id FROM photos WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE',
                       (ids,)).fetchall()
        refs = self.references_factory(repo,None,self._real(),order)
        codes,materials,photos = refs.closure_evidence(sub)
        data,context = from_order_snapshot(order,sub,work_code_ids=codes,
                                           material_ids=materials,photos=photos)
        assets = self.assets_factory(repo,refs,order,sub,include_images=include_images)
        if type(assets) is not ProviderAssets or (not include_images and assets.images):
            raise InputValidationError('PROVIDER_ASSETS_FACTORY_INVALID')
        before_ids = set(order.before_photo_ids)
        if any(p.id not in before_ids or p.order_id != order.id for p in assets.before_photos):
            raise InputValidationError('PROVIDER_BEFORE_BINDING_INVALID')
        request_context=DemoSubmissionContext.from_server_records(self.demo_project,order,sub) if self.demo_project else None
        return order, PreparedAssessment(data,context,assets,request_context)

    @staticmethod
    def _owns_after_lock(jobs, claim, real):
        if not jobs.owns(claim,now=real(),lock=True) or not jobs.owns(claim,now=real()):
            raise LostLease()

    def prepare(self, claim):
        """Server snapshot under a short transaction; connection closed on return."""
        with self._connection() as db:
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                _,prepared = self._snapshot(db,claim,include_images=True)
                self._owns_after_lock(JobRepository(db),claim,self._real)
            return prepared

    def complete(self, claim, candidate, *, image_derivations=()):
        """No network awaits; refreshed current evidence + claim fence at commit."""
        if (type(candidate) is not ModelCandidate or type(image_derivations) is not tuple
                or len(image_derivations)>2 or any(type(p) is not ImageDerivation for p in image_derivations)):
            raise InputValidationError('TYPED_MODEL_CANDIDATE_REQUIRED')
        try:
            with self._connection() as db:
                with db.transaction():
                    db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                    order,current = self._snapshot(db,claim,include_images=False)
                    jobs = ProviderJobRepository(db)
                    self._owns_after_lock(jobs,claim,self._real)
                    derivation_status='current' if image_derivations else 'not_applicable'
                    if current.assets.derivation_failed or image_derivations!=current.assets.image_derivations:
                        derivation_status='changed_or_unavailable'
                        candidate=replace(candidate,observation=None,evidence_ids=(),
                            fallback_reason='provider_unavailable',diagnostic_code='model_image_source_changed')
                    # Provider approval/budget/lease time stays real. The saved
                    # recommendation belongs to the business timeline.
                    domain_now=utc(self.domain_clock.now())
                    if domain_now < order.updated_at:
                        raise RuntimeError('Assessment business clock precedes snapshot')
                    assessment,_ = finalize_candidate(candidate,current.data,current.context,
                        assessment_id=str(uuid5(UUID(claim.id),'provider-assessment-v1')),
                        created_at=domain_now,before_photos=current.assets.before_photos)
                    jobs.persist_finalized(assessment)
                    if not assessment.stale:
                        jobs.publish_finalized(order,assessment,candidate,
                            domain_now=domain_now,real_now=self._real(),
                            image_derivations=image_derivations,derivation_status=derivation_status)
                    # Failure AFTER provisional INSERT/event/version also rolls
                    # every effect back. Never trust lease time from before locks.
                    if not jobs.finish(claim,now=self._real()):
                        raise LostLease()
                return RunResult('done',claim.id,assessment.id,assessment.stale)
        except LostLease:
            return RunResult('lost_lease',claim.id)

    async def run_once(self):
        claim = self.claim_one()
        if claim is None:
            return RunResult('idle')
        if claim is False:
            return RunResult('exhausted')
        try:
            prepared = self.prepare(claim)
            # Do not start a paid request if preparation consumed its lease.
            if self._real() + timedelta(seconds=self.adapter.settings.timeout_seconds + 1) >= claim.lease_until:
                return self.record_failure(claim)
            if prepared.assets.derivation_failed:
                payload=prepare_input(prepared.data,prepared.context)
                s=self.adapter.settings
                candidate=ModelCandidate(payload.snapshot_hash,payload.payload_hash,s.provider,s.model,
                    s.model_version,0,None,(),(),'provider_unavailable','model_image_derivation_unavailable',
                    settings_fingerprint=s.fingerprint)
            else:
                candidate = await self.adapter.assess(prepared.data,prepared.context,
                    images=prepared.assets.images,before_photos=prepared.assets.before_photos,
                    now=self._real(),request_context=prepared.request_context)
            return self.complete(claim,candidate,image_derivations=prepared.assets.image_derivations)
        except LostLease:
            return RunResult('lost_lease',claim.id)
        except InputValidationError:
            return self.record_failure(claim,invalid_input=True)
        except Exception:
            # No exception content, key, prompt or image is recorded.
            return self.record_failure(claim)

    async def run_batch(self, *, limit=20):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Batch limit must be in 1..1000')
        results=[]
        for _ in range(limit):
            result=await self.run_once()
            if result.state == 'idle':
                break
            results.append(result)
        return tuple(results)
