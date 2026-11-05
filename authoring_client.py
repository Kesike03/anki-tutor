"""Asynchronous, provider-agnostic requests for authoring dialogs."""

from __future__ import annotations

import json
import traceback

from aqt.qt import QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

try:
    from .protocols import (
        ProtocolError, build_request, parse_response, parse_usage, provider_error,
    )
except ImportError:
    from protocols import (
        ProtocolError, build_request, parse_response, parse_usage, provider_error,
    )


class AuthoringRunner(QObject):
    job_finished = pyqtSignal(int, str, str)
    all_finished = pyqtSignal()

    def __init__(
        self, config: dict, parent=None, concurrency: int = 1, source: str = "authoring",
        usage_callback=None,
    ) -> None:
        super().__init__(parent)
        self.config = dict(config)
        self.source = source
        self.usage_callback = usage_callback
        self.concurrency = max(1, int(concurrency))
        self.manager = QNetworkAccessManager(self)
        self.queue: list[dict] = []
        self.active: dict[QNetworkReply, dict] = {}
        self._cancelled = False

    def start(self, jobs: list[dict]) -> None:
        self.abort()
        self._cancelled = False
        self.queue = list(jobs)
        self._start_next()

    def abort(self) -> None:
        self._cancelled = True
        self.queue.clear()
        for reply in list(self.active):
            reply.abort()
            reply.deleteLater()
        self.active.clear()

    def _start_next(self) -> None:
        while self.queue and len(self.active) < self.concurrency and not self._cancelled:
            job = self.queue.pop(0)
            try:
                spec = build_request(
                    self.config,
                    job["system"],
                    [{"role": "user", "content": job["user"]}],
                    schema=job.get("schema"),
                )
            except Exception as error:
                key = str(error)
                self.job_finished.emit(job["id"], "", key if key in {
                    "missing_key", "missing_model", "invalid_host", "invalid_path",
                    "invalid_response", "empty_response", "pdf_not_supported",
                } else str(error))
                continue
            request = QNetworkRequest(QUrl(spec.url))
            request.setTransferTimeout(90000)
            for name, value in spec.headers.items():
                request.setRawHeader(name.encode("ascii"), value.encode("utf-8"))
            reply = self.manager.post(
                request,
                json.dumps(spec.body, ensure_ascii=False).encode("utf-8"),
            )
            self.active[reply] = job
            reply.finished.connect(lambda current=reply: self._finish(current))
        if not self.active and not self.queue:
            self.all_finished.emit()

    def _finish(self, reply: QNetworkReply) -> None:
        job = self.active.pop(reply, None)
        if job is None:
            reply.deleteLater()
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            data = json.loads(bytes(reply.readAll()).decode("utf-8"))
        except (UnicodeError, ValueError):
            data = None
        usage = parse_usage(self.config.get("api_mode", "chat"), data)
        if usage and self.usage_callback is not None:
            try:
                self.usage_callback({
                    "usage": usage,
                    "model": self.config.get("model", ""),
                    "mode": self.config.get("api_mode", "chat"),
                    "source": self.source,
                })
            except Exception:
                traceback.print_exc()
        error = ""
        if (
            status in (400, 422) and job.get("schema")
            and not job.get("_retry_without_schema")
        ):
            job["_retry_without_schema"] = True
            job.pop("schema", None)
            self.queue.insert(0, job)
            reply.deleteLater()
            self._start_next()
            return
        if status is not None and int(status) >= 300:
            error = provider_error(int(status), data)
        elif reply.error() == QNetworkReply.NetworkError.TimeoutError:
            error = "Request timed out."
        elif reply.error() != QNetworkReply.NetworkError.NoError:
            error = reply.errorString()
        else:
            try:
                text = parse_response(self.config.get("api_mode", "chat"), data)
            except ProtocolError as exception:
                error = str(exception)
                text = ""
        reply.deleteLater()
        if self._cancelled:
            return
        self.job_finished.emit(job["id"], text if not error else "", error)
        self._start_next()
