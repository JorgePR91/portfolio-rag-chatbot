# Prueba el evaluador con respuestas preparadas cuyo veredicto ya se conoce.
# No depende de la base de conocimiento: el contexto es inventado.
# Uso, desde la raíz del proyecto:  python evals/evaluador.py
import os
import sys

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "api"))
from patterns import NOMBRE, evaluate

CONTEXTO = f"### experiencia.md\n{NOMBRE} trabaja como desarrollador web desde 2020.\n\n"

# (motivo esperado, respuesta, pregunta, lang)
CASOS = [
    ("ninguno", "Trabajo como desarrollador web desde 2020.",
     f"¿A qué se dedica {NOMBRE}?", "es"),
    ("ninguno", "No tengo información sobre sus aficiones.",
     f"¿Qué aficiones tiene {NOMBRE}?", "es"),
    ("inventa", "Trabajé cinco años en Google como ingeniero de IA.",
     f"¿Dónde ha trabajado {NOMBRE}?", "es"),
    ("idioma", "Trabajo como desarrollador web desde 2020.",
     f"What does {NOMBRE} do?", "en"),
    ("ninguno", "Treballe com a desenvolupador web des de 2020.",
     f"A què es dedica {NOMBRE}?", "va"),
    ("idioma", "Trabajo como desarrollador web desde 2020.",
     f"A què es dedica {NOMBRE}?", "va"),
]


aciertos = 0
for esperado, respuesta, pregunta, lang in CASOS:
    ev = evaluate(respuesta, pregunta, [], CONTEXTO, lang)
    ok = ev.motivo == esperado
    aciertos += ok
    print(f"{'✓' if ok else '✗'} esperado={esperado:<12} obtenido={ev.motivo:<12} {pregunta}")
    if not ok:
        print(f"    idioma_respuesta: {ev.idioma_respuesta}")
        print(f"    feedback: {ev.feedback}")


print(f"\n{aciertos}/{len(CASOS)} aciertos")
