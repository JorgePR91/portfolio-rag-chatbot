"""GET /api/health — keep-alive diario de las bases de datos de Upstash."""
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from upstash_redis import Redis
from upstash_vector import Index

# Keep-alive: Upstash archiva las bases del plan gratuito tras ~30 días sin
# actividad. Vercel Cron llama a este endpoint una vez al día (ver vercel.json)
# y aquí se hace una operación real en cada base para que cuente como uso.

app = FastAPI()


@app.get("/api/health")
def health(authorization: str = Header(default="")):
    # Vercel Cron envía "Authorization: Bearer <CRON_SECRET>" si la variable
    # existe. Sin ella, cualquiera podría gastar comandos de Upstash llamando aquí.
    secreto = os.getenv("CRON_SECRET")
    if not secreto or authorization != f"Bearer {secreto}":
        raise HTTPException(status_code=401)

    estado = {}
    try:
        Redis.from_env().set("keepalive", datetime.now(timezone.utc).isoformat())
        estado["redis"] = "ok"
    except Exception as e:
        estado["redis"] = type(e).__name__
    try:
        # range() lee un vector sin calcular embeddings, así que no tiene coste.
        Index.from_env().range(cursor="", limit=1)
        estado["vector"] = "ok"
    except Exception as e:
        estado["vector"] = type(e).__name__

    print(f"[health] {estado}", flush=True)
    return estado
