"""
analyzer.py — Motor Claude para análisis de normativa argentina
Prompt experto senior + formato estructurado de 7 secciones
"""
import os
import json
import re
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
MODEL = "claude-haiku-4-5-20251001"

SISTEMA_EXPERTO = """Actuá como un experto senior en análisis normativo y regulatorio argentino, con especialización en derecho administrativo, comercio exterior, aduana (DGA), ARCA, AFIP, BCRA y normativa técnica.

Tu rol es analizar resoluciones, disposiciones, leyes y normativa en general de forma rigurosa, crítica y estructurada.

Principios de comportamiento:
- No asumas que el texto es claro: detectá ambigüedades, vacíos y posibles interpretaciones.
- No simplifiques en exceso: priorizá precisión antes que rapidez.
- Señalá inconsistencias, contradicciones o problemas prácticos de aplicación.
- Pensá como alguien que debe aplicar la norma en la vida real (operador, despachante, empresa).
- Si algo no está explícito en la norma, indicarlo claramente (no inventar).
- Diferenciá siempre entre lo que dice la norma y tu interpretación.
- Usá lenguaje claro pero técnico. Evitá relleno o explicaciones genéricas.
- No repitas el texto de la norma: interpretalo."""

FORMATO_SALIDA = """
Formato de salida OBLIGATORIO:

1. RESUMEN EJECUTIVO (máximo 10 líneas)
- Qué regula / A quién afecta / Qué cambia respecto a antes

2. PUNTOS CLAVE
- Obligaciones, prohibiciones, requisitos, plazos, montos, excepciones

3. ANÁLISIS OPERATIVO
- Impacto práctico / Acciones concretas a tomar

4. RIESGOS Y ZONAS GRISES
- Ambigüedades / Conflictos de interpretación / Riesgos de incumplimiento

5. EJEMPLO PRÁCTICO
- Caso concreto aplicado a una empresa o situación real

6. CHECKLIST ACCIONABLE
- Pasos concretos para cumplir la norma

7. DUDAS ABIERTAS
- Qué no queda claro / Qué confirmar con autoridad competente"""


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
        response = client.messages.create(
            model=MODEL, max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        text = re.sub(r"```json|```", "", response.content[0].text).strip()
        return json.loads(text)
    except Exception:
        return {"organismo": "BOLETIN", "tipo": "resolución", "numero_limpio": numero, "confianza": "baja", "razonamiento": "No determinado"}


def analizar_norma(texto_norma: str, organismo: str = "BOLETIN") -> dict:
    system = SISTEMA_EXPERTO + "\n\n" + FORMATO_SALIDA
    prompt = f"""Analizá esta normativa argentina con el formato de 7 secciones.

NORMATIVA:
{texto_norma[:7000]}

Al final, extraé metadatos entre <meta>...</meta>:
<meta>
{{
  "titulo": "identificación completa",
  "organismo": "organismo emisor",
  "fecha": "fecha si disponible",
  "vigencia": "desde cuándo rige",
  "impacto_principal": "cambiario|arancelario|impositivo|financiero|minero|comercial|sanitario|otro",
  "afectados": ["lista"],
  "tiene_anexo_ncm": true,
  "ncms_condiciones": {{"NCM": "condición o null"}}
}}
</meta>"""

    response = client.messages.create(
        model=MODEL, max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )

    texto_respuesta = response.content[0].text.strip()
    meta = {}
    meta_match = re.search(r"<meta>(.*?)</meta>", texto_respuesta, re.DOTALL)
    if meta_match:
        try:
            meta = json.loads(meta_match.group(1).strip())
        except Exception:
            meta = {}
        texto_respuesta = texto_respuesta[:meta_match.start()].strip()

    return {
        "analisis_completo": texto_respuesta,
        "titulo": meta.get("titulo", ""),
        "organismo": meta.get("organismo", organismo),
        "fecha": meta.get("fecha", ""),
        "vigencia": meta.get("vigencia", ""),
        "impacto_principal": meta.get("impacto_principal", ""),
        "afectados": meta.get("afectados", []),
        "tiene_anexo_ncm": meta.get("tiene_anexo_ncm", False),
        "ncms_condiciones": meta.get("ncms_condiciones", {}),
        "puntos_clave": [],
        "obligaciones": [],
    }


def evaluar_confianza_anexo(texto_norma: str, ncms_condiciones: dict) -> dict:
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

    response = client.messages.create(
        model=MODEL, max_tokens=400,
        system=system,
        messages=historial
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

    response = client.messages.create(
        model=MODEL, max_tokens=1000,
        system=system,
        messages=historial
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

    response = client.messages.create(model=MODEL, max_tokens=150, messages=[{"role": "user", "content": prompt}])
    try:
        return json.loads(re.sub(r"```json|```", "", response.content[0].text).strip())
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
            response = client.messages.create(model=MODEL, max_tokens=150, messages=[{"role": "user", "content": prompt}])
            resultado = json.loads(re.sub(r"```json|```", "", response.content[0].text).strip())
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
    response = client.messages.create(model=MODEL, max_tokens=1500, messages=[{"role": "user", "content": prompt}])
    return response.content[0].text.strip()
