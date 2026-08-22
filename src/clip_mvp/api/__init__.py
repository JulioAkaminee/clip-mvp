"""API local (FastAPI) que expõe o pipeline para a UI web."""

from .app import create_app

__all__ = ["create_app"]
