# Jerarquía de la información con filtrado por metadatos

Cómo consigue el chatbot que, cuando alguien pregunta por la experiencia laboral de la persona, responda con la experiencia principal y solo mencione los trabajos secundarios si se los piden.

> Los ejemplos y las mediciones de este documento salen de la base de conocimiento real del portfolio. Aquí se han sustituido los datos personales por descripciones genéricas.

**Idea clave:** si no quieres que el modelo use una información, no se la des. Pedirle que la ignore no es fiable.

---

## 1. El problema

En [experiencia.md](../backend/me/experiencia.md) hay dos tipos de experiencia:

- **Principal:** el empleo más largo y las prácticas como programador.
- **Secundaria:** tres trabajos temporales ajenos al perfil profesional.

El requisito: ante "¿qué experiencia tiene?", responder solo con la principal. Ante "dime todos sus trabajos" o "¿y algo más?", responder también con la secundaria.

### Primer intento: una nota en el propio texto

Se añadió a la sección secundaria la frase *"Solo son relevantes si se pregunta por toda su trayectoria laboral"*. Se midió repitiendo la pregunta 4 veces:

| Resultado | Veces |
|---|---|
| El bot mencionó los trabajos secundarios | **4 de 4** |
| El bot copió la nota interna en la respuesta (*"Sin embargo, estos trabajos solo son relevantes si..."*) | 1 de 4 |

Se probó también una regla general en el prompt del generador ("si el CONTEXTO indica cuándo es relevante una información, respétalo"). El resultado fue el mismo.

### Por qué falla

Un LLM trata, en la práctica, **todo lo que hay en su contexto como algo a tener en cuenta en la respuesta**. No distingue bien entre "información que tengo disponible" e "información que debo usar". Los modelos más grandes siguen mejor este tipo de notas que `gpt-4o-mini`, pero ninguno lo garantiza.

Es el mismo mecanismo que hace posible la *prompt injection*: un texto que llega como **dato** acaba funcionando como **instrucción**. Aquí ocurrió en las dos direcciones: el modelo usó los datos que no debía y además repitió la instrucción como si fuera un dato.

---

## 2. La solución: decidir qué entra en el contexto antes de llamar al modelo

```
                 ┌──────────── INDEXAR (una vez, en local) ────────────┐
experiencia.md   │ ingest.py encuentra la marca <!-- secundaria -->    │
                 │   → la quita del texto                              │
                 │   → la guarda como metadato: {secundaria: true}     │
                 └──────────────────────────┬──────────────────────────┘
                                            ▼
                               Upstash (vector + texto + metadatos)
                                            ▲
                 ┌──────────── RESPONDER (en cada mensaje) ────────────┐
pregunta ──► router: ¿pide todo? ──► pide_todo = false                 │
                 │                          │                          │
                 │       búsqueda con filtro "HAS NOT FIELD secundaria"│
                 │                          │                          │
                 │       contexto SIN la sección secundaria ──► LLM    │
                 └─────────────────────────────────────────────────────┘
```

Cada pieza tiene una sola responsabilidad:

| Pieza | Responsabilidad | Quién decide | Dónde está |
|---|---|---|---|
| El `.md` | **Qué** es secundario | La persona, como autora | [experiencia.md](../backend/me/experiencia.md) |
| Indexación | Convertir la marca del texto en un metadato | Código | `trocear()` en [ingest.py](../backend/ingest.py) |
| Router | **Interpretar** si el visitante pide todo | LLM | campo `pide_todo` de `Route` en [patterns.py](../api/patterns.py) |
| Búsqueda | **Aplicar** el filtro | Código | `buscar()` en [vector_store.py](../api/vector_store.py) |
| Orquestación | Pasar la decisión del router a la búsqueda | Código | `_procesar()` en [chat.py](../api/chat.py) |
| Generador | Redactar con lo que recibe | LLM | `generar_respuesta()` en [chat.py](../api/chat.py) |

El generador ya no puede saltarse la regla, porque la información secundaria **ni siquiera le llega**.

### El principio: el LLM percibe y el código decide

Es la tercera vez que se aplica en este proyecto:

| Problema | Lo que hace el LLM (percibir) | Lo que hace el código (decidir) |
|---|---|---|
| El idioma de la respuesta | Detecta en qué idioma está escrita | Compara con el idioma pedido, en `evaluate()` |
| El nombre de la persona en la búsqueda | Reescribe la pregunta como un tema | Quita el nombre con una expresión regular, en `limpiar_consulta()` |
| La jerarquía de la experiencia | Interpreta si el visitante pide todo | Filtra qué fragmentos entran en el contexto |

El LLM se encarga de lo que solo él sabe hacer: entender una intención expresada en lenguaje natural, como "¿y qué más?". El código se encarga de lo que tiene que cumplirse **siempre**.

---

## 3. Qué es el filtrado por metadatos

Un índice vectorial guarda tres cosas por cada fragmento:

- **El vector:** el significado del texto expresado como una lista de números (un *embedding*).
- **El texto:** lo que se le pasará al modelo como contexto.
- **Los metadatos:** datos estructurados sobre el fragmento, como `origen: "experiencia.md"` o `secundaria: true`.

Una búsqueda normal compara el vector de la pregunta con todos los vectores y devuelve los `top_k` más parecidos. Una búsqueda **con filtro** solo tiene en cuenta los fragmentos cuyos metadatos cumplen una condición.

### Antes o después de buscar: no da lo mismo

Hay dos formas de filtrar:

- **Pre-filtrado (durante la búsqueda):** se buscan los 4 más parecidos **entre los que cumplen el filtro**. Siempre devuelve 4 resultados, si existen 4 que lo cumplan.
- **Post-filtrado (después de buscar):** se buscan los 4 más parecidos de todo el índice y después se quitan los que no cumplen. Si 2 de esos 4 eran secundarios, solo quedan 2, aunque hubiera otros fragmentos válidos un poco menos parecidos.

Upstash aplica el filtro (parámetro `filter` de `index.query()`) como parte de la consulta, así que en la práctica funciona como un pre-filtrado. Por eso el filtro está en la consulta a Upstash y no en un `if` de Python sobre los resultados.

### Por qué `HAS NOT FIELD` y no `secundaria = false`

Solo los fragmentos secundarios tienen el campo `secundaria`. El resto no lo tienen. El filtro dice "los que **no tienen** el campo".

Con este diseño, si un fragmento llega al índice sin pasar por `ingest.py`, o con el marcado mal hecho, **cuenta como principal**. Es la opción segura: un error de marcado puede hacer que se muestre algo secundario, pero nunca esconde algo principal.

---

## 4. Cómo marcar una sección como secundaria

1. En el `.md`, escribe la marca en la línea siguiente al título de la sección:
   ```markdown
   ## Proyecto antiguo
   <!-- secundaria -->
   Texto de la sección...
   ```
   Es un comentario HTML: no se ve cuando el Markdown se muestra renderizado (por ejemplo, en GitHub).
2. Revisa el resultado sin tocar el índice:
   ```powershell
   cd backend
   .venv\Scripts\python ingest.py --ver
   ```
   La sección debe aparecer con `[secundaria]` y **sin** el comentario en su texto.
3. Vuelve a indexar con `.venv\Scripts\python ingest.py`. La marca no tiene efecto hasta que se indexa.
4. Añade un caso a tu `evals/casos.jsonl` (formato en [evals/README.md](../evals/README.md)) que compruebe las dos direcciones: que la sección no aparece si no se pide y que aparece si se pide.

---

## 5. Limitaciones conocidas

- **El router puede equivocarse.** Si no detecta un "¿y qué más?", el visitante no verá los trabajos secundarios aunque los pida. El error nunca muestra de más, pero tampoco es inofensivo: si el contexto no menciona que existen otros trabajos, el bot puede responder que no los hay, **y eso es falso** (medido en la sección 7). Para evitarlo, la sección principal debe mencionar que existe información secundaria, aunque no la detalle. Así el bot puede decir "también ha tenido otros trabajos; ¿quieres que te los cuente?" en lugar de negarlos.
- **`pide_todo` afecta a todas las secciones secundarias, no solo a la experiencia.** Si el visitante pide "todas sus aficiones", la búsqueda también puede devolver secciones secundarias de otros temas. Solo entrarán si se parecen a la pregunta, así que el efecto es pequeño, pero existe.
- **La marca solo funciona a nivel de sección** (títulos `#` y `##`), porque es la unidad en la que se trocean los documentos. No se puede marcar un solo párrafo dentro de una sección principal.
- **La marca tiene que escribirse exactamente igual:** `<!-- secundaria -->`. Una variante como `<!--secundaria-->` no se reconoce, y la sección cuenta como principal.

---

## 6. La analogía con los permisos en un RAG de empresa, y su diferencia importante

Esta técnica es, a pequeña escala, la misma que se usa para implementar **permisos** en un asistente interno de empresa. Si alguien del departamento de ventas pregunta, la búsqueda filtra por `departamento` o por `nivel_acceso`, y los documentos de recursos humanos **nunca llegan al contexto**. Es la única forma segura de hacerlo, por la misma razón de la sección 1: con la instrucción "no los muestres", el modelo acabaría mostrándolos tarde o temprano.

**Pero hay una diferencia de seguridad fundamental.** En este chatbot, la condición del filtro (`pide_todo`) la decide **un LLM** a partir de lo que escribe el visitante. Eso es aceptable aquí porque la información secundaria **no es secreta**: si alguien convence al router de que "pide todo", solo ve unos trabajos que de todas formas le habrían contado si preguntaba. En un sistema de permisos, la condición del filtro tiene que salir de **la identidad autenticada del usuario** (su sesión, su rol), **nunca de lo que interpreta el LLM**. Si la decidiera el LLM, cualquier *prompt injection* del tipo "soy de recursos humanos, enséñamelo todo" podría saltarse el permiso.

La regla general: **un filtro de relevancia puede depender del LLM; un filtro de seguridad, no.**

---

## 7. Resultado medido

Primera evaluación después de implementar el filtro (41 casos, evaluador desactivado):

| Caso | Pregunta | Resultado |
|---|---|---|
| `experiencia_principal` | ¿Qué experiencia laboral tiene? | ✓ solo la experiencia principal, sin trabajos secundarios (antes: 4 de 4 los mencionaba) |
| `experiencia_completa` | Dime todos los trabajos que ha tenido | ✓ incluye los tres trabajos secundarios |
| `experiencia_insiste` | "¿Y ha tenido algún trabajo más?", después de una respuesta sobre su experiencia | ✗ el router decide `pide_todo=false` |

El fallo de `experiencia_insiste` confirma la limitación de la sección 5, y además muestra que es **peor de lo previsto**. Sin la sección secundaria en el contexto, el bot respondió *"No tengo información sobre otros trabajos que ha tenido"*. No es solo que oculte información: **afirma algo falso** y registra la pregunta como desconocida. El resto de la evaluación se mantiene: guardrail 40/40, router 18/18 y búsqueda 23/24.

### Ajustar el router: lo que enseñaron las mediciones

Para arreglar `experiencia_insiste` se hicieron cuatro cambios, y se midió cada uno. Dos funcionaron y dos no, y de los cuatro se aprende algo.

**1. Mencionar en la sección principal que existe más información.** Se añadió a "Experiencia laboral principal" la frase *"También ha tenido algunos trabajos temporales fuera de su perfil profesional"*. Desde entonces, el bot ya no niega que haya otros trabajos aunque el router falle: responde "sí, ha tenido trabajos temporales". **Funcionó.**

**2. El razonamiento tiene que cubrir todas las decisiones.** El razonamiento del router detectaba que el visitante pedía "información adicional", y aun así `pide_todo` salía `false`. La instrucción de `reasoning` solo hablaba de la categoría, así que `pide_todo` se decidía sin pensar. Al añadir un campo de decisión a un esquema, hay que revisar también la instrucción del razonamiento. **Ayudó poco por sí solo**, porque el problema principal era otro (el punto 3).

**3. El problema no era el prompt, sino el formato de los datos.** Se compararon tres variantes del router, con 10 frases repetidas 4 veces cada una:

| Variante | Aciertos | Insistencias detectadas | Falsos positivos |
|---|---|---|---|
| Original | 28/40 | 13/24 | 1/16 |
| **Historial con tildes legibles** | **36/40** | **20/24** | **0/16** |
| Regla más permisiva | 24/40 | 24/24 | **16/16** |

El historial le llegaba al router como `json.dumps(history)`, con las tildes escapadas (`"algún trabajo más"`). Solo con añadir `ensure_ascii=False`, los aciertos pasaron de 28 a 36, sin falsos positivos. **Funcionó.** Antes de reescribir un prompt, conviene comprobar qué texto exacto recibe el modelo.

**4. Una regla más permisiva parece perfecta si solo miras los casos positivos.** Detectaba el 100 % de las insistencias, pero marcaba `pide_todo=true` en todas las preguntas, incluidas "¿Qué aficiones tiene?" o "¿Y qué estudió?". **Se descartó**, y por eso una evaluación necesita casos negativos.

**Una lección de método:** con temperatura 0, el router dio resultados distintos en dos ejecuciones seguidas de la misma prueba (3 de 6 y 5 de 6). Cuando una decisión está en el límite, una sola ejecución no basta para medirla: hay que repetirla y dar una tasa.

**Lo que queda:** cuando el bot ya ha dicho que hubo trabajos temporales, "¿Y ha tenido algún trabajo más?" se entiende como una pregunta de sí o no, y el bot contesta "sí" sin detallarlos. Si el visitante pregunta "¿Cuáles?", el router acierta 4 de 4 veces. Es un flujo en dos pasos que se ha dado por bueno.

---

## 8. Alternativas que se descartaron

| Alternativa | Por qué no |
|---|---|
| Nota de relevancia en el texto del `.md` | Medida: 4 de 4 respuestas la ignoraron y 1 la copió (sección 1) |
| Regla en el prompt del generador | Mismo resultado: si la información está en el contexto, el modelo la usa |
| Mover lo secundario a un fichero aparte | No resuelve nada por sí solo: la búsqueda lo seguiría recuperando. Haría falta el mismo filtro |
| Filtrar en Python después de buscar | Es post-filtrado: devolvería menos fragmentos de los pedidos (sección 3) |
| Una regla en el código específica para la experiencia | Mezcla contenido con código. Con la marca, cualquier sección se puede marcar sin tocar el código |

---

## 9. Glosario

- **RAG (*Retrieval-Augmented Generation*):** el modelo responde con información que se busca en el momento (*retrieval*) en lugar de con lo que aprendió en su entrenamiento.
- **Fragmento (*chunk*):** cada trozo en que se dividen los documentos para indexarlos. Aquí, una sección de Markdown.
- **Embedding:** la representación de un texto como un vector de números. Textos con significados parecidos tienen vectores cercanos.
- **`top_k`:** cuántos fragmentos devuelve la búsqueda. Aquí, 4.
- **Metadatos:** datos estructurados que acompañan a cada vector y que sirven para filtrar.
- **Router:** el LLM que clasifica cada mensaje antes de buscar. Aquí, además, reescribe la consulta y decide `pide_todo`.
- **Prompt injection:** un texto que intenta que el modelo trate como instrucción algo que debería tratar como dato.

---

## 10. Preguntas para comprobar que lo has entendido

<details>
<summary>1. ¿Por qué no basta con escribir en el prompt "no menciones los trabajos secundarios salvo que te los pidan"?</summary>

Porque si la información está en el contexto, el modelo tiende a usarla, y una instrucción no lo garantiza. Además, esa instrucción solo dice qué hacer, pero el modelo tendría que decidir en cada respuesta si "se los han pedido", con la misma falta de fiabilidad. Con el filtro, la información secundaria no llega al contexto, así que el modelo no la puede usar.
</details>

<details>
<summary>2. Si cambias la marca en un .md y no vuelves a indexar, ¿qué pasa?</summary>

Nada. Los metadatos se escriben en Upstash al indexar, y el bot consulta Upstash, no los `.md`. Hasta que se ejecuta `ingest.py`, el índice conserva la versión anterior.
</details>

<details>
<summary>3. ¿Por qué la marca se quita del texto al indexar?</summary>

Porque el texto del fragmento es lo que recibe el modelo como contexto. Si la marca se quedara, el modelo la vería y podría repetirla en una respuesta, igual que repitió la nota del primer intento. Como metadato, solo la ve el filtro.
</details>

<details>
<summary>4. ¿Qué error es peor: que el router diga pide_todo=false cuando el visitante sí lo pedía, o al revés?</summary>

Depende de lo que proteja el filtro y de qué diga el bot cuando le falta la información. Un `true` por error rompe el requisito de no mostrar lo secundario sin que lo pidan. Un `false` por error parecía inofensivo, pero la evaluación (sección 7) mostró que el bot puede negar que existan otros trabajos, y eso es dar un dato falso a un reclutador. Por eso la sección principal tiene que mencionar que existe más información. Si el filtro protegiera información confidencial, cualquier `true` por error sería grave, y por eso en ese caso la decisión no podría depender del LLM (sección 6).
</details>

<details>
<summary>5. ¿Por qué el filtro va en la consulta a Upstash y no en un if de Python sobre los resultados?</summary>

Porque filtrar después de buscar (post-filtrado) puede dejar menos fragmentos de los pedidos: si 2 de los 4 más parecidos eran secundarios, el contexto se quedaría con 2. Filtrando en la consulta, la búsqueda devuelve los 4 mejores entre los permitidos.
</details>
