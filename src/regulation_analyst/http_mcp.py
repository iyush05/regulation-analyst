"""Bearer-protected, read-only MCP for a small, single-worker hosted pilot.

Credentials are provisioned by the operator, independently of Agensi purchases.
This is not an OAuth authorization server. Only clients with bearer-header support
can connect. Limits are per credential, per process and reset on restart.
"""

import hashlib
import hmac
import math
import time
from collections import deque

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ResearchAccess:
    def __init__(self, app: ASGIApp, *, tokens: dict[str, str], requests_per_minute: int):
        self.app = app
        self.digests = {
            name: hashlib.sha256(token.encode()).digest() for name, token in tokens.items()
        }
        self.requests_per_minute = requests_per_minute
        # Only configured identities get buckets, so arbitrary tokens cannot grow memory.
        self.requests: dict[str, deque[float]] = {name: deque() for name in tokens}

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        scheme, _, token = Headers(scope=scope).get("authorization", "").partition(" ")
        digest = hashlib.sha256(token.encode()).digest()
        identity = None
        for name, expected in self.digests.items():
            if hmac.compare_digest(digest, expected) and scheme.lower() == "bearer":
                identity = name
        if identity is None:
            response = JSONResponse(
                {"detail": "Missing or invalid research access token"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="regulation-analyst"'},
            )
            await response(scope, receive, send)
            return

        now = time.monotonic()
        requests = self.requests[identity]
        while requests and now - requests[0] >= 60:
            requests.popleft()
        if len(requests) >= self.requests_per_minute:
            response = JSONResponse(
                {"detail": "Research request limit reached"},
                status_code=429,
                headers={"Retry-After": str(max(1, math.ceil(60 - (now - requests[0]))))},
            )
            await response(scope, receive, send)
            return
        requests.append(now)
        await self.app(scope, receive, send)
