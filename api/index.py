import asyncio
import logging
import os
import sys

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager

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
# Vercel serverless functions can only write to /tmp
config.output_dir = "/tmp/output"
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

app.add_middleware(APIRateLimitMiddleware, config=config)

app.include_router(router)

# Serve static files — resolve path relative to project root
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
