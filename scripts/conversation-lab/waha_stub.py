#!/usr/bin/env python3
"""A WAHA that always accepts, so the lab can read what the rep said.

The reply is written and the message is sent inside one transaction
(pipeline.py: `db.add(Message(...))` then `_send`, which re-raises). So when
the send fails -- and it always fails on staging, where no session is linked to
a real phone -- the transaction rolls back and the reply is never recorded.
The behaviour under test is what the rep SAYS; delivery is WhatsApp's job and
is not what the lab is for.

This answers every send endpoint with a plausible 2xx and nothing else.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import uuid


class Handler(BaseHTTPRequestHandler):
    def _reply(self, payload: dict, code: int = 201) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        # WAHA returns the message it accepted; the gateway reads `id` to
        # fingerprint its own send, so it has to be present and unique or the
        # bot treats its own echo as the owner replying (section 5.5).
        self._reply({"id": f"stub_{uuid.uuid4().hex[:18]}", "_data": {}})

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/sessions"):
            self._reply([], code=200)
        else:
            self._reply({"status": "WORKING"}, code=200)

    def log_message(self, *_args) -> None:
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 3000), Handler).serve_forever()
