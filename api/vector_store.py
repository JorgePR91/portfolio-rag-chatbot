"""Acceso a la base vectorial (Upstash Vector), compartido por la API y la ingesta.

El índice de Upstash está creado con un modelo de embeddings integrado: se le
envía texto plano (`data=`) y Upstash calcula los vectores, así que el proyecto
no necesita llamar a ninguna API de embeddings.
"""
import entorno  # noqa: F401  (carga backend/.env en local)

from upstash_vector import Index
from upstash_vector.types import Data

# Lee UPSTASH_VECTOR_REST_URL y UPSTASH_VECTOR_REST_TOKEN del entorno.
index = Index.from_env()


# ---------- SUBIR (ingesta) ----------
# El id "fichero.md#n" permite ver en los resultados de qué documento sale cada
# fragmento. Solo las secciones secundarias llevan el campo "secundaria".
def subir(chunks):
    items = []
    for i, chunk in enumerate(chunks):
        id_chunk = f"{chunk.metadata['origen']}#{i}"
        metadata = {"origen": chunk.metadata["origen"]}
        if chunk.metadata.get("secundaria"):
            metadata["secundaria"] = True
        items.append(Data(id=id_chunk, data=chunk.page_content, metadata=metadata))
    index.upsert(items)


# ---------- BUSCAR (recuperación) ----------
# UMBRAL: descarta fragmentos poco parecidos a la consulta. Calibrado con
# evals/umbral.py sobre la base de conocimiento real: el fragmento correcto
# puntuaba entre 0,685 y 0,853, y el mejor fragmento de las preguntas sin
# respuesta, entre 0,624 y 0,747. Las dos distribuciones se solapan, así que
# ningún umbral las separa: por encima de ~0,68 empieza a eliminar fragmentos
# correctos. Se queda en 0,65 como filtro de ruido; quien decide que no hay
# respuesta es el generador. Volver a calibrar al cambiar los documentos o el
# modelo de embeddings.
UMBRAL = 0.65


def buscar(pregunta, k=4, umbral=UMBRAL, incluir_secundarias=False):
    resultados = index.query(
        data=pregunta,
        top_k=k,
        include_metadata=True,
        include_data=True,
        # Las secciones secundarias solo entran si se piden: las demás no
        # tienen el campo, así que "HAS NOT FIELD" deja fuera solo las marcadas.
        filter="" if incluir_secundarias else "HAS NOT FIELD secundaria",
    )
    return [
        (r.data, r.metadata["origen"], r.score) for r in resultados if r.score >= umbral
    ]


# Ejecutado directamente, muestra el estado del índice (número de vectores, etc.).
if __name__ == "__main__":
    print(index.info())
