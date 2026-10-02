"""Bound multipart bytes before Starlette spools an untrusted request."""

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from ..settings import settings


class UploadLimitExceeded(Exception):
    pass


class CatalogUploadGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or not path.startswith("/api/admin/catalog-builder/") or not path.endswith("/pdf")):
            return await self.app(scope, receive, send)
        maximum = settings.catalog_pdf_max_bytes + 1024 * 1024
        consumed = 0
        exceeded = False
        responded = False

        def error_response():
            return JSONResponse({"detail": {"code": "catalog_source_too_large",
                "limit": settings.catalog_pdf_max_bytes, "configurable_setting": "CATALOG_PDF_MAX_BYTES"}},
                status_code=413)

        async def bounded_receive():
            nonlocal consumed, exceeded
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > maximum:
                exceeded = True
                # Starlette closes already-spooled files for this exception.
                raise MultiPartException("catalog_source_too_large")
            return message

        async def bounded_send(message):
            nonlocal responded
            if exceeded:
                if not responded:
                    responded = True
                    await error_response()(scope, receive, send)
                return
            await send(message)

        try:
            length = dict(scope.get("headers", [])).get(b"content-length", b"0")
            if int(length) > maximum:
                raise UploadLimitExceeded
        except (UploadLimitExceeded, ValueError):
            return await error_response()(scope, receive, send)
        return await self.app(scope, bounded_receive, bounded_send)
