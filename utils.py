"""
utils.py — Búsqueda de normas con web search + fetch + lectura de archivos
"""
import re
import io
import os
import requests
import anthropic

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AnálisisNormativo/1.0)"}
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

URLS_PRIORITARIAS = [
    "https://www.boletinoficial.gob.ar",
    "https://servicios.infoleg.gob.ar",
    "https://biblioteca.arca.gob.ar",
    "https://www.bcra.gob.ar",
    "https://www.argentina.gob.ar/normativa",
]


def buscar_norma(numero: str) -> tuple[str, str]:
    """
    Busca la norma usando web search + fetch del contenido completo.
    Returns: (texto_norma, fuente)
    """
    # Paso 1: buscar con web search para encontrar la URL correcta
    prompt_busqueda = f"""Buscá la norma argentina: "{numero}"

Encontrá la URL oficial donde está publicada (Boletín Oficial, Infoleg, ARCA, BCRA, etc).
Retorná SOLO la URL más relevante donde está el texto completo, sin ningún otro texto.
Ejemplo de respuesta: https://www.boletinoficial.gob.ar/detalleAviso/primera/305286/20260422"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt_busqueda}]
        )

        # Extraer URL de la respuesta
        url_encontrada = None
        for block in response.content:
            if hasattr(block, "text") and block.text:
                # Buscar URLs en el texto
                urls = re.findall(r'https?://[^\s\'"<>]+', block.text)
                for url in urls:
                    if any(dominio in url for dominio in [
                        "boletinoficial", "infoleg", "arca.gob", "bcra.gob",
                        "argentina.gob", "afip.gob", "biblioteca"
                    ]):
                        url_encontrada = url
                        break

        # Paso 2: si encontramos URL, fetchear el contenido completo
        if url_encontrada:
            texto = _fetch_url(url_encontrada)
            if texto and len(texto) > 300:
                return texto, url_encontrada

        # Paso 3: si no hay URL o el fetch falló, pedir a Claude que traiga el texto
        prompt_texto = f"""Buscá "{numero}" norma argentina. Traé el texto completo con artículos y considerandos."""

        response2 = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt_texto}]
        )

        texto_completo = ""
        for block in response2.content:
            if hasattr(block, "text") and block.text:
                texto_completo += block.text

        if len(texto_completo) > 300:
            return texto_completo, "Fuentes oficiales (web search)"

    except Exception as e:
        pass

    return "", ""


def _fetch_url(url: str) -> str:
    """Descarga y extrae el texto de una URL."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")

        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return leer_pdf(r.content)

        # HTML — extraer texto
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        # Remover scripts y estilos
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        texto = soup.get_text(separator="\n", strip=True)
        # Limpiar líneas vacías múltiples
        texto = re.sub(r'\n{3,}', '\n\n', texto)
        return texto[:8000]
    except Exception:
        return ""


# ── LECTURA DE ARCHIVOS ───────────────────────────────────────────────────────

def leer_pdf(file_bytes: bytes) -> str:
    try:
        import pdfplumber
        texto = ""
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                texto += (page.extract_text() or "") + "\n"
        return texto.strip()
    except Exception as e:
        return f"[Error leyendo PDF: {e}]"


def leer_pdf_desde_url(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return leer_pdf(r.content)
    except Exception:
        return ""


def leer_word(file_bytes: bytes) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return f"[Error leyendo Word: {e}]"


def leer_archivo(file_bytes: bytes, filename: str) -> str:
    ext = filename.lower().split(".")[-1]
    if ext == "pdf":
        return leer_pdf(file_bytes)
    elif ext in ("docx", "doc"):
        return leer_word(file_bytes)
    else:
        return file_bytes.decode("utf-8", errors="replace")


def leer_excel(file_bytes: bytes, filename: str):
    import pandas as pd
    ext = filename.lower().split(".")[-1]
    try:
        if ext == "csv":
            return pd.read_csv(io.BytesIO(file_bytes), dtype=str).fillna("")
        else:
            xl = pd.ExcelFile(io.BytesIO(file_bytes))
            for sheet in xl.sheet_names:
                df = xl.parse(sheet, dtype=str).fillna("")
                if len(df) > 0 and len(df.columns) > 1:
                    return df
    except Exception:
        return None
    return None
