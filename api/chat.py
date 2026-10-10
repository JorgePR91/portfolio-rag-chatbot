"""POST /api/chat — chatbot del portfolio (función Python en Vercel).

Flujo de cada mensaje:

    rate limit → guardrail → router → RAG → generación con herramientas → evaluador

El modelo solo puede responder con lo que recupera el RAG de los .md de
backend/me/. Lo que no sabe lo registra con una herramienta que avisa por
Telegram (ver tools.py), en lugar de inventarlo.
"""
import os, sys

# Vercel ejecuta cada fichero de api/ por separado: se añade su carpeta a la
# ruta para poder importar los módulos vecinos (patterns, rag, llm, tools).
sys.path.insert(0, os.path.dirname(__file__))
from patterns import NOMBRE, check_guardrail, route, route_instructions, evaluate
import traceback
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal
import json
from dotenv import load_dotenv
from rag import recuperar
from llm import responder
import tools

from fastapi import Request, HTTPException
from upstash_ratelimit import Ratelimit, FixedWindow
from upstash_redis import Redis

load_dotenv()

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
    lang: str = "es"


# 10 mensajes por minuto e IP: cada mensaje cuesta varias llamadas al LLM
# (guardrail, router, generación y evaluador), así que se limita el gasto.
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

# Idioma de la web (lo envía el frontend) → idioma en que debe responder el modelo.
IDIOMAS = {
    "es": "español",
    "en": "inglés (English)",
    "ca": "valenciano/català",
    "va": "valenciano/català",
}

# Mensaje de rechazo del guardrail, por idioma (fallback a español).
RECHAZO_GUARDRAIL = {
    "es": f"Lo siento, solo puedo hablar del perfil de {NOMBRE}.",
    "en": f"Sorry, I can only talk about {NOMBRE}'s profile.",
    "ca": f"Ho sent, només puc parlar del perfil de {NOMBRE}.",
    "va": f"Ho sent, només puc parlar del perfil de {NOMBRE}.",
}


def construir_system_prompt(fragmentos, lang="es"):
    idioma = IDIOMAS.get(lang, "español")

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
          regístralo con 'record_user_details'."""

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
        return {"reply": procesar(req)}
    except Exception:
        traceback.print_exc()  # queda en los logs de Vercel
        raise HTTPException(
            status_code=503, detail="El asistente no está disponible ahora mismo."
        )


def procesar(req: ChatRequest) -> str:
    """Ejecuta el flujo completo para un mensaje y devuelve la respuesta."""
    history = [m.model_dump() for m in req.history[-MAX_HISTORIAL:]]

    # (B) GUARDRAIL
    guard = check_guardrail(req.message)
    if not guard.is_safe:
        return RECHAZO_GUARDRAIL.get(req.lang, RECHAZO_GUARDRAIL["es"])

    # (C) ROUTING
    decision = route(req.message, history)
    extra = (
        "\n\n## Instrucción de enrutamiento ("
        + decision.category
        + "):\n"
        + route_instructions[decision.category]
    )

    # (D) RAG + SYSTEM PROMPT
    # Se busca con la reescritura en castellano que devuelve el router: los .md
    # están en castellano y el modelo de embeddings rinde mal en valenciano. Esa
    # reescritura además ya es autocontenida, así que resuelve las preguntas de
    # seguimiento ("¿y dónde lo aprendió?") mejor que concatenar el historial.
    fragmentos = recuperar(decision.consulta_es or req.message, k=4)
    system = construir_system_prompt(fragmentos, req.lang)

    contexto = "".join(
        f"### {origen}\n{texto}\n\n" for (texto, origen, _) in fragmentos
    )

    # (E) GENERACIÓN con herramientas
    reply = generar_respuesta(system, history, req.message, extra)

    # (F) EVALUADOR-OPTIMIZADOR: si la respuesta no supera la revisión, se
    # regenera una sola vez con el motivo del rechazo (sin bucle, por coste).
    ev = evaluate(reply, req.message, history, contexto)
    if not ev.is_acceptable:
        feedback = (
            extra
            + "\n\n## Tu respuesta fue rechazada.\nRespuesta:\n"
            + reply
            + "\nMotivo:\n"
            + ev.feedback
            + "\nCorrígela."
        )
        reply = generar_respuesta(system, history, req.message, feedback)

    return reply


def generar_respuesta(system_base, history, message, extra_system=""):
    """Llama al modelo y ejecuta las herramientas que pida hasta obtener texto."""
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
            funcion = HERRAMIENTAS.get(tool_call.function.name)
            try:
                args = json.loads(tool_call.function.arguments)
                resultado = (
                    funcion(**args) if funcion else {"error": "herramienta desconocida"}
                )
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
