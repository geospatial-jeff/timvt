"""TiVTiler app events."""

from typing import Callable

from .db.events import close_db_connection, connect_to_db

from fastapi import FastAPI


def create_start_app_handler(app: FastAPI) -> Callable:  # type: ignore
    """App start event."""

    async def start_app() -> None:
        await connect_to_db(app)

    return start_app


def create_stop_app_handler(app: FastAPI) -> Callable:  # type: ignore
    """App stop event."""

    async def stop_app() -> None:
        await close_db_connection(app)

    return stop_app
