"""Cliente del LLM (OpenAI) compartido por todos los módulos de api/.

También lleva la cuenta de las llamadas y los tokens de cada petición (uso),
que chat.py escribe en su línea de métricas.
"""
import threading
from contextvars import ContextVar

from openai import OpenAI

import entorno  # noqa: F401  (carga backend/.env en local)

MODELO = "gpt-4o-mini"  # barato y rápido: cada mensaje hace varias llamadas
MAX_TOKENS = 500        # tope por respuesta, para acotar el coste
# Precio de gpt-4o-mini en USD por token. Si cambias de modelo, actualízalo
# (openai.com/api/pricing). No descuenta la caché: es una cota superior.
PRECIO_ENTRADA = 0.15 / 1_000_000
PRECIO_SALIDA = 0.60 / 1_000_000

cliente = OpenAI()  # lee OPENAI_API_KEY del entorno

# Llamadas y tokens de la petición en curso. Es un ContextVar y no una variable
# global: si el servidor atiende varias peticiones a la vez, cada una suma lo suyo.
uso = ContextVar("uso", default=None)

# Guardrail y router se ejecutan en paralelo: el cerrojo evita que dos hilos
# sumen a la vez sobre el mismo contador y se pierda una de las sumas.
_cerrojo = threading.Lock()


def _anotar(resp):
    u = uso.get()
    if u is not None and resp.usage:
        with _cerrojo:
            u["llamadas"] += 1
            u["tokens_entrada"] += resp.usage.prompt_tokens
            u["tokens_salida"] += resp.usage.completion_tokens


def responder(messages, tools=None):
    """Respuesta de chat normal; con `tools`, el modelo puede pedir herramientas."""
    extra = {"tools": tools} if tools else {}
    resp = cliente.chat.completions.create(
        model=MODELO,
        messages=messages,
        max_tokens=MAX_TOKENS,
        **extra,
    )
    _anotar(resp)
    return resp


def responder_estructurado(messages, schema):
    """Respuesta validada contra un modelo Pydantic (la usan los patrones)."""
    resp = cliente.beta.chat.completions.parse(
        model=MODELO,
        messages=messages,
        response_format=schema,
        # Guardrail, router y evaluador clasifican: ante la misma entrada
        # deben dar la misma respuesta, no variedad.
        temperature=0,
    )
    _anotar(resp)
    return resp.choices[0].message.parsed
