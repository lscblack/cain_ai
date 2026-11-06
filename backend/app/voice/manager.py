"""VoiceModelManager: discovery, installation, loading, health and hardware checks.

Installed means verified on disk, not a flag someone once set. Workers are started on
demand and stopped when idle; stopping the process is the only reliable way to return
all of a model's memory.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import psutil

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice import catalog
from app.voice.catalog import EnvSpec, ModelSpec
from app.voice.supervisor import WORKERS_DIR, WorkerFailure, WorkerProcess

log = get_logger("kai.voice.models")


class ManagerError(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _conda_bin() -> str | None:
    configured = get_settings().voice_conda_bin
    if configured:
        return configured
    if os.environ.get("CONDA_EXE"):
        return os.environ["CONDA_EXE"]
    prefix = Path(sys.prefix)
    if prefix.parent.name == "envs" and (prefix.parent.parent / "bin" / "conda").exists():
        return str(prefix.parent.parent / "bin" / "conda")
    return shutil.which("conda")


def _envs_dir() -> Path:
    configured = get_settings().voice_envs_dir
    if configured:
        return Path(configured).expanduser()
    prefix = Path(sys.prefix)
    if prefix.parent.name == "envs":
        return prefix.parent
    conda = _conda_bin()
    if conda:
        return Path(conda).resolve().parent.parent / "envs"
    return Path(get_settings().voice_home).expanduser() / "envs"


def _dir_size(path: Path) -> int:
    total = 0
    if path.is_dir():
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    return total


def performance_cpus() -> list[int]:
    """One logical CPU per fastest-class physical core. Empty when that can't be determined."""
    best: dict[str, tuple[int, int]] = {}
    root = Path("/sys/devices/system/cpu")
    try:
        for cpu in sorted(root.glob("cpu[0-9]*"), key=lambda p: int(p.name[3:])):
            speed = int((cpu / "cpufreq" / "cpuinfo_max_freq").read_text())
            core = (cpu / "topology" / "core_id").read_text().strip()
            package = (cpu / "topology" / "physical_package_id").read_text().strip()
            best.setdefault(f"{package}:{core}", (int(cpu.name[3:]), speed))
    except (OSError, ValueError):
        return []
    if not best:
        return []
    top = max(speed for _, speed in best.values())
    return sorted(cpu for cpu, speed in best.values() if speed >= top * 0.9)


async def _run_capture(*argv: str, timeout: float = 15) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return 127, "not installed"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timed out"
    return proc.returncode or 0, out.decode(errors="replace").strip()


class InstallState:
    def __init__(self) -> None:
        self.state = "idle"
        self.step = ""
        self.progress = 0.0
        self.error = ""
        self.log: list[str] = []

    def as_dict(self) -> dict:
        return {"state": self.state, "step": self.step, "progress": round(self.progress, 4),
                "error": self.error, "log": self.log[-20:]}


async def _save_registry(spec: ModelSpec, *, status: str | None = None, size_bytes: int | None = None,
                         error: str | None = None, health: dict | None = None) -> None:
    """What survives a restart: install outcome and the last health check."""
    from sqlalchemy import select

    from app.database import session as db_session
    from app.database.models.voice import VoiceModelRegistry

    async with db_session.async_session_maker() as session:
        row = (await session.execute(
            select(VoiceModelRegistry).where(VoiceModelRegistry.model_id == spec.id)
        )).scalars().first()
        if row is None:
            row = VoiceModelRegistry(model_id=spec.id)
            session.add(row)
        if status is not None:
            row.status = status
            row.installed_revision = spec.revision if status == "installed" else row.installed_revision
        if size_bytes is not None:
            row.size_bytes = size_bytes
        if error is not None:
            row.error = error[:4000]
        if health is not None:
            row.health = health
        await session.commit()


async def _read_registry() -> dict:
    from sqlalchemy import select

    from app.database import session as db_session
    from app.database.models.voice import VoiceModelRegistry

    async with db_session.async_session_maker() as session:
        rows = (await session.execute(select(VoiceModelRegistry))).scalars().all()
    return {r.model_id: r for r in rows}


class VoiceModelManager:
    def __init__(self) -> None:
        self._workers: dict[str, WorkerProcess] = {}
        self._loaded: dict[str, dict] = {}  # env name → info about the loaded model
        self._installs: dict[str, InstallState] = {}
        self._install_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._idle_task: asyncio.Task | None = None
        self._realtime_measured: dict[str, dict] = {}

    # ── Paths ────────────────────────────────────────────────────────────────

    @property
    def home(self) -> Path:
        return Path(get_settings().voice_home).expanduser()

    def env_path(self, env: EnvSpec) -> Path:
        return _envs_dir() / env.name

    def python(self, env: EnvSpec) -> Path:
        return self.env_path(env) / "bin" / "python"

    def weights_dir(self, spec: ModelSpec) -> Path:
        return self.home / "models" / spec.id

    def source_dir(self, spec: ModelSpec) -> Path | None:
        return self.home / "src" / spec.source_dir if spec.source_dir else None

    def is_installed(self, spec: ModelSpec) -> bool:
        if not self.python(spec.env).exists():
            return False
        source = self.source_dir(spec)
        if source and not source.is_dir():
            return False
        return all((self.weights_dir(spec) / f).exists() for f in spec.required_files)

    # ── Discovery ────────────────────────────────────────────────────────────

    def _compatibility(self, spec: ModelSpec, gpu_ok: bool) -> dict:
        notes: list[str] = []
        ok = True
        ram = psutil.virtual_memory().total / 2**30
        if ram < spec.min_ram_gb:
            ok = False
            notes.append(f"Needs {spec.min_ram_gb} GB of RAM; this machine has {ram:.0f} GB.")
        free = shutil.disk_usage(self.home if self.home.exists() else Path.home()).free / 2**30
        if not self.is_installed(spec) and free < spec.download_gb + 1:
            ok = False
            notes.append(f"Needs {spec.download_gb} GB of free disk; {free:.1f} GB is available.")
        if not gpu_ok and spec.kind == "vc" and not spec.extra.get("cpu_preferred"):
            notes.append("No working GPU: this engine is far too slow on a CPU to run live.")
        elif not gpu_ok and spec.kind == "vc":
            notes.append("No working GPU: runs continuously, with a delay of a few seconds.")
        elif not gpu_ok and spec.kind == "tts":
            notes.append("No working GPU: generation runs on the CPU, slower than playback.")
        return {"ok": ok, "notes": notes}

    async def list_models(self) -> list[dict]:
        gpu_ok = (await self._gpu_facts())["smi_ok"]
        registry = await _read_registry()
        out = []
        for spec in catalog.MODELS:
            loaded = self._loaded.get(spec.env.name, {})
            is_loaded = loaded.get("model_id") == spec.id and self._worker_running(spec.env)
            installed = self.is_installed(spec)
            install = self._installs.get(spec.id)
            out.append({
                "id": spec.id, "name": spec.name, "kind": spec.kind, "license": spec.license,
                "description": spec.description, "optional": spec.optional, "repo_url": spec.repo_url,
                "revision": spec.revision, "download_gb": spec.download_gb, "min_ram_gb": spec.min_ram_gb,
                "min_vram_gb": spec.min_vram_gb,
                "status": "installing" if install and install.state == "running" else ("installed" if installed else "not_installed"),
                "installed": installed, "loaded": is_loaded, "device": loaded.get("device") if is_loaded else None,
                "size_bytes": _dir_size(self.weights_dir(spec)) if installed else 0,
                "location": str(self.weights_dir(spec)), "env_path": str(self.env_path(spec.env)),
                "env_ready": self.python(spec.env).exists(),
                "install": install.as_dict() if install else None,
                "health": registry[spec.id].health if spec.id in registry else {},
                "installed_revision": registry[spec.id].installed_revision if spec.id in registry else "",
                "compatibility": self._compatibility(spec, gpu_ok),
                "realtime": self._realtime_measured.get(spec.id),
            })
        return out

    # ── Hardware ─────────────────────────────────────────────────────────────

    async def _gpu_facts(self) -> dict:
        facts = {"pci_present": False, "pci_name": "", "driver_loaded": False, "driver_version": "",
                 "smi_ok": False, "smi_message": "", "name": "", "vram_total_mb": 0, "vram_free_mb": 0}
        _, pci = await _run_capture("lspci", "-nn")
        for line in pci.splitlines():
            if "NVIDIA" in line and ("VGA" in line or "3D" in line):
                facts["pci_present"] = True
                match = re.search(r"\]: (.*?) \[", line)
                facts["pci_name"] = match.group(1) if match else line
                break
        version = Path("/proc/driver/nvidia/version")
        if version.exists():
            facts["driver_loaded"] = True
            match = re.search(r"Kernel Module(?: for \S+)?\s+(\d[\d.]+)", version.read_text())
            if match:
                facts["driver_version"] = match.group(1)
        code, out = await _run_capture(
            "nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits",
        )
        if code == 0 and out and "," in out:
            name, total, free = [p.strip() for p in out.splitlines()[0].split(",")]
            facts.update(smi_ok=True, name=name, vram_total_mb=int(total), vram_free_mb=int(free))
            facts["smi_message"] = "ok"
        else:
            facts["smi_message"] = out.splitlines()[0][:200] if out else f"exit code {code}"
        return facts

    async def hardware(self, probe: bool = False) -> dict:
        gpu = await self._gpu_facts()
        torch_info = None
        if probe:
            for spec in catalog.of_kind("tts") + catalog.of_kind("vc"):
                if self.python(spec.env).exists():
                    try:
                        torch_info, _ = await (await self._worker(spec.env)).request("health", timeout=120)
                    except WorkerFailure as exc:
                        torch_info = {"cuda_available": False, "error": f"{exc.code}: {exc}"}
                    break
        gpu["torch"] = torch_info
        mem = psutil.virtual_memory()
        cpu_model = ""
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
        device = self.selected_device(gpu)
        self.home.mkdir(parents=True, exist_ok=True)
        return {
            "cpu": {"model": cpu_model, "threads": psutil.cpu_count() or 0},
            "ram": {"total_gb": round(mem.total / 2**30, 1), "available_gb": round(mem.available / 2**30, 1)},
            "disk_free_gb": round(shutil.disk_usage(self.home).free / 2**30, 1),
            "gpu": gpu, "selected_device": device, "summary": self._summary(gpu, device),
        }

    @staticmethod
    def selected_device(gpu: dict) -> str:
        requested = get_settings().voice_device
        if requested == "cpu":
            return "cpu"
        return "cuda" if gpu["smi_ok"] else "cpu"

    @staticmethod
    def _summary(gpu: dict, device: str) -> str:
        if device == "cuda":
            return f"Using the GPU: {gpu['name']}, {gpu['vram_free_mb']} MB of VRAM free."
        if gpu["pci_present"] and gpu["driver_loaded"] and not gpu["smi_ok"]:
            return (f"Running on the CPU. {gpu['pci_name']} is installed and its driver is loaded, but the card "
                    f"failed to initialize ({gpu['smi_message']}). Restart the computer to reset it. "
                    "Until then, speech generation is slower than playback and live conversion has a delay of a few seconds.")
        if gpu["pci_present"]:
            return f"Running on the CPU. {gpu['pci_name']} is installed, but no working NVIDIA driver was found."
        return "Running on the CPU. No NVIDIA GPU was found."

    # ── Workers ──────────────────────────────────────────────────────────────

    def _worker_running(self, env: EnvSpec) -> bool:
        worker = self._workers.get(env.name)
        return bool(worker and worker.running)

    async def _worker(self, env: EnvSpec) -> WorkerProcess:
        worker = self._workers.get(env.name)
        if worker is None:
            cores = psutil.cpu_count(logical=False) or 4
            threads = max(2, min(8, cores))
            args = ["--threads", str(threads)]
            if env.worker == "tts_worker.py":
                args += ["--asr-dir", str(self.home / "models" / "faster-whisper")]
            else:
                cpus = performance_cpus()
                if cpus:
                    args = ["--threads", str(max(2, min(8, len(cpus)))), "--cpus", ",".join(map(str, cpus))]
            worker = WorkerProcess(
                env.name, self.python(env), env.worker, args=args,
                env={"HF_HOME": str(self.home / "hf-cache")},
            )
            self._workers[env.name] = worker
        await worker.start()
        self._ensure_idle_task()
        return worker

    def _device_arg(self) -> str:
        return get_settings().voice_device

    async def tts_worker(self, model_id: str) -> WorkerProcess:
        """A worker with this model loaded. Only one TTS model at a time."""
        spec = catalog.find(model_id)
        if spec is None:
            raise WorkerFailure("unknown_model", model_id)
        if not self.is_installed(spec):
            raise WorkerFailure("model_not_installed", spec.name)
        async with self._lock:
            # Callers refuse to run during a live session, so this worker is idle: free its memory.
            await self._stop_worker(catalog.VC_ENV)
            worker = await self._worker(spec.env)
            info, _ = await worker.request(
                "load", {"model_id": spec.id, "path": str(self.weights_dir(spec)), "device": self._device_arg()},
                timeout=900,
            )
            self._loaded[spec.env.name] = {"model_id": spec.id, "device": info["device"]}
        return worker

    async def vc_worker(self, spec: ModelSpec, *, diffusion_steps: int | None = None) -> tuple[WorkerProcess, dict]:
        if not self.is_installed(spec):
            raise WorkerFailure("model_not_installed", spec.name)
        async with self._lock:
            # Controlled loading: the voices of a live session must not compete with TTS for
            # an 8 GB card. Stopping the worker is what actually returns the memory.
            await self._stop_worker(catalog.TTS_ENV)
            worker = await self._worker(spec.env)
            args = {"engine": spec.id, "source_dir": str(self.source_dir(spec)),
                    "weights_dir": str(self.weights_dir(spec)), "device": self._device_arg()}
            if diffusion_steps:
                args["diffusion_steps"] = diffusion_steps
            info, _ = await worker.request("load", args, timeout=900)
            self._loaded[spec.env.name] = {"model_id": spec.id, "device": info["device"]}
        return worker, info

    async def choose_vc_spec(self) -> ModelSpec | None:
        """The engine that suits the hardware that works right now."""
        gpu = await self._gpu_facts()
        use_cpu = self.selected_device(gpu) == "cpu"
        installed = [s for s in catalog.of_kind("vc") if self.is_installed(s)]
        installed.sort(key=lambda s: bool(s.extra.get("cpu_preferred")) != use_cpu)
        return installed[0] if installed else None

    def record_realtime(self, model_id: str, stats: dict) -> None:
        self._realtime_measured[model_id] = stats

    async def _stop_worker(self, env: EnvSpec) -> None:
        worker = self._workers.get(env.name)
        if worker:
            await worker.stop()
        self._loaded.pop(env.name, None)

    async def load(self, model_id: str) -> dict:
        spec = catalog.get(model_id)
        if not self.is_installed(spec):
            raise ManagerError("model_not_installed")
        try:
            if spec.kind == "tts":
                await self.tts_worker(model_id)
            else:
                await self.vc_worker(spec)
        except WorkerFailure as exc:
            raise ManagerError(exc.code, status=503) from exc
        return {"loaded": True, **self._loaded[spec.env.name]}

    async def unload(self, model_id: str) -> dict:
        spec = catalog.get(model_id)
        await self._stop_worker(spec.env)
        return {"loaded": False}

    async def health_check(self, model_id: str) -> dict:
        """Actually runs the model; a process that merely starts proves nothing."""
        spec = catalog.get(model_id)
        if not self.is_installed(spec):
            raise ManagerError("model_not_installed")
        started = time.monotonic()
        result: dict
        try:
            if spec.kind == "tts":
                worker = await self.tts_worker(model_id)
                info, _ = await worker.request("probe_inference", {"model_id": model_id}, timeout=900)
                result = {"ok": True, "device": info["device"]}
            else:
                from app.voice.realtime import get_realtime

                if get_realtime().active:
                    raise ManagerError("live_conversion_active")
                worker, _ = await self.vc_worker(spec)
                info, _ = await worker.request("probe_inference", timeout=300)
                result = {"ok": True, "device": info["device"], "proc_ms": info["proc_ms"], "block_ms": info["block_ms"]}
        except WorkerFailure as exc:
            result = {"ok": False, "error": f"{exc.code}: {exc}"[:500]}
        result["seconds"] = round(time.monotonic() - started, 1)
        result["at"] = time.time()
        await _save_registry(spec, status="installed", size_bytes=_dir_size(self.weights_dir(spec)), health=result)
        return result

    # ── Installation ─────────────────────────────────────────────────────────

    def start_install(self, model_id: str) -> dict:
        spec = catalog.get(model_id)
        if self._install_task and not self._install_task.done():
            raise ManagerError("install_in_progress")
        state = InstallState()
        state.state = "running"
        self._installs[model_id] = state
        self._install_task = asyncio.create_task(self._install(spec, state))
        return state.as_dict()

    async def _exec(self, state: InstallState, *argv: str, cwd: str | None = None) -> None:
        state.log.append("$ " + " ".join(argv))
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=cwd,
            env={**os.environ, "HF_HUB_DISABLE_TELEMETRY": "1"},
        )
        assert proc.stdout is not None
        tail: list[str] = []
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if line:
                tail = (tail + [line])[-15:]
                state.log.append(line[-300:])
                state.log = state.log[-60:]
        code = await proc.wait()
        if code != 0:
            raise ManagerError("\n".join(tail)[-1500:] or f"command failed with exit code {code}", status=500)

    async def _install(self, spec: ModelSpec, state: InstallState) -> None:
        try:
            await self._install_steps(spec, state)
            if not self.is_installed(spec):
                raise ManagerError("Installation finished, but the expected files are missing.", status=500)
            state.state = "done"
            state.step = "Installed"
            state.progress = 1.0
            await _save_registry(spec, status="installed", size_bytes=_dir_size(self.weights_dir(spec)), error="")
        except Exception as exc:  # noqa: BLE001 — shown to the operator as the reason it failed
            log.exception("voice model install failed: %s", spec.id)
            state.state = "failed"
            state.step = "Installation failed"
            state.error = str(exc)
            await _save_registry(spec, status="failed", error=str(exc))

    async def _install_steps(self, spec: ModelSpec, state: InstallState) -> None:
        env = spec.env
        python = self.python(env)
        if not python.exists():
            conda = _conda_bin()
            if not conda:
                raise ManagerError("conda was not found. Set VOICE_CONDA_BIN.", status=500)
            state.step = f"Creating the {env.name} environment"
            state.progress = 0.02
            await self._exec(state, conda, "create", "-y", "-q", "-p", str(self.env_path(env)), f"python={env.python}")
        state.step = "Installing PyTorch (about 3 GB)"
        state.progress = 0.05
        await self._exec(state, str(python), "-m", "pip", "install", "-q", "torch", "torchaudio", "--index-url", env.torch_index)
        state.step = "Installing Python packages"
        state.progress = 0.3
        await self._exec(state, str(python), "-m", "pip", "install", "-q", *env.packages)
        if spec.source_repo:
            source = self.source_dir(spec)
            assert source is not None
            source.parent.mkdir(parents=True, exist_ok=True)
            state.step = "Downloading the engine source"
            state.progress = 0.4
            if not source.is_dir():
                await self._exec(state, "git", "clone", "-q", spec.source_repo, str(source))
            await self._exec(state, "git", "-C", str(source), "checkout", "-q", spec.source_commit)
        target = self.weights_dir(spec)
        target.mkdir(parents=True, exist_ok=True)
        state.step = f"Downloading model weights ({spec.download_gb} GB)"
        payload = json.dumps({"dir": str(target), "weights": [
            {"repo": w.repo, "revision": w.revision, "filename": w.filename, "patterns": list(w.patterns), "subdir": w.subdir}
            for w in spec.weights
        ]})

        async def watch_progress() -> None:
            expected = spec.download_gb * 1e9
            while True:
                state.progress = 0.45 + 0.54 * min(1.0, _dir_size(target) / expected)
                await asyncio.sleep(1)

        watcher = asyncio.create_task(watch_progress())
        try:
            await self._exec(state, str(python), str(WORKERS_DIR / "fetch_weights.py"), payload)
        finally:
            watcher.cancel()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _ensure_idle_task(self) -> None:
        if self._idle_task is None or self._idle_task.done():
            self._idle_task = asyncio.create_task(self._idle_loop())

    async def _idle_loop(self) -> None:
        while any(w.running for w in self._workers.values()):
            await asyncio.sleep(30)
            limit = get_settings().voice_idle_unload_s
            for name, worker in self._workers.items():
                if worker.running and not worker.busy and time.monotonic() - worker.last_used > limit:
                    log.info("unloading idle voice worker %s", name)
                    await worker.stop()
                    self._loaded.pop(name, None)

    async def shutdown(self) -> None:
        for worker in self._workers.values():
            await worker.stop()
        self._loaded.clear()
        from app.voice.virtual_mic import get_virtual_mic

        await get_virtual_mic().disable()


_manager: VoiceModelManager | None = None


def get_manager() -> VoiceModelManager:
    global _manager
    if _manager is None:
        _manager = VoiceModelManager()
    return _manager
