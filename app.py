import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import CloneConfig
from web.job_manager import JobManager
from web.login_manager import LoginManager
from web.routes import router, init_routes
from web.middleware import APIRateLimitMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

config = CloneConfig()
os.makedirs(config.output_dir, exist_ok=True)

manager = JobManager(config)
login_mgr = LoginManager()
init_routes(manager, login_mgr)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.start_cleanup_loop()

    async def login_cleanup_loop():
        while True:
            await asyncio.sleep(60)
            login_mgr.cleanup_expired()

    cleanup_task = asyncio.create_task(login_cleanup_loop())
    yield
    cleanup_task.cancel()


app = FastAPI(title="Static Website Cloner", lifespan=lifespan)

# API rate limiting middleware (D3)
app.add_middleware(APIRateLimitMiddleware, config=config)

app.include_router(router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
