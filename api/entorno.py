# Carga backend/.env para ejecutar en local (uvicorn, evals, ingest, rag.py).
# En Vercel ese fichero no existe y no hace nada: allí las variables las
# inyecta la plataforma. Cada módulo que lee variables de entorno importa
# este módulo, así que no depende del orden en que se importen los demás.
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))
