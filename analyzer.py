"""
analyzer.py — Motor de análisis de normativa argentina
Groq (llama-3.3-70b) como motor principal — rápido y gratuito
Claude Haiku como fallback si Groq falla

CAMBIOS v3:
- Motor principal: Groq llama-3.3-70b (~2-5s, gratis)
- Fallback: Claude Haiku (se usa solo si Groq falla)
- Web search: siempre Claude Sonnet (Groq no tiene)
- Límites y lógica de anexos: sin cambios
"""
import os
import json
import re
import anthropic
from groq import Groq

client_claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
client_groq   = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))

MODEL_GROQ   = "llama-3.3-70b-versatile"
MODEL_CLAUDE = "claude-haiku-4-5-20251001"  # fallback


def _llamar_modelo(system: str, prompt: str, max_tokens: int = 4000) -> str:
    """Claude Haiku primero (calidad), Groq como fallback (si Haiku falla o timeout)."""
    try:
        response = client_claude.messages.create(
            model=MODEL_CLAUDE, max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception:
        response = client_groq.chat.completions.create(
            model=MODEL_GROQ,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ]
        )
        return response.choices[0].message.content.strip()

# ── Límites calibrados al contenido real ──────────────────────────────────────
LIMITE_NORMA   = 9_500   # chars — cubre normas de hasta ~4 páginas completas
LIMITE_ANEXO   = 7_000   # chars — cubre anexos de hasta ~3 páginas completas
LIMITE_TOTAL   = 28_000  # chars — techo de seguridad Tier 1 (~7k tokens input)
# ─────────────────────────────────────────────────────────────────────────────

SISTEMA_EXPERTO = """Sos un experto senior en normativa argentina (derecho administrativo, comercio exterior, aduana, ARCA, AFIP, BCRA). Analizás resoluciones con criterio riguroso y práctico. Detectás ambigüedades, señalás riesgos, diferenciás lo que dice la norma de tu interpretación. No inventás información no explícita.
IMPORTANTE: Tu interlocutor es un despachante de aduana o profesional del comercio exterior. NUNCA recomendés contratar asesores aduanales ni despachantes — ellos ya son los expertos. Dirigí las recomendaciones a la operatoria concreta, no a buscar ayuda profesional externa."""

FORMATO_SALIDA = """Analizás como un experto que le habla a otro experto. Sin introduciones, sin paja, sin recomendar buscar ayuda externa. Directo al punto operativo. El operador puede pedir detalle en el chat.

Formato de 6 secciones:
1. RESUMEN EJECUTIVO — qué cambia, a quién afecta, desde cuándo. Máx 5 oraciones.
2. PUNTOS CLAVE — las obligaciones y plazos que realmente importan. Máx 6 bullets concisos.
3. ANÁLISIS OPERATIVO — qué tiene que hacer el operador en la práctica. Máx 4 pasos de alto nivel, sin detallar subpasos.
4. RIESGOS Y ZONAS GRISES — ambigüedades reales de la norma que pueden generar contingencias. Máx 3 riesgos concretos.
5. CHECKLIST — lo que hay que tener listo antes de operar. Máx 8 ítems.
6. DUDAS ABIERTAS — preguntas que la norma no responde y que conviene consultar con ARCA. Máx 4."""


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


def _detectar_y_bajar_anexos(texto: str) -> list:
    """Busca URLs de PDFs de Anexos en el texto y los descarga."""
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
                    # FIX: usar LIMITE_ANEXO en lugar de hardcodear 600
                    anexos.append({
                        "nombre": nombre,
                        "url": url,
                        "contenido": contenido.strip()
                    })
        except Exception:
            pass
    return anexos


def _detectar_anexos_faltantes(texto: str, encontrados: list) -> list:
    """Detecta Anexos mencionados en la norma que no pudieron obtenerse."""
    menciones = re.findall(r'ANEXO\s+([IVX\d]+)', texto, re.IGNORECASE)
    faltantes = []
    for m in menciones:
        nombre = f"ANEXO {m.upper()}"
        if not any(nombre in a["nombre"].upper() for a in encontrados):
            if nombre not in faltantes:
                faltantes.append(nombre)
    return faltantes


def _construir_bloque_anexos(anexos_encontrados: list, anexos_usuario: list = None) -> tuple[str, list, list]:
    """
    Combina anexos descargados automáticamente + subidos por el usuario.
    Respeta LIMITE_ANEXO por anexo y LIMITE_TOTAL global.
    Retorna (bloque_texto, lista_completa, nombres_incluidos).
    """
    todos = list(anexos_encontrados)  # copia

    # Agregar los subidos por el usuario (formato: {"nombre": str, "contenido": str})
    if anexos_usuario:
        for au in anexos_usuario:
            nombre = au.get("nombre", "ANEXO SUBIDO")
            # No duplicar si ya se descargó
            if not any(nombre.upper() in a["nombre"].upper() for a in todos):
                todos.append({"nombre": nombre, "contenido": au.get("contenido", ""), "url": None})

    if not todos:
        return "", [], []

    bloques = []
    chars_usados = 0
    incluidos = []

    for a in todos:
        contenido = a["contenido"].strip()
        # Truncar al límite por anexo
        if len(contenido) > LIMITE_ANEXO:
            contenido = contenido[:LIMITE_ANEXO] + "\n[... contenido truncado por longitud ...]"

        # Verificar techo global
        if chars_usados + len(contenido) > LIMITE_TOTAL:
            break

        bloques.append(f"--- {a['nombre']} ---\n{contenido}")
        chars_usados += len(contenido)
        incluidos.append(a["nombre"])

    bloque_texto = "\n\nANEXOS DISPONIBLES:\n" + "\n\n".join(bloques) if bloques else ""
    return bloque_texto, todos, incluidos


def analizar_norma(
    texto_norma: str,
    organismo: str = "BOLETIN",
    anexos_usuario: list = None   # ← NUEVO: lista de {"nombre": str, "contenido": str}
) -> dict:
    """
    Analiza una norma con todos sus anexos.

    anexos_usuario: anexos subidos manualmente por el usuario en Tab 3.
    Cada elemento: {"nombre": "ANEXO I", "contenido": "texto extraído del PDF"}
    """
    # 1. Intentar bajar anexos referenciados en el texto
    anexos_descargados = _detectar_y_bajar_anexos(texto_norma)

    # 2. Combinar con los subidos por el usuario
    bloque_anexos, todos_anexos, nombres_incluidos = _construir_bloque_anexos(
        anexos_descargados, anexos_usuario or []
    )

    # 3. Detectar faltantes (menciones en norma que no están en ninguna fuente)
    anexos_faltantes = _detectar_anexos_faltantes(texto_norma, todos_anexos)

    # 4. Truncar norma al límite (respetando techo total)
    chars_disponibles_norma = min(LIMITE_NORMA, LIMITE_TOTAL - len(bloque_anexos))
    texto_norma_truncado = texto_norma[:chars_disponibles_norma]
    if len(texto_norma) > chars_disponibles_norma:
        texto_norma_truncado += "\n[... norma truncada por longitud total ...]"

    # 5. Aviso de cobertura para el modelo
    aviso_cobertura = ""
    if nombres_incluidos:
        aviso_cobertura = f"\nNOTA: Se incluyen los siguientes Anexos completos: {', '.join(nombres_incluidos)}. Analizalos en detalle.\n"
    if anexos_faltantes:
        aviso_cobertura += f"AVISO: Los siguientes Anexos no están disponibles: {', '.join(anexos_faltantes)}. Indicalo en el análisis.\n"

    system = SISTEMA_EXPERTO + "\n\n" + FORMATO_SALIDA

    # ── LLAMADA 1: secciones 1-4 + metadatos ─────────────────────────────────
    prompt1 = f"""Analizá esta normativa argentina. Generá SOLO las secciones 1 a 4:
1. RESUMEN EJECUTIVO
2. PUNTOS CLAVE
3. ANÁLISIS OPERATIVO
4. RIESGOS Y ZONAS GRISES
{aviso_cobertura}
IMPORTANTE: Tenés el texto COMPLETO. NO digas que está incompleta. Sé exhaustivo en cada sección.

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
</meta>
{bloque_anexos}

NORMATIVA:
{texto_norma_truncado}"""

    texto_parte1 = _llamar_modelo(system, prompt1, max_tokens=4000)

    # Extraer metadatos de parte 1
    meta = {}
    meta_match = re.search(r"<meta>(.*?)</meta>", texto_parte1, re.DOTALL)
    if meta_match:
        try:
            meta = json.loads(meta_match.group(1).strip())
        except Exception:
            meta = {}
        texto_parte1 = texto_parte1[:meta_match.start()].strip()

    # ── LLAMADA 2: secciones 5-7 ─────────────────────────────────────────────
    prompt2 = f"""Continuás el análisis de esta normativa argentina. Generá SOLO las secciones 5 y 6:
5. CHECKLIST ACCIONABLE - pasos concretos para cumplir
6. DUDAS ABIERTAS - qué confirmar con autoridad competente
{aviso_cobertura}
Contexto del análisis previo (secciones 1-4 ya generadas):
{texto_parte1[:2000]}

NORMATIVA:
{texto_norma_truncado[:3000]}"""

    texto_parte2 = _llamar_modelo(system, prompt2, max_tokens=3000)

    # Limpiar cualquier <meta> residual de parte 2
    meta_match2 = re.search(r"<meta>(.*?)</meta>", texto_parte2, re.DOTALL)
    if meta_match2:
        texto_parte2 = texto_parte2[:meta_match2.start()].strip()

    texto_respuesta = texto_parte1 + "\n\n" + texto_parte2

    return {
        "analisis_completo": texto_respuesta,
        "titulo": meta.get("titulo", ""),
        "organismo": meta.get("organismo", organismo),
        "fecha": meta.get("fecha", ""),
        "vigencia": meta.get("vigencia", ""),
        "impacto_principal": meta.get("impacto_principal", ""),
        "afectados": meta.get("afectados", []),
        "tiene_anexo_ncm": meta.get("tiene_anexo_ncm", False),
        "ncms_condiciones": meta.get("ncms_condiciones") or {},
        "puntos_clave": [],
        "obligaciones": [],
        "anexos_encontrados": todos_anexos,
        "anexos_faltantes": anexos_faltantes,
        # Info de diagnóstico — útil para debug en Streamlit
        "_debug": {
            "chars_norma_enviada": len(texto_norma_truncado),
            "chars_anexos_enviados": len(bloque_anexos),
            "anexos_incluidos": nombres_incluidos,
        }
    }


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

    # Convertir historial al formato Groq/OpenAI
    msgs = [{"role": m["role"], "content": m["content"]} for m in historial]
    try:
        response = client_groq.chat.completions.create(
            model=MODEL_GROQ, max_tokens=400,
            messages=[{"role": "system", "content": system}] + msgs
        )
        return response.choices[0].message.content.strip()
    except Exception:
        response = client_claude.messages.create(
            model=MODEL_CLAUDE, max_tokens=400,
            system=system, messages=historial
        )
        return response.content[0].text.strip()


def responder_en_dialogo(texto_norma: str, analisis: dict, historial: list, organismo: str = "BOLETIN") -> str:
    system = SISTEMA_EXPERTO + f"""

Norma analizada: {analisis.get('titulo', '')}
Análisis previo:
{analisis.get('analisis_completo', '')[:3000]}

Texto norma:
{texto_norma[:3000]}

Respondé con criterio experto. Si algo no está en la norma, indicalo claramente."""

    msgs = [{"role": m["role"], "content": m["content"]} for m in historial]
    try:
        response = client_groq.chat.completions.create(
            model=MODEL_GROQ, max_tokens=1000,
            messages=[{"role": "system", "content": system}] + msgs
        )
        return response.choices[0].message.content.strip()
    except Exception:
        response = client_claude.messages.create(
            model=MODEL_CLAUDE, max_tokens=1000,
            system=system, messages=historial
        )
        return response.content[0].text.strip()


def generar_pregunta_output(analisis: dict, historial: list) -> str:
    titulo = analisis.get('titulo', 'la norma')
    return (f"Analizé **{titulo}**. "
            "¿Qué necesitás? Podés pedirme que profundice en algún punto, "
            "cruzar con tu catálogo, generar un memo, o hacerme cualquier consulta.")


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
    resultados = []
    total = len(df)
    contexto_ncm = json.dumps(ncms_condiciones, ensure_ascii=False) if ncms_condiciones else ""

    for i, row in df.iterrows():
        articulo = str(row.get(cols.get("col_articulo", ""), "")).strip()
        ncm_art  = str(row.get(cols.get("col_ncm", ""), "")).strip()
        desc     = str(row.get(cols.get("col_descripcion", ""), "")).strip()
        ncm_limpio = re.sub(r"[^0-9]", "", ncm_art)[:8]
        ncm_en_anexo = any(re.sub(r"[^0-9]", "", k)[:8] == ncm_limpio for k in ncms_condiciones.keys()) if ncms_condiciones else None

        if ncms_condiciones and ncm_en_anexo is False:
            resultados.append({"articulo": articulo, "ncm": ncm_art, "descripcion": desc, "estado": "NO ENCUADRA", "fundamento": "NCM no figura en el Anexo", "color": "🔴"})
            if progress_cb: progress_cb((i + 1) / total)
            continue

        condicion = next((v for k, v in ncms_condiciones.items() if re.sub(r"[^0-9]", "", k)[:8] == ncm_limpio), None) if ncms_condiciones else "Evaluar por texto"

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

        color = {"ENCUADRA": "🟢", "NO ENCUADRA": "🔴", "A ANALIZAR": "🟡"}.get(estado, "🟡")
        resultados.append({"articulo": articulo, "ncm": ncm_art, "descripcion": desc, "estado": estado, "fundamento": fundamento, "color": color})
        if progress_cb: progress_cb((i + 1) / total)

    return resultados


def generar_resumen_ejecutivo(analisis: dict, resultados: list = None, organismo: str = "BOLETIN") -> str:
    stats = ""
    if resultados:
        enc = sum(1 for r in resultados if r["estado"] == "ENCUADRA")
        no  = sum(1 for r in resultados if r["estado"] == "NO ENCUADRA")
        aal = sum(1 for r in resultados if r["estado"] == "A ANALIZAR")
        detalle = "\n".join(f"- {r['articulo']} ({r['ncm']}): {r['estado']} — {r['fundamento']}" for r in resultados[:25])
        stats = f"\nCruce: {len(resultados)} artículos | Encuadran: {enc} | No: {no} | A analizar: {aal}\n{detalle}"

    prompt = f"""{SISTEMA_EXPERTO}\nRedactá memo ejecutivo profesional:\nNORMA: {analisis.get('titulo','')}\n{analisis.get('analisis_completo','')[:3000]}\n{stats}\nIncluir: encabezado, marco normativo, análisis técnico, conclusiones y recomendaciones."""
    return _llamar_modelo(SISTEMA_EXPERTO, prompt, max_tokens=1500)
