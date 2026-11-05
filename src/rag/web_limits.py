"""Small JSON-body boundary and static UI response headers."""

import json


class BodyLimit(Exception):
    pass


class WebLimits:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        limited = path.startswith("/library") and scope["method"] == "POST"
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            event = await receive()
            consumed += len(event.get("body", b""))
            if limited and consumed > 2 * 1024**2:
                raise BodyLimit
            return event

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")]
                )
                if path == "/" or path.startswith("/ui"):
                    headers.append(
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                        )
                    )
                if path.startswith("/library"):
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        # FastAPI may translate a receive exception to400; both reject before parsing.
        headers = dict(scope.get("headers", []))
        if limited:
            try:
                declared = int(headers.get(b"content-length", b"0"))
            except ValueError:
                declared = 2 * 1024**2 + 1
            if declared > 2 * 1024**2:
                body = json.dumps(
                    {"detail": "Selection JSON exceeds 2 MiB. Select fewer files."}
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                return await send({"type": "http.response.body", "body": body})
        await self.app(scope, bounded_receive, secure_send)
