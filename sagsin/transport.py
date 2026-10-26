"""Bounded local HTTP workers; exact JSON-body counters, no packet-byte claim."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import hashlib
import multiprocessing
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from .client import serve_shard_logged
from .database import credentials
from .model import envelope, validate_envelope


class ClientPool:
    def __init__(self, ids, config, directory, check_cancel=lambda: None):
        self.ids, self.config, self.directory = ids, config, directory
        self.check_cancel = check_cancel
        self.workers = {}
        self.lock = threading.Lock()
        self.counters = {}

    def __enter__(self):
        self.startup_retries=[]
        for attempt in range(2):
            try:
                return self._start()
            except RuntimeError as exc:
                if "exited during startup" not in str(exc) or attempt:
                    raise
                # No round has started. Immutable local datasets make one
                # restart safe; retain the failure and count all HTTP attempts.
                self.startup_retries.append(str(exc))
                directory=Path(self.directory);directory.mkdir(parents=True,exist_ok=True)
                (directory/"startup-retries.json").write_text(json.dumps(self.startup_retries),encoding="utf-8")
                self.workers={}

    def _start(self):
        ctx = multiprocessing.get_context("spawn")
        try:
            slots = min(len(self.ids), self.config.max_workers)
            groups = [self.ids[i::slots] for i in range(slots)] if slots else []
            settings = credentials()["clients"]
            for group in groups:
                self.check_cancel()
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.bind(("127.0.0.1", 0))
                listener.listen(128)
                port = listener.getsockname()[1]
                token = secrets.token_urlsafe(32)
                process = ctx.Process(target=serve_shard_logged, args=(group, self.config.model_dump(),
                    str(self.directory), token, listener, {key:settings[key] for key in group}), daemon=True)
                process.start()
                listener.close()
                for identifier in group:
                    key = hashlib.sha256(identifier.encode()).hexdigest()[:24]
                    self.workers[identifier] = {"process": process, "url": f"http://127.0.0.1:{port}/{key}", "token": token}
            deadline = time.monotonic() + 100
            waiting = set(self.ids)
            while waiting:
                self.check_cancel()
                for identifier in list(waiting):
                    if not self.workers[identifier]["process"].is_alive():
                        process=self.workers[identifier]["process"]
                        raise RuntimeError(f"Client {identifier} exited during startup (exit {process.exitcode}); inspect clients/*-startup.log")
                    try:
                        self.call(identifier, "/health", category="startup", timeout=.5)
                        waiting.remove(identifier)
                    except (urllib.error.URLError, TimeoutError, OSError):
                        pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Client startup timed out: {sorted(waiting)}")
                time.sleep(.1)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        unique = {w["process"].pid:w for w in self.workers.values()}.values()
        for worker in unique:
            if worker["process"].is_alive():
                worker["process"].terminate()
        for worker in unique:
            worker["process"].join(timeout=5)
            if worker["process"].is_alive():
                worker["process"].kill()
                worker["process"].join(timeout=5)

    def call(self, identifier, path, body=None, category="control", timeout=None):
        started = time.perf_counter()
        worker = self.workers[identifier]
        dense_length = len(json.dumps(body,separators=(",", ":"),allow_nan=False).encode()) if body is not None else 0
        if body is not None and "model" in body:
            body = dict(body,model=envelope(validate_envelope(body["model"]),self.config.transport_codec))
        data = json.dumps(body, separators=(",", ":"), allow_nan=False).encode() if body is not None else None
        request = urllib.request.Request(worker["url"] + path, data=data,
                    headers={"Authorization": "Bearer " + worker["token"], "Content-Type": "application/json"})
        with self.lock:
            counter = self.counters.setdefault(category, {"sent_bytes": 0, "received_bytes": 0, "requests": 0, "errors": 0})
            counter["sent_bytes"] += len(data or b"")
            counter["dense_equivalent_sent_bytes"] = counter.get("dense_equivalent_sent_bytes",0)+dense_length
            counter["requests"] += 1
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.config.timeout_s) as response:
                result = response.read()
            with self.lock:
                counter["received_bytes"] += len(result)
            decoded = json.loads(result)
            dense_result = dict(decoded,model=envelope(validate_envelope(decoded["model"]))) if "model" in decoded else decoded
            dense_received = len(json.dumps(dense_result,separators=(",", ":"),allow_nan=False).encode())
            with self.lock:
                counter["dense_equivalent_received_bytes"] = counter.get("dense_equivalent_received_bytes",0)+dense_received
            decoded["_http_elapsed_s"] = time.perf_counter()-started
            return decoded
        except Exception:
            with self.lock:
                counter["errors"] += 1
            raise

    def parallel(self, ids, path, bodies, category):
        results = {}
        executor = ThreadPoolExecutor(max_workers=min(len(ids) or 1, self.config.max_workers))
        futures = {executor.submit(self.call, identifier, path, bodies[identifier], category): identifier for identifier in ids}
        pending = set(futures)
        try:
            while pending:
                self.check_cancel()
                completed, pending = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
                for future in completed:
                    identifier = futures[future]
                    try:
                        results[identifier] = {"ok": True, "result": future.result()}
                    except Exception as exc:
                        results[identifier] = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
        except BaseException:
            # Terminating local workers closes their sockets and unblocks HTTP
            # callers; cancellation need not wait for the full training timeout.
            self.__exit__()
            raise
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        return results
