from pydantic import BaseModel, HttpUrl


class CloneRequest(BaseModel):
    url: str
    max_depth: int | None = None
    max_pages: int | None = None


class JobResponse(BaseModel):
    job_id: str
    url: str
    domain: str
    status: str
    pages_crawled: int
    assets_downloaded: int
    errors_count: int
    error_message: str


class CloneResponse(BaseModel):
    job_id: str
    message: str
