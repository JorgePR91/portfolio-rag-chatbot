"""Recuperación (la "R" de RAG) y herramienta de calibrado por línea de comandos.

Uso para probar qué fragmentos encuentra un tema (es lo que busca el bot,
porque el router reescribe cada pregunta como un tema antes de buscar):

    python rag.py "nivel de inglés"
"""
import os
import re
import sys

import entorno  # noqa: F401  (carga backend/.env en local)
import vector_store


# Todos los documentos hablan de la misma persona: su nombre en la consulta no
# ayuda a encontrar el fragmento correcto, y acerca la búsqueda a los
# fragmentos genéricos ("Perfil", "Preguntas frecuentes"). En la evaluación,
# quitarlo llevó la sección correcta de la posición 23 a la 1 en algún caso.
# El router ya intenta quitarlo, pero no siempre lo hace; aquí se garantiza.
def _patron_nombre(nombre):
    # "Nombre Apellido1 Apellido2" -> el nombre solo, con uno o con los dos
    # apellidos, y la preposición que lo precede ("de Nombre").
    palabras = [re.escape(p) for p in nombre.split()]
    if not palabras:
        return None
    apellidos = "".join(rf"(?:\s+{p})?" for p in palabras[1:])
    return re.compile(
        rf"\b(?:(?:de|a|sobre|con|para)\s+)?{palabras[0]}{apellidos}\b",
        re.IGNORECASE,
    )


NOMBRE_EN_CONSULTA = _patron_nombre(os.getenv("PERFIL_NOMBRE", ""))


def limpiar_consulta(consulta):
    if NOMBRE_EN_CONSULTA is None:
        return consulta
    sin_nombre = NOMBRE_EN_CONSULTA.sub("", consulta)
    return re.sub(r"\s{2,}", " ", sin_nombre).strip(" ,.?¿")


def recuperar(pregunta, k=4, umbral=vector_store.UMBRAL, incluir_secundarias=False):
    """Devuelve hasta k fragmentos (texto, origen, score) parecidos a la consulta.

    Las secciones marcadas como secundarias solo se incluyen si se pide.
    """
    return vector_store.buscar(
        limpiar_consulta(pregunta) or pregunta, k, umbral, incluir_secundarias
    )


if __name__ == "__main__":
    pregunta = sys.argv[1]
    # umbral=0 para calibrar: muestra TODOS los scores, también los que el
    # backend descartaría. Para calibrar con datos, ver evals/umbral.py.
    for texto, origen, score in recuperar(pregunta, k=4, umbral=0):
        marca = "✓" if score >= vector_store.UMBRAL else "✗"
        print(f"{marca} [{score:.3f}] ({origen}) {texto[:120]}")
