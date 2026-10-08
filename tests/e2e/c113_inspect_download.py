"""Bounded, fail-closed inspection of C5-generated PDF/XLSX subsets only.

No generic PDF safety or native application readability claim. No network,
credential files, renderer import or external executable. Output is fixed facts.
"""
import base64
from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import PurePosixPath
import re
import stat
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
import zlib

MAX_BYTES = 8 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
MAX_TEXT = 2 * 1024 * 1024
STAGES = frozenset({'START','READ_EXPECTED_FILE','PARSE_EXPECTED_JSON','READ_SAVED_FILE','EXPECTED_CONTRACT','FILE_BOUND',
    'PDF_XREF','PDF_OBJECTS','PDF_CATALOG_PAGES','PDF_PAGE_SHAPE','PDF_FONT_RESOURCES','PDF_STREAM','PDF_FONT_MAP',
    'PDF_OPERATORS','PDF_VISIBLE_STYLE','PDF_TEXT_DECODE','PDF_CONTENT','XLSX_ARCHIVE','XLSX_ENTRY','XLSX_XML',
    'XLSX_RELATIONSHIPS','XLSX_CELLS','XLSX_CONTENT','RESULT','UNCLASSIFIED'})
_stage = 'START'


def checkpoint(stage):
    global _stage
    _stage = stage if stage in STAGES else 'UNCLASSIFIED'


def require(condition):
    if not condition:
        raise ValueError('C113_DOWNLOAD_INSPECTION_FAILED')


def bounded_file(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= limit)
        with os.fdopen(fd, 'rb', closefd=False) as source:
            data = source.read(limit + 1)
        require(len(data) == st.st_size and len(data) <= limit)
        return data
    finally:
        os.close(fd)


def xml(data):
    checkpoint('XLSX_XML')
    require(len(data) <= MAX_EXPANDED and b'<!DOCTYPE' not in data.upper() and b'<!ENTITY' not in data.upper())
    result = ET.fromstring(data)
    require(sum(1 for _ in result.iter()) <= 300000)
    return result


NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}


def xlsx(data):
    checkpoint('XLSX_ARCHIVE')
    require(data.startswith(b'PK\x03\x04'))
    with ZipFile(BytesIO(data)) as archive:
        entries = archive.infolist()
        require(5 <= len(entries) <= 80 and len({e.filename for e in entries}) == len(entries))
        require(sum(e.file_size for e in entries) <= MAX_EXPANDED)
        contents = {}
        for entry in entries:
            checkpoint('XLSX_ENTRY')
            name = entry.filename
            require(not entry.is_dir() and len(name) <= 160 and '\\' not in name and not name.startswith('/') and '..' not in PurePosixPath(name).parts)
            require(entry.compress_type in {ZIP_DEFLATED, ZIP_STORED} and not entry.flag_bits & 1 and 0 < entry.file_size <= MAX_EXPANDED)
            require(not stat.S_ISLNK(entry.external_attr >> 16))
            require(name.endswith(('.xml', '.rels')) and not any(s in name.lower() for s in ('externallinks', 'vbaproject', 'embeddings', 'media/')))
            # ZipFile verifies CRC and declared size; expansion was bounded first.
            contents[name] = archive.read(entry)
            require(len(contents[name]) == entry.file_size)
        require({'[Content_Types].xml', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels'} <= contents.keys())
        for name, raw in contents.items():
            root = xml(raw)
            require(not any(e.tag.rsplit('}', 1)[-1] in {'f', 'hyperlink', 'externalReference'} for e in root.iter()))
            if name.endswith('.rels'):
                require(all(e.attrib.get('TargetMode') != 'External' for e in root))
        checkpoint('XLSX_RELATIONSHIPS')
        relations = {r.attrib['Id']: r.attrib['Target'] for r in xml(contents['xl/_rels/workbook.xml.rels'])}
        sheets = {}
        text_size = 0
        for sheet in xml(contents['xl/workbook.xml']).findall('s:sheets/s:sheet', NS):
            target = relations[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            target = target.lstrip('/') if target.startswith('/xl/') else 'xl/' + target
            require(re.fullmatch(r'xl/worksheets/sheet[1-9][0-9]*\.xml', target) and target in contents)
            rows = []
            previous_row = 0
            for row in xml(contents[target]).findall('s:sheetData/s:row', NS):
                checkpoint('XLSX_CELLS')
                row_number = int(row.attrib['r'])
                require(row_number > previous_row and row_number <= 30000)
                previous_row = row_number
                cells = []; previous_col = 0
                for cell in row.findall('s:c', NS):
                    coordinate = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]*)', cell.attrib['r'])
                    require(coordinate is not None and int(coordinate[2]) == row_number)
                    col = 0
                    for ch in coordinate[1]:
                        col = col*26+ord(ch)-64
                    require(previous_col < col <= 100)
                    while len(cells) < col-1:
                        cells.append('')
                    previous_col = col
                    kind = cell.attrib.get('t', 'n')
                    require(kind in {'inlineStr', 'n', 'b'})
                    value = ''.join(cell.itertext()) if kind == 'inlineStr' else cell.findtext('s:v', default='', namespaces=NS)
                    require(len(value) <= 30000)
                    text_size += len(value)
                    require(text_size <= MAX_TEXT)
                    cells.append(value)
                rows.append(cells)
            name = sheet.attrib['name']
            require(name not in sheets and len(rows) <= 30000)
            sheets[name] = rows
        require(1 <= len(sheets) <= 20 and 'Об отчёте' in sheets)
        return sheets


def inflate(data, budget):
    dec = zlib.decompressobj()
    output = dec.decompress(data, budget + 1)
    require(len(output) <= budget and dec.eof and not dec.unconsumed_tail and not dec.unused_data)
    return output


def pdf(data):
    """Only traditional xref and ReportLab direct page/font/content objects."""
    checkpoint('PDF_XREF')
    require(data.startswith(b'%PDF-1.') and len(data) <= MAX_BYTES)
    end = re.search(rb'startxref\s+(\d+)\s+%%EOF\s*$', data)
    require(end is not None)
    offset = int(end[1])
    require(0 < offset < len(data) and data[offset:].startswith(b'xref\n'))
    cross = re.match(rb'xref\n0 (\d+)\n((?:\d{10} \d{5} [fn] \r?\n)+)trailer\s*(<<.*?>>)\s*startxref', data[offset:], re.S)
    require(cross is not None)
    size = int(cross[1]); lines = cross[2].splitlines()
    require(4 <= size <= 1500 and len(lines) == size and lines[0] == b'0000000000 65535 f ')
    offsets = [int(line[:10]) for line in lines[1:]]
    require(all(line[11:18] == b'00000 n' for line in lines[1:]) and offsets == sorted(set(offsets)) and offsets[-1] < offset)
    checkpoint('PDF_OBJECTS')
    objects = {}
    for number, begin in enumerate(offsets, 1):
        finish = offsets[number] if number < len(offsets) else offset
        raw = data[begin:finish]
        head = re.match(str(number).encode() + rb' 0 obj\s*', raw)
        require(head is not None and re.search(rb'\s*endobj\s*$', raw))
        objects[number] = re.sub(rb'\s*endobj\s*$', b'', raw[head.end():])
        dictionary = objects[number].split(b'\nstream\n', 1)[0]
        require(not re.search(rb'/(?:OpenAction|AA|JS|JavaScript|Launch|URI|EmbeddedFile|Filespec|Encrypt|CropBox|BleedBox|TrimBox|ArtBox|UserUnit)\b', dictionary))
    require(re.search(rb'/Size\s+' + str(size).encode() + rb'\b', cross[3]) is not None)
    checkpoint('PDF_CATALOG_PAGES')
    root_match = re.search(rb'/Root\s+(\d+) 0 R', cross[3]); require(root_match is not None)
    catalog = objects[int(root_match[1])]
    require(re.fullmatch(rb'<<\s*/PageMode /UseNone\s*/Pages [1-9][0-9]* 0 R\s*/Type /Catalog\s*>>', catalog) is not None)
    pages_ref = re.search(rb'/Pages (\d+) 0 R', catalog); require(pages_ref is not None)
    pages_id = int(pages_ref[1]); tree = objects[pages_id]
    require(re.fullmatch(rb'<<\s*/Count [1-9][0-9]*\s*/Kids\s*\[(?:\s*[1-9][0-9]* 0 R)+\s*\]\s*/Type /Pages\s*>>', tree) is not None)
    count = re.search(rb'/Count (\d+)\b', tree); kids = re.search(rb'/Kids\s*\[([^]]*)\]', tree)
    require(count is not None and kids is not None and b'/Type /Pages' in tree)
    page_ids = [int(v) for v in re.findall(rb'(\d+) 0 R', kids[1])]
    require(1 <= int(count[1]) <= 200 and len(page_ids) == int(count[1]) and len(set(page_ids)) == len(page_ids))
    require(not re.sub(rb'\d+ 0 R|\s+', b'', kids[1]))
    expanded = 0
    cache = {}
    def stream(number):
        nonlocal expanded
        checkpoint('PDF_STREAM')
        if number in cache:
            return cache[number]
        obj = objects[number]
        header, separator, rest = obj.partition(b'\nstream\n')
        require(separator and header.rstrip().endswith(b'>>'))
        length = re.search(rb'/Length (\d+)\s', header); require(length is not None)
        length = int(length[1]); require(length <= MAX_BYTES and rest[length:].strip() == b'endstream')
        payload = rest[:length]
        filters = re.search(rb'/Filter\s*\[\s*([^]]*)\]', header); require(filters is not None)
        filters = filters[1].split()
        require(filters in ([b'/FlateDecode'], [b'/ASCII85Decode', b'/FlateDecode']))
        if filters[0] == b'/ASCII85Decode':
            payload = base64.a85decode(payload, adobe=True)
        payload = inflate(payload, min(MAX_TEXT, MAX_EXPANDED-expanded))
        expanded += len(payload); cache[number] = payload
        require(expanded <= MAX_EXPANDED)
        return payload
    fonts = {}
    def font_map(number):
        checkpoint('PDF_FONT_MAP')
        if number in fonts:
            return fonts[number]
        obj = objects[number]
        match = re.search(rb'/ToUnicode (\d+) 0 R', obj)
        if match:
            cmap = stream(int(match[1]))
            mapping = {}
            for chunk in re.findall(rb'beginbfchar\s*(.*?)\s*endbfchar', cmap, re.S):
                for a, b in re.findall(rb'<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{4,8})>', chunk):
                    key = int(a, 16); require(key not in mapping)
                    mapping[key] = bytes.fromhex(b.decode()).decode('utf-16-be')
            require(1 <= len(mapping) <= 256)
        else:
            require(b'/BaseFont /Helvetica' in obj and b'/Subtype /Type1' in obj)
            mapping = {i: chr(i) for i in range(128)}
        fonts[number] = mapping
        return mapping
    lines = []
    for page_id in page_ids:
        checkpoint('PDF_PAGE_SHAPE')
        page = objects[page_id]
        # Exact producer-owned page/resource shape. New extensions fail closed;
        # no crop, inherited viewport, optional-content or graphics-state seam.
        page_shape = (rb'<<\s*/Contents [1-9][0-9]* 0 R\s*'
            rb'/MediaBox\s*\[\s*0 0 595\.2756 841\.8898\s*\]\s*'
            rb'/Parent [1-9][0-9]* 0 R\s*/Resources\s*<<\s*'
            rb'/Font [1-9][0-9]* 0 R\s*/ProcSet\s*\[ /PDF /Text /ImageB /ImageC /ImageI \]\s*>>\s*'
            rb'/Rotate 0\s*/Trans\s*<<\s*>>\s*/Type /Page\s*>>')
        require(re.fullmatch(page_shape, page) is not None)
        require(re.search(rb'/Type /Page\b', page) and re.search(rb'/Parent ' + str(pages_id).encode() + rb' 0 R', page))
        require(not any(x in page for x in (b'/Annots', b'/AA ', b'/XObject')))
        require(re.search(rb'/Rotate 0\b', page) is not None)
        require(not re.search(rb'/Rotate\s+(?!0\b)', tree))
        box = re.search(rb'/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]', page)
        require(box is not None)
        left, bottom, width, height = (float(v) for v in box.groups())
        require(left == bottom == 0 and abs(width-595.2756) < 0.001 and abs(height-841.8898) < 0.001)
        content = re.search(rb'/Contents (\d+) 0 R', page); font = re.search(rb'/Font (\d+) 0 R', page)
        require(content is not None and font is not None)
        checkpoint('PDF_FONT_RESOURCES')
        resource = objects[int(font[1])]
        require(re.fullmatch(rb'<<\s*(?:/F[0-9]+(?:\+[0-9]+)? [1-9][0-9]* 0 R\s*)+>>', resource) is not None)
        refs = {k.decode(): int(v) for k, v in re.findall(rb'/(F[0-9]+(?:\+[0-9]+)?) (\d+) 0 R', objects[int(font[1])])}
        require(1 <= len(refs) <= 20)
        raw = stream(int(content[1])); current = None; count_text = 0
        checkpoint('PDF_OPERATORS')
        # C5 Canvas emits only these fixed drawing/text operators. Strip literal
        # strings first so harmless source text cannot masquerade as an operator.
        literal_pattern = rb'\((?:[^()\\]|\\(?:[0-7]{1,3}|.|\n))*\)'
        operators = re.sub(literal_pattern, b'', raw, flags=re.S)
        operators = re.sub(rb'/[A-Za-z0-9+]+|[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)|\s+', b' ', operators)
        require(set(operators.split()) <= {b'cm',b'BT',b'ET',b'Tf',b'TL',b'rg',b'RG',b'n',b'm',b'l',b'S',b'Tm',b'Tj',b'T*'})
        # No transparency, clipping, invisible text, external XObjects, arbitrary
        # transforms or rendering-mode switches are in the generated subset.
        transforms = re.findall(rb'([^\n]+) cm', raw)
        require(all(t.strip() == b'1 0 0 1 0 0' for t in transforms))
        checkpoint('PDF_VISIBLE_STYLE')
        # Fixed C5 palette and font sizes; this is generated-subset validation,
        # not a claim that decoded strings alone guarantee visible content.
        number = rb'[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)'
        fills = re.findall(rb'(' + number + rb') (' + number + rb') (' + number + rb') rg', raw)
        require(fills and len(fills) == len(re.findall(rb'\brg\b', raw)))
        require(all(tuple(float(v) for v in fill) in {(0.09,0.29,0.38),(0.08,0.13,0.18)} for fill in fills))
        sizes = re.findall(rb'/F[0-9]+(?:\+[0-9]+)? (' + number + rb') Tf', raw)
        require(sizes and len(sizes) == len(re.findall(rb'\bTf\b', raw)))
        require(all(float(size) in {8,9,10,12,13,18} for size in sizes))
        matrices = re.findall(rb'(' + number + rb') (' + number + rb') (' + number + rb') (' + number + rb') (' + number + rb') (' + number + rb') Tm', raw)
        require(matrices and len(matrices) == len(re.findall(rb'\bTm\b', raw)))
        for matrix in matrices:
            a,b,c,d,x,y = (float(v) for v in matrix)
            require((a,b,c,d) == (1,0,0,1) and 0 <= x < width and 18 <= y < height-18)
        # Actual C5 emits one Tj at an explicit Tm per BT/ET text object.
        # This excludes relative-line movement hiding later accepted strings.
        for block in re.findall(rb'\bBT\b(.*?)\bET\b', raw, re.S):
            if re.search(rb'\bTj\b', block):
                require(len(re.findall(rb'\bTj\b', block)) == 1 and len(re.findall(rb'\bTm\b', block)) == 1)
                require(block.index(b'Tm') < block.index(b'Tj') and not b'T*' in block[:block.index(b'Tj')])
        # Literal-string grammar handles escapes, octal bytes and escaped parens.
        pattern = rb'/(F[0-9]+(?:\+[0-9]+)?) [0-9.]+ Tf|\(((?:[^()\\]|\\(?:[0-7]{1,3}|.|\n))*)\) Tj'
        for token in re.finditer(pattern, raw, re.S):
            if token[1]:
                current = font_map(refs[token[1].decode()]); continue
            checkpoint('PDF_TEXT_DECODE')
            require(current is not None)
            literal = token[2]
            def unescape(m):
                value = m[1]
                if re.fullmatch(rb'[0-7]{1,3}', value):
                    return bytes([int(value, 8)])
                return {b'n':b'\n', b'r':b'\r', b't':b'\t', b'b':b'\b', b'f':b'\f', b'\n':b''}.get(value, value)
            literal = re.sub(rb'\\([0-7]{1,3}|.|\n)', unescape, literal, flags=re.S)
            require(all(ch in current for ch in literal))
            lines.append(''.join(current[ch] for ch in literal)); count_text += 1
        require(count_text > 0 and len(re.findall(rb'\bTj\b', raw)) == count_text and not re.search(rb'\b(TJ|Do)\b', raw))
        require(sum(len(line) for line in lines) <= MAX_TEXT)
    return lines, len(page_ids)


def validate_expected(e):
    checkpoint('EXPECTED_CONTRACT')
    require(set(e) == {'kind','order_id','order_number','period','historical_counts'})
    require(e['kind'] in {'shift','order'} and e['period'] == {'start':'2026-07-01T00:00:00Z','end':'2026-10-01T00:00:00Z'})
    if e['kind'] == 'order':
        require(re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', e['order_id']))
        require(isinstance(e['order_number'], str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', e['order_number']))
        require(e['historical_counts'][0] == 1 and e['historical_counts'][1] in {1,2} and e['historical_counts'][2:] == [e['historical_counts'][1]]*2)
    else:
        require(e['order_id'] is None and e['order_number'] is None and e['historical_counts'] == [540,568,444,444])


def inspect(data, fmt, expected):
    validate_expected(expected)
    checkpoint('FILE_BOUND')
    require(0 < len(data) <= MAX_BYTES and fmt in {'pdf','xlsx'})
    title = 'Отчёт смены' if expected['kind'] == 'shift' else 'Наряд ' + expected['order_number']
    labels = ['Исторических нарядов','Исторических попыток','Исторических ссылок на фото','Отсутствующих записей фото']
    if fmt == 'pdf':
        lines, units = pdf(data)
        checkpoint('PDF_CONTENT')
        text = '\n'.join(lines)
        require(title in lines and 'СИНТЕТИЧЕСКИЕ ДАННЫЕ' in text and 'Asia/Almaty (UTC+05:00)' in text)
        require('Начало периода, включено: 01.07.2026 05:00:00 +0500' in text and 'Конец периода, исключён: 01.10.2026 05:00:00 +0500' in text)
        require(all(f'{label}: {count}' in lines for label,count in zip(labels,expected['historical_counts'])))
        require('НЕТ ПРОВЕРЕННЫХ ИЗОБРАЖЕНИЙ.' in text)
        if expected['kind'] == 'order':
            require('ID наряда: ' + expected['order_id'] in lines and 'Номер: ' + expected['order_number'] in lines)
        else:
            require('issued_orders' in text and 'Значение точно: 540' in lines)
    else:
        sheets = xlsx(data); units = len(sheets)
        checkpoint('XLSX_CONTENT')
        meta = {r[0]:r[1] for r in sheets['Об отчёте'] if len(r)==2}
        require(meta.get('Отчёт') == title and meta.get('Режим') == 'СИНТЕТИЧЕСКИЕ ДАННЫЕ' and meta.get('Часовой пояс всех дат') == 'Asia/Almaty (UTC+05:00)')
        for label, stamp in [('Начало периода, включено','2026-07-01T05:00:00'),('Конец периода, исключён','2026-10-01T05:00:00')]:
            actual = datetime(1899,12,30)+timedelta(days=float(meta[label]))
            require(abs((actual-datetime.fromisoformat(stamp)).total_seconds()) < 0.001)
        require(all(meta.get(label) == str(count) for label,count in zip(labels,expected['historical_counts'])))
        require('НЕТ ПРОВЕРЕННЫХ ИЗОБРАЖЕНИЙ.' in meta.get('Исторические фото',''))
        if expected['kind'] == 'order':
            fields = {r[0]:r[1] for r in sheets['Наряд'] if len(r)==2}
            require(fields.get('ID наряда') == expected['order_id'] and fields.get('Номер') == expected['order_number'])
        else:
            require(any(len(row)>5 and row[0]=='Смена' and row[1]=='issued_orders' and row[5]=='540' for row in sheets['Показатели']))
    checkpoint('RESULT')
    return {'validator':'c113-generated-subset-v1','format':fmt,'bytes':len(data),'sha256':sha256(data).hexdigest(),
            'units':units,'signature_valid':True,'content_valid':True,'synthetic_disclosure':True,
            'period_matches':True,'scope_matches':True,'historical_disclosure':True,'bounded_structure':True,
            'expected_sha256':sha256(json.dumps(expected,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}


def main():
    try:
        require(len(sys.argv)==4)
        checkpoint('READ_EXPECTED_FILE');raw = bounded_file(sys.argv[3],4096)
        checkpoint('PARSE_EXPECTED_JSON');expected = json.loads(raw)
        checkpoint('READ_SAVED_FILE');data = bounded_file(sys.argv[1],MAX_BYTES)
        result = inspect(data,sys.argv[2],expected)
        print(json.dumps(result,sort_keys=True)); return 0
    except Exception:
        print(json.dumps({'status':'BLOCKED','code':'C113_DOWNLOAD_INSPECTION_FAILED','stage':_stage})); return 2


if __name__=='__main__':
    sys.exit(main())
