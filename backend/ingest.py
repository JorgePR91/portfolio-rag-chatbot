"""Ingesta del RAG: indexa los documentos de me/ en la base vectorial.

Se ejecuta en local, cada vez que cambia algún .md de me/ (si no, el chatbot
sigue respondiendo con la versión anterior):

    cd backend
    python ingest.py --ver   # muestra los fragmentos sin tocar el índice
    python ingest.py         # sustituye el índice por completo

Trocea los textos por secciones de Markdown, los sube a Upstash Vector (que
calcula los embeddings) y sustituye por completo el índice anterior. Más
detalles en ACTUALIZAR_RAG.md.
"""
import os
import sys
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# vector_store.py vive en api/ (es el módulo que también usa el backend desplegado).
# Lo añadimos a la ruta de importación para no duplicarlo aquí.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import vector_store

CARPETA_DOCS = "me/"
# Tope por fragmento: casi todas las secciones caben enteras. Solo si una
# sección es más larga se parte, con solapamiento para no cortar una frase.
CHUNK_SIZE     = 1000     # caracteres por fragmento
CHUNK_OVERLAP  = 100      # solapamiento, solo si una sección hay que partirla
# Marca para secciones secundarias: solo se usan cuando el visitante pide toda
# la información (ver 'pide_todo' en el router). Va debajo del título en el .md.
MARCA_SECUNDARIA = "<!-- secundaria -->"


def cargar_documentos(carpeta = CARPETA_DOCS):
    """Lee cada .md/.txt de la carpeta (sin subcarpetas) como un documento.

    El nombre del fichero se guarda como metadato "origen", para saber luego de
    qué documento sale cada fragmento recuperado.
    """
    documentos = []
    for fichero in os.listdir(carpeta):
        ruta_completa = os.path.join(carpeta, fichero)
        if os.path.isfile(ruta_completa):
            _, extension = os.path.splitext(ruta_completa)
            if extension in ('.md','.txt'):
                with open(ruta_completa, 'r', encoding='utf-8') as archivo:
                    texto = archivo.read()
                    documentos.append(Document(
                        page_content=texto,
                        metadata={"origen": fichero}
                    ))
    return documentos


def trocear(documentos):
    """Trocea por la estructura del documento, no por número de caracteres.

    - Primero por títulos (# y ##): cada fragmento es una sección completa, así
      no quedan títulos sueltos sin contenido ni párrafos sin su título.
    - Solo si una sección es muy larga, se parte por tamaño.

    Cada fragmento lleva delante su ruta de títulos ("Proyectos > Nombre") para
    que "sepa" de qué trata aunque su texto no lo diga.
    """
    por_titulos = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2")]
    )
    por_tamano = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks = []
    for doc in documentos:
        for seccion in por_titulos.split_text(doc.page_content):
            ruta = " > ".join(
                seccion.metadata[nivel] for nivel in ("h1", "h2") if nivel in seccion.metadata
            )
            # La marca pasa a los metadatos y se quita del texto: el modelo
            # nunca la ve, así que no puede repetirla en una respuesta.
            secundaria = MARCA_SECUNDARIA in seccion.page_content
            contenido = seccion.page_content.replace(MARCA_SECUNDARIA, "").strip()
            metadata = {**doc.metadata, "secundaria": True} if secundaria else doc.metadata
            for trozo in por_tamano.split_text(contenido):
                chunks.append(Document(
                    page_content=f"{ruta}\n{trozo}" if ruta else trozo,
                    metadata=metadata,
                ))
    return chunks


if __name__ == "__main__":
    documentos = cargar_documentos()
    chunks = trocear(documentos)

    # --ver: muestra los fragmentos SIN tocar el índice. Úsalo antes de indexar,
    # porque indexar empieza borrando todo lo que hay.
    if "--ver" in sys.argv:
        for c in chunks:
            marca = " [secundaria]" if c.metadata.get("secundaria") else ""
            print(f"--- {c.metadata['origen']}{marca} ({len(c.page_content)} caracteres)")
            print(c.page_content)
        print(f"\nDocumentos = {len(documentos)} | Chunks = {len(chunks)}")
        sys.exit()

    # Se vacía el índice antes de subir: así no quedan fragmentos de textos
    # borrados o modificados.
    vector_store.index.reset()
    vector_store.subir(chunks)

    # La confirmación viene del propio Upstash, no del número de fragmentos enviados.
    info = vector_store.index.info()
    print(f"Documentos = {len(documentos)} | Chunks subidos = {len(chunks)} | "
          f"En el índice: {info.vector_count} (+{info.pending_vector_count} pendientes)")
