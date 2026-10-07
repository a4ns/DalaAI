"""Synthetic raster/private-store tests only; never a visual-model quality eval."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import random
import struct
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from PIL import Image,PngImagePlugin
from app.ai.image_derivation import derive_model_png,MAX_SOURCE_BYTES,MAX_MODEL_BYTES
from app.ai.model_adapter import SyntheticImage,prepare_input,EgressApproval
from app.ai.models import InputValidationError
from app.jobs.provider_worker import CameraAssetsFactory,ProviderAssets
from app.photos.integrity import PhotoIntegrityVerifier
from app.photos.storage import PrivateFileStore
from test_model_adapter import good,uid,NOW,BEFORE,AFTER
import test_provider_worker_unit as worker_fixture


def raster(fmt='JPEG',*,size=(240,160),metadata=True,alpha=False):
    image=Image.new('RGBA' if alpha else 'RGB',size,(23,50,100,0) if alpha else (23,50,100))
    exif=Image.Exif();exif[270]='PRIVATE_GPS_EMPLOYEE_MARKER';exif[315]='PRIVATE_AUTHOR';exif[274]=6
    options={}
    if metadata:
        if fmt=='PNG':
            info=PngImagePlugin.PngInfo();info.add_text('GPS','PRIVATE_GPS_EMPLOYEE_MARKER')
            options={'pnginfo':info,'exif':exif}
        else:options={'exif':exif}
    out=BytesIO()
    image.save(out,format=fmt,**options);image.close()
    return out.getvalue()


def derive(raw,mime='image/jpeg'):
    return derive_model_png(raw,photo_id=AFTER,source_mime=mime,source_sha256=sha256(raw).hexdigest())


class DerivationTests(unittest.TestCase):
    def test_jpeg_webp_png_reencode_full_decode_and_remove_all_metadata(self):
        for fmt,mime in [('JPEG','image/jpeg'),('WEBP','image/webp'),('PNG','image/png')]:
            with self.subTest(fmt=fmt):
                raw=raster(fmt)
                png,proof=derive(raw,mime)
                self.assertNotIn(b'PRIVATE',png)
                SyntheticImage(AFTER,'after',png)
                with Image.open(BytesIO(png)) as out:
                    out.load();self.assertEqual(out.format,'PNG');self.assertEqual(out.mode,'RGB')
                    self.assertEqual(out.info,{})
                    self.assertEqual(len(out.getexif()),0)
                    self.assertEqual(out.size,(160,240))
                self.assertEqual(proof.source_sha256,sha256(raw).hexdigest())
                self.assertEqual(proof.derived_sha256,sha256(png).hexdigest())
                self.assertEqual(proof.source_mime,mime)
                self.assertNotIn('PRIVATE',json.dumps(proof.to_audit()))

    def test_large_camera_jpeg_is_bounded_and_aspect_preserved(self):
        raw=raster(size=(4000,3000),metadata=False)
        png,proof=derive(raw)
        self.assertLessEqual(len(png),MAX_MODEL_BYTES)
        self.assertEqual((proof.derived_width,proof.derived_height),(1280,960))
        self.assertEqual((proof.source_width,proof.source_height),(4000,3000))

    def test_noisy_large_png_shrinks_until_real_byte_limit(self):
        rng=random.Random(42)
        image=Image.frombytes('RGB',(1800,1400),rng.randbytes(1800*1400*3))
        out=BytesIO();image.save(out,format='PNG');image.close()
        raw=out.getvalue();self.assertGreater(len(raw),MAX_MODEL_BYTES);self.assertLess(len(raw),MAX_SOURCE_BYTES)
        png,proof=derive(raw,'image/png')
        self.assertLessEqual(len(png),MAX_MODEL_BYTES)
        self.assertLess(max(proof.derived_width,proof.derived_height),1280)
        SyntheticImage(AFTER,'after',png)

    def test_jpeg_larger_than_previous_one_mib_model_limit_is_supported(self):
        rng=random.Random(91)
        image=Image.frombytes('RGB',(1800,1400),rng.randbytes(1800*1400*3))
        out=BytesIO();image.save(out,format='JPEG',quality=95);image.close()
        raw=out.getvalue();self.assertGreater(len(raw),MAX_MODEL_BYTES)
        self.assertLess(len(raw),MAX_SOURCE_BYTES)
        png,proof=derive(raw,'image/jpeg')
        self.assertLessEqual(len(png),MAX_MODEL_BYTES)
        self.assertEqual(proof.source_bytes,len(raw))
        SyntheticImage(AFTER,'after',png)

    def test_transparency_is_composited_without_exposing_hidden_rgb(self):
        png,_=derive(raster('PNG',alpha=True,metadata=False),'image/png')
        with Image.open(BytesIO(png)) as image:self.assertEqual(image.getpixel((0,0)),(255,255,255))

    def test_repeat_derivation_same_source_has_identical_provenance(self):
        raw=raster()
        self.assertEqual(derive(raw),derive(raw))

    def test_wrong_hash_mime_unsupported_truncated_and_too_large_fail_closed(self):
        raw=raster()
        with self.assertRaises(InputValidationError):
            derive_model_png(raw,photo_id=AFTER,source_mime='image/jpeg',source_sha256='0'*64)
        for raw,mime in [(raw,'image/png'),(raw[:80],'image/jpeg'),(b'<svg/>','image/png'),
                         (b'x'*(MAX_SOURCE_BYTES+1),'image/jpeg')]:
            with self.subTest(mime=mime,length=len(raw)),self.assertRaises(InputValidationError):derive(raw,mime)

    def test_pixel_bomb_rejected_from_header_before_full_decode(self):
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',5001,4000,8,2,0,0,0))
        raw+=chunk(b'IDAT',zlib.compress(b'\0'))+chunk(b'IEND',b'')
        with self.assertRaisesRegex(InputValidationError,'DIMENSION'):derive(raw,'image/png')

    def test_animated_webp_rejected(self):
        first=Image.new('RGB',(10,10),'red');second=Image.new('RGB',(10,10),'blue');out=BytesIO()
        first.save(out,format='WEBP',save_all=True,append_images=[second],duration=100,loop=0)
        first.close();second.close()
        with self.assertRaises(InputValidationError):derive(out.getvalue(),'image/webp')

    def test_busy_decoder_fails_without_queue_or_unbounded_work(self):
        import app.ai.image_derivation as module
        raw=raster()
        self.assertTrue(module._DECODE_SLOT.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(InputValidationError,'BUSY'):derive(raw)
        finally:module._DECODE_SLOT.release()


class PrivateCameraFactoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=PrivateFileStore(Path(self.tmp.name))
        self.verifier=PhotoIntegrityVerifier(self.store)
        self.d,self.c=good()
        self.order=SimpleNamespace(id=self.d.order_id,section_id=uid(80),before_photo_ids=(BEFORE,))
        self.sub=SimpleNamespace(id=self.d.submission_id,assignment_revision=1,submitted_by=uid(81),
                                payload=SimpleNamespace(after_photo_ids=(AFTER,)))
        self.rows={}
        for photo_id,purpose,fmt,mime in [(BEFORE,'before','JPEG','image/jpeg'),(AFTER,'after','WEBP','image/webp')]:
            raw=raster(fmt,size=(1800,1200))
            key=self.store.put(raw)
            self.rows[photo_id]={'id':photo_id,'order_id':self.d.order_id,'section_id':uid(80),
                'attached_at':NOW,'purpose':purpose,'file_valid':True,'owner_id':uid(81),
                'submission_id':None if purpose=='before' else self.d.submission_id,
                'assignment_revision':None if purpose=='before' else 1,
                'storage_key':key,'bytes':len(raw),'mime_type':mime,'sha256':sha256(raw).hexdigest()}
        self.repo=SimpleNamespace(db=SimpleNamespace(execute=lambda sql,params:
            SimpleNamespace(fetchone=lambda:self.rows.get(params[0]))))
        self.factory=CameraAssetsFactory(self.verifier.read,selections={self.sub.id:(BEFORE,AFTER)})

    def test_real_private_store_bytes_derive_without_mutating_source(self):
        before={key:Path(self.tmp.name,key).read_bytes() for key in [p['storage_key'] for p in self.rows.values()]}
        result=self.factory(self.repo,None,self.order,self.sub,include_images=True)
        self.assertFalse(result.derivation_failed);self.assertEqual(len(result.images),2)
        self.assertEqual([p.source_mime for p in result.image_derivations],['image/jpeg','image/webp'])
        current=self.factory(self.repo,None,self.order,self.sub,include_images=False)
        self.assertEqual(current.images,());self.assertEqual(current.image_derivations,result.image_derivations)
        self.assertEqual(before,{key:Path(self.tmp.name,key).read_bytes() for key in before})
        self.assertIsNone(self.rows[BEFORE]['submission_id']);self.assertIsNone(self.rows[BEFORE]['assignment_revision'])

    def test_corrupt_current_private_bytes_marks_derivation_unavailable(self):
        row=self.rows[BEFORE];path=Path(self.tmp.name,row['storage_key'])
        path.write_bytes(b'x'*row['bytes'])
        result=self.factory(self.repo,None,self.order,self.sub,include_images=False)
        self.assertTrue(result.derivation_failed)

    def test_unknown_file_valid_not_upgraded_or_sent(self):
        self.rows[BEFORE]['file_valid']=None
        result=self.factory(self.repo,None,self.order,self.sub,include_images=True)
        self.assertTrue(result.derivation_failed)
        self.assertNotIn(BEFORE,[p.photo_id for p in result.images])

    def test_foreign_source_binding_falls_back(self):
        self.rows[AFTER]['order_id']=uid(99)
        result=self.factory(self.repo,None,self.order,self.sub,include_images=True)
        self.assertTrue(result.derivation_failed)


class CameraWorkerTests(unittest.IsolatedAsyncioTestCase):
    setUp=worker_fixture.ProviderWorkerUnitTests.setUp

    def setup_derivative(self):
        raw=raster('JPEG',metadata=True)
        png,proof=derive(raw)
        image=SyntheticImage(AFTER,'after',png)
        def assets(repo,refs,order,sub,*,include_images):
            return ProviderAssets((image,) if include_images else (),(),(proof,))
        self.worker.assets_factory=assets
        p=prepare_input(self.store.data,self.store.context,images=(image,))
        self.worker.adapter.approval=replace(self.worker.adapter.approval,
            synthetic_payload_hashes=frozenset({p.payload_hash}),image_egress=True)
        return proof

    async def test_camera_derivative_model_mode_and_source_provenance(self):
        proof=self.setup_derivative()
        result=await self.worker.run_once()
        self.assertEqual(result.state,'done')
        self.assertEqual(self.store.effects[0][1][3],'model')
        details=self.store.effects[2][1]['details']
        self.assertEqual(details['image_derivations'],[proof.to_audit()])
        self.assertEqual(details['image_derivation_status'],'current')
        self.assertNotIn('PRIVATE',json.dumps(self.transport.calls))

    async def test_changed_source_digest_after_model_discards_observation(self):
        proof=self.setup_derivative();original=self.worker.assets_factory
        def changed(repo,refs,order,sub,*,include_images):
            a=original(repo,refs,order,sub,include_images=include_images)
            return a if include_images else replace(a,image_derivations=(replace(proof,source_sha256='a'*64),))
        self.worker.assets_factory=changed
        result=await self.worker.run_once()
        self.assertEqual(result.state,'done')
        self.assertEqual(self.store.effects[0][1][3],'rules_fallback')
        self.assertEqual(self.store.effects[2][1]['details']['image_derivation_status'],'changed_or_unavailable')

    async def test_derivation_failure_before_model_yields_rules_without_spend(self):
        self.worker.assets_factory=lambda *a,**k:ProviderAssets(derivation_failed=True)
        result=await self.worker.run_once()
        self.assertEqual(result.state,'done');self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.store.effects[0][1][3],'rules_fallback')
        self.assertEqual(self.worker.adapter.ledger.counters()['calls_reserved'],0)

    async def test_current_derivation_failure_discards_model(self):
        self.setup_derivative();original=self.worker.assets_factory
        self.worker.assets_factory=lambda *a,**k:original(*a,**k) if k['include_images'] else ProviderAssets(derivation_failed=True)
        result=await self.worker.run_once()
        self.assertEqual(result.state,'done')
        self.assertEqual(self.store.effects[0][1][3],'rules_fallback')
