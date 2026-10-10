"""Cliente del LLM (OpenAI) compartido por todos los módulos de api/."""
import os
from openai import OpenAI
from dotenv import load_dotenv

# En local las variables están en backend/.env; en Vercel ese fichero no existe
# y load_dotenv no hace nada, porque las variables las inyecta Vercel.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

MODELO = "gpt-4o-mini"  # barato y rápido: cada mensaje hace varias llamadas
MAX_TOKENS = 500        # tope por respuesta, para acotar el coste

cliente = OpenAI()  # lee OPENAI_API_KEY del entorno

def responder(messages, tools=None):
    """Respuesta de chat normal; con `tools`, el modelo puede pedir herramientas."""
    extra = {"tools": tools} if tools else {}
    return cliente.chat.completions.create(
        model = MODELO,
        messages = messages,
        max_tokens = MAX_TOKENS,
        **extra,
    )


def responder_estructurado(messages, schema):
    """Respuesta validada contra un modelo Pydantic (la usan los patrones)."""
    return cliente.beta.chat.completions.parse(
        model=MODELO,
        messages=messages,
        response_format=schema,
    ).choices[0].message.parsed
