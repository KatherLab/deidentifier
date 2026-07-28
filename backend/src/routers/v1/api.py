from fastapi import APIRouter

from .endpoints import anonymize, export, status

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(anonymize.router, tags=["anonymize"])
api_router.include_router(export.router, tags=["export"])
api_router.include_router(status.router, tags=["status"])
