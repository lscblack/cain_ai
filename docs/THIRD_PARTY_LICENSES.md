# Third-Party Licenses

KAI uses the following third-party software. Verify each license against your
intended use before any non-research/commercial deployment — **note the
InsightFace model caveat below.**

| Project | Purpose in KAI | License | Version |
|---------|----------------|---------|---------|
| FastAPI | Web framework | MIT | 0.141.1 |
| Starlette | ASGI toolkit (via FastAPI) | BSD-3 | bundled |
| Uvicorn | ASGI server | BSD-3 | 0.53.0 |
| Pydantic / pydantic-settings | Validation / config | MIT | 2.x |
| SQLModel | ORM models | MIT | 0.0.38 |
| SQLAlchemy | ORM core | MIT | 2.x |
| Alembic | DB migrations | MIT | 1.20 |
| psycopg (3) | PostgreSQL driver | LGPL-3.0 | 3.3.6 |
| asyncpg | (alt) PG driver | Apache-2.0 | 0.30 |
| redis-py | Redis client | MIT | 8.x |
| fakeredis | Test Redis | BSD-3 | 2.x |
| argon2-cffi | Password hashing | MIT | 25.x |
| python-jose | JWT | MIT | 3.x |
| phonenumbers | Phone parsing (libphonenumber port) | Apache-2.0 | 9.0.40 |
| dnspython | DNS lookups | ISC | — |
| httpx | HTTP client | BSD-3 | 0.28 |
| **InsightFace** | Face detection + ArcFace embeddings | **MIT (code)** | 2.0 |
| **buffalo_l model** | Pretrained detector + recognizer weights | **Non-commercial / research** | model-zoo |
| onnxruntime | Model inference | MIT | 1.30 |
| onnx | Model format | Apache-2.0 | 1.23 |
| OpenCV (opencv-python) | Image decode | Apache-2.0 | — |
| Pillow | Image ops / perceptual hash | HPND (PIL) | — |
| NumPy | Vector math | BSD-3 | — |
| React / React DOM | Frontend UI | MIT | 18.x |
| TypeScript | Types | Apache-2.0 | 5.x |
| Vite | Build tool | MIT | 5.x |
| Tailwind CSS | Styling | MIT | 3.x |
| Framer Motion | Animation | MIT | 11.x |
| lucide-react | Icons | ISC | — |
| react-router-dom | Routing | MIT | 6.x |
| Leaflet / react-leaflet | Maps | BSD-2 / MIT | 1.9 / 4.x |
| CARTO dark basemap tiles | Map tiles | CC-BY (attribution shown) | service |

## Important caveats

- **InsightFace pretrained models (buffalo_l):** the InsightFace *code* is MIT,
  but the pretrained model weights are distributed for **non-commercial /
  academic research use**. Do not use them in a commercial product without
  obtaining appropriate rights or training/using a commercially-licensed model.
- **psycopg3** is LGPL-3.0; dynamic linking as a library is generally fine, but
  review if you redistribute a bundled binary.
- Reference repositories named in the original brief
  (`arc_search`, `eye_of_web`, `osint-face-search`, `PhoneInfoga`) were **not
  copied** into this codebase; KAI reimplements equivalent functionality. If you
  later vendor any of their code, add it here with its license and commit hash.
