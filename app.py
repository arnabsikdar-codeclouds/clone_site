import logging
import os

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import CloneConfig
from web.job_manager import JobManager
from web.routes import router, init_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

config = CloneConfig()
os.makedirs(config.output_dir, exist_ok=True)

app = FastAPI(title="Static Website Cloner")
manager = JobManager(config)
init_routes(manager)

app.include_router(router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
