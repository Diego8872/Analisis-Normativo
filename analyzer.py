"""
analyzer.py — Motor Claude para análisis de normativa argentina
"""
import os
import json
import re
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
MODEL = "claude-opus-4-6"

# ── PERFILES DE EXPERTO POR ORGANISMO ────────────────────────────────────────

EXPERTOS = {
    "BCRA": """Sos un experto en regulación cambiaria y financiera argentina.
Conocés en profundidad las comunicaciones del BCRA, el régimen de cambios,
las normas de entidades financieras y la operatoria cambiaria.""",

    "AFIP": """Sos un experto en derecho tributario y aduanero argentino.
Conocés el sistema impositivo nacional, los regímenes de retención,
percepciones, y las resoluciones generales de AFIP/ARCA.""",

    "SIC": """Sos un experto en comercio exterior y regulación arancelaria argentina.
Conocés la nomenclatura NCM, el régimen de importaciones y exportaciones,
las resoluciones de la Secretaría de Industria y Comercio, y el marco
del MEOSP 909/94 y normas conexas.""",

    "MINERIA": """Sos un experto en el régimen de inversiones mineras argentino.
Conocés en profundidad la Ley 24.196, el Decreto 2686/93, las resoluciones
de la Secretaría de Minería (SPM/SM), el régimen de exención arancelaria
del Art. 21 y los procedimientos de importación con beneficio minero.""",

    "BOLETIN": """Sos un experto en normativa legal y regulatoria argentina.
Analizás resoluciones, decretos y disposiciones con criterio técnico-jurídico,
identificando impacto práctico, condiciones y obligaciones.""",
}


def _limpiar_json(text: str) -> str:
    return re.sub(r"```json|```", "", text).strip()


# ── 1. ANÁLISIS INICIAL ───────────────────────────────────────────────────────

def analizar_norma(texto_norma: str, organismo: str = "BOLETIN") -> dict:
    perfil = EXPERTOS.get(organismo, EXPERTOS["BOLETIN"])

    prompt = f"""{perfil}

Analizá la siguiente normativa y respondé SOLO con JSON válido, sin texto adicional:

{{
  "titulo": "título o identificación de la norma",
  "organismo": "organismo emisor",
  "fecha": "fecha de publicación si está disponible",
  "resumen": "resumen ejecutivo en 3-4 oraciones claras",
  "impacto_principal": "cambiario | arancelario | impositivo | financiero | minero | comercial | otro",
  "afectados": ["quiénes se ven afectados"],
  "puntos_clave": ["punto 1", "punto 2", "punto 3"],
  "obligaciones": ["obligación 1", "obligación 2"],
  "vigencia": "fecha de vigencia o 'desde publicación'",
  "tiene_anexo_ncm": true,
  "ncms_condiciones": {{"NCM": "condición o null"}}
}}

NORMATIVA:
{texto_norma[:6000]}"""

    response = client.messages.create(
        model=MODEL, max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        return json.loads(_limpiar_json(response.content[0].text))
    except Exception:
        return {
            "resumen": response.content[0].text,
            "puntos_clave": [], "obligaciones": [],
            "afectados": [], "ncms_condiciones": {},
            "tiene_anexo_ncm": False
        }


# ── 2. NIVEL DE CONFIANZA DEL ANEXO ──────────────────────────────────────────

def evaluar_confianza_anexo(texto_norma: str, ncms_condiciones: dict) -> dict:
    """
    Evalúa qué tan completo es el Anexo extraído y retorna
    nivel de confianza con mensaje para mostrar al usuario.
    """
    tiene_ncms = bool(ncms_condiciones)
    cantidad = len(ncms_condiciones)
    menciona_anexo = any(p in texto_norma.upper() for p in [
        "ANEXO I", "ANEXO 1", "IF-20", "FORMA PARTE INTEGRANTE"
    ])

    if not tiene_ncms and menciona_anexo:
        return {
            "nivel": "sin_anexo",
            "icono": "❌",
            "mensaje": (
                "**Análisis sin Anexo completo:** esta norma tiene un Anexo con NCMs/condiciones "
                "que no pudo obtenerse desde las fuentes oficiales. El cruce se realizará por "
                "conocimiento general de la nomenclatura arancelaria, lo que puede generar "
                "resultados incompletos. **Para un análisis definitivo, subí el PDF del Anexo.**"
            ),
            "color": "error"
        }
    elif tiene_ncms and cantidad < 10:
        return {
            "nivel": "parcial",
            "icono": "⚠️",
            "mensaje": (
                f"**Análisis parcial:** se extrajeron {cantidad} NCMs del Anexo. "
                "Es posible que el listado no esté completo. Los artículos marcados "
                "🟡 **A ANALIZAR** requieren verificación contra el Anexo oficial. "
                "Si tenés el PDF del Anexo, subilo para mejorar la precisión."
            ),
            "color": "warning"
        }
    elif tiene_ncms and cantidad >= 10:
        return {
            "nivel": "completo",
            "icono": "✅",
            "mensaje": (
                f"**Análisis con confianza alta:** se extrajeron {cantidad} NCMs del Anexo. "
                "El cruce es confiable. Revisá igualmente los marcados 🟡 A ANALIZAR."
            ),
            "color": "success"
        }
    else:
        return {
            "nivel": "general",
            "icono": "ℹ️",
            "mensaje": (
                "**Análisis por conocimiento general:** esta norma no tiene Anexo de NCMs. "
                "El cruce se realiza por análisis semántico de cada artículo vs el texto de la norma."
            ),
            "color": "info"
        }


# ── 3. DIÁLOGO ────────────────────────────────────────────────────────────────

def generar_pregunta_output(analisis: dict, historial: list) -> str:
    perfil_norma = f"""
Norma: {analisis.get('titulo', '')}
Impacto: {analisis.get('impacto_principal', '')}
Afectados: {', '.join(analisis.get('afectados', []))}
Tiene NCMs: {analisis.get('tiene_anexo_ncm', False)}
"""
    response = client.messages.create(
        model=MODEL, max_tokens=300,
        messages=historial + [{
            "role": "user",
            "content": f"""Sos un asistente experto en normativa argentina.
Acabás de analizar esta norma: {perfil_norma}
Hacé UNA pregunta concisa al operador para entender qué necesita como output.
Ofrecé opciones concretas. Sé breve."""
        }]
    )
    return response.content[0].text.strip()


def responder_en_dialogo(texto_norma: str, analisis: dict,
                          historial: list, organismo: str = "BOLETIN") -> str:
    perfil = EXPERTOS.get(organismo, EXPERTOS["BOLETIN"])
    system = f"""{perfil}

Contexto de la norma analizada:
TÍTULO: {analisis.get('titulo', '')}
RESUMEN: {analisis.get('resumen', '')}
PUNTOS CLAVE: {'; '.join(analisis.get('puntos_clave', []))}
OBLIGACIONES: {'; '.join(analisis.get('obligaciones', []))}

TEXTO COMPLETO:
{texto_norma[:5000]}

Respondé las consultas del operador con criterio experto. Sé preciso y conciso."""

    response = client.messages.create(
        model=MODEL, max_tokens=800,
        system=system,
        messages=historial
    )
    return response.content[0].text.strip()


# ── 4. DETECCIÓN DE COLUMNAS ──────────────────────────────────────────────────

def detectar_columnas(columnas: list, muestra: list) -> dict:
    prompt = f"""Tenés un DataFrame con columnas: {columnas}
Muestra de filas: {json.dumps(muestra[:4], ensure_ascii=False)}

Identificá:
1. Columna de código/artículo (Artículo, Código, SKU, Part Number...)
2. Columna de NCM/posición arancelaria (Referencia, NCM, Posición...)
3. Columna de descripción (Descripción, Nombre, Denominación...) — puede no existir

Respondé SOLO JSON sin texto adicional:
{{"col_articulo": "nombre_o_null", "col_ncm": "nombre_o_null", "col_descripcion": "nombre_o_null"}}"""

    response = client.messages.create(
        model=MODEL, max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        return json.loads(_limpiar_json(response.content[0].text))
    except Exception:
        return {"col_articulo": None, "col_ncm": None, "col_descripcion": None}


# ── 5. CLASIFICACIÓN FILA POR FILA ────────────────────────────────────────────

def clasificar_articulos(df, cols: dict, ncms_condiciones: dict,
                          texto_norma: str, organismo: str,
                          progress_cb=None) -> list:
    perfil = EXPERTOS.get(organismo, EXPERTOS["BOLETIN"])
    resultados = []
    total = len(df)
    contexto_ncm = json.dumps(ncms_condiciones, ensure_ascii=False) if ncms_condiciones else ""

    for i, row in df.iterrows():
        articulo = str(row.get(cols.get("col_articulo", ""), "")).strip()
        ncm_art  = str(row.get(cols.get("col_ncm", ""), "")).strip()
        desc     = str(row.get(cols.get("col_descripcion", ""), "")).strip()

        # Verificar si el NCM está en el Anexo (primeros 8 dígitos)
        ncm_limpio = re.sub(r"[^0-9]", "", ncm_art)[:8]
        ncm_en_anexo = any(
            re.sub(r"[^0-9]", "", k)[:8] == ncm_limpio
            for k in ncms_condiciones.keys()
        ) if ncms_condiciones else None  # None = no tenemos Anexo

        # Si tenemos Anexo y el NCM no está → NO ENCUADRA directo
        if ncms_condiciones and ncm_en_anexo is False:
            resultados.append({
                "articulo": articulo, "ncm": ncm_art, "descripcion": desc,
                "estado": "NO ENCUADRA",
                "fundamento": "NCM no figura en el Anexo de la resolución",
                "color": "🔴"
            })
            if progress_cb: progress_cb((i + 1) / total)
            continue

        # Obtener condición para ese NCM
        condicion = next(
            (v for k, v in ncms_condiciones.items()
             if re.sub(r"[^0-9]", "", k)[:8] == ncm_limpio),
            None
        ) if ncms_condiciones else "No disponible — analizar por texto de norma"

        prompt = f"""{perfil}

{"NCMs y condiciones del Anexo: " + contexto_ncm if contexto_ncm else "Texto de la norma (sin Anexo extraído): " + texto_norma[:2000]}

Artículo a evaluar:
- Código: {articulo}
- NCM: {ncm_art}
- Descripción: {desc}
- Condición del Anexo para esta NCM: {condicion or 'Sin condición adicional'}

¿Este artículo encuadra en la norma para acceder al beneficio?

Respondé SOLO JSON:
{{"estado": "ENCUADRA|NO ENCUADRA|A ANALIZAR", "fundamento": "explicación en 1 oración"}}"""

        try:
            response = client.messages.create(
                model=MODEL, max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )
            resultado = json.loads(_limpiar_json(response.content[0].text))
            estado = resultado.get("estado", "A ANALIZAR")
            fundamento = resultado.get("fundamento", "")
        except Exception:
            estado = "A ANALIZAR"
            fundamento = "Error en clasificación — revisar manualmente"

        color = {"ENCUADRA": "🟢", "NO ENCUADRA": "🔴", "A ANALIZAR": "🟡"}.get(estado, "🟡")
        resultados.append({
            "articulo": articulo, "ncm": ncm_art, "descripcion": desc,
            "estado": estado, "fundamento": fundamento, "color": color
        })

        if progress_cb: progress_cb((i + 1) / total)

    return resultados


# ── 6. MEMO EJECUTIVO ─────────────────────────────────────────────────────────

def generar_resumen_ejecutivo(analisis: dict, resultados: list = None,
                               organismo: str = "BOLETIN") -> str:
    perfil = EXPERTOS.get(organismo, EXPERTOS["BOLETIN"])

    stats = ""
    if resultados:
        enc = sum(1 for r in resultados if r["estado"] == "ENCUADRA")
        no  = sum(1 for r in resultados if r["estado"] == "NO ENCUADRA")
        aal = sum(1 for r in resultados if r["estado"] == "A ANALIZAR")
        detalle = "\n".join(
            f"- {r['articulo']} ({r['ncm']}): {r['estado']} — {r['fundamento']}"
            for r in resultados[:25]
        )
        stats = f"""
Resultados del cruce de catálogo:
- Total analizados: {len(resultados)}
- Encuadran: {enc}
- No encuadran: {no}
- A analizar: {aal}

Detalle:
{detalle}
"""

    prompt = f"""{perfil}

Redactá un memo ejecutivo profesional basado en este análisis normativo:

NORMA: {analisis.get('titulo', '')}
RESUMEN: {analisis.get('resumen', '')}
PUNTOS CLAVE: {'; '.join(analisis.get('puntos_clave', []))}
OBLIGACIONES: {'; '.join(analisis.get('obligaciones', []))}
VIGENCIA: {analisis.get('vigencia', '')}
AFECTADOS: {', '.join(analisis.get('afectados', []))}
{stats}

El memo debe incluir: encabezado formal, marco normativo, análisis técnico,
conclusiones y recomendaciones. Estilo profesional y lenguaje técnico preciso."""

    response = client.messages.create(
        model=MODEL, max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()
