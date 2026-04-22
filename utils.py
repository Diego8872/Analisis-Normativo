"""
utils.py — Lectura de archivos y búsqueda de normas en fuentes oficiales
"""
import re
import io
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AnálisisNormativo/1.0)"}


# ── DETECCIÓN DE ORGANISMO ────────────────────────────────────────────────────

def detectar_organismo(numero: str) -> str:
    """Detecta el organismo según el formato del número de norma."""
    n = numero.upper().strip()
    if re.match(r"COM\.?\s*[ABCP]\s*\d+|COMUNICACI[OÓ]N\s*[ABCP]", n):
        return "BCRA"
    if re.match(r"RG\s*\d+|RESOLUCI[OÓ]N\s*GENERAL", n):
        return "AFIP"
    if re.match(r"RES\.?\s*SIC|SIC\s*\d+", n):
        return "SIC"
    if re.match(r"RES\.?\s*SPM|SPM\s*\d+|RES\.?\s*SM\s*\d+", n):
        return "MINERIA"
    return "BOLETIN"


# ── BÚSQUEDA POR ORGANISMO ────────────────────────────────────────────────────

def buscar_bcra(numero: str) -> str:
    """Busca una comunicación del BCRA por número."""
    m = re.search(r"([ABCP])\s*(\d+)", numero.upper())
    if not m:
        return ""
    tipo, num = m.group(1), m.group(2)
    url = (
        f"https://www.bcra.gob.ar/SistemasFinancierosYdePagos/"
        f"Buscador_por_tipo.asp?tipo={tipo}&numero={num}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if ".pdf" in a["href"].lower():
                pdf_url = a["href"] if a["href"].startswith("http") \
                    else "https://www.bcra.gob.ar" + a["href"]
                return leer_pdf_desde_url(pdf_url)
        return soup.get_text(separator="\n", strip=True)[:8000]
    except Exception:
        return ""


def buscar_boletin_oficial(numero: str) -> str:
    """Busca en el Boletín Oficial argentino."""
    query = numero.strip()
    try:
        url = "https://www.boletinoficial.gob.ar/busquedaAvanzada/realizarBusqueda"
        r = requests.get(url, params={"textoBusqueda": query, "limit": 3},
                         headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        # Intentar encontrar link a PDF o texto
        for a in soup.find_all("a", href=True):
            if ".pdf" in a["href"].lower():
                return leer_pdf_desde_url(a["href"])
        return soup.get_text(separator="\n", strip=True)[:6000]
    except Exception:
        return ""


def buscar_norma(numero: str) -> tuple[str, str]:
    """
    Intenta encontrar la norma en fuentes oficiales.
    Returns: (texto_norma, fuente_descripcion)
    """
    organismo = detectar_organismo(numero)

    if organismo == "BCRA":
        texto = buscar_bcra(numero)
        fuente = "BCRA — bcra.gob.ar"
    else:
        texto = buscar_boletin_oficial(numero)
        fuente = "Boletín Oficial — boletinoficial.gob.ar"

    return texto.strip(), fuente


# ── LECTURA DE ARCHIVOS ───────────────────────────────────────────────────────

def leer_pdf(file_bytes: bytes) -> str:
    """Extrae texto de un PDF."""
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
    """Descarga y extrae texto de un PDF desde URL."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return leer_pdf(r.content)
    except Exception:
        return ""


def leer_word(file_bytes: bytes) -> str:
    """Extrae texto de un archivo Word (.docx)."""
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return f"[Error leyendo Word: {e}]"


def leer_archivo(file_bytes: bytes, filename: str) -> str:
    """Detecta el tipo y extrae el texto."""
    ext = filename.lower().split(".")[-1]
    if ext == "pdf":
        return leer_pdf(file_bytes)
    elif ext in ("docx", "doc"):
        return leer_word(file_bytes)
    else:
        return file_bytes.decode("utf-8", errors="replace")


def leer_excel(file_bytes: bytes, filename: str):
    """Lee un Excel o CSV y retorna un DataFrame."""
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
    except Exception as e:
        return None
    return None
