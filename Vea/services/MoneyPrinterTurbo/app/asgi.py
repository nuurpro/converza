"""Application implementation - ASGI."""

import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from uuid import UUID
import re
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config import config
from app.models.exception import HttpException
from app.router import root_api_router
from app.services import state as sm
from app.utils import utils, file_security


def exception_handler(request: Request, e: HttpException):
    return JSONResponse(
        status_code=e.status_code,
        content=utils.get_response(e.status_code, e.data, e.message),
    )


def validation_exception_handler(request: Request, e: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content=utils.get_response(
            status=400, data=jsonable_encoder(e.errors(), custom_encoder={Exception: str}), message="invalid request"
        ),
    )


def get_application() -> FastAPI:
    """Initialize FastAPI application.

    Returns:
       FastAPI: Application object instance.

    """
    instance = FastAPI(
        title=config.project_name,
        description=config.project_description,
        version=config.project_version,
        debug=False,
    )
    instance.include_router(root_api_router)
    instance.add_exception_handler(HttpException, exception_handler)
    instance.add_exception_handler(RequestValidationError, validation_exception_handler)
    return instance


app = get_application()

# Configures the CORS middleware for the FastAPI app
cors_allowed_origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "")
origins = cors_allowed_origins_str.split(",") if cors_allowed_origins_str else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

task_dir = utils.task_dir()
if config.app.get('approved_only', False):
    @app.get('/tasks/{task_id}/{filename}')
    def approved_video_preview(task_id: UUID, filename: str):
        if not re.fullmatch(r'final-[1-9][0-9]*\.(mp4|jpg)', filename):
            raise HTTPException(status_code=404, detail='Video not found')
        try:
            video_file = file_security.resolve_path_within_directory(task_dir, f'{task_id}/{filename}')
        except ValueError:
            raise HTTPException(status_code=404, detail='Video not found') from None
        if not os.path.isfile(video_file):
            raise HTTPException(status_code=404, detail='Video not found')
        return FileResponse(video_file, media_type='image/jpeg' if filename.endswith('.jpg') else 'video/mp4')
else:
    app.mount('/tasks', StaticFiles(directory=task_dir, html=True, follow_symlink=True), name='')

public_dir = utils.public_dir()
app.mount("/", StaticFiles(directory=public_dir, html=True), name="")


@app.on_event("shutdown")
def shutdown_event():
    # Non-daemon render threads may outlive ASGI shutdown. Keep the process lock
    # until interpreter exit so another process cannot abandon their receipts.
    logger.info("shutdown event")


@app.on_event("startup")
def startup_event():
    if config.app.get('approved_only', False):
        sm.state.start_runtime()
    logger.info("startup event")
