# Manual rápido: actualizar o ampliar el RAG

Guía breve para añadir, corregir o reindexar la información que usa el chatbot del portfolio.

---

## 1. Cómo funciona (en 30 segundos)

1. La información del perfil vive en ficheros `.md` dentro de [backend/me/](backend/me/).
2. [backend/ingest.py](backend/ingest.py) lee esos `.md`, los **trocea en fragmentos de ~400 caracteres** y los sube a la base vectorial **Upstash** (vía [api/vector_store.py](api/vector_store.py)).
3. Cuando un visitante pregunta, [api/chat.py](api/chat.py) recupera **solo los 4 fragmentos más parecidos** a la pregunta y construye con ellos el prompt.
4. Regla de oro del sistema: **el bot responde ÚNICAMENTE con lo que hay en esos fragmentos**. Si algo no está, no lo dirá (lo registra como pregunta desconocida).

---

## 2. Los ficheros de conocimiento

| Fichero | Qué va aquí |
|---|---|
| [personal.md](backend/me/personal.md) | Perfil, rol, motivación, bagaje, personalidad, aficiones |
| [formación.md](backend/me/formación.md) | Estudios académicos |
| [experiencia.md](backend/me/experiencia.md) | Experiencia laboral y profesional |
| [skills.md](backend/me/skills.md) | Soft skills, idiomas y conocimientos técnicos (hard skills) |
| [proyectos.md](backend/me/proyectos.md) | Proyectos propios y enlaces |
| [disponibilidad.md](backend/me/disponibilidad.md) | Disponibilidad y qué se busca profesionalmente |
| [contacto.md](backend/me/contacto.md) | Cómo contactar (formulario de la web) |
| [preguntas.md](backend/me/preguntas.md) | Preguntas frecuentes sobre la persona |

Para añadir un tipo de contenido nuevo (p. ej. certificaciones), **crea un `.md` nuevo en [backend/me/](backend/me/)**. La ingesta lo recoge automáticamente; no hay que registrar nada en el código.

---

## 3. Las 3 reglas para escribir buen contenido RAG

Por cómo trocea y recupera el sistema, sigue siempre estas reglas:

### Regla 1 — Cada párrafo, autosuficiente
Solo se recuperan 4 trozos de ~400 caracteres y el único dato de origen es el nombre del fichero. Un fragmento que diga solo `Angular` no sirve. Escribe **el dato y su justificación en el mismo párrafo**:

```markdown
✅ [Nombre] trabaja con Angular para el frontend de su portfolio. Lo aprendió en
   la asignatura de Desarrollo web en entorno cliente.

❌ Angular
```

### Regla 2 — Un hecho = un párrafo, por debajo de ~400 caracteres
Separa cada idea con una **línea en blanco** y mantén cada bloque corto, para que no se parta a mitad al trocearse.

### Regla 3 — Que el texto "suene" a la pregunta
La búsqueda es por significado. Si esperas la pregunta *"¿por qué te pasaste a la programación?"*, usa ese vocabulario en la respuesta e incluye sinónimos (*puntos fuertes / fortalezas / virtudes*).

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
Respuesta completa y autónoma (se entiende sin leer la pregunta),
por debajo de ~400 caracteres.
```

---

## 5. Reindexar (OBLIGATORIO tras cualquier cambio)

Si editas un `.md` y **no** reindexas, la base vectorial sigue con la versión antigua y el bot responde con datos viejos.

```bash
cd backend
python ingest.py
```

El script borra el índice anterior (`index.reset()`) y vuelve a subir todo. Al terminar imprime:

```
Documentos = N | Chunks subidos = M
```

### Requisitos previos
- Variables de entorno de Upstash Vector configuradas en [backend/.env](backend/.env) (ver [backend/.env.example](backend/.env.example)). `ingest.py` carga este `.env` de forma explícita al arrancar.
- Entorno Python con las dependencias instaladas (`pip install -r requirements.txt`).

### Detalles de arquitectura (no romper al reorganizar carpetas)
- [ingest.py](backend/ingest.py) vive en `backend/` pero **reutiliza el `vector_store.py` de `api/`** (el mismo que usa el backend desplegado, para no duplicar código). Lo importa añadiendo `../api` a la ruta: si mueves carpetas, ajusta ese `sys.path.insert`.
- `ingest.py` es una herramienta **solo local**: nunca se ejecuta en Vercel (allí solo corren las funciones de `api/`, y `backend/` está en [.vercelignore](.vercelignore)). Por eso carga el `.env` local, mientras que en producción Vercel inyecta sus propias variables de entorno.

---

## 6. Comprobar que funciona

Lanza una consulta de prueba contra el índice para ver qué fragmentos recupera:

```bash
cd api
python rag.py "¿Sabe Angular?"
```

Muestra los 4 fragmentos más parecidos con su puntuación y fichero de origen. Si tu nuevo contenido no aparece, revisa las 3 reglas de la sección 3 o reindexa de nuevo.

---

## 7. Checklist para añadir/ampliar información

- [ ] Escribir el contenido en el `.md` correcto de [backend/me/](backend/me/) siguiendo las 3 reglas.
- [ ] Revisar erratas (el bot repite literalmente lo que pongas).
- [ ] Mantener coherencia con el resto (3ª persona, mismos nombres propios).
- [ ] Reindexar: `cd backend && python ingest.py`.
- [ ] Probar con `python rag.py "tu pregunta"` desde `api/`.
- [ ] Confirmar en el chat del sitio web.
