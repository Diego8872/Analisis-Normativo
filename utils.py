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


def buscar_norma(numero: str) -> tuple[str, str]:
    """
    Busca la norma usando web search.
    Estrategia: pedir directamente el texto, no solo la URL.
    Returns: (texto_norma, fuente)
    """
    # Estrategia única: pedir texto completo directamente con web search
    prompt = f"""Buscá la norma argentina "{numero}" y traé el texto completo con todos sus artículos y considerandos.
Priorizá fuentes como Infoleg, ARCA, BCRA, o Boletín Oficial.
Incluí número, organismo emisor, fecha, y el texto íntegro de los artículos."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        # Leer TODOS los bloques de texto (no solo el primero)
        texto_completo = ""
        url_encontrada = "Fuentes oficiales (web search)"

        for block in response.content:
            # Bloque de texto final de Claude
            if hasattr(block, "text") and block.text:
                texto_completo += block.text + "\n"
            # Resultado de tool — extraer URL y contenido
            if hasattr(block, "type") and block.type == "tool_result":
                if hasattr(block, "content"):
                    for sub in block.content:
                        if hasattr(sub, "text"):
                            texto_completo += sub.text + "\n"
            # tool_use — capturar query ejecutada (debug)
            if hasattr(block, "type") and block.type == "tool_use":
                pass

        # Extraer primera URL oficial mencionada
        urls = re.findall(r'https?://[^\s\'"<>)\]]+', texto_completo)
        for url in urls:
            if any(d in url for d in ["infoleg", "arca.gob", "bcra.gob", "boletinoficial", "argentina.gob"]):
                url_encontrada = url
                break

        if len(texto_completo.strip()) > 300:
            return texto_completo.strip(), url_encontrada

    except Exception as e:
        return "", f"Error: {e}"

    return "", "No encontrada — subí el PDF manualmente."


def _fetch_url(url: str) -> str:
    """Descarga y extrae el texto de una URL."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")

        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return leer_pdf(r.content)

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        texto = soup.get_text(separator="\n", strip=True)
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
