"""
utils.py — Búsqueda de normas con web search via Claude API + lectura de archivos
"""
import re
import io
import json
import os
import requests
import anthropic

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AnálisisNormativo/1.0)"}
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


# ── BÚSQUEDA CON WEB SEARCH ───────────────────────────────────────────────────

def buscar_norma(numero: str) -> tuple[str, str]:
    """
    Usa Claude con web_search para encontrar la norma en fuentes oficiales.
    Busca en Boletín Oficial, Infoleg, ARCA, BCRA, AFIP, etc.
    Returns: (texto_norma, fuente)
    """
    prompt = f"""Buscá la siguiente norma argentina: "{numero}"

Buscá en estas fuentes en orden de prioridad:
1. boletinoficial.gob.ar
2. infoleg.gob.ar / argentina.gob.ar/normativa
3. biblioteca.arca.gob.ar (para resoluciones ARCA/AFIP)
4. bcra.gob.ar (para comunicaciones BCRA)
5. servicios.infoleg.gob.ar

Una vez que la encuentres, extraé el texto COMPLETO de la norma incluyendo:
- Considerandos
- Articulado completo
- Anexos si están disponibles
- Fecha de publicación y vigencia

Retorná el texto completo de la norma. Si encontrás los Anexos también incluilos.
Al final indicá la URL donde la encontraste entre etiquetas <fuente>URL</fuente>."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        texto_completo = ""
        fuente_url = ""

        for block in response.content:
            if hasattr(block, "text"):
                texto_completo += block.text

        # Extraer URL de fuente
        fuente_match = re.search(r"<fuente>(.*?)</fuente>", texto_completo, re.DOTALL)
        if fuente_match:
            fuente_url = fuente_match.group(1).strip()
            texto_completo = texto_completo[:fuente_match.start()].strip()

        if len(texto_completo) > 300:
            return texto_completo, fuente_url or "Fuentes oficiales (web search)"
        else:
            return "", ""

    except Exception as e:
        # Fallback a scraping directo si falla web search
        return _buscar_scraping(numero)


def _buscar_scraping(numero: str) -> tuple[str, str]:
    """Fallback: scraping directo del Boletín Oficial."""
    try:
        url = "https://www.boletinoficial.gob.ar/busquedaAvanzada/realizarBusqueda"
        r = requests.get(url, params={"textoBusqueda": numero.strip(), "limit": 3},
                         headers=HEADERS, timeout=12)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if ".pdf" in a["href"].lower():
                texto = leer_pdf_desde_url(a["href"])
                if texto:
                    return texto, "Boletín Oficial — boletinoficial.gob.ar"
        texto = soup.get_text(separator="\n", strip=True)[:6000]
        return texto, "Boletín Oficial — boletinoficial.gob.ar"
    except Exception:
        return "", ""


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
