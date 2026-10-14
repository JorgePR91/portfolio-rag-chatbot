# Evaluación del chatbot

Scripts para medir la calidad del chatbot con datos, en lugar de a ojo.

| Script | Qué hace | Coste aproximado |
|---|---|---|
| [chatbot.py](chatbot.py) | Lanza los casos contra el flujo completo y comprueba cada componente por separado. Da también la latencia (p50 y p95), las llamadas al LLM y el coste por mensaje | ~0,0005 $ por caso |
| [umbral.py](umbral.py) | Calibra el umbral de similitud de la búsqueda (ver `UMBRAL` en `api/vector_store.py`) | Una llamada al router por caso |
| [evaluador.py](evaluador.py) | Prueba el evaluador con respuestas preparadas. No depende de la base de conocimiento | 6 llamadas |

```bash
# Desde la raíz del proyecto, con backend/.env configurado
python evals/chatbot.py              # usa evals/casos.jsonl
python evals/umbral.py
python evals/evaluador.py
```

Las herramientas se sustituyen por una versión que no envía nada, así que la evaluación **no manda avisos a Telegram**.

## Los casos

Los casos de la base de conocimiento real no se publican, porque contienen datos personales. [casos.ejemplo.jsonl](casos.ejemplo.jsonl) muestra el formato. Cópialo como `evals/casos.jsonl` y sustituye los `_____` por datos de tus documentos. Los casos de guardrail, contacto, fuera de tema y preguntas sin respuesta sirven tal cual.

Un caso por línea. Todos los campos menos `id` y `pregunta` son opcionales, y cada caso solo se comprueba en lo que declara:

| Campo | Qué comprueba |
|---|---|
| `lang` | Idioma de la web (`es`, `en`, `ca`, `va`). Por defecto, `es` |
| `history` | Conversación previa, para probar preguntas de seguimiento |
| `bloquear` | `true` si el guardrail debe bloquearlo. Los casos sin este campo comprueban que **no** se bloquean |
| `categoria` | Categoría que debe elegir el router. Omítela si la pregunta encaja de verdad en dos |
| `fuentes` | Sección que debe recuperar la búsqueda, como `"fichero.md > Título"`. Basta con un prefijo: `"skills.md"` acepta cualquier sección del fichero. Con este campo se comprueba también que el bot no diga que no lo sabe (`sabe`) |
| `contiene` | Palabras que debe incluir la respuesta. Sin tildes ni mayúsculas, y `"a\|b"` acepta cualquiera de las dos |
| `no_contiene` | Palabras que no debe incluir |
| `herramienta` | Herramienta que debe llamar (`record_unknown_question` o `record_user_details`) |

## Cómo escribir buenos casos

- **Por cada comportamiento, un caso positivo y uno negativo.** Por ejemplo, que el guardrail bloquee una inyección y que no bloquee una pregunta sobre seguridad informática.
- **Los ejemplos de los prompts nunca son casos de la evaluación.** Si lo son, el caso mide si el modelo reconoce el ejemplo, no si aplica la regla.
- **Incluye casos trampa:** preguntas con premisas falsas o que piden datos que no están.
- **Cuando un caso falle, decide primero quién tiene razón:** si falla el sistema, se arregla el sistema; si el caso está mal planteado, se corrige el caso y se explica por qué. Nunca se cambia un caso solo para que pase.
- **Una ejecución no es una medida.** Los modelos varían entre ejecuciones; repite las decisiones que estén en el límite y da una tasa.
