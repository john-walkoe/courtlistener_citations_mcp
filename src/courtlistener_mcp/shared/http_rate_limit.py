"""
Inbound Rate Limit Middleware for HTTP Transport

Simple per-IP token bucket rate limiter. No external dependencies.
Applied only when TRANSPORT=http to protect against abuse.
"""

import asyncio
import time
from collections import defaultdict

from starlette.responses import JSONResponse


class InboundRateLimitMiddleware:
    """ASGI middleware that enforces per-IP request rate limits."""

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._last_cleanup = time.monotonic()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        client_ip = scope.get("client", ("unknown", 0))[0]
        now = time.monotonic()

        async with self._lock:
            # Periodic cleanup of stale IPs (every 60s)
            if now - self._last_cleanup > 60:
                cutoff = now - self.window_seconds
                self.requests = defaultdict(list, {
                    ip: [t for t in timestamps if t > cutoff]
                    for ip, timestamps in self.requests.items()
                    if any(t > cutoff for t in timestamps)
                })
                self._last_cleanup = now

            # Prune expired entries for this IP
            self.requests[client_ip] = [
                t for t in self.requests[client_ip]
                if now - t < self.window_seconds
            ]

            if len(self.requests[client_ip]) >= self.max_requests:
                resp = JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
                await resp(scope, receive, send)
                return

            self.requests[client_ip].append(now)

        await self.app(scope, receive, send)
