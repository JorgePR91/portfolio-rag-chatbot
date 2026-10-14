"""POST /api/chat — chatbot del portfolio (función Python en Vercel).

Flujo de cada mensaje:

    rate limit → guardrail ∥ router → RAG → generación con herramientas

El guardrail y el router se ejecutan en paralelo. El modelo solo puede
responder con lo que recupera el RAG de los .md de backend/me/. Lo que no sabe
lo registra con una herramienta que avisa por Telegram (ver tools.py), en lugar
de inventarlo. El evaluador-optimizador existe, pero está desactivado (ver
USAR_EVALUADOR). Cada petición deja una línea [metricas] en el log.
"""
import os, sys

# Vercel ejecuta cada fichero de api/ por separado: se añade su carpeta a la
# ruta para poder importar los módulos vecinos (patterns, rag, llm, tools).
sys.path.insert(0, os.path.dirname(__file__))
import entorno  # noqa: F401  (carga backend/.env en local)
from patterns import NOMBRE, check_guardrail, route, route_instructions, evaluate
import traceback
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal
import json
from rag import recuperar
from llm import responder, uso, PRECIO_ENTRADA, PRECIO_SALIDA
import tools

from fastapi import Request, HTTPException
from upstash_ratelimit import Ratelimit, FixedWindow
from upstash_redis import Redis

import time
from contextlib import contextmanager

import contextvars
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()

# Orígenes del frontend, separados por comas (los mismos que usa contact.js).
ORIGENES_PERMITIDOS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:4200").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES_PERMITIDOS,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

# El historial llega del navegador, así que no es de fiar: se valida el rol
# (nada de "system") y se limita la longitud para que nadie dispare el coste.
MAX_HISTORIAL = 10  # últimos mensajes que se envían al modelo


class Mensaje(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[Mensaje] = []
    # Un idioma desconocido da error 422 en lugar de responder en castellano
    # sin avisar.
    lang: Literal["es", "en", "ca", "va"] = "es"


# 10 mensajes por minuto e IP: cada mensaje cuesta varias llamadas al LLM
# (guardrail, router y generación), así que se limita el gasto.
redis = Redis.from_env()
limitador = Ratelimit(
    redis=redis,
    limiter=FixedWindow(max_requests=10, window=60),
)

# Solo estas funciones puede ejecutar el modelo. Con getattr(tools, nombre)
# podría llamar a cualquier cosa del módulo, incluida push().
HERRAMIENTAS = {
    "record_user_details": tools.record_user_details,
    "record_unknown_question": tools.record_unknown_question,
}
MAX_VUELTAS = 3  # tope de rondas de herramientas, para no colgarse

# Evaluador-optimizador: desactivado por defecto. Medido con evals/chatbot.py,
# no detectó ningún error real y empeoró respuestas correctas, a cambio de
# ~1 s y al menos una llamada más por mensaje. Se reactiva con USAR_EVALUADOR=1.
USAR_EVALUADOR = os.getenv("USAR_EVALUADOR", "0") == "1"

# Idioma de la web (lo envía el frontend) → idioma en que debe responder el modelo.
IDIOMAS = {
    "es": "español",
    "en": "inglés (English)",
    "ca": "valenciano/català",
    "va": "valenciano/català",
}

# Mensaje de rechazo del guardrail, por idioma.
RECHAZO_GUARDRAIL = {
    "es": f"Lo siento, solo puedo hablar del perfil de {NOMBRE}.",
    "en": f"Sorry, I can only talk about {NOMBRE}'s profile.",
    "ca": f"Ho sent, només puc parlar del perfil de {NOMBRE}.",
    "va": f"Ho sent, només puc parlar del perfil de {NOMBRE}.",
}


def construir_system_prompt(fragmentos, lang="es"):
    idioma = IDIOMAS[lang]

    # fragmentos = lista de (texto, origen, score) que devuelve recuperar()

    persona = f"""Actúas como {NOMBRE}. Respondes en su sitio web preguntas
        sobre su trayectoria, formación, habilidades y experiencia.
        Tono profesional y cercano, como ante un posible cliente o empleador."""

    reglas = f"""
        - IMPORTANTE: responde SIEMPRE en {idioma}, con independencia del
          idioma en que esté escrita la pregunta o el contexto.
        - Responde ÚNICAMENTE con la información del CONTEXTO de abajo.
        - Si la respuesta NO está en el contexto, NO la inventes: usa la
          herramienta 'record_unknown_question' para registrar la pregunta.
        - Si el visitante muestra interés en contactar, pídele su email y
          regístralo con 'record_user_details'.
        - Si la pregunta da por hecho algo que el CONTEXTO contradice (un dato
          o una cifra distintos), corrígelo con el dato correcto del CONTEXTO.
          Eso SÍ es saber la respuesta: no la registres como desconocida.
        - Responde a lo que se pregunta, no a todo lo que hay en el CONTEXTO.
          Si el CONTEXTO indica cuándo es relevante una información (por
          ejemplo, "solo son relevantes si se pregunta por..."), respétalo."""

    # ensamblar el contexto a partir de los fragmentos
    contexto = ""
    for texto, origen, _ in fragmentos:
        contexto += f"### Fuente: {origen}\n{texto}\n\n"

    return persona + "\n" + reglas + "\n\n## CONTEXTO\n" + contexto


def permitido(ip):
    try:
        return limitador.limit(ip).allowed
    except Exception as e:
        # Fail-open: si Redis no responde, el chat sigue funcionando.
        print(
            f"[ratelimit] Redis no disponible, se deja pasar: {type(e).__name__}",
            flush=True,
        )
        return True


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):

    # 1) PRIMERO el rate limit, antes de cualquier llamada que cueste dinero.
    # Vercel rellena x-forwarded-for con la IP real del cliente.
    ip = (
        request.headers.get("x-forwarded-for", request.client.host)
        .split(",")[0]
        .strip()
    )
    if not permitido(ip):
        raise HTTPException(
            status_code=429, detail="Demasiadas peticiones, inténtalo más tarde."
        )

    # 2) El resto, protegido: una excepción sin capturar daría un 500 sin
    # cabeceras CORS, y el navegador solo vería "error de CORS".
    try:
        reply, _ = procesar(req)
        return {"reply": reply}
    except Exception:
        traceback.print_exc()  # queda en los logs de Vercel
        raise HTTPException(
            status_code=503, detail="El asistente no está disponible ahora mismo."
        )


def ms_desde(inicio):
    return round((time.perf_counter() - inicio) * 1000)


@contextmanager
def medir(metricas, etapa):
    # Uso: with medir(metricas, "router"): ...  -> guarda los ms de ese bloque.
    inicio = time.perf_counter()
    try:
        yield
    finally:
        metricas["etapas_ms"][etapa] = ms_desde(inicio)


def medido(metricas, etapa, funcion, *args):
    # medir() en forma de función, para poder ejecutarla en otro hilo.
    with medir(metricas, etapa):
        return funcion(*args)


def procesar(req: ChatRequest) -> tuple[str, dict]:
    """Ejecuta el flujo completo para un mensaje y devuelve (respuesta, métricas)."""
    # Métricas de la petición: se escriben en UNA línea de log al terminar,
    # pase lo que pase (respuesta normal, bloqueo del guardrail o excepción).
    # Sin el texto del usuario: solo números y categorías.
    metricas = {"lang": req.lang, "etapas_ms": {}}
    uso.set({"llamadas": 0, "tokens_entrada": 0, "tokens_salida": 0})
    inicio = time.perf_counter()
    try:
        return _procesar(req, metricas), metricas
    finally:
        metricas["total_ms"] = ms_desde(inicio)
        metricas.update(uso.get())
        metricas["coste_usd"] = round(
            metricas["tokens_entrada"] * PRECIO_ENTRADA
            + metricas["tokens_salida"] * PRECIO_SALIDA,
            6,
        )
        visibles = {k: v for k, v in metricas.items() if not k.startswith("_")}
        print("[metricas] " + json.dumps(visibles), flush=True)


def _procesar(req: ChatRequest, metricas) -> str:
    history = [m.model_dump() for m in req.history[-MAX_HISTORIAL:]]

    # (B) GUARDRAIL y (C) ROUTING, en paralelo: ninguno necesita el resultado
    # del otro, así que se espera al más lento en lugar de a la suma de los dos.
    # copy_context(): los hilos nuevos no heredan las ContextVar, y sin ella las
    # llamadas al LLM de cada hilo no sumarían en el contador 'uso'.
    with ThreadPoolExecutor(max_workers=2) as hilos:
        futuro_guard = hilos.submit(
            contextvars.copy_context().run,
            medido,
            metricas,
            "guardrail",
            check_guardrail,
            req.message,
        )
        futuro_ruta = hilos.submit(
            contextvars.copy_context().run,
            medido,
            metricas,
            "router",
            route,
            req.message,
            history,
        )
        guard = futuro_guard.result()
        if not guard.is_safe:
            metricas["bloqueado"] = True
            return RECHAZO_GUARDRAIL[req.lang]
        decision = futuro_ruta.result()
    metricas["categoria"] = decision.category
    extra = (
        "\n\n## Instrucción de enrutamiento ("
        + decision.category
        + "):\n"
        + route_instructions[decision.category]
    )

    # (D) RAG + SYSTEM PROMPT
    # Se busca con la consulta que devuelve el router: el tema de la pregunta,
    # en castellano (como los .md; el modelo de embeddings rinde mal en
    # valenciano), sin el nombre de la persona y autocontenida, así que también
    # resuelve las preguntas de seguimiento ("¿y dónde lo aprendió?").
    with medir(metricas, "rag"):
        fragmentos = recuperar(
            decision.consulta_es or req.message,
            k=4,
            incluir_secundarias=decision.pide_todo,
        )

    metricas["pide_todo"] = decision.pide_todo
    metricas["fragmentos"] = len(fragmentos)
    # Fichero y sección de cada fragmento ("skills.md > Idiomas"): la primera
    # línea de cada fragmento es su ruta de títulos.
    metricas["fuentes"] = sorted(
        {f"{origen} > {texto.splitlines()[0]}" for texto, origen, _ in fragmentos}
    )
    system = construir_system_prompt(fragmentos, req.lang)

    contexto = "".join(
        f"### {origen}\n{texto}\n\n" for (texto, origen, _) in fragmentos
    )

    # Herramientas ya ejecutadas en ESTA petición. La comparten la primera
    # generación y la regeneración, para no avisar dos veces por Telegram.
    ejecutadas = set()

    # (E) GENERACIÓN con herramientas
    with medir(metricas, "generacion"):
        reply = generar_respuesta(system, history, req.message, extra, ejecutadas)

    # (F) EVALUADOR-OPTIMIZADOR: desactivado por defecto (ver USAR_EVALUADOR).
    # Si está activo y rechaza la respuesta, se regenera una sola vez.
    if USAR_EVALUADOR:
        with medir(metricas, "evaluador"):
            ev = evaluate(reply, req.message, history, contexto, req.lang)
        metricas["motivo"] = ev.motivo
        if not ev.is_acceptable:
            # Para la evaluación offline: la respuesta rechazada, el porqué y las
            # herramientas usadas hasta ahora. Las claves que empiezan por "_" no
            # se escriben en el log: contienen texto que puede incluir datos del visitante.
            metricas["_revision"] = {
                "inicial": reply,
                "feedback": ev.feedback,
                "herramientas_inicial": sorted(ejecutadas),
            }
            feedback = (
                extra
                + "\n\n## Tu respuesta fue rechazada.\nRespuesta:\n"
                + reply
                + "\nMotivo:\n"
                + ev.feedback
                + "\nCorrígela."
            )
            with medir(metricas, "regeneracion"):
                reply = generar_respuesta(
                    system, history, req.message, feedback, ejecutadas
                )

    metricas["herramientas"] = sorted(ejecutadas)
    return reply


def generar_respuesta(system_base, history, message, extra_system="", ejecutadas=None):
    """Llama al modelo y ejecuta las herramientas que pida hasta obtener texto."""
    if ejecutadas is None:
        ejecutadas = set()

    messages = (
        [{"role": "system", "content": system_base + extra_system}]
        + history
        + [{"role": "user", "content": message}]
    )

    for _ in range(MAX_VUELTAS):
        resp = responder(messages, tools=tools.tools)
        msg = resp.choices[0].message
        if resp.choices[0].finish_reason != "tool_calls":
            return msg.content or ""

        messages.append(msg)
        for tool_call in msg.tool_calls:
            nombre = tool_call.function.name
            funcion = HERRAMIENTAS.get(nombre)
            try:
                args = json.loads(tool_call.function.arguments)
                if not funcion:
                    resultado = {"error": "herramienta desconocida"}
                elif nombre in ejecutadas:
                    # Ya se ejecutó en esta petición: se le confirma al modelo
                    # sin volver a avisar.
                    print(f"[tools] {nombre} ya ejecutada, se omite", flush=True)
                    resultado = {"recorded": "ok"}
                else:
                    resultado = funcion(**args)
                    ejecutadas.add(nombre)
            except Exception as e:
                resultado = {"error": type(e).__name__}
            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(resultado),
                    "tool_call_id": tool_call.id,
                }
            )

    # Si se agotan las vueltas, se pide una respuesta final SIN herramientas.
    return responder(messages).choices[0].message.content or ""
