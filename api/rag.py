"""Recuperación (la "R" de RAG) y herramienta de calibrado por línea de comandos.

Uso para probar qué fragmentos encuentra una pregunta:

    python rag.py "¿Sabe Angular?"
"""
import os
import sys
from dotenv import load_dotenv

# El .env está en backend/, no junto a este fichero. En Vercel no existe
# y load_dotenv no hace nada: allí las variables las inyecta Vercel.
# Se carga ANTES de importar vector_store, que conecta con Upstash al importarse.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

import vector_store

def recuperar(pregunta, k=4, umbral=vector_store.UMBRAL):
    """Devuelve hasta k fragmentos (texto, origen, score) parecidos a la pregunta."""
    return vector_store.buscar(pregunta, k, umbral)

if __name__=="__main__":
    pregunta = sys.argv[1]
    # umbral=0 para calibrar: muestra TODOS los scores, también los que el
    # backend descartaría, y así decides dónde poner UMBRAL en vector_store.py.
    for (texto, origen, score) in recuperar(pregunta, k=4, umbral=0):
        marca = "✓" if score >= vector_store.UMBRAL else "✗"
        print(f"{marca} [{score:.3f}] ({origen}) {texto[:120]}")
