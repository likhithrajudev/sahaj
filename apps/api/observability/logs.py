"""Logging setup: plain text for the terminal, or one JSON object per line (LOG_FORMAT=json) for log shipping.
Each line carries the request id of the request that produced it."""
import json
import logging
import sys

import config

EXTRA = ("request_id", "status", "ms", "client", "route")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        from gateway.middleware import request_id
        out = {"time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
               "logger": record.name, "message": record.getMessage(), "env": config.ENVIRONMENT,
               "request_id": getattr(record, "request_id", None) or request_id.get()}
        out.update({k: getattr(record, k) for k in EXTRA[1:] if hasattr(record, k)})
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def setup() -> None:
    root = logging.getLogger("sahaj")
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if config.LOG_FORMAT == "json"
                         else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False
