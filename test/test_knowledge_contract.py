"""Business validation and FastAPI input validation share an accurate 422 contract."""
import company_knowledge as kb
from test_company_workspace import setup, project


def test_422_contract_accepts_both_business_and_request_validation(setup):
    directory=project(setup,'接口约定验收')
    business=setup.client.post('/company-knowledge/projects/'+directory['id']+'/folders',json={'name':'..'})
    validation=setup.client.post('/company-knowledge/projects',json={'name':''})
    assert business.status_code==validation.status_code==422
    assert isinstance(business.json()['detail'],str)
    assert isinstance(validation.json()['detail'],list)
    for response in (business,validation):kb.KnowledgeValidationError.model_validate(response.json())
    schema=setup.client.app.openapi()
    for path,method in [('/company-knowledge/projects','post'),('/company-knowledge/projects/{project_id}/folders','post')]:
        response=schema['paths'][path][method]['responses']['422']
        assert response['content']['application/json']['schema']['$ref'].endswith('/KnowledgeValidationError')
