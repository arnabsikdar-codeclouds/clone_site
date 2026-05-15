"""API rate limiting middleware — in-memory sliding window per IP."""

import time
from collections import defaultdict

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from config import CloneConfig


class APIRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config: CloneConfig) -> None:
        super().__init__(app)
        self._limit = config.api_rate_limit
        self._window = config.api_rate_window
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only rate-limit POST /api/clone
        if request.method == "POST" and request.url.path == "/api/clone":
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()
            cutoff = now - self._window

            # Prune old entries
            timestamps = self._requests[client_ip]
            self._requests[client_ip] = [t for t in timestamps if t > cutoff]

            if len(self._requests[client_ip]) >= self._limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Max {self._limit} requests per {self._window}s.",
                )

            self._requests[client_ip].append(now)

        return await call_next(request)
