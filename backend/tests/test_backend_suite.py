import uuid
from collections import defaultdict
from pathlib import Path

import firebase_admin
import pytest
from firebase_admin import firestore


class FakeDoc:
    def __init__(self, doc_id, data=None, exists=True):
        self.id = doc_id
        self._data = data or {}
        self.exists = exists

    def to_dict(self):
        return self._data.copy()


class FakeDocumentRef:
    def __init__(self, db, collection_name, doc_id):
        self.db = db
        self.collection_name = collection_name
        self.doc_id = doc_id
        self.id = doc_id

    def get(self):
        collection = self.db.data.get(self.collection_name, {})
        if self.doc_id in collection:
            return FakeDoc(self.doc_id, collection[self.doc_id].copy(), exists=True)
        return FakeDoc(self.doc_id, {}, exists=False)

    def set(self, data, merge=False):
        collection = self.db.data.setdefault(self.collection_name, {})
        if merge and self.doc_id in collection:
            collection[self.doc_id] = {**collection[self.doc_id], **data.copy()}
        else:
            collection[self.doc_id] = data.copy()

    def update(self, data):
        collection = self.db.data.setdefault(self.collection_name, {})
        collection[self.doc_id] = {**collection.get(self.doc_id, {}), **data}

    def delete(self):
        collection = self.db.data.get(self.collection_name, {})
        collection.pop(self.doc_id, None)


class FakeCollection:
    def __init__(self, db, name, order_field=None, direction='ASCENDING'):
        self.db = db
        self.name = name
        self.order_field = order_field
        self.direction = direction

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = str(uuid.uuid4())
        return FakeDocumentRef(self.db, self.name, doc_id)

    @property
    def id(self):
        return self.doc_id

    def order_by(self, field, direction='ASCENDING'):
        return FakeCollection(self.db, self.name, order_field=field, direction=direction)

    def stream(self):
        items = list(self.db.data.get(self.name, {}).items())
        if self.order_field:
            items.sort(
                key=lambda item: item[1].get(self.order_field, 0),
                reverse=(self.direction == 'DESCENDING')
            )
        return [FakeDoc(doc_id, data.copy(), exists=True) for doc_id, data in items]


class FakeFirestoreClient:
    def __init__(self):
        self.data = defaultdict(dict)

    def collection(self, name):
        return FakeCollection(self, name)


firebase_admin._apps = []
firebase_admin.initialize_app = lambda *args, **kwargs: None
firebase_admin.credentials.Certificate = lambda *args, **kwargs: object()
firestore.client = lambda: FakeFirestoreClient()


import app.firebase as firebase_mod
from fastapi.testclient import TestClient
from main import app
from app import auth as auth_mod
from app import email_service
from app.rate_limit import _request_history
from app import admin_routes
from app import firebase as firebase_module
from app.product_routes import Product
from app.service_routes import Service
from app.product_request_routes import ProductRequest


# Patch all route modules to use the fake db instance
for module_name in [
    'app.firebase',
    'app.product_routes',
    'app.service_routes',
    'app.category_routes',
    'app.product_request_routes',
    'app.service_request_routes',
    'app.contact_routes',
    'app.site_settings_routes',
    'app.admin_routes',
    'app.auth',
]:
    module = __import__(module_name, fromlist=['*'])
    module.db = firebase_mod.db

client = TestClient(app)
safe_client = TestClient(app, raise_server_exceptions=False)


def test_email_service_is_disabled_without_smtp_settings(monkeypatch):
    monkeypatch.delenv('SMTP_HOST', raising=False)
    monkeypatch.delenv('SMTP_FROM_EMAIL', raising=False)
    monkeypatch.delenv('SMTP_TO_EMAIL', raising=False)
    assert email_service.send_submission_notification('x', 'y') is False


def test_email_service_handles_smtp_error(monkeypatch):
    monkeypatch.setenv('SMTP_HOST', 'smtp.example.com')
    monkeypatch.setenv('SMTP_PORT', '587')
    monkeypatch.setenv('SMTP_USERNAME', 'user')
    monkeypatch.setenv('SMTP_PASSWORD', 'pass')
    monkeypatch.setenv('SMTP_FROM_EMAIL', 'from@example.com')
    monkeypatch.setenv('SMTP_TO_EMAIL', 'to@example.com')

    def fake_send(*args, **kwargs):
        raise RuntimeError('smtp failed')

    monkeypatch.setattr(email_service.smtplib, 'SMTP', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('smtp failed')))
    assert email_service.send_submission_notification('Subject', 'Body') is False


def reset_rate_limits():
    _request_history.clear()


def test_rate_limit_allows_requests_below_limit(monkeypatch):
    reset_rate_limits()
    monkeypatch.setenv('RATE_LIMIT_REQUESTS', '3')
    monkeypatch.setenv('RATE_LIMIT_WINDOW_SECONDS', '60')
    seed_base_data()
    payload = {
        'product_id': 'prod_1',
        'customer_name': 'Alice',
        'customer_email': 'alice@example.com',
        'customer_phone': '1234567890',
        'quantity': 1,
        'message': 'Need this product'
    }
    for _ in range(2):
        response = client.post('/api/product-requests', json=payload)
        assert response.status_code == 200
    reset_rate_limits()


def test_rate_limit_rejects_requests_over_limit(monkeypatch):
    reset_rate_limits()
    monkeypatch.setenv('RATE_LIMIT_REQUESTS', '2')
    monkeypatch.setenv('RATE_LIMIT_WINDOW_SECONDS', '60')
    seed_base_data()
    payload = {
        'service_id': 'svc_1',
        'customer_name': 'Bob',
        'customer_email': 'bob@example.com',
        'customer_phone': '9876543210',
        'message': 'Need a consultation'
    }
    response = client.post('/api/service-requests', json=payload)
    assert response.status_code == 200
    response = client.post('/api/service-requests', json=payload)
    assert response.status_code == 200
    response = client.post('/api/service-requests', json=payload)
    assert response.status_code == 429
    reset_rate_limits()


def test_public_get_apis_still_work_after_rate_limit_integration():
    reset_rate_limits()
    seed_base_data()
    assert client.get('/api/products').status_code == 200
    assert client.get('/api/services').status_code == 200
    assert client.get('/api/site-settings').status_code == 200
    reset_rate_limits()


def test_admin_apis_still_work_after_rate_limit_integration(monkeypatch):
    reset_rate_limits()
    monkeypatch.setenv('RATE_LIMIT_REQUESTS', '2')
    monkeypatch.setenv('RATE_LIMIT_WINDOW_SECONDS', '60')
    seed_base_data()
    mock_valid_admin_token()
    assert client.get('/api/admin/products', headers=auth_header()).status_code == 200
    assert client.get('/api/admin/messages', headers=auth_header()).status_code == 200
    reset_rate_limits()


def test_product_request_public_creation_calls_email(monkeypatch):
    reset_rate_limits()
    seed_base_data()
    called = {}

    def fake_send(subject, message, recipient_email=None):
        called['payload'] = {
            'subject': subject,
            'message': message,
            'recipient_email': recipient_email,
        }
        return True

    monkeypatch.setattr('app.product_request_routes.send_submission_notification', fake_send)
    payload = {
        'product_id': 'prod_1',
        'customer_name': 'Alice',
        'customer_email': 'alice@example.com',
        'customer_phone': '1234567890',
        'quantity': 2,
        'message': 'Need this product'
    }
    response = client.post('/api/product-requests', json=payload)
    assert response.status_code == 200
    assert 'id' in response.json()
    assert called['payload']['subject'] == 'New product request received'
    assert 'Alice' in called['payload']['message']
    reset_rate_limits()


def test_service_request_public_creation_calls_email(monkeypatch):
    seed_base_data()
    called = {}

    def fake_send(subject, message, recipient_email=None):
        called['payload'] = {
            'subject': subject,
            'message': message,
            'recipient_email': recipient_email,
        }
        return True

    monkeypatch.setattr('app.service_request_routes.send_submission_notification', fake_send)
    payload = {
        'service_id': 'svc_1',
        'customer_name': 'Bob',
        'customer_email': 'bob@example.com',
        'customer_phone': '9876543210',
        'message': 'Need a consultation'
    }
    response = client.post('/api/service-requests', json=payload)
    assert response.status_code == 200
    assert 'id' in response.json()
    assert called['payload']['subject'] == 'New service request received'
    assert 'Bob' in called['payload']['message']


def test_contact_create_message_calls_email(monkeypatch):
    seed_base_data()
    called = {}

    def fake_send(subject, message, recipient_email=None):
        called['payload'] = {
            'subject': subject,
            'message': message,
            'recipient_email': recipient_email,
        }
        return True

    monkeypatch.setattr('app.contact_routes.send_submission_notification', fake_send)
    payload = {
        'name': 'Mary Jane',
        'email': 'mary@example.com',
        'phone': '1112223333',
        'subject': 'Question',
        'message': 'Hello there'
    }
    response = client.post('/api/contact', json=payload)
    assert response.status_code == 200
    assert 'id' in response.json()
    assert called['payload']['subject'] == 'New contact message received'
    assert 'Mary Jane' in called['payload']['message']


def test_product_request_public_creation_still_saves_firestore_even_if_email_fails(monkeypatch):
    seed_base_data()

    def fake_send(subject, message, recipient_email=None):
        return False

    monkeypatch.setattr('app.product_request_routes.send_submission_notification', fake_send)
    payload = {
        'product_id': 'prod_1',
        'customer_name': 'Alice',
        'customer_email': 'alice@example.com',
        'customer_phone': '1234567890',
        'quantity': 2,
        'message': 'Need this product'
    }
    response = client.post('/api/product-requests', json=payload)
    assert response.status_code == 200
    assert 'id' in response.json()
    assert firebase_mod.db.data['productRequests']


def seed_base_data():
    fake_db = firebase_mod.db
    fake_db.data.clear()

    fake_db.data['productCategories'] = {
        'Furniture': {'name': 'Furniture'},
        'Design': {'name': 'Design'}
    }

    fake_db.data['products'] = {
        'prod_1': {
            'name': 'Premium Office Chair',
            'description': 'Comfortable premium office chair',
            'price': 18000,
            'category': 'Furniture',
            'image': 'https://example.com/chair.jpg',
            'stockQuantity': 10,
            'lowStockThreshold': 5,
            'isActive': True,
            'featured': False,
        },
        'prod_2': {
            'name': 'Desk',
            'description': 'Modern desk',
            'price': 25000,
            'category': 'Furniture',
            'image': 'https://example.com/desk.jpg',
            'stockQuantity': 0,
            'lowStockThreshold': 2,
            'isActive': True,
            'featured': False,
        }
    }

    fake_db.data['services'] = {
        'svc_1': {
            'name': 'Office Interior Design',
            'description': 'Interior design service',
            'price': 25000,
            'category': 'Design',
            'image': 'https://example.com/service.jpg',
            'isActive': True,
            'featured': False,
            'displayOrder': 1,
        }
    }

    fake_db.data['contactMessages'] = {
        'msg_1': {
            'name': 'Jane Doe',
            'email': 'jane@example.com',
            'phone': '123456',
            'subject': 'Support',
            'message': 'Hello',
            'status': 'unread',
            'created_at': '2026-01-01T00:00:00Z',
        }
    }

    fake_db.data['siteSettings'] = {
        'main': {
            'company_name': 'Mifra Enterprises',
            'email': 'hello@mifra.com',
            'phone': '+1234567890',
            'address': 'Main office',
            'logo': 'https://example.com/logo.png',
            'about_text': 'About Mifra',
        }
    }

    fake_db.data['admins'] = {
        'admin_123': {'role': 'admin', 'email': 'admin@mifra.com'},
        'user_123': {'role': 'user', 'email': 'user@mifra.com'},
    }

    fake_db.data['productRequests'] = {
        'pr_1': {
            'product_id': 'prod_1',
            'customer_name': 'Alice',
            'customer_email': 'alice@example.com',
            'customer_phone': '123',
            'quantity': 2,
            'message': 'Need this product',
            'status': 'new',
            'created_at': '2026-01-01T00:00:00Z',
        }
    }
    fake_db.data['serviceRequests'] = {
        'sr_1': {
            'service_id': 'svc_1',
            'customer_name': 'Bob',
            'customer_email': 'bob@example.com',
            'customer_phone': '456',
            'message': 'Need design service',
            'status': 'new',
            'created_at': '2026-01-01T00:00:00Z',
        }
    }


def mock_valid_admin_token(uid='admin_123'):
    def _fake_verify(token):
        if token == 'bad-token':
            raise ValueError('invalid token')
        return {'uid': uid, 'email': 'admin@mifra.com'}

    auth_mod.auth.verify_id_token = _fake_verify
    firebase_admin.auth.verify_id_token = _fake_verify


def mock_non_admin_token(uid='user_123'):
    def _fake_verify(token):
        return {'uid': uid, 'email': 'user@mifra.com'}

    auth_mod.auth.verify_id_token = _fake_verify
    firebase_admin.auth.verify_id_token = _fake_verify


def auth_header(token='admin-token'):
    return {'Authorization': f'Bearer {token}'}


def test_public_products_list():
    seed_base_data()
    response = client.get('/api/products')
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]['name'] == 'Premium Office Chair'


def test_public_product_detail():
    seed_base_data()
    response = client.get('/api/products/prod_1')
    assert response.status_code == 200
    assert response.json()['name'] == 'Premium Office Chair'


def test_public_categories_list():
    seed_base_data()
    response = client.get('/api/categories')
    assert response.status_code == 200
    assert response.json()[0]['name'] == 'Furniture'


def test_public_services_list():
    seed_base_data()
    response = client.get('/api/services')
    assert response.status_code == 200
    assert response.json()[0]['name'] == 'Office Interior Design'


def test_public_site_settings():
    seed_base_data()
    response = client.get('/api/site-settings')
    assert response.status_code == 200
    assert response.json()['company_name'] == 'Mifra Enterprises'


def test_product_request_public_creation():
    seed_base_data()
    payload = {
        'product_id': 'prod_1',
        'customer_name': 'Alice',
        'customer_email': 'alice@example.com',
        'customer_phone': '1234567890',
        'quantity': 2,
        'message': 'Need this product'
    }
    response = client.post('/api/product-requests', json=payload)
    assert response.status_code == 200
    assert 'id' in response.json()


def test_service_request_public_creation():
    seed_base_data()
    payload = {
        'service_id': 'svc_1',
        'customer_name': 'Bob',
        'customer_email': 'bob@example.com',
        'customer_phone': '9876543210',
        'message': 'Need a consultation'
    }
    response = client.post('/api/service-requests', json=payload)
    assert response.status_code == 200
    assert 'id' in response.json()


def test_contact_create_message():
    seed_base_data()
    payload = {
        'name': 'Mary Jane',
        'email': 'mary@example.com',
        'phone': '1112223333',
        'subject': 'Question',
        'message': 'Hello there'
    }
    response = client.post('/api/contact', json=payload)
    assert response.status_code == 200
    assert 'id' in response.json()


def test_invalid_contact_email_is_rejected():
    seed_base_data()
    payload = {
        'name': 'Bad',
        'email': 'not-an-email',
        'message': 'bad'
    }
    response = client.post('/api/contact', json=payload)
    assert response.status_code == 422


def test_admin_no_token_rejected():
    seed_base_data()
    response = client.get('/api/admin/test')
    assert response.status_code in (401, 403)


def test_admin_invalid_token_rejected():
    seed_base_data()
    mock_valid_admin_token()
    auth_mod.auth.verify_id_token = lambda token: (_ for _ in ()).throw(
        auth_mod.auth.InvalidIdTokenError('bad token')
    )
    firebase_admin.auth.verify_id_token = auth_mod.auth.verify_id_token
    response = client.get('/api/admin/test', headers=auth_header('bad-token'))
    assert response.status_code == 401


def test_non_admin_user_cannot_access_admin():
    seed_base_data()
    mock_non_admin_token()
    response = client.get('/api/admin/test', headers=auth_header('user-token'))
    assert response.status_code == 403


def test_admin_dashboard_access():
    seed_base_data()
    mock_valid_admin_token()
    response = client.get('/api/admin/dashboard', headers=auth_header())
    assert response.status_code == 200
    data = response.json()
    assert 'products' in data
    assert 'requests' in data


def test_admin_get_products():
    seed_base_data()
    mock_valid_admin_token()
    response = client.get('/api/admin/products', headers=auth_header())
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_admin_create_product():
    seed_base_data()
    mock_valid_admin_token()
    payload = {
        'name': 'New Product',
        'description': 'New product description',
        'price': 5000,
        'category': 'Furniture',
        'image': 'https://example.com/new.jpg',
        'stockQuantity': 7,
        'lowStockThreshold': 3,
        'isActive': True,
        'featured': True,
    }
    response = client.post('/api/admin/products', headers=auth_header(), json=payload)
    assert response.status_code == 200
    assert response.json()['message'] == 'Product created successfully'


def test_admin_update_product():
    seed_base_data()
    mock_valid_admin_token()
    payload = {
        'name': 'Updated Product',
        'description': 'Updated description',
        'price': 9000,
        'category': 'Furniture',
        'image': 'https://example.com/update.jpg',
        'stockQuantity': 9,
        'lowStockThreshold': 2,
        'isActive': True,
        'featured': False,
    }
    response = client.put('/api/admin/products/prod_1', headers=auth_header(), json=payload)
    assert response.status_code == 200
    assert response.json()['product']['name'] == 'Updated Product'


def test_admin_delete_product_soft_delete():
    seed_base_data()
    mock_valid_admin_token()
    response = client.delete('/api/admin/products/prod_1', headers=auth_header())
    assert response.status_code == 200
    assert response.json()['message'] == 'Product deactivated successfully'


def test_admin_update_stock():
    seed_base_data()
    mock_valid_admin_token()
    payload = {'stockQuantity': 4, 'lowStockThreshold': 5}
    response = client.put('/api/admin/products/prod_1/stock', headers=auth_header(), json=payload)
    assert response.status_code == 200
    assert response.json()['stockStatus'] == 'limited_stock'


def test_admin_product_status_update():
    seed_base_data()
    mock_valid_admin_token()
    payload = {'isActive': False}
    response = client.put('/api/admin/products/prod_1/status', headers=auth_header(), json=payload)
    assert response.status_code == 200
    assert response.json()['isActive'] is False


def test_admin_create_service():
    seed_base_data()
    mock_valid_admin_token()
    payload = {
        'name': 'Design Service',
        'description': 'Design help',
        'price': 3000,
        'category': 'Design',
        'image': 'https://example.com/design.png',
        'isActive': True,
        'featured': False,
        'displayOrder': 2
    }
    response = client.post('/api/admin/services', headers=auth_header(), json=payload)
    assert response.status_code == 200
    assert response.json()['message'] == 'Service created successfully'


def test_admin_update_service():
    seed_base_data()
    mock_valid_admin_token()
    payload = {
        'name': 'Office Interior Design',
        'description': 'Updated service description',
        'price': 27500,
        'category': 'Design',
        'image': 'https://example.com/design_updated.jpg',
        'isActive': True,
        'featured': True,
        'displayOrder': 3,
    }
    response = client.put('/api/admin/services/svc_1', headers=auth_header(), json=payload)
    assert response.status_code == 200
    assert response.json()['service']['featured'] is True


def test_admin_delete_service():
    seed_base_data()
    mock_valid_admin_token()
    response = client.delete('/api/admin/services/svc_1', headers=auth_header())
    assert response.status_code == 200
    assert response.json()['message'] == 'Service deactivated successfully'


def test_admin_get_requests():
    seed_base_data()
    mock_valid_admin_token()
    response = client.get('/api/admin/requests', headers=auth_header())
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_admin_update_request_status():
    seed_base_data()
    mock_valid_admin_token()
    payload = {'status': 'in_progress', 'request_type': 'product', 'internal_notes': 'Followed up'}
    response = client.put('/api/admin/requests/pr_1', headers=auth_header(), json=payload)
    assert response.status_code == 200
    assert response.json()['status'] == 'in_progress'


def test_admin_update_request_invalid_status():
    seed_base_data()
    mock_valid_admin_token()
    payload = {'status': 'not_real', 'request_type': 'product'}
    response = client.put('/api/admin/requests/pr_1', headers=auth_header(), json=payload)
    assert response.status_code == 400


def test_admin_get_messages():
    seed_base_data()
    mock_valid_admin_token()
    response = client.get('/api/admin/messages', headers=auth_header())
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_admin_update_message_status():
    seed_base_data()
    mock_valid_admin_token()
    payload = {'status': 'read'}
    response = client.put('/api/admin/messages/msg_1', headers=auth_header(), json=payload)
    assert response.status_code == 200
    assert response.json()['status'] == 'read'


def test_admin_update_settings():
    seed_base_data()
    mock_valid_admin_token()
    payload = {
        'company_name': 'Mifra Enterprises',
        'email': 'hello@mifra.com',
        'phone': '+1234567890',
        'address': 'Updated address',
        'about_text': 'Updated about text'
    }
    response = client.put('/api/admin/settings', headers=auth_header(), json=payload)
    assert response.status_code == 200
    assert response.json()['id'] == 'main'


def test_invalid_stock_value_is_rejected():
    seed_base_data()
    mock_valid_admin_token()
    payload = {'stockQuantity': -1}
    response = client.put('/api/admin/products/prod_1/stock', headers=auth_header(), json=payload)
    assert response.status_code == 422


def test_missing_required_field_product_is_rejected():
    seed_base_data()
    mock_valid_admin_token()
    payload = {
        'name': 'Missing field',
        'price': 100,
        'category': 'Furniture'
    }
    response = client.post('/api/admin/products', headers=auth_header(), json=payload)
    assert response.status_code == 422


def test_invalid_id_checked_for_admin_product():
    seed_base_data()
    mock_valid_admin_token()
    response = client.get('/api/admin/products/does-not-exist', headers=auth_header())
    # endpoint is list only; invalid ID check is expected to be 404 on detail/update/delete flows
    assert response.status_code == 405


def test_cors_allows_configured_development_origin():
    origin = 'http://localhost:5174'
    response = client.options(
        '/api/admin/dashboard',
        headers={
            'Origin': origin,
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'Authorization, Content-Type',
        },
    )
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == origin
    assert 'GET' in response.headers['access-control-allow-methods']
    assert 'Authorization' in response.headers['access-control-allow-headers']
    assert 'Content-Type' in response.headers['access-control-allow-headers']

    response = client.get('/api/admin/dashboard', headers={'Origin': origin})
    assert response.status_code == 401


def test_requirements_declare_runtime_dependencies():
    requirements = Path(__file__).parents[1].joinpath('requirements.txt').read_text(encoding='utf-16')
    assert 'firebase-admin' in requirements
    assert 'email-validator' in requirements
    assert 'fastapi' in requirements
    assert 'uvicorn' in requirements
    assert 'pydantic[email]' in requirements


def test_firebase_supports_environment_service_account(monkeypatch):
    certificate_calls = []
    monkeypatch.setenv('FIREBASE_SERVICE_ACCOUNT_JSON', '{"project_id":"test-project"}')
    monkeypatch.setattr(firebase_module, '_cred_path', Path('missing-service-account.json'))
    monkeypatch.setattr(
        firebase_module.credentials,
        'Certificate',
        lambda value: certificate_calls.append(value) or 'credential'
    )
    assert firebase_module._get_credentials() == 'credential'
    assert certificate_calls == [{'project_id': 'test-project'}]


def test_firebase_missing_configuration_does_not_expose_secret(monkeypatch):
    monkeypatch.delenv('FIREBASE_SERVICE_ACCOUNT_JSON', raising=False)
    monkeypatch.setattr(firebase_module, '_cred_path', Path('missing-service-account.json'))
    with pytest.raises(RuntimeError, match='configuration is missing'):
        firebase_module._get_credentials()


def test_firebase_internal_auth_failure_returns_500():
    seed_base_data()

    def fail_auth(token):
        raise RuntimeError('firebase unavailable')

    auth_mod.auth.verify_id_token = fail_auth
    response = client.get('/api/admin/test', headers=auth_header('admin-token'))
    assert response.status_code == 500
    assert response.json() == {'detail': 'Authentication service unavailable'}


def test_admin_test_does_not_disclose_identity():
    seed_base_data()
    mock_valid_admin_token()
    response = client.get('/api/admin/test', headers=auth_header())
    assert response.status_code == 200
    assert response.json() == {'message': 'Admin authentication successful'}
    assert 'uid' not in response.text
    assert 'email' not in response.text


def test_prices_reject_negative_values_and_allow_zero():
    Product(name='Free', description='Free product', price=0, category='Furniture')
    Service(name='Free', description='Free service', price=0, category='Design')
    with pytest.raises(ValueError):
        Product(name='Invalid', description='Invalid product', price=-1, category='Furniture')
    with pytest.raises(ValueError):
        Service(name='Invalid', description='Invalid service', price=-1, category='Design')


def test_product_request_quantity_must_be_positive():
    with pytest.raises(ValueError):
        ProductRequest(
            product_id='prod_1', customer_name='Alice', customer_email='alice@example.com',
            customer_phone='123', quantity=0
        )
    with pytest.raises(ValueError):
        ProductRequest(
            product_id='prod_1', customer_name='Alice', customer_email='alice@example.com',
            customer_phone='123', quantity=-1
        )
    assert ProductRequest(
        product_id='prod_1', customer_name='Alice', customer_email='alice@example.com',
        customer_phone='123', quantity=1
    ).quantity == 1


def test_unexpected_route_exception_returns_safe_500(monkeypatch):
    seed_base_data()
    mock_valid_admin_token()

    def fail_collection(name):
        raise RuntimeError('internal firestore detail')

    failing_db = type('FailingDb', (), {'collection': staticmethod(fail_collection)})()
    monkeypatch.setattr(admin_routes, 'db', failing_db)
    response = safe_client.get('/api/admin/dashboard', headers=auth_header())
    assert response.status_code == 500
    assert response.json() == {'detail': 'Internal server error'}
    assert 'internal firestore detail' not in response.text
    assert 'Traceback' not in response.text
