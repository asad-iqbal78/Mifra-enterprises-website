# MIFRA Enterprises Backend API Documentation

This document reflects the current backend implementation in this repository as of the latest verified code state. It documents only APIs that actually exist in the codebase and intentionally omits features not implemented.

## 1. Overview

The backend is built with FastAPI and uses Firebase Admin SDK + Firestore for persistence.

### Base URL
- Local development default: `http://127.0.0.1:8000`

### App metadata
- Title: `Mifra Enterprises API`
- Version: `1.0.0`

### Included routers
- `/api/products`
- `/api/services`
- `/api/categories`
- `/api/product-requests`
- `/api/service-requests`
- `/api/contact`
- `/api/site-settings`
- `/api/admin`

### Root endpoints
- `GET /` — returns a basic running message
- `GET /home` — returns a FastAPI + Firebase connected message
- `GET /api/health` — returns `{ "status": "ok" }`

---

## 2. Firebase authentication flow

### Firebase ID token usage
The app uses Firebase Admin SDK to validate Firebase ID tokens through `verify_admin` in [backend/app/auth.py](../backend/app/auth.py).

### Authentication mechanism
The backend uses an HTTP Bearer token:
- Header: `Authorization: Bearer <firebase-id-token>`

### Admin authorization logic
`verify_admin` does the following:
1. Reads the Bearer token from the request
2. Calls `firebase_admin.auth.verify_id_token(token)`
3. Reads the Firestore document `admins/{uid}`
4. Requires `admins/{uid}.role == "admin"`
5. Returns the decoded token payload for downstream use

### Authentication/authorization responses
- Invalid or expired token: HTTP 401
- Missing admin document or role not equal to `admin`: HTTP 403

---

## 3. CORS configuration

CORS is enabled in [backend/main.py](../backend/main.py) with `CORSMiddleware`.

### Default allowed origins
- `https://mifra-enterprises-frontend.vercel.app`
- `https://mifra-enterprises-admin.vercel.app`
- `http://localhost:5173`
- `http://localhost:5174`
- `http://127.0.0.1:5173`
- `http://127.0.0.1:5174`

Additional origins can be supplied through the environment variable (comma-separated):
- `CORS_ORIGINS`

The production client and admin origins remain enabled even when `CORS_ORIGINS` is set.

---

## 4. Rate limiting behavior

A minimal per-IP, per-route rate limiter is implemented for the public submission endpoints.

### Configuration
Environment variables:
- `RATE_LIMIT_REQUESTS` (default: `5`)
- `RATE_LIMIT_WINDOW_SECONDS` (default: `60`)

### Protected endpoints
- `POST /api/product-requests`
- `POST /api/service-requests`
- `POST /api/contact`

### Rate limit response
- HTTP 429
- Body is the standard FastAPI HTTPException detail message:
  - `"Rate limit exceeded. Please try again later."`

### Public GET APIs
- not rate limited by the current implementation

### Admin APIs
- not rate limited by the current implementation

---

## 5. Email notification behavior

Email notifications are triggered after a successful Firestore save for these public submission endpoints:
- `POST /api/product-requests`
- `POST /api/service-requests`
- `POST /api/contact`

### Email implementation details
The backend includes an SMTP sender in [backend/app/email_service.py](../backend/app/email_service.py).

### Required environment variables
- `SMTP_HOST`
- `SMTP_PORT` (default `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `SMTP_TO_EMAIL` (optional fallback: `ADMIN_EMAIL` or `SMTP_FROM_EMAIL`)
- `SMTP_USE_TLS` (default `true`)
- `SMTP_USE_SSL` (default `false`)

### Behavior
- If SMTP configuration is missing, the function logs a warning and returns without raising an API error.
- If SMTP send fails, the email send is handled safely and logged; the API response still reflects the original submission result.
- No SMTP credentials or Firebase private keys are stored in source files.

---

## 6. Firestore collections used

The current backend uses the following Firestore collections:

- `products`
- `productCategories`
- `services`
- `productRequests`
- `serviceRequests`
- `contactMessages`
- `siteSettings`
- `admins`

### Document IDs
- Product/category/service documents use auto-generated IDs unless the app references a specific one.
- `siteSettings` uses document id `main`

---

## 7. Public Read APIs

## 7.1 GET /api/products

### Purpose
Returns all publicly visible products.

### Authentication
Not required.

### Headers
None required.

### Request body
None.

### Success response
- HTTP 200
- JSON array of product objects

### Product object fields
- `id: string`
- `name: string`
- `description: string`
- `price: number` (must be `>= 0`)
- `category: string`
- `image: string | null`
- `stockQuantity: integer` (`>= 0`)
- `lowStockThreshold: integer` (`>= 0`)
- `isActive: boolean`
- `featured: boolean` (if present in stored data)
- additional stored fields may be present

### Price rule
The current product and service schemas use `ge=0`, so zero-priced products and services are intentionally supported. Negative prices are rejected.

### Public visibility rule
Only products with `isActive != false` are returned.

### Error responses
- 404 only on individual product lookup, not on list request

---

## 7.2 GET /api/products/{product_id}

### Purpose
Returns one public product by ID.

### Authentication
Not required.

### Headers
None required.

### Request body
None.

### Success response
- HTTP 200
- JSON object with the product fields plus `id`

### Error responses
- HTTP 404 if product does not exist
- HTTP 404 if product is inactive

---

## 7.3 GET /api/categories

### Purpose
Returns all product categories.

### Authentication
Not required.

### Headers
None required.

### Request body
None.

### Success response
- HTTP 200
- JSON array of category objects

### Category object fields
- `id: string`
- `name: string`
- `description: string | null`
- `image: string | null`

---

## 7.4 GET /api/categories/{category_id}

### Purpose
Returns one category by ID.

### Authentication
Not required.

### Headers
None required.

### Request body
None.

### Success response
- HTTP 200
- JSON object for the category

### Error responses
- HTTP 404 if category does not exist

---

## 7.5 GET /api/services

### Purpose
Returns all publicly visible services.

### Authentication
Not required.

### Headers
None required.

### Request body
None.

### Success response
- HTTP 200
- JSON array of service objects

### Service object fields
- `id: string`
- `name: string`
- `description: string`
- `price: number` (`>= 0`)
- `category: string`
- `image: string | null`
- `isActive: boolean`
- `featured: boolean`
- `displayOrder: integer` (`>= 0`)

### Public visibility rule
Only services with `isActive != false` are returned.

### Sorting
Sorted by `displayOrder` ascending.

---

## 7.6 GET /api/services/{service_id}

### Purpose
Returns one public service by ID.

### Authentication
Not required.

### Headers
None required.

### Request body
None.

### Success response
- HTTP 200
- JSON object with the service fields plus `id`

### Error responses
- HTTP 404 if service does not exist
- HTTP 404 if service is inactive

---

## 7.7 GET /api/site-settings

### Purpose
Returns the public site settings document.

### Authentication
Not required.

### Headers
None required.

### Request body
None.

### Success response
- HTTP 200
- JSON object of the document

### Site settings fields
- `id: string`
- `company_name: string`
- `email: string`
- `phone: string`
- `address: string`
- `logo: string | null`
- `about_text: string | null`
- `facebook: string | null`
- `instagram: string | null`
- `whatsapp: string | null`

### Error responses
- HTTP 404 if the `siteSettings/main` document does not exist

---

## 8. Public Submission APIs

## 8.1 POST /api/product-requests

### Purpose
Creates a product inquiry/request.

### Authentication
Not required.

### Headers
None required.

### Request schema
```json
{
  "product_id": "string",
  "customer_name": "string",
  "customer_email": "string (email)",
  "customer_phone": "string",
  "quantity": "integer",
  "message": "string | null"
}
```

### Validation rules
- `product_id` required
- `customer_name` required
- `customer_email` must be valid email format
- `customer_phone` required
- `quantity` required; not strictly constrained by Pydantic in this route beyond normal JSON integer handling
- `message` optional

### Success response
- HTTP 200
- JSON:
```json
{
  "message": "Product request submitted successfully",
  "id": "<document-id>"
}
```

### Error responses
- HTTP 404 if the referenced product does not exist
- HTTP 422 validation errors for malformed input

### Additional behavior
- Firestore document written to `productRequests`
- `status` set to `new`
- `created_at` set to current UTC timestamp
- email notification is attempted after a successful save

---

## 8.2 POST /api/service-requests

### Purpose
Creates a service inquiry/request.

### Authentication
Not required.

### Headers
None required.

### Request schema
```json
{
  "service_id": "string",
  "customer_name": "string",
  "customer_email": "string (email)",
  "customer_phone": "string",
  "message": "string | null"
}
```

### Validation rules
- `service_id` required
- `customer_name` required
- `customer_email` must be valid email format
- `customer_phone` required
- `message` optional

### Success response
- HTTP 200
- JSON:
```json
{
  "message": "Service request submitted successfully",
  "id": "<document-id>"
}
```

### Error responses
- HTTP 404 if the referenced service does not exist
- HTTP 422 validation errors for malformed input

### Additional behavior
- Firestore document written to `serviceRequests`
- `status` set to `new`
- `created_at` set to current UTC timestamp
- email notification is attempted after a successful save

---

## 8.3 POST /api/contact

### Purpose
Creates a contact message.

### Authentication
Not required.

### Headers
None required.

### Request schema
```json
{
  "name": "string",
  "email": "string (email)",
  "phone": "string | null",
  "subject": "string | null",
  "message": "string"
}
```

### Validation rules
- `name` required
- `email` required and valid email format
- `message` required
- `phone` optional
- `subject` optional

### Success response
- HTTP 200
- JSON:
```json
{
  "message": "Contact message submitted successfully",
  "id": "<document-id>"
}
```

### Error responses
- HTTP 422 validation errors for malformed input

### Additional behavior
- Firestore document written to `contactMessages`
- `status` set to `unread`
- `created_at` set to current UTC timestamp
- email notification is attempted after a successful save

---

## 9. Admin APIs

All admin routes require Firebase admin authentication via the `verify_admin` dependency.

### Required header
- `Authorization: Bearer <firebase-id-token>`

### Admin test/auth endpoint

## 9.1 GET /api/admin/test

### Purpose
Checks whether the provided Firebase token is valid and the user is an admin.

### Authentication
Required.

### Response
- HTTP 200 on success with:
```json
{
  "message": "Admin authentication successful!",
  "uid": "<firebase-uid>",
  "email": "<admin-email>"
}
```

### Error responses
- HTTP 401 invalid/expired token
- HTTP 403 non-admin or missing admin record

---

## 9.2 GET /api/admin/dashboard

### Purpose
Returns aggregated dashboard stats for active products and incoming requests.

### Authentication
Required.

### Response fields
- `products.total_active`
- `products.in_stock`
- `products.low_stock`
- `products.out_of_stock`
- `requests.pending_product`
- `requests.pending_service`
- `recent_requests` array

### Error responses
- HTTP 401/403 auth failures

---

## 9.3 Admin Product APIs

## 9.3.1 GET /api/admin/products

### Purpose
Returns all products in Firestore.

### Authentication
Required.

### Response
- HTTP 200
- JSON array of product objects with added `id` and `stockStatus`

### Stock status values
- `out_of_stock`
- `limited_stock`
- `in_stock`

---

## 9.3.2 POST /api/admin/products

### Purpose
Creates a product.

### Authentication
Required.

### Request schema
```json
{
  "name": "string",
  "description": "string",
  "price": "number >= 0",
  "category": "string",
  "image": "string | null",
  "stockQuantity": "integer >= 0",
  "lowStockThreshold": "integer >= 0",
  "isActive": "boolean",
  "featured": "boolean"
}
```

### Validation rules
- `category` must already exist in `productCategories`
- `price >= 0`
- `stockQuantity >= 0`
- `lowStockThreshold >= 0`

### Success response
```json
{
  "message": "Product created successfully",
  "id": "<product-id>",
  "product": { ... }
}
```

### Error responses
- HTTP 404 if category does not exist
- HTTP 401/403 auth failures
- HTTP 422 validation errors

---

## 9.3.3 PUT /api/admin/products/{product_id}

### Purpose
Updates a product.

### Authentication
Required.

### Request schema
Same as create product body.

### Success response
```json
{
  "message": "Product updated successfully",
  "id": "<product-id>",
  "product": { ... }
}
```

### Error responses
- HTTP 404 if product not found
- HTTP 404 if category does not exist
- HTTP 401/403 auth failures
- HTTP 422 validation errors

---

## 9.3.4 DELETE /api/admin/products/{product_id}

### Purpose
Soft-deactivates a product by setting `isActive` to false and adding `deletedAt`.

### Authentication
Required.

### Success response
```json
{
  "message": "Product deactivated successfully",
  "id": "<product-id>"
}
```

### Error responses
- HTTP 404 if product does not exist
- HTTP 401/403 auth failures

---

## 9.3.5 PUT /api/admin/products/{product_id}/status

### Purpose
Updates product active/inactive state.

### Authentication
Required.

### Request schema
```json
{
  "isActive": "boolean"
}
```

### Success response
```json
{
  "message": "Product status updated successfully",
  "id": "<product-id>",
  "isActive": true
}
```

### Error responses
- HTTP 404 if product not found
- HTTP 401/403 auth failures
- HTTP 422 validation errors

---

## 9.3.6 PUT /api/admin/products/{product_id}/stock

### Purpose
Updates stock and threshold data.

### Authentication
Required.

### Request schema
```json
{
  "stockQuantity": "integer >= 0",
  "lowStockThreshold": "integer >= 0 | null"
}
```

### Success response
```json
{
  "message": "Product stock updated successfully",
  "id": "<product-id>",
  "stockQuantity": 4,
  "lowStockThreshold": 5,
  "stockStatus": "limited_stock"
}
```

### Validation rules
- `stockQuantity >= 0`
- `lowStockThreshold >= 0` when provided

### Error responses
- HTTP 404 if product not found
- HTTP 401/403 auth failures
- HTTP 422 validation errors

---

## 9.4 Admin Service APIs

## 9.4.1 POST /api/admin/services

### Purpose
Creates a service.

### Authentication
Required.

### Request schema
```json
{
  "name": "string",
  "description": "string",
  "price": "number >= 0",
  "category": "string",
  "image": "string | null",
  "isActive": "boolean",
  "featured": "boolean",
  "displayOrder": "integer >= 0"
}
```

### Success response
```json
{
  "message": "Service created successfully",
  "id": "<service-id>",
  "service": { ... }
}
```

### Error responses
- HTTP 401/403 auth failures
- HTTP 422 validation errors

---

## 9.4.2 PUT /api/admin/services/{service_id}

### Purpose
Updates a service.

### Authentication
Required.

### Success response
```json
{
  "message": "Service updated successfully",
  "id": "<service-id>",
  "service": { ... }
}
```

### Error responses
- HTTP 404 if service not found
- HTTP 401/403 auth failures
- HTTP 422 validation errors

---

## 9.4.3 DELETE /api/admin/services/{service_id}

### Purpose
Soft-deactivates a service by setting `isActive` to false and adding `deletedAt`.

### Authentication
Required.

### Success response
```json
{
  "message": "Service deactivated successfully",
  "id": "<service-id>"
}
```

### Error responses
- HTTP 404 if service not found
- HTTP 401/403 auth failures

---

## 9.5 Admin Request APIs

## 9.5.1 GET /api/admin/requests

### Purpose
Returns product and service requests sorted by most recent.

### Authentication
Required.

### Response
- HTTP 200
- JSON array of request objects with `id` and `request_type`

### Supported fields
- original request fields plus `id`
- `request_type`: `product` or `service`

---

## 9.5.2 PUT /api/admin/requests/{request_id}

### Purpose
Updates request status.

### Authentication
Required.

### Request schema
```json
{
  "status": "string",
  "request_type": "string | null",
  "internal_notes": "string | null"
}
```

### Allowed statuses
- product/service requests: `new`, `contacted`, `in_progress`, `completed`, `cancelled`

### Validation rules
- `status` must be one of the allowed values
- `request_type` may be `product` or `service`
- if omitted, the code searches both request collections to find the matching record

### Success response
```json
{
  "message": "Request status updated successfully",
  "id": "<request-id>",
  "request_type": "product",
  "status": "in_progress",
  "internal_notes": "..."
}
```

### Error responses
- HTTP 400 invalid status
- HTTP 404 request not found
- HTTP 401/403 auth failures

---

## 9.6 Admin Message APIs

## 9.6.1 GET /api/admin/messages

### Purpose
Returns all contact messages.

### Authentication
Required.

### Response
- HTTP 200
- JSON array of contact messages with `id`

---

## 9.6.2 PUT /api/admin/messages/{message_id}

### Purpose
Updates a contact message status.

### Authentication
Required.

### Request schema
```json
{
  "status": "string"
}
```

### Allowed statuses
- `unread`, `read`

### Success response
```json
{
  "message": "Contact message status updated successfully",
  "id": "<message-id>",
  "status": "read"
}
```

### Error responses
- HTTP 400 invalid status
- HTTP 404 message not found
- HTTP 401/403 auth failures

---

## 9.7 Admin Settings API

## 9.7.1 PUT /api/admin/settings

### Purpose
Updates the site settings document in Firestore.

### Authentication
Required.

### Request schema
```json
{
  "company_name": "string | null",
  "email": "string (email) | null",
  "phone": "string | null",
  "address": "string | null",
  "logo": "string | null",
  "about_text": "string | null",
  "facebook": "string | null",
  "instagram": "string | null",
  "whatsapp": "string | null"
}
```

### Validation rules
- `email` must be a valid email if supplied
- at least one field must be present; otherwise 400 is returned

### Success response
```json
{
  "message": "Site settings updated successfully",
  "id": "main",
  "settings": { ... }
}
```

### Error responses
- HTTP 400 if no settings provided
- HTTP 401/403 auth failures
- HTTP 422 validation errors

---

## 10. Environment variables used by the backend

These are all currently used in code:

- `CORS_ORIGINS`
- `RATE_LIMIT_REQUESTS`
- `RATE_LIMIT_WINDOW_SECONDS`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `SMTP_TO_EMAIL`
- `ADMIN_EMAIL`
- `SMTP_USE_TLS`
- `SMTP_USE_SSL`

No secrets should be added to the repository. Use environment variables or a secure deployment environment.

---

## 11. How to run the FastAPI backend

From the backend folder:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

### Local base URL
- `http://127.0.0.1:8000`

### OpenAPI docs
FastAPI auto-generates OpenAPI at:
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/redoc`

---

## 12. How to run pytest

From the backend folder:

```bash
cd backend
python -m pytest -q tests/test_backend_suite.py
```

---

## 13. Current test status

The current backend test suite is passing with the latest verified run.

### Verified command
```bash
cd "c:/Users/Asad Iqbal/Desktop/Mifra/Mifra-enterprises-website/backend"; python -m pytest -q tests/test_backend_suite.py
```

### Result
- 41 passed
- 0 failed
- 0 skipped
- 1 warning (Starlette/HTTPX deprecation warning)

---

## 14. Summary

This documentation covers the API surface that actually exists in the current codebase and intentionally excludes unimplemented features. The implementation includes public reads, public submissions, admin APIs, Firebase auth enforcement, email notifications, and rate limiting. No runtime or source-code secrets are documented.
