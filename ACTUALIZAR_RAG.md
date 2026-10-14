# Manual rápido: actualizar o ampliar el RAG

Guía breve para añadir, corregir o reindexar la información que usa el chatbot del portfolio.

---

## 1. Cómo funciona (en 30 segundos)

1. La información del perfil vive en ficheros `.md` dentro de [backend/me/](backend/me/).
2. [backend/ingest.py](backend/ingest.py) trocea cada `.md` **por secciones** (títulos `#` y `##`): cada sección es un fragmento, con su ruta de títulos delante (por ejemplo, `Proyectos > Nombre del proyecto`). Solo si una sección pasa de ~1000 caracteres se parte en varios trozos. Después sube los fragmentos a **Upstash Vector**, que calcula los embeddings.
3. Cuando un visitante pregunta, el router reescribe la pregunta como un **tema de búsqueda** (en castellano y sin el nombre de la persona), y [api/chat.py](api/chat.py) recupera **las 4 secciones más parecidas**.
4. Regla de oro del sistema: **el bot responde ÚNICAMENTE con lo que hay en esas secciones**. Si algo no está, no lo dirá (lo registra como pregunta desconocida).

---

## 2. Los ficheros de conocimiento

| Fichero | Qué va aquí |
|---|---|
| [personal.md](backend/me/personal.md) | Perfil, rol, motivación, bagaje, personalidad, aficiones |
| [formación.md](backend/me/formación.md) | Estudios académicos |
| [experiencia.md](backend/me/experiencia.md) | Experiencia laboral, prácticas y otros trabajos (secundarios) |
| [skills.md](backend/me/skills.md) | Soft skills, idiomas y conocimientos técnicos (hard skills) |
| [proyectos.md](backend/me/proyectos.md) | Proyectos propios y enlaces |
| [disponibilidad.md](backend/me/disponibilidad.md) | Disponibilidad y qué se busca profesionalmente |
| [contacto.md](backend/me/contacto.md) | Cómo contactar (formulario de la web) |
| [preguntas.md](backend/me/preguntas.md) | Preguntas frecuentes sobre la persona |

Para añadir un tipo de contenido nuevo (p. ej. certificaciones), **crea un `.md` nuevo en [backend/me/](backend/me/)**. La ingesta lo recoge automáticamente; no hay que registrar nada en el código.

---

## 3. Las reglas para escribir buen contenido RAG

### Regla 1 — Una sección = un tema, con un título que diga de qué trata
El título forma parte del fragmento (`Proyectos > Nombre del proyecto`), así que la búsqueda lo usa. Un título genérico ("Perfil") ayuda poco; uno concreto ("Experiencia laboral principal") ayuda mucho. Una sección que solo tiene título y no tiene texto no genera ningún fragmento.

### Regla 2 — Cada sección, autosuficiente y por debajo de ~1000 caracteres
El bot solo recibe 4 secciones. Escribe **el dato y su contexto en la misma sección**, y evita que una sección dependa de otra para entenderse:

```markdown
✅ ## Angular
   [Nombre] trabaja con Angular para el frontend de su portfolio. Lo aprendió en
   la asignatura de Desarrollo web en entorno cliente.

❌ ## Angular
   Lo usa en el portfolio (ver sección anterior).
```

Si una sección pasa de ~1000 caracteres, se parte por tamaño y el segundo trozo pierde parte del sentido. Mejor dividirla en dos secciones con títulos propios.

### Regla 3 — Que el texto "suene" a la pregunta, y que diga el cuándo
La búsqueda es por significado. Si esperas *"¿dónde trabajó antes de dedicarse a la programación?"*, escribe "Antes de dedicarse a la programación, [Nombre] trabajó...". Sin ese "antes", la búsqueda puede no relacionar el dato con la pregunta. Incluye también sinónimos (*puntos fuertes / fortalezas / virtudes*).

### Regla 4 — Nada de datos que caducan
Escribe la fecha de nacimiento, no la edad. Escribe "desde septiembre de 2024", no "desde hace un año".

### Regla 5 — Lo secundario, marcado
Si una sección solo debe usarse cuando el visitante pide **toda** la información (por ejemplo, trabajos temporales ajenos al perfil), pon la marca en la línea siguiente al título:

```markdown
# Otras experiencias laborales
<!-- secundaria -->
Texto de la sección...
```

La marca se convierte en un metadato y se quita del texto. La sección solo entra en el contexto cuando el router decide que se pide todo. **Menciona en la sección principal que existe esa información** ("También ha tenido algunos trabajos temporales..."): si no, cuando no se pide, el bot puede negar que exista. Detalles en [docs/filtrado-por-metadatos.md](docs/filtrado-por-metadatos.md).

---

## 4. Plantillas

**Conocimiento técnico (en [skills.md](backend/me/skills.md)):**
```markdown
[Nombre] [domina / tiene nociones de] X. Lo aprendió en [asignatura / curso /
prácticas] y lo ha aplicado en [proyecto / empresa].
```

**Pregunta sobre la persona (en [preguntas.md](backend/me/preguntas.md)):**
```markdown
## ¿Pregunta tal y como la haría un visitante?
Respuesta completa y autónoma (se entiende sin leer la pregunta).
```

---

## 5. Reindexar (OBLIGATORIO tras cualquier cambio)

Si editas un `.md` y **no** reindexas, la base vectorial sigue con la versión antigua y el bot responde con datos viejos. Guarda los ficheros antes: `ingest.py` lee lo que hay en disco, no lo que ves en el editor.

```bash
cd backend
python ingest.py --ver   # muestra los fragmentos SIN tocar el índice
python ingest.py         # borra el índice y vuelve a subir todo
```

Revisa primero con `--ver`: si el índice es el mismo que usa el bot en producción, la indexación empieza borrándolo. Al terminar, `ingest.py` imprime lo que confirma el propio Upstash:

```
Documentos = N | Chunks subidos = M | En el índice: M (+P pendientes)
```

Upstash indexa en segundo plano: justo después de subir puede haber fragmentos "pendientes". En unos segundos están disponibles.

### Requisitos previos
- Variables de entorno de Upstash Vector configuradas en `backend/.env` (ver [backend/.env.example](backend/.env.example)). Las carga [api/entorno.py](api/entorno.py), que importan todos los módulos que las necesitan.
- Entorno Python con las dependencias de desarrollo instaladas (`pip install -r requirements-dev.txt`).

### Detalles de arquitectura (no romper al reorganizar carpetas)
- [ingest.py](backend/ingest.py) vive en `backend/` pero **reutiliza el `vector_store.py` de `api/`** (el mismo que usa el backend desplegado, para no duplicar código). Lo importa añadiendo `../api` a la ruta: si mueves carpetas, ajusta ese `sys.path.insert`.
- `ingest.py` es una herramienta **solo local**: nunca se ejecuta en Vercel (allí solo corren las funciones de `api/`, y `backend/` está en [.vercelignore](.vercelignore)).

---

## 6. Comprobar que funciona

Para ver qué secciones recupera una consulta y con qué puntuación:

```bash
cd api
python rag.py "nivel de inglés"
```

Usa el **tema**, no la pregunta completa: es lo que busca el bot, porque el router reescribe la pregunta antes de buscar.

Para comprobar que no se ha roto nada, lanza la evaluación desde la raíz (ver [evals/](evals/)):

```bash
python evals/chatbot.py evals/casos.jsonl
```

Si has añadido información nueva, añade también un caso que pregunte por ella. Si has cambiado mucho los documentos, vuelve a calibrar el umbral con `evals/umbral.py`.

---

## 7. Checklist para añadir o ampliar información

- [ ] Escribir el contenido en la sección correcta de [backend/me/](backend/me/) siguiendo las reglas de la sección 3.
- [ ] Revisar erratas (el bot repite literalmente lo que pongas).
- [ ] Mantener coherencia con el resto (3ª persona, mismos nombres propios).
- [ ] Guardar los ficheros.
- [ ] Revisar con `ingest.py --ver` y reindexar con `ingest.py`.
- [ ] Probar con `rag.py "tema"` y lanzar la evaluación.
- [ ] Confirmar en el chat del sitio web.
