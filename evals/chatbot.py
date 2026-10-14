# Evaluación de extremo a extremo: lanza los casos de un fichero JSONL contra
# procesar() y mide guardrail, router, búsqueda, contenido, herramientas,
# latencia y coste.
# Uso, desde la raíz del proyecto:
#   python evals/chatbot.py                      # usa evals/casos.jsonl
#   python evals/chatbot.py ruta/a/casos.jsonl   # otro fichero de casos
# El formato de los casos se explica en evals/README.md.
import contextlib
import io
import json
import os
import statistics
import sys
import unicodedata


RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "api"))
import tools
from chat import ChatRequest, procesar, USAR_EVALUADOR

# Sin avisos reales a Telegram durante la evaluación. Las herramientas buscan
# push() en el módulo tools cada vez que se ejecutan, así que basta con sustituirla.
tools.push = lambda texto: None

COMPROBACIONES = ["guardrail", "router", "busqueda", "sabe", "contenido", "herramienta"]
RUTA_CASOS = (
    sys.argv[1] if len(sys.argv) > 1
    else os.path.join(os.path.dirname(__file__), "casos.jsonl")
)


def normalizar(texto):
    # Minúsculas y sin tildes: "València" y "valencia" cuentan igual.
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.lower()


def aparece(clave, texto):
    # "inmediat|immediat": basta con que aparezca una de las alternativas.
    return any(normalizar(alt) in texto for alt in clave.split("|"))


def cumple_contenido(caso, texto):
    texto = normalizar(texto)
    return all(aparece(c, texto) for c in caso.get("contiene", [])) and not any(
        aparece(c, texto) for c in caso.get("no_contiene", [])
    )


def comprobar(caso, reply, m):
    checks = {"guardrail": m.get("bloqueado", False) == caso.get("bloquear", False)}
    if m.get("bloqueado"):
        return checks  # bloqueado (con razón o sin ella): no hay nada más que mirar
    if "categoria" in caso:
        checks["router"] = m.get("categoria") == caso["categoria"]
    if "fuentes" in caso:
        # Basta con que una fuente esperada esté contenida en una recuperada:
        # "skills.md" acepta cualquier sección; "skills.md > Idiomas", solo esa.
        checks["busqueda"] = any(
            esperada in recuperada
            for esperada in caso["fuentes"]
            for recuperada in m.get("fuentes", [])
        )
        # Tiene respuesta en los .md: el bot no debe decir que no lo sabe.
        checks["sabe"] = "record_unknown_question" not in m.get("herramientas", [])
    if "contiene" in caso or "no_contiene" in caso:
        checks["contenido"] = cumple_contenido(caso, reply)
    if "herramienta" in caso:
        checks["herramienta"] = caso["herramienta"] in m.get("herramientas", [])
    return checks


def percentil(valores, p):
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(p / 100 * len(ordenados)))]


if not os.path.exists(RUTA_CASOS):
    sys.exit(
        f"No existe {RUTA_CASOS}. Copia evals/casos.ejemplo.jsonl como "
        "evals/casos.jsonl y adapta los casos a tu base de conocimiento."
    )
with open(RUTA_CASOS, encoding="utf-8") as f:
    casos = [json.loads(linea) for linea in f if linea.strip()]

resultados = []  # (caso, checks, metricas)
errores = 0
regeneradas = []  # (caso, revision, respuesta final, metricas)

for caso in casos:
    req = ChatRequest(
        message=caso["pregunta"],
        lang=caso.get("lang", "es"),
        history=caso.get("history", []),
    )
    try:
        # Se silencia el print de [metricas]: aquí ya se muestran los resultados.
        with contextlib.redirect_stdout(io.StringIO()):
            reply, m = procesar(req)
    except Exception as e:
        errores += 1
        print(f"! {caso['id']:<24} error: {type(e).__name__}")
        continue
    checks = comprobar(caso, reply, m)
    resultados.append((caso, checks, m))
    if "_revision" in m:
        regeneradas.append((caso, m["_revision"], reply, m))
    fallos = [nombre for nombre, ok in checks.items() if not ok]
    print(
        f"{'✗' if fallos else '✓'} {caso['id']:<24} {m['total_ms']:>5} ms  {', '.join(fallos)}"
    )
    if fallos:
        print(f"    respuesta: {reply[:200]!r}")
        print(f"    metricas:  {json.dumps(m, ensure_ascii=False)}")

# --- Resumen, en Markdown para poder pegarlo en el README ---
print(f"\nEvaluador: {'ACTIVADO' if USAR_EVALUADOR else 'desactivado'}")
print("\n| Métrica | Resultado |\n|---|---|")
for nombre in COMPROBACIONES:
    valores = [checks[nombre] for _, checks, _ in resultados if nombre in checks]
    if valores:
        print(
            f"| {nombre} | {sum(valores)}/{len(valores)} ({100 * sum(valores) / len(valores):.0f} %) |"
        )

# Latencia y coste, solo de los mensajes no bloqueados: los bloqueados hacen
# menos llamadas y bajarían la media de forma engañosa.
respondidos = [(caso, m) for caso, _, m in resultados if not m.get("bloqueado")]
if respondidos:
    tiempos = [m["total_ms"] for _, m in respondidos]
    print(f"| latencia p50 | {percentil(tiempos, 50)} ms |")
    print(f"| latencia p95 | {percentil(tiempos, 95)} ms |")
    print(
        f"| llamadas al LLM por mensaje (media) | {statistics.mean(m['llamadas'] for _, m in respondidos):.1f} |"
    )
    print(
        f"| coste por mensaje (media) | {statistics.mean(m['coste_usd'] for _, m in respondidos):.6f} $ |"
    )
if USAR_EVALUADOR:
    rechazos = sum(m.get("motivo") != "ninguno" for _, m in respondidos)
    print(f"| respuestas rechazadas por el evaluador | {rechazos}/{len(respondidos)} |")


# ¿El UMBRAL distingue las preguntas con respuesta de las que no la tienen?
con = [m["fragmentos"] for caso, m in respondidos if "fuentes" in caso]
sin = [
    m["fragmentos"]
    for caso, m in respondidos
    if caso.get("herramienta") == "record_unknown_question"
]
if con and sin:
    print(
        f"| fragmentos recuperados: con respuesta / sin respuesta | {statistics.mean(con):.1f} / {statistics.mean(sin):.1f} |"
    )

# --- ¿El evaluador mejora las respuestas que rechaza? ---
if regeneradas:
    print("\n## Respuestas rechazadas por el evaluador\n")
    balance = {"mejora": 0, "empeora": 0, "igual": 0}
    for caso, revision, final, m in regeneradas:
        efecto = ""
        if "contiene" in caso or "no_contiene" in caso:
            antes = cumple_contenido(caso, revision["inicial"])
            despues = cumple_contenido(caso, final)
            resultado = (
                "mejora"
                if despues > antes
                else "empeora" if despues < antes else "igual"
            )
            balance[resultado] += 1
            efecto = f"contenido {'✓' if antes else '✗'} -> {'✓' if despues else '✗'} ({resultado})"
        # La regeneración dice "no lo sé" donde la original no lo decía.
        if (
            "record_unknown_question" in m["herramientas"]
            and "record_unknown_question" not in revision["herramientas_inicial"]
        ):
            efecto += "  ¡registra como desconocida!"
        print(f"↻ {caso['id']}  motivo={m['motivo']}  {efecto}")
        print(f"    inicial:  {revision['inicial'][:300]!r}")
        print(f"    feedback: {revision['feedback'][:300]!r}")
        print(f"    final:    {final[:300]!r}\n")
    print(f"Balance de contenido: {balance}")


if errores:
    print(f"\n{errores} casos con error (no cuentan en el resumen)")
