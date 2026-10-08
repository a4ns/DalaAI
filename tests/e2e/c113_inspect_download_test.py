"""Dummy-only parser regression tests, never browser or acceptance evidence."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
import importlib.util
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('c113_inspect',HERE/'c113_inspect_download.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
sys.path[:0]=[str(HERE.parents[1]/'backend'),str(HERE.parents[1]/'backend/tests')]
from app.reports.c5_exports import render_export
from app.analytics.c3_types import Period
from test_c4_render import fixture, metric


def expected(kind='shift'):
    return {'kind':kind,'order_id':'00000000-0000-4000-8000-000000000001' if kind=='order' else None,
            'order_number':'37' if kind=='order' else None,
            'period':{'start':'2026-07-01T00:00:00Z','end':'2026-10-01T00:00:00Z'},
            'historical_counts':[1,2,2,2] if kind=='order' else [540,568,444,444]}


def generated(kind,fmt):
    facts=fixture();item=facts.orders[0]
    facts=replace(facts,period=Period(datetime(2026,7,1,tzinfo=timezone.utc),datetime(2026,10,1,tzinfo=timezone.utc)),
        orders=(replace(item,order=replace(item.order,number='37')),),
        metrics=(metric('issued_orders',Decimal(540)),))
    counts=expected(kind)['historical_counts']
    history=dict(zip(('historical_order_count','historical_submission_count','historical_after_photo_reference_count','missing_after_photo_row_count'),counts))
    return render_export(facts,fmt,order_id=item.order.id if kind=='order' else None,historical_evidence=history)


def rewrite_zip(data,change,extra=()):
    output=BytesIO()
    with ZipFile(BytesIO(data)) as source,ZipFile(output,'w',ZIP_DEFLATED) as target:
        for entry in source.infolist():
            target.writestr(entry,change(entry.filename,source.read(entry)))
        for name,body in extra:target.writestr(name,body)
    return output.getvalue()


class InspectionContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifacts={(kind,fmt):generated(kind,fmt) for kind in ('shift','order') for fmt in ('pdf','xlsx')}

    def test_all_four_actual_c5_generated_subsets(self):
        for (kind,fmt),data in self.artifacts.items():
            with self.subTest(kind=kind,fmt=fmt):
                result=m.inspect(data,fmt,expected(kind))
                self.assertTrue(result['content_valid']);self.assertEqual(result['bytes'],len(data))
                self.assertNotIn('text',result)

    def test_wrong_kind_order_number_period_and_counts_fail(self):
        for fmt in ('pdf','xlsx'):
            for field,value in [('order_id','00000000-0000-4000-8000-000000000002'),('order_number','38'),('period',{'start':'2026-07-02T00:00:00Z','end':'2026-10-01T00:00:00Z'}),('historical_counts',[1,1,1,1])]:
                e=expected('order');e[field]=value
                with self.subTest(fmt=fmt,field=field),self.assertRaises(Exception):m.inspect(self.artifacts['order',fmt],fmt,e)
            with self.assertRaises(Exception):m.inspect(self.artifacts['order',fmt],fmt,expected('shift'))

    def test_invalid_signatures_and_bounds_fail(self):
        for fmt in ('pdf','xlsx'):
            for data in (b'',b'not a file',self.artifacts['shift',fmt][:100]):
                with self.subTest(fmt=fmt),self.assertRaises(Exception):m.inspect(data,fmt,expected())
        with patch.object(m,'MAX_BYTES',100):
            with self.assertRaises(Exception):m.inspect(self.artifacts['shift','pdf'],'pdf',expected())
        with patch.object(m,'MAX_EXPANDED',100):
            with self.assertRaises(Exception):m.inspect(self.artifacts['shift','xlsx'],'xlsx',expected())

    def test_zip_duplicate_traversal_xml_formula_and_external_fail(self):
        data=self.artifacts['shift','xlsx']
        changes=[
          (lambda name,b:b,(('xl/workbook.xml',b'<xml/>'),)),
          (lambda name,b:b,(('../outside.xml',b'<xml/>'),)),
          (lambda name,b:b,(('xl/extra.xml',b'<!DOCTYPE a [<!ENTITY x "Y">]><a>&x;</a>'),)),
          (lambda name,b:b.replace(b'<sheetData>',b'<sheetData><f>1+1</f>') if name=='xl/worksheets/sheet1.xml' else b,()),
          (lambda name,b:b.replace(b'Type=',b'TargetMode="External" Type=',1) if name=='xl/_rels/workbook.xml.rels' else b,()),
          (lambda name,b:b'<malformed' if name=='xl/workbook.xml' else b,()),
          (lambda name,b:b.replace(b'r="B2"',b'r="Z2"',1) if name=='xl/worksheets/sheet1.xml' else b,()),
          (lambda name,b:b.replace(b'r="A2"',b'r="A1"',1) if name=='xl/worksheets/sheet1.xml' else b,()),
        ]
        for change,extra in changes:
            with self.subTest(extra=extra),self.assertRaises(Exception):m.inspect(rewrite_zip(data,change,extra),'xlsx',expected())

    def test_pdf_bad_xref_page_tree_filter_and_expansion_fail(self):
        data=self.artifacts['shift','pdf']
        for mutated in (re.sub(rb'startxref\s+\d+',b'startxref\n1',data),data.replace(b'/Type /Page\n',b'/Type /Fake\n',1),data.replace(b'/FlateDecode',b'/WrongDecode',1)):
            with self.assertRaises(Exception):m.inspect(mutated,'pdf',expected())
        with patch.object(m,'MAX_TEXT',16):
            with self.assertRaises(Exception):m.inspect(data,'pdf',expected())

    def test_pdf_invisible_text_and_orphan_content_are_rejected(self):
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        pdfmetrics.registerFont(TTFont('C113Dummy','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        def fake(invisible=False,orphan=False,white=False,zero=False,offpage=False,cropped=False,rotated=False,transparent=False):
            output=BytesIO();canvas=Canvas(output,pageCompression=1,invariant=1)
            if cropped:canvas.setCropBox((0,0,1,1))
            if rotated:canvas.setPageRotation(90)
            if transparent:canvas.setFillAlpha(0)
            lines=['Отчёт смены','СИНТЕТИЧЕСКИЕ ДАННЫЕ','Asia/Almaty (UTC+05:00)',
              'Начало периода, включено: 01.07.2026 05:00:00 +0500','Конец периода, исключён: 01.10.2026 05:00:00 +0500',
              'Исторических нарядов: 540','Исторических попыток: 568','Исторических ссылок на фото: 444',
              'Отсутствующих записей фото: 444','НЕТ ПРОВЕРЕННЫХ ИЗОБРАЖЕНИЙ.','issued_orders','Значение точно: 540']
            if orphan:canvas.beginForm('unused')
            canvas.setFillColorRGB(*( (1,1,1) if white else (0.08,0.13,0.18) ))
            for index,line in enumerate(lines):
                text=canvas.beginText(4000 if offpage else 30,800-index*20)
                text.setFont('C113Dummy',0 if zero else 10)
                if invisible:text.setTextRenderMode(3)
                text.textLine(line);canvas.drawText(text)
            if orphan:canvas.endForm();canvas.drawString(30,30,'blank document')
            canvas.save();return output.getvalue()
        self.assertTrue(m.inspect(fake(),'pdf',expected())['content_valid'])
        for data in (fake(invisible=True),fake(orphan=True),fake(white=True),fake(zero=True),fake(offpage=True),fake(cropped=True),fake(rotated=True),fake(transparent=True)):
            with self.assertRaises(Exception):m.inspect(data,'pdf',expected())

    def test_inspector_has_no_external_process_dependency_or_private_environment(self):
        source=Path(m.__file__).read_text()
        for forbidden in ('subprocess','requests.','urllib','os.environ','read_text('):self.assertNotIn(forbidden,source)
        self.assertIn('os.O_NOFOLLOW',source)


if __name__=='__main__':unittest.main()
