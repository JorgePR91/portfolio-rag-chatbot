"""Acceso a la base vectorial (Upstash Vector), compartido por la API y la ingesta.

El índice de Upstash está creado con un modelo de embeddings integrado: se le
envía texto plano (`data=`) y Upstash calcula los vectores, así que el proyecto
no necesita llamar a ninguna API de embeddings.
"""
from dotenv import load_dotenv
from upstash_vector import Index
from upstash_vector.types import Data

load_dotenv()

# Lee UPSTASH_VECTOR_REST_URL y UPSTASH_VECTOR_REST_TOKEN del entorno.
index = Index.from_env()

# ---------- SUBIR (ingesta) ----------
# El id "fichero.md#n" permite ver en los resultados de qué documento sale cada fragmento.
def subir(chunks):
    items = []
    for i, chunk in enumerate(chunks):
        id_chunk = f"{chunk.metadata['origen']}#{i}"
        items.append( Data(
            id = id_chunk,
            data = chunk.page_content,
            metadata = { 'origen': chunk.metadata['origen'] }
        ))
    index.upsert(items)

# ---------- BUSCAR (recuperación) ----------
# UMBRAL: descarta fragmentos poco parecidos a la pregunta. Sin esto, query()
# siempre devuelve k resultados aunque ninguno venga a cuento, y el modelo acaba
# "rellenando" con ruido. Si la lista vuelve vacía, chat.py deja que el modelo
# registre la pregunta como desconocida en vez de inventar.
# Es un valor a calibrar: pruébalo con `python rag.py "tu pregunta"` y mira los
# scores reales antes de subirlo/bajarlo.
UMBRAL = 0.65

def buscar(pregunta, k=4, umbral=UMBRAL):
    resultados = index.query(
        data = pregunta,
        top_k = k,
        include_metadata = True,
        include_data = True
    )
    return [ (r.data, r.metadata['origen'], r.score) for r in resultados if r.score >= umbral]

# Ejecutado directamente, muestra el estado del índice (número de vectores, etc.).
if __name__ == "__main__":
    print(index.info())