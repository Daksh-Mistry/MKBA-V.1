"""Bounded local speech with owned subprocesses; no shell or cloud API."""
from __future__ import annotations

import asyncio
import hashlib
import shutil
from collections import OrderedDict


class SpeechService:
    def __init__(self, *, simulation=False, device="default"):
        self.simulation = simulation
        self.device = device
        self._task = None
        self._process = None
        self._records = OrderedDict()
        self.current = {"state": "idle", "request_id": None, "simulation": simulation}

    @property
    def available(self):
        return self.simulation or bool(shutil.which("espeak-ng") and shutil.which("aplay"))

    def status(self):
        return {**self.current, "available": self.available}

    def submit(self, request_id, text):
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if request_id in self._records:
            record, previous = self._records[request_id]
            if previous != fingerprint:
                raise ValueError("request_id was already used for different text")
            return {**record, "duplicate": True}
        if self._task is not None and not self._task.done():
            raise RuntimeError("speech is busy; retry after it finishes")
        if not self.available:
            raise FileNotFoundError("Install espeak-ng and alsa-utils on the Pi")
        self.current = {"state": "accepted", "request_id": request_id, "simulation": self.simulation}
        self._records[request_id] = (self.current, fingerprint)
        while len(self._records) > 64:
            self._records.popitem(last=False)
        self._task = asyncio.create_task(self._run(text), name="pi-speech")
        return dict(self.current)

    async def _communicate(self, args, data):
        self._process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await self._process.communicate(data)
        if self._process.returncode:
            raise RuntimeError(f"{args[0]} exited with code {self._process.returncode}")
        self._process = None
        return stdout

    async def _run(self, text):
        try:
            async with asyncio.timeout(20):
                self.current["state"] = "playing"
                if self.simulation:
                    await asyncio.sleep(0.02)
                else:
                    wav = await self._communicate(["espeak-ng", "--stdout", "--stdin"], text.encode("utf-8"))
                    await self._communicate(["aplay", "-q", "-D", self.device], wav)
                self.current["state"] = "completed"
        except asyncio.CancelledError:
            self.current["state"] = "stopped"
            raise
        except Exception as exc:
            self.current.update(state="error", error=str(exc)[:200])
        finally:
            if self._process is not None:
                if self._process.returncode is None:
                    try:
                        self._process.kill()
                    except ProcessLookupError:
                        pass
                await self._process.wait()
                self._process = None

    def stop_now(self):
        if self._task is not None and not self._task.done():
            self.current["state"] = "stopped"
            self._task.cancel()

    async def stop(self):
        self.stop_now()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        return self.status()
