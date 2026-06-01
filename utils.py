"""
utils.py — Búsqueda de normas con web search + fetch + lectura de archivos
Estrategia en cascada:
  1. Web search apuntando al Boletín Oficial → fetch directo
  2. Web search apuntando a Infoleg → fetch directo
  3. Web search genérico (fallback)
  
  Para web search: Anthropic primero → si falla por saldo → Groq
"""
import re
import io
import os
import requests
import anthropic
from groq import Groq

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AnálisisNormativo/1.0)"}
client_claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
client_groq   = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
MODEL_GROQ    = "llama-3.3-70b-versatile"

DOMINIOS_OFICIALES = [
    "boletinoficial.gob.ar",
    "infoleg.gob.ar",
    "servicios.infoleg.gob.ar",
    "arca.gob.ar",
    "biblioteca.arca.gob.ar",
    "bcra.gob.ar",
    "argentina.gob.ar/normativa",
]


def _es_error_saldo(e: Exception) -> bool:
    """Detecta si el error es por saldo insuficiente en Anthropic."""
    msg = str(e).lower()
    return "credit" in msg or "balance" in msg or "billing" in msg or "402" in msg


def _extraer_url_oficial(texto: str) -> str | None:
    """Extrae la primera URL de un dominio oficial del texto dado."""
    urls = re.findall(r'https?://[^\s\'"<>)\]]+', texto)
    for url in urls:
        if any(d in url for d in DOMINIOS_OFICIALES):
            url = re.sub(r'[.,;)\]]+$', '', url)
            return url
    return None


def _fetch_texto(url: str) -> str:
    """Descarga y extrae el texto limpio de una URL (HTML o PDF)."""
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
        return texto[:12000]
    except Exception:
        return ""


def _web_search_claude(prompt: str, max_tokens: int = 1000) -> str:
    """Web search usando Anthropic con tool web_search."""
    response = client_claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}]
    )
    texto = ""
    for block in response.content:
        if hasattr(block, "text") and block.text:
            texto += block.text + "\n"
        if hasattr(block, "type") and block.type == "tool_result":
            if hasattr(block, "content"):
                for sub in block.content:
                    if hasattr(sub, "text"):
                        texto += sub.text + "\n"
    return texto


def _web_search_groq(prompt: str) -> str:
    """Web search usando Groq (sin tool nativo — pide que infiera la URL)."""
    response = client_groq.chat.completions.create(
        model=MODEL_GROQ,
        max_tokens=500,
        messages=[
            {
                "role": "system",
                "content": "Sos un asistente especializado en normativa argentina. "
                           "Cuando te pidan buscar una norma, construí la URL más probable "
                           "en boletinoficial.gob.ar o infoleg.gob.ar e indicála claramente."
            },
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content.strip()


def _web_search_con_fallback(prompt: str, max_tokens_claude: int = 1000) -> str:
    """Intenta web search con Anthropic; si falla por saldo, usa Groq."""
    try:
        return _web_search_claude(prompt, max_tokens_claude)
    except Exception as e:
        if _es_error_saldo(e):
            return _web_search_groq(prompt)
        raise


def _web_search_y_fetch(prompt_busqueda: str) -> tuple[str, str]:
    """
    Hace web search, extrae URL oficial y hace fetch.
    Returns: (texto, fuente)
    """
    try:
        texto_respuesta = _web_search_con_fallback(prompt_busqueda)

        url = _extraer_url_oficial(texto_respuesta)
        if url:
            texto_fetcheado = _fetch_texto(url)
            if len(texto_fetcheado.strip()) > 300:
                return texto_fetcheado, url

        if len(texto_respuesta.strip()) > 300:
            return texto_respuesta.strip(), "Fuentes oficiales (web search)"

    except Exception as e:
        return "", f"Error: {e}"

    return "", ""


def buscar_norma(numero: str) -> tuple[str, str]:
    """
    Busca la norma argentina usando estrategia en cascada.
    Returns: (texto_norma, fuente)
    """

    # ── PASO 1: Boletín Oficial ───────────────────────────────────────────────
    texto, fuente = _web_search_y_fetch(
        f'Buscá "{numero}" en el sitio boletinoficial.gob.ar. '
        f'Necesito la URL exacta del aviso en boletinoficial.gob.ar/detalleAviso/...'
    )
    if texto and len(texto) > 300:
        return texto, fuente

    # ── PASO 2: Infoleg ───────────────────────────────────────────────────────
    texto, fuente = _web_search_y_fetch(
        f'Buscá "{numero}" en servicios.infoleg.gob.ar o infoleg.gob.ar. '
        f'Necesito la URL exacta de la norma en infoleg.'
    )
    if texto and len(texto) > 300:
        return texto, fuente

    # ── PASO 3: Fallback genérico ─────────────────────────────────────────────
    texto, fuente = _web_search_y_fetch(
        f'Buscá la norma argentina "{numero}" y traé el texto completo con todos '
        f'sus artículos y considerandos. Priorizá Infoleg, ARCA, BCRA o Boletín Oficial.'
    )
    if texto and len(texto) > 300:
        return texto, fuente

    return "", "No encontrada — subí el PDF manualmente."


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
