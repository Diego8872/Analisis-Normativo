"""
analyzer.py — Motor de análisis de normativa argentina
Anthropic Sonnet como motor principal
Groq (openai/gpt-oss-120b) como fallback si Anthropic falla por saldo

LÓGICA DE FALLBACK:
- _es_error_saldo() detecta errores 402 / credit / balance
- _llamar_modelo() → Sonnet → si saldo insuficiente → Groq
- _llamar_modelo_chat() → Groq primero (chat/saludo) → fallback Anthropic
- Web search: solo Anthropic (Groq no tiene tool nativo)

LÍMITES DE CARACTERES (bloque único para ajustar):
- Perfil SONNET: se usa cuando el análisis corre en Anthropic (límites amplios).
- Perfil GROQ: se usa si cae a Groq (TPM ajustado en plan gratis).
- Todos se pueden sobreescribir con variables de entorno, sin tocar el código.
"""
import os
import json
import re
import anthropic
from groq import Groq

client_claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
client_groq   = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))

MODEL_SONNET   = os.environ.get("MODEL_SONNET", "claude-sonnet-4-6")
MODEL_HAIKU    = os.environ.get("MODEL_HAIKU", "claude-haiku-4-5-20251001")
MODEL_GROQ     = os.environ.get("MODEL_GROQ", "openai/gpt-oss-120b")


# ── LÍMITES DE CARACTERES ─────────────────────────────────────────────────────
def _env_int(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, defecto))
    except (TypeError, ValueError):
        return defecto


# Perfil Sonnet (Anthropic) — amplio
LIMITE_NORMA_SONNET = _env_int("LIMITE_NORMA_SONNET", 30_000)   # texto de la norma
LIMITE_ANEXO_SONNET = _env_int("LIMITE_ANEXO_SONNET", 25_000)   # por anexo
LIMITE_TOTAL_SONNET = _env_int("LIMITE_TOTAL_SONNET", 90_000)   # norma + anexos

# Perfil Groq (fallback) — el plan gratis permite ~8.000 tokens/min entre
# entrada y salida (error 413 si se pasa). Con ~3 chars/token: 12.000 chars
# ≈ 4.000 tokens + ~700 de instrucciones + 2.000 de salida = ~6.700.
# No subir salvo plan pago de Groq.
LIMITE_NORMA_GROQ   = _env_int("LIMITE_NORMA_GROQ", 8_000)
LIMITE_ANEXO_GROQ   = _env_int("LIMITE_ANEXO_GROQ", 4_000)
LIMITE_TOTAL_GROQ   = _env_int("LIMITE_TOTAL_GROQ", 12_000)
GROQ_MAX_TOKENS     = _env_int("GROQ_MAX_TOKENS", 2_000)   # tope de salida en Groq

# Motor que respondió en la última llamada de análisis ("sonnet" | "haiku" | "groq")
ULTIMO_MOTOR = ""

SISTEMA_EXPERTO = """Sos un experto senior en normativa argentina (derecho administrativo, comercio exterior, aduana, ARCA, AFIP, BCRA). Analizás resoluciones con criterio riguroso y práctico. Detectás ambigüedades, señalás riesgos, diferenciás lo que dice la norma de tu interpretación. No inventás información no explícita.
IMPORTANTE: Tu interlocutor es un despachante de aduana o profesional del comercio exterior. NUNCA recomendés contratar asesores aduanales ni despachantes — ellos ya son los expertos. Dirigí las recomendaciones a la operatoria concreta, no a buscar ayuda profesional externa."""

FORMATO_SALIDA = """Análisis profesional para cliente de comercio exterior. Conciso y directo — el operador profundiza en el chat.

LÍMITE ESTRICTO: máx 120 palabras por sección. Sin relleno, sin repetir info entre secciones.

Secciones FIJAS (siempre presentes):
1. RESUMEN EJECUTIVO — qué regula, a quién afecta, qué cambia. Prosa, máx 5 oraciones.
2. PUNTOS CLAVE — máx 6 bullets con obligaciones y plazos que realmente importan.
3. ANÁLISIS OPERATIVO — máx 4 pasos de alto nivel con riesgo principal por paso.
4. RIESGOS Y ZONAS GRISES — máx 3, con 🔴 alto / 🟡 medio.

Sección CONDICIONAL (solo si la norma crea códigos, regímenes o mecanismos específicos):
- SUBREGÍMENES / MECANISMOS — tabla: código | descripción | tributos. Insertá entre sección 2 y 3.

Diferenciá norma (texto) de interpretación (inferencia). Sin checklist, sin dudas abiertas, sin recomendar asesores externos."""


def _groq_chat(messages: list, max_tokens: int) -> str:
    """Llamada a Groq. Con modelos gpt-oss baja el esfuerzo de razonamiento
    para que los tokens se usen en la respuesta y no en pensar."""
    kwargs = {}
    if "gpt-oss" in MODEL_GROQ:
        kwargs["extra_body"] = {"reasoning_effort": "low"}
    response = client_groq.chat.completions.create(
        model=MODEL_GROQ, max_tokens=max_tokens,
        messages=messages, **kwargs
    )
    return (response.choices[0].message.content or "").strip()


def _es_error_saldo(e: Exception) -> bool:
    """Detecta si el error es por saldo insuficiente en Anthropic."""
    msg = str(e).lower()
    return "credit" in msg or "balance" in msg or "billing" in msg or "402" in msg


def _llamar_modelo(system: str, prompt: str, max_tokens: int = 4000, prompt_groq: str = None) -> str:
    """
    Análisis: Sonnet primero → si falla por saldo → Groq → si no → Haiku.
    prompt_groq: versión reducida del prompt para el fallback a Groq
    (si no se pasa, se usa el mismo prompt).
    """
    global ULTIMO_MOTOR

    # Intento 1: Anthropic Sonnet
    try:
        response = client_claude.messages.create(
            model=MODEL_SONNET, max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}]
        )
        ULTIMO_MOTOR = "sonnet"
        return response.content[0].text.strip()
    except Exception as e:
        if not _es_error_saldo(e):
            # Error distinto al saldo → probar Haiku antes de Groq
            try:
                response = client_claude.messages.create(
                    model=MODEL_HAIKU, max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}]
                )
                ULTIMO_MOTOR = "haiku"
                return response.content[0].text.strip()
            except Exception:
                pass

    # Fallback: Groq (con el prompt reducido si existe)
    texto = _groq_chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt_groq or prompt}
        ],
        max_tokens=min(max_tokens, GROQ_MAX_TOKENS)
    )
    ULTIMO_MOTOR = "groq"
    return texto


def _llamar_modelo_chat(system: str, historial: list, max_tokens: int = 1000) -> str:
    """
    Chat/saludo: Groq primero (más rápido y gratis) → fallback Anthropic.
    """
    msgs = [{"role": m["role"], "content": m["content"]} for m in historial]
    try:
        texto = _groq_chat(
            [{"role": "system", "content": system}] + msgs,
            max_tokens=min(max_tokens, GROQ_MAX_TOKENS)
        )
        if texto:
            return texto
        raise ValueError("Respuesta vacía de Groq")
    except Exception:
        response = client_claude.messages.create(
            model=MODEL_SONNET, max_tokens=max_tokens,
            system=system, messages=historial
        )
        return response.content[0].text.strip()


# ── DETECCIÓN DE ORGANISMO ────────────────────────────────────────────────────

def detectar_organismo_con_ia(numero: str) -> dict:
    prompt = f"""Sos un experto en normativa argentina. El operador ingresó: "{numero}"

Determiná organismo y tipo. Respondé SOLO JSON:
{{
  "organismo": "BCRA|AFIP|SIC|MINERIA|ANMAT|SENASA|BOLETIN|DESCONOCIDO",
  "tipo": "resolución|comunicación|disposición|decreto|circular|otro",
  "numero_limpio": "número extraído",
  "confianza": "alta|media|baja",
  "razonamiento": "breve explicación"
}}

Ejemplos: "Com. A 8330"→BCRA, "RG 5424"→AFIP, "Res SIC 5/2026"→SIC, "Res 5838/2026"→BOLETIN, "SPM 89/19"→MINERIA, "Disp ANMAT 537"→ANMAT"""

    try:
        text = _llamar_modelo(
            "Respondé SOLO con JSON válido, sin texto adicional.",
            prompt, max_tokens=300
        )
        text = re.sub(r"```json|```", "", text).strip()
        return json.loads(text)
    except Exception:
        return {
            "organismo": "BOLETIN", "tipo": "resolución",
            "numero_limpio": numero, "confianza": "baja",
            "razonamiento": "No determinado"
        }


# ── ANEXOS ────────────────────────────────────────────────────────────────────

RE_NCM = re.compile(r'(?<![\d.])(\d{4}\.\d{2}\.\d{2})(?!\d)')
RE_RUIDO = re.compile(r'^(IF-|P[áa]gina\b|Digitally|Date:|ELECTRONICA|GESTION DOCUMENTAL)', re.IGNORECASE)


def _digitos8(ncm) -> str:
    """NCM a solo dígitos, primeros 8 (el catálogo puede venir a 12)."""
    return re.sub(r"[^0-9]", "", str(ncm))[:8]


def _extraer_ncms(texto: str) -> list:
    """Códigos NCM (0000.00.00) sin duplicados y en orden. Ignora firmas digitales."""
    vistos, salida = set(), []
    for linea in texto.splitlines():
        if linea.strip().lower().startswith(("date:", "digitally signed")):
            continue
        for m in RE_NCM.findall(linea):
            if m not in vistos:
                vistos.add(m)
                salida.append(m)
    return salida


def _es_listado_ncm(contenido: str) -> bool:
    """True si el anexo es básicamente una lista de códigos NCM (sin condiciones/descripciones)."""
    solo_codigo = otras = 0
    for linea in contenido.splitlines():
        l = linea.strip()
        if not l or RE_RUIDO.match(l):
            continue
        if RE_NCM.fullmatch(l):
            solo_codigo += 1
        else:
            otras += 1
    return solo_codigo >= 30 and solo_codigo >= 0.85 * (solo_codigo + otras)


def _nombre_anexo_desde_contenido(contenido: str):
    """Si el texto empieza con 'ANEXO II' (o similar) devuelve 'ANEXO II'."""
    m = re.search(r'^\s*ANEXO\s+([IVX\d]+)\b', contenido[:600], re.IGNORECASE | re.MULTILINE)
    return f"ANEXO {m.group(1).upper()}" if m else None


def _mismo_anexo(nombre_a: str, nombre_b: str) -> bool:
    """Compara nombres de anexo sin confundir 'ANEXO I' con 'ANEXO II'."""
    a, b = nombre_a.upper().strip(), nombre_b.upper().strip()
    return bool(re.search(rf'(?<!\w){re.escape(a)}(?!\w)', b))


def _detectar_y_bajar_anexos(texto: str) -> list:
    import requests as _req
    import pdfplumber
    import io as _io
    HEADERS = {"User-Agent": "Mozilla/5.0"}
    anexos = []
    urls = re.findall(r'https?://[^\s\'"<>\)]+\.pdf', texto, re.IGNORECASE)
    nombres_raw = re.findall(r'ANEXO\s+([IVX\d]+)', texto, re.IGNORECASE)
    for i, url in enumerate(urls[:3]):
        nombre = f"ANEXO {nombres_raw[i]}" if i < len(nombres_raw) else f"ANEXO {i+1}"
        try:
            r = _req.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                contenido = ""
                with pdfplumber.open(_io.BytesIO(r.content)) as pdf:
                    for page in pdf.pages:
                        contenido += (page.extract_text() or "") + "\n"
                if contenido.strip():
                    anexos.append({"nombre": nombre, "url": url, "contenido": contenido.strip()})
        except Exception:
            pass
    return anexos


def _detectar_anexos_faltantes(texto: str, encontrados: list) -> list:
    menciones = re.findall(r'ANEXO\s+([IVX\d]+)', texto, re.IGNORECASE)
    faltantes = []
    for m in menciones:
        nombre = f"ANEXO {m.upper()}"
        if not any(_mismo_anexo(nombre, a["nombre"]) for a in encontrados):
            if nombre not in faltantes:
                faltantes.append(nombre)
    return faltantes


def _unir_anexos(anexos_encontrados: list, anexos_usuario: list = None) -> list:
    """Une anexos descargados + subidos por el usuario (sin duplicar por nombre)."""
    todos = list(anexos_encontrados)
    if anexos_usuario:
        for au in anexos_usuario:
            contenido = au.get("contenido", "")
            # El nombre del archivo puede ser cualquier cosa: si el texto dice "ANEXO II", se usa eso
            nombre = _nombre_anexo_desde_contenido(contenido) or au.get("nombre", "ANEXO SUBIDO")
            if not any(_mismo_anexo(nombre, a["nombre"]) for a in todos):
                todos.append({"nombre": nombre, "contenido": contenido, "url": None})
    return todos


def _construir_bloque_anexos(todos: list, limite_anexo: int, limite_total: int) -> tuple[str, list]:
    """Arma el bloque de texto de anexos respetando los límites. Devuelve (bloque, nombres_incluidos)."""
    if not todos:
        return "", []

    bloques = []
    chars_usados = 0
    incluidos = []

    for a in todos:
        contenido = a["contenido"].strip()
        if _es_listado_ncm(contenido):
            # Listado puro de NCM: se procesa por código, no hace falta mandarlo entero al modelo
            ncms_a = _extraer_ncms(contenido)
            titulo = " / ".join(l.strip() for l in contenido.splitlines()[:2] if l.strip())
            contenido = (f"[Anexo con listado de {len(ncms_a)} códigos NCM. Se procesa automáticamente; no se reproduce.]\n"
                         f"Encabezado: {titulo}\n"
                         f"Primeros códigos: {', '.join(ncms_a[:15])} ...")
        if len(contenido) > limite_anexo:
            contenido = contenido[:limite_anexo] + "\n[... contenido truncado por longitud ...]"
        if chars_usados + len(contenido) > limite_total:
            break
        bloques.append(f"--- {a['nombre']} ---\n{contenido}")
        chars_usados += len(contenido)
        incluidos.append(a["nombre"])

    bloque_texto = "\n\nANEXOS DISPONIBLES:\n" + "\n\n".join(bloques) if bloques else ""
    return bloque_texto, incluidos


# ── ANÁLISIS PRINCIPAL ────────────────────────────────────────────────────────

def _armar_prompt_analisis(texto_norma: str, todos_anexos: list, anexos_faltantes: list,
                           limite_norma: int, limite_anexo: int, limite_total: int,
                           n_ncms: int = 0) -> tuple[str, dict]:
    """Arma el prompt de análisis para un perfil de límites. Devuelve (prompt, info_debug)."""
    bloque_anexos, nombres_incluidos = _construir_bloque_anexos(todos_anexos, limite_anexo, limite_total)

    chars_disponibles_norma = max(0, min(limite_norma, limite_total - len(bloque_anexos)))
    texto_norma_truncado = texto_norma[:chars_disponibles_norma]
    if len(texto_norma) > chars_disponibles_norma:
        texto_norma_truncado += "\n[... norma truncada por longitud total ...]"

    aviso_cobertura = ""
    if nombres_incluidos:
        aviso_cobertura = f"\nNOTA: Se incluyen los siguientes Anexos completos: {', '.join(nombres_incluidos)}. Analizalos en detalle.\n"
    if n_ncms:
        aviso_cobertura += (f"NOTA: los {n_ncms} NCM del listado ya fueron extraídos por el sistema. "
                            "Dejá \"ncms_condiciones\" vacío ({}) y poné \"tiene_anexo_ncm\" en true.\n")
    if anexos_faltantes:
        aviso_cobertura += f"AVISO: Los siguientes Anexos no están disponibles: {', '.join(anexos_faltantes)}. Indicalo en el análisis.\n"

    prompt = f"""Analizá esta normativa argentina. Sé conciso — máx 5 oraciones por sección.
{aviso_cobertura}
{bloque_anexos}

NORMATIVA:
{texto_norma_truncado}

Al final incluí metadatos entre <meta>...</meta>:
<meta>
{{
  "titulo": "identificación completa",
  "organismo": "organismo emisor",
  "fecha": "fecha si disponible",
  "vigencia": "desde cuándo rige",
  "impacto_principal": "cambiario|arancelario|impositivo|financiero|minero|comercial|sanitario|otro",
  "afectados": ["lista"],
  "tiene_anexo_ncm": false,
  "ncms_condiciones": {{}}
}}
</meta>"""

    info = {
        "chars_norma_enviada": len(texto_norma_truncado),
        "chars_anexos_enviados": len(bloque_anexos),
        "anexos_incluidos": nombres_incluidos,
    }
    return prompt, info


def analizar_norma(texto_norma: str, organismo: str = "BOLETIN", anexos_usuario: list = None) -> dict:
    anexos_descargados = _detectar_y_bajar_anexos(texto_norma)
    todos_anexos = _unir_anexos(anexos_descargados, anexos_usuario or [])
    anexos_faltantes = _detectar_anexos_faltantes(texto_norma, todos_anexos)

    # NCM de los anexos que son listados puros: extracción directa, sin pasar por el modelo
    ncms_listados = []
    for a in todos_anexos:
        if _es_listado_ncm(a["contenido"]):
            for c in _extraer_ncms(a["contenido"]):
                if c not in ncms_listados:
                    ncms_listados.append(c)

    system = SISTEMA_EXPERTO + "\n\n" + FORMATO_SALIDA

    # Prompt amplio para Sonnet y prompt reducido para el fallback a Groq
    prompt_sonnet, info_sonnet = _armar_prompt_analisis(
        texto_norma, todos_anexos, anexos_faltantes,
        LIMITE_NORMA_SONNET, LIMITE_ANEXO_SONNET, LIMITE_TOTAL_SONNET,
        n_ncms=len(ncms_listados)
    )
    prompt_groq, info_groq = _armar_prompt_analisis(
        texto_norma, todos_anexos, anexos_faltantes,
        LIMITE_NORMA_GROQ, LIMITE_ANEXO_GROQ, LIMITE_TOTAL_GROQ,
        n_ncms=len(ncms_listados)
    )

    texto_respuesta = _llamar_modelo(system, prompt_sonnet, max_tokens=2500, prompt_groq=prompt_groq)

    # Info de debug según el motor que realmente respondió
    info = info_groq if ULTIMO_MOTOR == "groq" else info_sonnet

    meta = {}
    meta_match = re.search(r"<meta>(.*?)</meta>", texto_respuesta, re.DOTALL)
    if meta_match:
        try:
            meta = json.loads(meta_match.group(1).strip())
        except Exception:
            meta = {}
        texto_respuesta = texto_respuesta[:meta_match.start()].strip()

    # Si hay listado NCM extraído por código, ese es el que manda (sin condiciones adicionales)
    if ncms_listados:
        ncms_final = {c: "" for c in ncms_listados}
        tiene_ncm = True
    else:
        ncms_final = meta.get("ncms_condiciones") or {}
        tiene_ncm = meta.get("tiene_anexo_ncm", False)

    return {
        "analisis_completo": texto_respuesta,
        "titulo": meta.get("titulo", ""),
        "organismo": meta.get("organismo", organismo),
        "fecha": meta.get("fecha", ""),
        "vigencia": meta.get("vigencia", ""),
        "impacto_principal": meta.get("impacto_principal", ""),
        "afectados": meta.get("afectados", []),
        "tiene_anexo_ncm": tiene_ncm,
        "ncms_condiciones": ncms_final,
        "puntos_clave": [],
        "obligaciones": [],
        "anexos_encontrados": todos_anexos,
        "anexos_faltantes": anexos_faltantes,
        "_debug": {
            "motor": ULTIMO_MOTOR,
            "chars_norma_enviada": info["chars_norma_enviada"],
            "chars_anexos_enviados": info["chars_anexos_enviados"],
            "anexos_incluidos": info["anexos_incluidos"],
            "ncms_extraidos": len(ncms_listados),
        }
    }


# ── CONFIANZA ANEXO ───────────────────────────────────────────────────────────

def evaluar_confianza_anexo(texto_norma: str, ncms_condiciones: dict) -> dict:
    ncms_condiciones = ncms_condiciones or {}
    tiene_ncms = bool(ncms_condiciones)
    cantidad = len(ncms_condiciones)
    menciona_anexo = any(p in texto_norma.upper() for p in ["ANEXO I", "ANEXO 1", "IF-20", "FORMA PARTE INTEGRANTE"])

    if not tiene_ncms and menciona_anexo:
        return {"nivel": "sin_anexo", "icono": "❌", "mensaje": "**Sin Anexo completo:** no pudo obtenerse desde fuentes oficiales. Subí el PDF del Anexo para análisis definitivo."}
    elif tiene_ncms and cantidad < 10:
        return {"nivel": "parcial", "icono": "⚠️", "mensaje": f"**Análisis parcial:** {cantidad} NCMs extraídos. Verificá los 🟡 A ANALIZAR contra el Anexo oficial."}
    elif tiene_ncms and cantidad >= 10:
        return {"nivel": "completo", "icono": "✅", "mensaje": f"**Confianza alta:** {cantidad} NCMs extraídos correctamente."}
    else:
        return {"nivel": "general", "icono": "ℹ️", "mensaje": "**Análisis semántico:** norma sin Anexo NCMs. Cruce por texto."}


# ── CHAT Y SALUDO ─────────────────────────────────────────────────────────────

def saludo_inicial() -> str:
    return ("Hola, soy tu asistente de normativa argentina. "
            "Podés decirme el número de norma (*Res 5838/2026*, *Com. A 8330*, *RG 5424*...), "
            "describir el tema, o contarme qué problema necesitás resolver. "
            "También podés subir el documento o pegar el texto directamente.")


def chat_inicial_respuesta(historial: list) -> str:
    system = SISTEMA_EXPERTO + """

Tu rol ahora: guiar al operador para encontrar y analizar la norma.
- Si menciona un número, confirmá y decile que vas a buscarlo.
- Si describe un problema, orientalo a qué norma corresponde.
- Si es ambiguo, preguntá organismo o más contexto.
- Máximo 4 oraciones. Directo y profesional."""
    return _llamar_modelo_chat(system, historial, max_tokens=400)


def responder_en_dialogo(texto_norma: str, analisis: dict, historial: list, organismo: str = "BOLETIN") -> str:
    system = SISTEMA_EXPERTO + f"""

Norma analizada: {analisis.get('titulo', '')}
Análisis previo:
{analisis.get('analisis_completo', '')[:3000]}

Texto norma:
{texto_norma[:3000]}

Respondé con criterio experto. Si algo no está en la norma, indicalo claramente."""
    return _llamar_modelo_chat(system, historial, max_tokens=1000)


def generar_pregunta_output(analisis: dict, historial: list) -> str:
    titulo = analisis.get('titulo', 'la norma')
    return (f"Analizé **{titulo}**. "
            "¿Qué necesitás? Podés pedirme que profundice en algún punto, "
            "cruzar con tu catálogo, generar un memo, o hacerme cualquier consulta.")


# ── CRUCE CON CATÁLOGO ────────────────────────────────────────────────────────

def detectar_columnas(columnas: list, muestra: list) -> dict:
    prompt = f"""Columnas: {columnas}
Muestra: {json.dumps(muestra[:4], ensure_ascii=False)}
Identificá artículo/código, NCM y descripción.
SOLO JSON: {{"col_articulo": "nombre_o_null", "col_ncm": "nombre_o_null", "col_descripcion": "nombre_o_null"}}"""
    try:
        text = _llamar_modelo("Respondé SOLO con JSON válido.", prompt, max_tokens=150)
        return json.loads(re.sub(r"```json|```", "", text).strip())
    except Exception:
        return {"col_articulo": None, "col_ncm": None, "col_descripcion": None}


def clasificar_articulos(df, cols: dict, ncms_condiciones: dict, texto_norma: str, organismo: str, progress_cb=None) -> list:
    """
    Cruza el catálogo contra los NCM de la norma, comparando a 8 dígitos
    (el catálogo puede traer 12). Sin IA cuando el anexo es solo una lista de NCM.
    """
    resultados = []
    total = len(df)
    ncms_condiciones = ncms_condiciones or {}
    idx_anexo = {_digitos8(k): v for k, v in ncms_condiciones.items()}
    contexto_ncm = json.dumps(ncms_condiciones, ensure_ascii=False) if (ncms_condiciones and len(ncms_condiciones) <= 60) else ""

    for n, (_, row) in enumerate(df.iterrows(), start=1):
        articulo = str(row.get(cols.get("col_articulo", ""), "")).strip()
        ncm_art  = str(row.get(cols.get("col_ncm", ""), "")).strip()
        desc     = str(row.get(cols.get("col_descripcion", ""), "")).strip()
        ncm_limpio = _digitos8(ncm_art)

        def agregar(estado, fundamento):
            color = {"ENCUADRA": "🟢", "NO ENCUADRA": "🔴", "A ANALIZAR": "🟡"}.get(estado, "🟡")
            resultados.append({"articulo": articulo, "ncm": ncm_art, "descripcion": desc,
                               "estado": estado, "fundamento": fundamento, "color": color})
            if progress_cb:
                progress_cb(n / total)

        if ncms_condiciones:
            if len(ncm_limpio) < 8:
                agregar("A ANALIZAR", "NCM vacío o incompleto en el catálogo")
                continue
            if ncm_limpio not in idx_anexo:
                agregar("NO ENCUADRA", "NCM no figura en el Anexo")
                continue
            condicion = idx_anexo[ncm_limpio]
            if not condicion:
                agregar("ENCUADRA", "El NCM (8 dígitos) figura en el Anexo, sin condiciones adicionales")
                continue
        else:
            condicion = "Evaluar por texto"

        prompt = f"""{SISTEMA_EXPERTO}

{"NCMs Anexo: " + contexto_ncm if contexto_ncm else "Texto norma: " + texto_norma[:2000]}
Artículo: {articulo} | NCM: {ncm_art} | Desc: {desc} | Condición: {condicion or 'Sin condición'}
¿Encuadra? SOLO JSON: {{"estado": "ENCUADRA|NO ENCUADRA|A ANALIZAR", "fundamento": "1 oración"}}"""

        try:
            text = _llamar_modelo("Respondé SOLO con JSON válido.", prompt, max_tokens=150)
            resultado = json.loads(re.sub(r"```json|```", "", text).strip())
            estado = resultado.get("estado", "A ANALIZAR")
            fundamento = resultado.get("fundamento", "")
        except Exception:
            estado = "A ANALIZAR"
            fundamento = "Error — revisar manualmente"

        agregar(estado, fundamento)

    return resultados


def generar_resumen_ejecutivo(analisis: dict, resultados: list = None, organismo: str = "BOLETIN") -> str:
    stats = ""
    if resultados:
        enc = sum(1 for r in resultados if r["estado"] == "ENCUADRA")
        no  = sum(1 for r in resultados if r["estado"] == "NO ENCUADRA")
        aal = sum(1 for r in resultados if r["estado"] == "A ANALIZAR")
        detalle = "\n".join(f"- {r['articulo']} ({r['ncm']}): {r['estado']} — {r['fundamento']}" for r in resultados[:25])
        stats = f"\nCruce: {len(resultados)} artículos | Encuadran: {enc} | No: {no} | A analizar: {aal}\n{detalle}"

    prompt = f"""Redactá memo ejecutivo profesional:\nNORMA: {analisis.get('titulo','')}\n{analisis.get('analisis_completo','')[:3000]}\n{stats}\nIncluir: encabezado, marco normativo, análisis técnico, conclusiones y recomendaciones."""
    return _llamar_modelo(SISTEMA_EXPERTO, prompt, max_tokens=1500)
