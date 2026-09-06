import os
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.product_routes import router as product_router
from app.service_routes import router as service_router
from app.category_routes import router as category_router
from app.product_request_routes import router as product_request_router
from app.service_request_routes import router as service_request_router
from app.contact_routes import router as contact_router
from app.site_settings_routes import router as site_settings_router
from app.admin_routes import router as admin_router

app = FastAPI(
    title="Mifra Enterprises API",
    version="1.0.0",
)

logger = logging.getLogger(__name__)


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception):
    logger.exception("Unhandled backend exception for %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,https://mifra-enterprises-frontend.vercel.app"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "Mifra Enterprises API is running!"
    }


@app.get("/home")
def home():
    return {
        "message": "FastAPI + firebase connected!"
    }


@app.get("/api/health")
def health_check():
    return {
        "status": "ok"
    }


app.include_router(product_router)
app.include_router(service_router)
app.include_router(category_router)
app.include_router(product_request_router)
app.include_router(service_request_router)
app.include_router(contact_router)
app.include_router(site_settings_router)
app.include_router(admin_router)