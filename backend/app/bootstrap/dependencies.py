"""HTTP access to dependencies constructed by the application lifespan."""

from fastapi import Request, WebSocket

from app.modules.printing.printer_hub import PrinterHub
from app.runtime.work_wakeup import WorkWakeup


def get_work_wakeup(request: Request) -> WorkWakeup:
    return request.app.state.work_wakeup


def get_hub(request: Request) -> PrinterHub:
    """FastAPI dependency: returns the PrinterHub stored on app.state."""
    return request.app.state.printer_hub


def get_hub_from_ws(websocket: WebSocket) -> PrinterHub:
    """FastAPI dependency (WebSocket variant): returns the PrinterHub."""
    return websocket.app.state.printer_hub
