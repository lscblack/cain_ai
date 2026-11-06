"""Voice Intelligence: voice profiles, cloned TTS and real-time voice conversion.

The FastAPI process never imports torch or a model. Models run in worker processes
inside their own conda environments (see ``catalog``, ``workers``), because they need
incompatible dependencies, and because Seed-VC is GPL-3.0 and stays process-isolated.
"""
