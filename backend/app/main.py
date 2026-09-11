"""FastAPI application entry point.

Run with:  python -m uvicorn app.main:app --reload --port 8000   (from backend/)
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import console as console_api
from .api import context as context_api
from .api import recovery as recovery_api
from .api import routes, ws
from .config import APP_NAME, APP_VERSION

app = FastAPI(title=APP_NAME, version=APP_VERSION)

# The Vite dev server proxies /api and /ws, so CORS is only a convenience for
# direct development against :8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router, prefix="/api", tags=["api"])
app.include_router(context_api.router, prefix="/api", tags=["context"])
app.include_router(recovery_api.router, prefix="/api", tags=["recovery"])
app.include_router(console_api.router, prefix="/api", tags=["console"])
app.include_router(ws.router, tags=["ws"])
