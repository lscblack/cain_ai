# Voice Intelligence

Local voice cloning, text-to-speech and live voice conversion, in KAI under
**Voice Intelligence** (`/voice`). Everything runs on this machine. There are no paid APIs
and no audio leaves it.

## How it fits together

```
Browser (AudioWorklet)  ──WebSocket──▶  FastAPI (app/voice, app/api/voice.py)
   mic capture, playback                  auth, ownership, storage, sessions
                                              │ stdin/stdout frames
                        ┌─────────────────────┴─────────────────┐
                 kai_voice_tts env                        kai_voice_vc env
                 tts_worker.py                            vc_worker.py
                 Qwen3-TTS, Silero VAD, faster-whisper    Seed-VC, Silero VAD
                                                              │
                                              pw-cat ─▶ KAI Voice Sink ─▶ KAI Voice Microphone
```

The backend process never imports PyTorch. Models run in worker processes inside their own
conda environments because their dependencies conflict (Seed-VC needs Python 3.10 and
`numpy<2`, Qwen3-TTS needs `transformers==4.57.3`). Stopping a worker is what returns its memory.

- **Storage:** audio lives under `VOICE_HOME` (default `~/.local/share/kai-voice/users/<user>/`), mode
  0600. PostgreSQL holds references, metadata and ownership.
- **Voice representations** are stored per engine with the engine id, revision and format version.
- **Live conversion and speech generation don't run at once.** Starting one while the other is busy
  returns a clear error, so they never compete for an 8 GB card.

## Setup

1. Apply the migration from `backend/`:
   ```bash
   conda run -n fastapi_setup alembic upgrade head
   ```
2. Restart the backend and the frontend. The frontend sends `/api/voice` straight to
   `http://127.0.0.1:8008`; set `VITE_VOICE_API_URL` if your backend is elsewhere.
3. Open KAI **on this machine** (`http://localhost:<port>`), then go to
   **Voice Intelligence → Model Management** and install:
   - **Qwen3-TTS 0.6B Base** (about 2.5 GB, plus about 8 GB for its environment)
   - **Seed-VC Tiny** (about 1.6 GB, plus about 7 GB for its environment)
   - **OpenVoice V2** (0.13 GB, shares the Seed-VC environment), for when there's no working GPU

Settings (`.env`):

| Setting | Default | Meaning |
|---|---|---|
| `VOICE_HOME` | `~/.local/share/kai-voice` | Audio and model weights |
| `VOICE_ENVS_DIR` | conda's envs folder | Where the model environments are created |
| `VOICE_CONDA_BIN` | found automatically | Path to `conda` |
| `VOICE_DEVICE` | `auto` | `auto`, `cuda` or `cpu` |
| `VOICE_TTS_MODEL` | `qwen3-tts-0.6b` | Default model for new voices |
| `VOICE_UPLOAD_MAX_MB` | `100` | Upload limit |
| `VOICE_TTS_MAX_CHARS` | `20000` | Longest text for one generation |
| `VOICE_RATE_LIMIT_PER_MIN` | `30` | Limit per operator for costly operations |
| `VOICE_IDLE_UNLOAD_S` | `600` | Stop an idle worker after this long |
| `VOICE_ALLOW_REMOTE` | `false` | See *Access* below |

## Access

Voice recordings are biometric data, so voice routes **refuse anything that arrives through a proxy
or tunnel** (Cloudflare, Tailscale Serve, reverse proxies) with `voice_local_only`.

Only set `VOICE_ALLOW_REMOTE=true` after turning off `KAI_OPEN_ACCESS`. While open access is on,
`POST /auth/open` gives a token to anyone who can reach the backend, and that includes the public tunnel.

## Consent and responsible use

Creating a voice or replacing its recording requires an attestation: it's your own voice, or a named
person gave explicit permission. The attestation is stored with the voice and in the audit log. KAI
can't verify it; it's a record of what the operator declared.

Don't clone anyone without their permission, deceive people about who is speaking, or try to get past
voice authentication. If you use the virtual microphone on a call, tell people your voice is being
converted. A badge in the header shows whenever conversion is on, on every page, and every session is
recorded. Deleting a voice removes its recordings, voice data and all speech generated with it.

The voice module deliberately has no connection to KAI's investigation data: chat and the agents
can't call it, and voices can only come from an upload or the microphone.

## Using it

**Clone a voice:** record or upload 5 to 30 seconds of one person speaking clearly, and name it. An exact
transcript gives the best match; if you leave it empty, KAI transcribes the recording locally.

**Text-to-speech:** choose a voice, type, and generate. Long text is split at sentences and paragraphs,
each piece is leveled, and they're joined with short pauses. Download as WAV or MP3.

- *Speed* and *pitch* are applied after synthesis, because the model has neither control.
- *Expressiveness* is the sampling temperature. The cloning model has no emotion presets, so KAI doesn't offer any.

**Live voice changer:** choose a voice and press Start. KAI first times real inference on this machine:

- KAI picks Seed-VC on a working GPU and OpenVoice V2 on a CPU.
- **Fast enough:** conversion goes live. If a block ever falls behind, it's dropped and counted rather than
  letting the delay grow.
- **Too slow for short blocks, on OpenVoice V2:** KAI tries longer blocks, times each one, and shows how many seconds behind you it is.
- **Too slow:** KAI says so, with the measured numbers. You can choose **Convert with a delay**, which keeps every
  word and is labelled as not live. Each phrase plays once it's finished, both in the browser and on the virtual
  microphone, so it's continuous but arrives long after you said it.

Latency on screen is measured on each block, from capture to leaving the output device (using the delay the
browser reports for that device). Silence never reaches the model.

Use headphones when monitoring, or your speakers will feed back into the microphone.

### Virtual microphone (Linux, PipeWire)

Browser audio doesn't become a system microphone by itself. KAI's backend creates one:

1. Under **Live Voice Changer**, enable **KAI Voice Microphone**.
2. Check it exists: `wpctl status | grep -i kai`, or
   `pw-cli ls Node | grep kai_voice_mic`.
3. In Discord, Zoom, Meet or another app, choose **KAI Voice Microphone** as the input. Start conversion and speak.
4. To test without an app:
   ```bash
   pw-record --target kai_voice_mic --rate 48000 --channels 1 test.wav   # speak for a few seconds, then Ctrl+C
   pw-play test.wav
   ```

The backend must run on the same computer and as the same user as your desktop session, since PipeWire is per-user.
It needs `pw-loopback`, `pw-cat` and `pw-cli` (the `pipewire-bin` package). Browsers list the device after you
restart them or grant microphone access again.

## Measured performance

Measured on 2026-11-04 on an i7-13700HX (24 threads, CPU load average about 20 from other work), **with the GPU not
working**, so these are CPU numbers. Your numbers will differ; Model Management and the Live page show current ones.

| Operation | Engine | Result |
|---|---|---|
| Clone a voice (13 s reference) | Qwen3-TTS 0.6B | 3 to 15 s |
| Text-to-speech | Qwen3-TTS 0.6B | 4.7× to 7.9× slower than playback |
| Live conversion, about 2 s blocks, performance cores only | OpenVoice V2 | keeps up with no dropped audio; about 4.4 s behind in Chrome, while other KAI services shared the CPU |
| Live conversion, 180 ms blocks, 6 diffusion steps, 6 threads | Seed-VC Tiny | about 3,600 ms per block: **0.05× real time** |
| Best case tried: 500 ms blocks, 2 steps, 12 threads | Seed-VC Tiny | about 2,400 ms per block: **0.2× real time** |

Speaker similarity from an independent model (Resemblyzer; source and target speakers score 0.525 against each other):
cloned speech scored **0.94** against its target, and Seed-VC output **0.845** against its target and 0.622 against the source.

**On a GPU:** Seed-VC's authors report about 150 ms per block and 430 ms of total delay on an RTX 3060 Laptop (10 steps).
That is their figure, not one measured on this machine, so an RTX 4060 is expected to be real-time but **hasn't been verified**.

## Hardware

- Target: NVIDIA RTX 4060 Laptop (8 GB), 32 GB RAM, Ubuntu. Estimated VRAM, not yet measured on this card: 3 GB for Qwen3-TTS 0.6B, 6 GB for 1.7B, 2 GB for Seed-VC Tiny.
- Without a GPU: cloning and text-to-speech work, more slowly. Live conversion runs on OpenVoice V2 in pieces of about 2 s, so it stays a few seconds behind you: continuous, but too slow for natural conversation.
- Disk: about 20 GB for both environments and all default models.

## Engines and licenses

| Engine | License | Decision |
|---|---|---|
| Qwen3-TTS 0.6B / 1.7B | Apache-2.0 | Used. 0.6B by default; 1.7B is optional and untested here. |
| Seed-VC | GPL-3.0, **archived** upstream | Used for live conversion, pinned to its final commit, with its own environment and process. `seed_vc_engine.py` is GPL-3.0 because it imports Seed-VC. If you distribute KAI, check how the GPL applies to that. |
| Silero VAD | MIT | Used for speech detection. |
| faster-whisper | MIT | Only used to transcribe references. Never used in live conversion. |
| RVC | MIT | Not used: it needs a model trained per voice (minutes of clean audio, and hours of training on a CPU), which doesn't fit "pick any saved voice". The adapter design leaves room to add it. Not tested. |
| OpenVoice V2 | MIT | Used for live conversion when there's no working GPU. It changes timbre and keeps the speaker's pitch, so a cross-gender conversion is less convincing than Seed-VC's. Its optional audio watermark needs a whole clip, so it can't be used on a live stream. |

Seed-VC's real-time script crashes without CUDA because it calls `torch.cuda.Event` unconditionally, so KAI has
its own streaming loop.

## Testing

```bash
cd backend
conda run -n fastapi_setup pytest tests/test_voice_units.py tests/test_voice_api.py   # no models needed

# Real models against a running backend:
python ../scripts/kai_voice_verify.py clone --reference a.wav --name "Test A"
python ../scripts/kai_voice_verify.py tts   --name "Test A" --text "Hello there." --out out.wav
python ../scripts/kai_voice_verify.py live  --name "Test A" --source speech.wav --out converted.wav
python ../scripts/kai_voice_verify.py live  --name "Test A" --source speech.wav --virtual-mic vmic.wav
python ../scripts/kai_voice_verify.py delete --name "Test A"
```

`live` fails if the hardware is too slow; add `--delayed` to test the pipeline anyway. The API
needs authentication: set `KAI_TOKEN`, or leave it unset where open access is on.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| The KAI frontend won't stay up: `ENOSPC: System limit for number of file watchers reached` | `sudo sysctl fs.inotify.max_user_watches=524288`. To keep it, add that line to a file in `/etc/sysctl.d/`. |
| Polling instead of file watchers | `frontend/.env` sets `CHOKIDAR_USEPOLLING=true` so port 8011 runs despite the watcher limit. Remove it once the limit is raised. |
| On the `kai-frontend` service (port 5174) everything but voice fails with a 530 | That service doesn't set `VITE_API_URL`, so the proxy falls back to the default host in `vite.config.ts`. Set it in the unit, or use the `systmd-kai-frontend` service. |
| `nvidia-smi` says "No devices were found" | The kernel log (`journalctl -k \| grep NVRM`) shows `RmInitAdapter failed` / `GFW_BOOT`. The card is in a bad state after power management. Restart the computer. If it comes back, consider `NVreg_DynamicPowerManagement=0x00`, or a full power-off rather than a reboot. |
| PyTorch says CUDA is unavailable but `nvidia-smi` works | Model Management → **Test GPU in PyTorch** shows the reason. |
| "Live conversion can't run on this hardware" | Measured too slow. Check the GPU above. Close other heavy programs. |
| `voice_local_only` | You opened KAI through a tunnel. Open it on `localhost`. See *Access*. |
| Blocks dropped, or gaps in output | The machine is falling behind. Stop other GPU or CPU work. |
| No microphone or output device names | Grant the browser microphone access; device names are hidden until then. |
| Can't start recording | Browsers only allow the microphone on `localhost` or HTTPS. |
| Hearing an echo | Use headphones, or turn off monitoring. |
| App doesn't list KAI Voice Microphone | Enable it first, then restart the app. Check with `pw-cli ls Node`. |
| Generated speech starts with words from the recording | The voice was analyzed before the transcript check was added. Press **Re-analyze** on it in the Voice Library. |
| A voice sounds unlike its recording | Use a clean 10 to 30 second clip of one speaker with an exact transcript, then re-analyze. |
| Install failed | The Model Management card shows the error. Installing again resumes where it stopped. |
