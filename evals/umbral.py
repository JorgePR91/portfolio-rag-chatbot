# Calibra vector_store.UMBRAL con los casos de evaluación: compara el score del
# fragmento correcto (preguntas con respuesta) con el del mejor fragmento
# (preguntas sin respuesta). Volver a ejecutarlo al cambiar los documentos o el
# modelo de embeddings, porque los scores cambian.
# Uso, desde la raíz:  python evals/umbral.py [ruta/a/casos.jsonl]
import json
import os
import sys

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "api"))
from patterns import route
from rag import recuperar
from vector_store import UMBRAL

CANDIDATOS = [0.60, 0.65, 0.68, 0.70, 0.72, 0.74, 0.76]
RUTA_CASOS = (
    sys.argv[1] if len(sys.argv) > 1
    else os.path.join(os.path.dirname(__file__), "casos.jsonl")
)

with open(RUTA_CASOS, encoding="utf-8") as f:
    casos = [json.loads(linea) for linea in f if linea.strip()]

con_respuesta, sin_respuesta = [], []  # (id, score)
for caso in casos:
    con = "fuentes" in caso
    sin = caso.get("herramienta") == "record_unknown_question"
    if caso.get("bloquear") or not (con or sin):
        continue
    # La misma consulta que usaría el bot: la del router, no la pregunta tal cual.
    decision = route(caso["pregunta"], caso.get("history", []))
    fragmentos = recuperar(
        decision.consulta_es or caso["pregunta"],
        k=4,
        umbral=0,  # sin filtrar: queremos ver todos los scores
        incluir_secundarias=decision.pide_todo,
    )
    if not fragmentos:
        continue
    if con:
        # Mismo formato que metricas["fuentes"] en chat.py: "fichero > sección".
        correctos = [
            score for texto, origen, score in fragmentos
            if any(f in f"{origen} > {texto.splitlines()[0]}" for f in caso["fuentes"])
        ]
        con_respuesta.append((caso["id"], max(correctos) if correctos else None))
    else:
        sin_respuesta.append((caso["id"], max(score for _, _, score in fragmentos)))

print("Con respuesta: score del fragmento correcto (de menor a mayor)")
for id_, score in sorted(con_respuesta, key=lambda x: x[1] or 0):
    print(f"  {'no recuperado' if score is None else f'{score:.3f}'}  {id_}")
print("\nSin respuesta: score del mejor fragmento (de mayor a menor)")
for id_, score in sorted(sin_respuesta, key=lambda x: -x[1]):
    print(f"  {score:.3f}  {id_}")

print(f"\n| UMBRAL | Correcto conservado | Sin respuesta, todo filtrado |\n|---|---|---|")
for t in CANDIDATOS:
    conserva = sum(1 for _, s in con_respuesta if s is not None and s >= t)
    filtra = sum(1 for _, s in sin_respuesta if s < t)
    actual = "  ← actual" if t == UMBRAL else ""
    print(f"| {t:.2f}{actual} | {conserva}/{len(con_respuesta)} | {filtra}/{len(sin_respuesta)} |")
