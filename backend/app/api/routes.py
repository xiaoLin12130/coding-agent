"""REST routes.

M0 exposes only a health probe and a state read used by the Workbench panel.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import APP_NAME, APP_VERSION
from ..models import Memory, ProjectState
from ..storage import StateStore
from ..deps import get_state_store

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


@router.get("/project_state", response_model=ProjectState)
def read_project_state(store: StateStore = Depends(get_state_store)) -> ProjectState:
    return store.load_project_state()


@router.get("/memory", response_model=Memory)
def read_memory(store: StateStore = Depends(get_state_store)) -> Memory:
    return store.load_memory()
