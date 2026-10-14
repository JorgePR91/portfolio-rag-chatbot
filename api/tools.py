"""Herramientas (function calling) que el modelo puede invocar durante el chat.

Las dos avisan al propietario del portfolio por Telegram: cuando un visitante
deja su email y cuando el bot no sabe responder una pregunta (señal de que
falta información en los .md del RAG).
"""
import os
import requests
import entorno  # noqa: F401  (carga backend/.env en local)


# --- el "avisador" ---
# Fire-and-forget: si Telegram falla, solo se registra en los logs y el chat
# sigue. Se registra el tipo de error y no el error completo, porque este
# incluiría la URL con el token del bot.
def push(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage",
            data={
                "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
                "text": text,
            },
            timeout=5
        )
        if not r.ok:
            print(f"[push] Telegram respondió {r.status_code}", flush=True)
    except requests.RequestException as e:
        print(f"[push] No se pudo avisar por Telegram: {type(e).__name__}", flush=True)

# --- las dos herramientas ---
# Devuelven siempre "ok" para que el modelo siga con la conversación.
def record_user_details(email, name="Nombre no indicado", notes="no proporcionadas"):
    push(f"Registrando {name} con email {email} y notas {notes}")
    return {"recorded": "ok"}

def record_unknown_question(question):
    push(f"Registrando {question}")
    return {"recorded": "ok"}

# --- los ESQUEMAS (lo que el LLM "ve" para decidir si las llama) ---
# El modelo decide si llama a una herramienta mirando sobre todo su
# descripción, así que las reglas de cuándo usarla van aquí.
record_user_details_json = {
    "name": "record_user_details",
    "description": "Utiliza esta herramienta para registrar que un usuario está interesado en estar en contacto y proporcionó una dirección de correo electrónico.",
    "parameters": {
        "type": "object",
        "properties": {
            "email": {
                "type": "string",
                "description": "La dirección de email del usuario"
            },
            "name": {
                "type": "string",
                "description": "El nombre del usuario, si se indica"
            }
            ,
            "notes": {
                "type": "string",
                "description": "¿Alguna información adicional sobre la conversación que valga la pena registrar para dar contexto?"
            }
        },
        "required": ["email"],
        "additionalProperties": False
    }
}

record_unknown_question_json = {
    "name": "record_unknown_question",
    "description": "Registra una pregunta que no puedes responder porque el CONTEXTO no contiene la información que se pide. Úsala SOLO en ese caso: no la uses si la pregunta contiene un dato erróneo que puedes corregir con el CONTEXTO.",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "La pregunta que no se ha sabido responder"
            },
        },
        "required": ["question"],
        "additionalProperties": False
    }
}

# --- lista que se pasa al modelo ---
tools = [{"type": "function", "function": record_user_details_json},
        {"type": "function", "function": record_unknown_question_json}]
