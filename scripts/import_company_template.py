"""Refresh company prompt text from XLSX without changing the workbook.

Usage: python scripts/import_company_template.py TEMPLATE.xlsx --check
       python scripts/import_company_template.py TEMPLATE.xlsx --write
Questions, adapters and subsection rules remain explicit reviewed configuration.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / 'backend/company_chapters.json'


def company_cells(path):
    with zipfile.ZipFile(path) as archive:
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        sheet = next(s for s in book.find('m:sheets', NS)
                     if s.attrib['name'] == '目标公司桌面研究')
        relationship = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
        rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        target = next(r.attrib['Target'] for r in rels if r.attrib['Id'] == relationship)
        member = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(node.itertext()) for node in
                      ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si', NS)]
        result = {}
        for cell in ET.fromstring(archive.read(member)).findall('.//m:sheetData/m:row/m:c', NS):
            value = cell.find('m:v', NS)
            if cell.attrib.get('t') == 's':
                text = shared[int(value.text)] if value is not None else ''
            elif cell.attrib.get('t') == 'inlineStr':
                text = ''.join(cell.find('m:is', NS).itertext())
            else:
                text = value.text if value is not None else ''
            if text:
                result[cell.attrib['r']] = text
        return result


def refresh(path, registry):
    cells = company_cells(path)
    starts = []
    for ref, text in cells.items():
        match = re.match(r'^\s*(\d+)[.、．]\s*(.+)', text, re.S)
        if ref.startswith('A') and match:
            starts.append((int(match[1]), int(ref[1:]), match[2].strip().replace('\n', '')))
    starts.sort()
    if [n for n, _, _ in starts] != list(range(1, 15)):
        raise ValueError('Expected exactly fourteen numbered company chapters.')
    updated = deepcopy(registry)
    for offset, (number, row, title) in enumerate(starts):
        c = updated['chapters'][offset]
        if c['chapter'] != number:
            raise ValueError('Registry chapter order mismatch.')
        end = starts[offset + 1][1] if offset < 13 else row + 1
        descriptions = [f'B{r}' for r in range(row, end) if cells.get(f'B{r}')]
        examples = [f'C{r}' for r in range(row, end) if cells.get(f'C{r}')]
        if not descriptions or len(examples) > 1:
            raise ValueError(f'Chapter {number}: inspect missing requirements or multiple examples before import.')
        raw = cells[examples[0]] if examples else ''
        c.update(title=title, description='\n'.join(cells[r] for r in descriptions),
                 source_cells={'sheet': '目标公司桌面研究', 'title': f'A{row}',
                               'description': descriptions, 'example': examples[0] if examples else None},
                 few_shot={'status': 'quarantined' if number == 7 and raw else 'active' if raw else 'absent',
                           'text': raw, 'reason': '原表C16为供应商采购和经销主题，与管理团队标题不符。' if number == 7 else ''})
    updated['source'] = {'file': Path(path).name, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                         'sheet': '目标公司桌面研究'}
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workbook', type=Path)
    parser.add_argument('--registry', type=Path, default=DEFAULT_REGISTRY)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--write', action='store_true')
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding='utf-8'))
    updated = refresh(args.workbook, registry)
    if args.check and updated != registry:
        raise SystemExit('Template differs from registry; review and import the changes.')
    if args.write:
        args.registry.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Company template: 14 chapters checked; workbook unchanged.')


if __name__ == '__main__':
    main()
