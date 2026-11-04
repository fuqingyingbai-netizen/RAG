import io

import pytest
from fastapi import HTTPException
from PIL import Image
from reportlab.pdfgen import canvas

import company_knowledge as kb
import company_discovery as discovery
from company_catalog import CompanyDocument
from test_company_workspace import setup, upload, stored_original


def ready(setup, title='original.txt', category='项目原件'):
    row = upload(setup, name=title, category=category).json()
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        doc.state, doc.cloud_id = 'ready', 'cloud-' + doc.id
        db.commit()
    return row['id'], 'cloud-' + row['id']


def test_content_search_has_scoped_filters_and_rejects_foreign_results(setup, monkeypatch):
    local, cloud = ready(setup)
    experience, experience_cloud = ready(setup, 'experience.txt', '项目经验')
    calls = []
    async def rpc(client, cfg, path, body):
        calls.append(body)
        return {'nodes': [
            {'score': 5, 'metadata': {'doc_id': experience_cloud, 'content': 'secret other collection'}},
            {'score': 4, 'metadata': {'doc_id': cloud, 'pipeline_id': 'another-index', 'content': 'foreign index'}},
            {'score': 3, 'metadata': {'doc_id': cloud, 'content': 'inside text only', 'page_number': [2]}},
            {'score': 2, 'metadata': {'doc_id': cloud, 'content': 'inside text only', 'page_number': [2]}},
        ]}
    monkeypatch.setattr(kb, 'cloud_rpc', rpc)
    response = setup.client.post('/company-knowledge/search', json={'query': 'inside text', 'scope': 'accessible'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['total'] == 1 and result['matches'][0]['reference']['pages'] == [2]
    assert result['matches'][0]['document']['id'] == local
    assert calls[0]['search_filters'] == [{'doc_id': [cloud]}]
    assert 'secret' not in response.text and 'foreign index' not in response.text
    assert setup.client.post('/company-knowledge/search', json={'query': 'text', 'document_ids': [experience]}).status_code == 403
    count = len(calls)
    assert setup.client.post('/company-knowledge/search', json={'query': 'text', 'document_ids': []}).json()['total'] == 0
    assert len(calls) == count


def test_search_rechecks_revoked_permissions_after_upstream_await(setup, monkeypatch):
    local, cloud = ready(setup)
    with setup.db() as db:
        doc = db.get(CompanyDocument, local)
        doc.owner, doc.owner_user_id = 'bob', 2
        db.commit()
    async def rpc(*args, **kwargs):
        with setup.db() as db:
            doc = db.get(CompanyDocument, local)
            doc.visibility, doc.readers = 'restricted', []
            db.commit()
        return {'nodes': [{'metadata': {'doc_id': cloud, 'content': 'revoked text'}}]}
    monkeypatch.setattr(kb, 'cloud_rpc', rpc)
    response = setup.client.post('/company-knowledge/search', json={'query': 'revoked'})
    assert response.status_code == 200 and response.json()['total'] == 0
    assert 'revoked text' not in response.text


def test_search_paginates_deduplicated_body_snippets(setup, monkeypatch):
    _, cloud = ready(setup)
    async def rpc(*args, **kwargs):
        return {'nodes': [{'score': 30-i, 'metadata': {'doc_id': cloud, 'content': 'paragraph '+str(i)}} for i in range(25)]}
    monkeypatch.setattr(kb, 'cloud_rpc', rpc)
    response = setup.client.post('/company-knowledge/search', json={'query': 'paragraph', 'page': 2, 'page_size': 10}).json()
    assert response['total'] == 25 and len(response['matches']) == 10
    assert response['matches'][0]['reference']['text'] == 'paragraph 10'


def test_thumbnail_is_personalized_and_preserves_original(setup):
    output = io.BytesIO()
    Image.new('RGB', (1000, 800), '#b8d6de').save(output, 'PNG')
    original = output.getvalue()
    row = upload(setup, original, 'photo.png', category='现场照片').json()
    response = setup.client.get('/company-knowledge/documents/'+row['id']+'/thumbnail')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    image = Image.open(io.BytesIO(response.content))
    assert image.width <= 720 and image.height <= 480
    assert response.content != original and stored_original(setup, row['id']) == original
    setup.user.username, setup.user.id = 'bob', 2
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        doc.visibility, doc.readers = 'restricted', []
        db.commit()
    assert setup.client.get('/company-knowledge/documents/'+row['id']+'/thumbnail').status_code == 404


def pdf_bytes():
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(40, 700, 'First page only')
    pdf.showPage()
    pdf.drawString(40, 700, 'Evidence on the second page')
    pdf.save()
    return output.getvalue()


def test_source_locator_finds_actual_page_and_normalized_highlight():
    result = discovery.locate_pdf(pdf_bytes(), discovery.SourceLocation(text='Evidence on the second page', pages=[1]))
    assert result['matched'] and result['page'] == 2
    assert result['rectangles']
    for rect in result['rectangles']:
        assert all(0 <= coordinate <= 1 for coordinate in rect.values())
    result = discovery.locate_pdf(pdf_bytes(), discovery.SourceLocation(text='No actual source match', pages=[1]))
    assert not result['matched'] and result['page'] == 1 and result['rectangles'] == []


def test_locate_endpoint_does_not_disclose_locked_source(setup):
    row = upload(setup, pdf_bytes(), 'evidence.pdf').json()
    assert setup.client.post('/company-knowledge/documents/'+row['id']+'/locate', json={'text': 'Evidence on the second page'}).json()['page'] == 2
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        doc.visibility, doc.readers = 'restricted', []
        db.commit()
    setup.user.username, setup.user.id = 'bob', 2
    assert setup.client.post('/company-knowledge/documents/'+row['id']+'/locate', json={'text': 'Evidence'}).status_code == 404


def test_office_reading_page_uses_authenticated_marked_derivative(setup, monkeypatch):
    row = upload(setup).json()
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        doc.format = 'XLSX'
        db.commit()
    monkeypatch.setattr(discovery, 'reading_pdf', lambda doc: pdf_bytes())
    response = setup.client.get('/company-knowledge/documents/'+row['id']+'/page?page=2')
    assert response.status_code == 200 and response.headers['x-document-pages'] == '2'
    assert response.headers['content-type'] == 'image/png'

def test_pdf_outline_uses_original_bookmarks():
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(40, 700, 'First page')
    pdf.showPage()
    pdf.bookmarkPage('evidence')
    pdf.addOutlineEntry('Evidence chapter', 'evidence')
    pdf.drawString(40, 700, 'Second page')
    pdf.save()
    assert discovery.pdf_outline(output.getvalue()) == [{'title': 'Evidence chapter', 'page': 2}]
