"""Ingesta del RAG: indexa los documentos de me/ en la base vectorial.

Se ejecuta en local, cada vez que cambia algún .md de me/ (si no, el chatbot
sigue respondiendo con la versión anterior):

    cd backend
    python ingest.py

Trocea los textos, los sube a Upstash Vector (que calcula los embeddings) y
sustituye por completo el índice anterior. Más detalles en ACTUALIZAR_RAG.md.
"""
import os
import sys
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

# Carga las variables del .env de backend/ ANTES de importar vector_store:
# ese módulo crea el índice de Upstash al importarse (Index.from_env()), así que
# las variables ya deben estar en el entorno. Damos la ruta explícita porque
# load_dotenv() sin argumentos busca el .env junto al fichero que lo llama (api/),
# donde no existe. (Esto solo afecta a la ejecución LOCAL: ingest.py no se ejecuta
# en Vercel, que inyecta sus propias variables de entorno.)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# vector_store.py vive en api/ (es el módulo que también usa el backend desplegado).
# Lo añadimos a la ruta de importación para no duplicarlo aquí.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import vector_store

CARPETA_DOCS = "me/"
# Fragmentos pequeños: el chat solo recupera 4, así que cada uno debe contener
# un único hecho. El solapamiento evita perder una frase que caiga en un corte.
CHUNK_SIZE     = 400      # caracteres por fragmento
CHUNK_OVERLAP  = 100      # solapamiento entre fragmentos contiguos

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


if __name__ == "__main__":
    documentos = cargar_documentos()
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = splitter.split_documents(documentos)

    # Se vacía el índice antes de subir: así no quedan fragmentos de textos
    # borrados o modificados.
    vector_store.index.reset()
    vector_store.subir(chunks)

    print(f"Documentos = {len(documentos)} | Chunks subidos = {len(chunks)}")
