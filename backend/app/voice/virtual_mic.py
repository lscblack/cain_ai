"""PipeWire virtual microphone.

Creates a linked sink/source pair: converted audio is written into the sink, and other
applications select the source ("KAI Voice Microphone") as their input. The audio goes
straight from the backend into PipeWire, so it does not depend on the browser, and only
works when the backend runs on the machine whose applications should see the device.
"""
from __future__ import annotations

import asyncio
import shutil

from app.core.logging import get_logger

log = get_logger("kai.voice.vmic")

SINK_NAME = "kai_voice_sink"
SOURCE_NAME = "kai_voice_mic"
SOURCE_DESCRIPTION = "KAI Voice Microphone"
RATE = 48000


class VirtualMicError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def _props(media_class: str, name: str, description: str) -> str:
    return (
        f'media.class={media_class} node.name={name} node.description="{description}" '
        f"audio.position=[MONO] audio.rate={RATE}"
    )


async def _node_exists(name: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "pw-cli", "ls", "Node", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return f'node.name = "{name}"'.encode() in out


class VirtualMicrophone:
    """The device outlives sessions (so an app stays connected across restarts of
    conversion) and is removed by ``disable``."""

    def __init__(self) -> None:
        self._loopback: asyncio.subprocess.Process | None = None
        self._writer: asyncio.subprocess.Process | None = None
        self._writer_rate = 0
        self.frames_written = 0

    @staticmethod
    def supported() -> dict:
        missing = [b for b in ("pw-loopback", "pw-cat", "pw-cli") if not shutil.which(b)]
        return {"supported": not missing, "missing": missing}

    @property
    def enabled(self) -> bool:
        return self._loopback is not None and self._loopback.returncode is None

    async def status(self) -> dict:
        info = self.supported()
        node = await _node_exists(SOURCE_NAME) if info["supported"] else False
        return {**info, "enabled": self.enabled and node, "source_name": SOURCE_NAME,
                "source_description": SOURCE_DESCRIPTION, "sink_name": SINK_NAME}

    async def enable(self) -> dict:
        info = self.supported()
        if not info["supported"]:
            raise VirtualMicError("pipewire_tools_missing", f"missing: {', '.join(info['missing'])}")
        if self.enabled:
            return await self.status()
        self._loopback = await asyncio.create_subprocess_exec(
            "pw-loopback", "--latency=20",
            f"--capture-props={_props('Audio/Sink', SINK_NAME, 'KAI Voice Sink')}",
            f"--playback-props={_props('Audio/Source', SOURCE_NAME, SOURCE_DESCRIPTION)}",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        for _ in range(30):  # creation is asynchronous; confirm rather than assume
            if await _node_exists(SOURCE_NAME):
                log.info("virtual microphone created")
                return await self.status()
            if self._loopback.returncode is not None:
                break
            await asyncio.sleep(0.1)
        await self.disable()
        raise VirtualMicError("virtual_mic_failed", "PipeWire did not create the device")

    async def _ensure_writer(self, rate: int) -> asyncio.subprocess.Process:
        if self._writer and self._writer.returncode is None and self._writer_rate == rate:
            return self._writer
        await self._close_writer()
        self._writer = await asyncio.create_subprocess_exec(
            "pw-cat", "-p", "--target", SINK_NAME, "--raw", "--rate", str(rate),
            "--channels", "1", "--format", "s16", "--latency", "20ms", "-",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._writer_rate = rate
        return self._writer

    async def write(self, pcm16: bytes, rate: int) -> None:
        if not self.enabled:
            return
        writer = await self._ensure_writer(rate)
        assert writer.stdin is not None
        try:
            writer.stdin.write(pcm16)
            await writer.stdin.drain()
            self.frames_written += len(pcm16) // 2
        except (BrokenPipeError, ConnectionResetError):
            await self._close_writer()

    async def _close_writer(self) -> None:
        writer, self._writer = self._writer, None
        if writer and writer.returncode is None:
            if writer.stdin:
                writer.stdin.close()
            try:
                await asyncio.wait_for(writer.wait(), 2)
            except asyncio.TimeoutError:
                writer.kill()

    async def release_stream(self) -> None:
        """Stop feeding audio; the device stays visible to other applications."""
        await self._close_writer()

    async def disable(self) -> None:
        await self._close_writer()
        proc, self._loopback = self._loopback, None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                proc.kill()


_instance: VirtualMicrophone | None = None


def get_virtual_mic() -> VirtualMicrophone:
    global _instance
    if _instance is None:
        _instance = VirtualMicrophone()
    return _instance
