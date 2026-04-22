"""
app.py — Analizador Universal de Normativa Argentina
Streamlit app — github.com/Analisis-normativo
"""
import streamlit as st
import pandas as pd
import json
import io
import os
from datetime import datetime

from utils import detectar_organismo, buscar_norma, leer_archivo, leer_excel
from analyzer import (
    analizar_norma, generar_pregunta_output, responder_en_dialogo,
    detectar_columnas, clasificar_articulos, generar_resumen_ejecutivo,
    evaluar_confianza_anexo
)

# ── CONFIG ────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Analizador de Normativa AR",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.stApp { background: #f8f7f4; }
.norma-card {
    background: white;
    border-radius: 12px;
    padding: 1.5rem;
    border: 1px solid #e8e6e0;
    margin-bottom: 1rem;
}
.chat-user { background:#e8f4fd; border-radius:10px; padding:0.8rem; margin:0.5rem 0; }
.chat-ai { background:white; border-radius:10px; padding:0.8rem; margin:0.5rem 0; border:1px solid #e8e6e0; }
</style>
""", unsafe_allow_html=True)

# ── SESSION STATE ─────────────────────────────────────────────────────────────

def init_state():
    defaults = {
        "texto_norma": "",
        "analisis": None,
        "organismo": "BOLETIN",
        "fuente": "",
        "historial_chat": [],
        "df_catalogo": None,
        "cols_catalogo": None,
        "resultados_cruce": None,
        "confianza_anexo": None,
        "fase": "busqueda",
        "norma_nombre": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ── SIDEBAR ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚖️ Normativa AR")
    st.markdown("---")
    st.markdown("""
🔍 Buscamos en BCRA, AFIP, DGI, Boletín Oficial y Fuentes Oficiales.

Si no la encontramos, subí el PDF o pegá el texto — analizamos cualquier normativa argentina.
    """)
    st.markdown("---")

    if st.button("🔄 Nueva consulta", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

    if st.session_state.get("analisis"):
        st.markdown("---")
        st.markdown("**Norma activa**")
        an = st.session_state["analisis"]
        st.markdown(f"📄 {an.get('titulo', 'Sin título')[:50]}")
        st.markdown(f"🏢 {an.get('organismo', st.session_state['organismo'])}")
        if an.get("impacto_principal"):
            st.markdown(f"⚡ {an['impacto_principal'].capitalize()}")
        if st.session_state.get("confianza_anexo"):
            c = st.session_state["confianza_anexo"]
            st.markdown(f"{c['icono']} Anexo: {c['nivel']}")

    st.markdown("---")
    api_key = st.text_input(
        "API Key Anthropic", type="password",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="O setear ANTHROPIC_API_KEY como variable de entorno"
    )
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key
        import anthropic as _a
        import analyzer as _az
        _az.client = _a.Anthropic(api_key=api_key)

# ── MAIN ──────────────────────────────────────────────────────────────────────

st.markdown("# ⚖️ Analizador de Normativa Argentina")
st.markdown("Consultá, analizá y cruzá resoluciones de BCRA, AFIP, Aduana, Minería y Boletín Oficial.")
st.markdown("---")

# ════════════════════════════════════════════════════════
# FASE 1: BÚSQUEDA
# ════════════════════════════════════════════════════════

if not st.session_state["texto_norma"]:

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("### 🔍 ¿Qué norma querés analizar?")
        numero = st.text_input(
            "Número de norma",
            placeholder="Ej: Com. A 8330 / RG 5424 / Res. SIC 5/2026 / Res. SPM 89/19",
            help="Escribí el número y lo buscamos automáticamente en fuentes oficiales"
        )

        if st.button("🔎 Buscar norma", use_container_width=True, disabled=not numero):
            with st.spinner("Buscando en fuentes oficiales..."):
                organismo = detectar_organismo(numero)
                texto, fuente = buscar_norma(numero)

            if texto and len(texto) > 200:
                st.session_state.update({
                    "texto_norma": texto,
                    "organismo": organismo,
                    "fuente": fuente,
                    "norma_nombre": numero,
                })
                st.rerun()
            else:
                st.warning(
                    "⚠️ No encontré la norma automáticamente en las fuentes oficiales. "
                    "Podés subirla como archivo o pegar el texto abajo."
                )

    with col2:
        st.markdown("### 📎 O subila directamente")
        archivo = st.file_uploader(
            "PDF, Word o .txt",
            type=["pdf", "docx", "doc", "txt"],
            help="Subí el archivo de la resolución"
        )
        if archivo:
            with st.spinner("Leyendo archivo..."):
                texto = leer_archivo(archivo.read(), archivo.name)
            if texto and len(texto) > 100:
                st.session_state.update({
                    "texto_norma": texto,
                    "organismo": detectar_organismo(archivo.name),
                    "fuente": f"Archivo: {archivo.name}",
                    "norma_nombre": archivo.name,
                })
                st.success(f"✅ {len(texto):,} caracteres leídos")
                st.rerun()

    st.markdown("### ✍️ O pegá el texto directamente")
    texto_pegado = st.text_area(
        "Texto de la norma",
        height=200,
        placeholder="Pegá aquí el texto completo de la resolución..."
    )
    if st.button("📋 Usar este texto", disabled=not texto_pegado):
        st.session_state.update({
            "texto_norma": texto_pegado,
            "organismo": "BOLETIN",
            "fuente": "Texto ingresado manualmente",
            "norma_nombre": "Norma ingresada",
        })
        st.rerun()

# ════════════════════════════════════════════════════════
# FASE 2: ANÁLISIS
# ════════════════════════════════════════════════════════

else:
    texto = st.session_state["texto_norma"]
    organismo = st.session_state["organismo"]

    # Analizar si no está en caché
    if not st.session_state["analisis"]:
        with st.spinner("🤖 Claude analizando la norma como experto..."):
            analisis = analizar_norma(texto, organismo)
            confianza = evaluar_confianza_anexo(texto, analisis.get("ncms_condiciones", {}))
            st.session_state["analisis"] = analisis
            st.session_state["confianza_anexo"] = confianza

    analisis = st.session_state["analisis"]
    confianza = st.session_state["confianza_anexo"]

    # Card de la norma
    st.markdown(f"""
    <div class="norma-card">
        <h3>📄 {analisis.get('titulo', st.session_state['norma_nombre'])}</h3>
        <p>
            <strong>Organismo:</strong> {analisis.get('organismo', organismo)} &nbsp;|&nbsp;
            <strong>Vigencia:</strong> {analisis.get('vigencia', 'N/D')} &nbsp;|&nbsp;
            <strong>Fuente:</strong> {st.session_state['fuente']}
        </p>
        <p>{analisis.get('resumen', '')}</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs([
        "💬 Chat con la norma",
        "📊 Cruce con catálogo",
        "📋 Puntos clave",
        "📥 Exportar"
    ])

    # ── TAB 1: CHAT ──────────────────────────────────────────────────────────
    with tab1:
        st.markdown("#### 💬 Consultá sobre esta norma")
        st.caption("Claude responde como experto en el área. Podés preguntar lo que necesites.")

        for msg in st.session_state["historial_chat"]:
            css = "chat-user" if msg["role"] == "user" else "chat-ai"
            icono = "👤" if msg["role"] == "user" else "🤖"
            st.markdown(
                f'<div class="{css}">{icono} {msg["content"]}</div>',
                unsafe_allow_html=True
            )

        if not st.session_state["historial_chat"]:
            with st.spinner("Preparando consulta inicial..."):
                pregunta_inicial = generar_pregunta_output(analisis, [])
            st.markdown(
                f'<div class="chat-ai">🤖 {pregunta_inicial}</div>',
                unsafe_allow_html=True
            )
            st.session_state["historial_chat"].append({
                "role": "assistant", "content": pregunta_inicial
            })

        if pregunta := st.chat_input("Escribí tu consulta..."):
            st.session_state["historial_chat"].append({"role": "user", "content": pregunta})
            with st.spinner("Analizando..."):
                respuesta = responder_en_dialogo(
                    texto, analisis,
                    st.session_state["historial_chat"],
                    organismo
                )
            st.session_state["historial_chat"].append({"role": "assistant", "content": respuesta})
            st.rerun()

    # ── TAB 2: CRUCE ─────────────────────────────────────────────────────────
    with tab2:
        st.markdown("#### 📊 Cruzá la norma con tu catálogo o datos")

        # Badge de confianza SIEMPRE visible
        if confianza["nivel"] == "sin_anexo":
            st.error(confianza["mensaje"])
        elif confianza["nivel"] == "parcial":
            st.warning(confianza["mensaje"])
        elif confianza["nivel"] == "completo":
            st.success(confianza["mensaje"])
        else:
            st.info(confianza["mensaje"])

        archivo_cat = st.file_uploader(
            "Subí tu Excel o CSV",
            type=["xlsx", "xls", "csv"],
            key="catalogo_upload"
        )

        if archivo_cat:
            df = leer_excel(archivo_cat.read(), archivo_cat.name)
            if df is not None and not df.empty:
                st.session_state["df_catalogo"] = df
                st.success(f"✅ {len(df)} filas · {len(df.columns)} columnas")
                st.dataframe(df.head(5), use_container_width=True)

                if not st.session_state["cols_catalogo"]:
                    with st.spinner("Claude detectando columnas..."):
                        cols = detectar_columnas(
                            list(df.columns),
                            df.head(4).to_dict(orient="records")
                        )
                    st.session_state["cols_catalogo"] = cols

                cols = st.session_state["cols_catalogo"]
                c1, c2, c3 = st.columns(3)
                all_cols = [None] + list(df.columns)

                def idx(col): return all_cols.index(col) if col in all_cols else 0

                with c1:
                    cols["col_articulo"] = st.selectbox(
                        "Columna artículo/código", all_cols, index=idx(cols.get("col_articulo")))
                with c2:
                    cols["col_ncm"] = st.selectbox(
                        "Columna NCM / referencia", all_cols, index=idx(cols.get("col_ncm")))
                with c3:
                    cols["col_descripcion"] = st.selectbox(
                        "Columna descripción (opcional)", all_cols, index=idx(cols.get("col_descripcion")))

                ncms = analisis.get("ncms_condiciones", {})

                if st.button("🚀 Iniciar cruce con IA", use_container_width=True, type="primary"):
                    progress = st.progress(0)
                    status = st.empty()

                    def cb(pct):
                        progress.progress(pct)
                        status.text(f"Analizando fila {int(pct * len(df))} de {len(df)}...")

                    resultados = clasificar_articulos(
                        df, cols, ncms, texto, organismo, cb
                    )
                    st.session_state["resultados_cruce"] = resultados
                    progress.empty()
                    status.empty()
                    st.rerun()

        if st.session_state["resultados_cruce"]:
            resultados = st.session_state["resultados_cruce"]
            enc = [r for r in resultados if r["estado"] == "ENCUADRA"]
            no  = [r for r in resultados if r["estado"] == "NO ENCUADRA"]
            aal = [r for r in resultados if r["estado"] == "A ANALIZAR"]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total", len(resultados))
            c2.metric("🟢 Encuadran", len(enc))
            c3.metric("🔴 No encuadran", len(no))
            c4.metric("🟡 A analizar", len(aal))

            df_r = pd.DataFrame(resultados)
            df_r["semaforo"] = df_r["color"] + " " + df_r["estado"]
            st.dataframe(
                df_r[["articulo", "ncm", "descripcion", "semaforo", "fundamento"]],
                use_container_width=True, height=400
            )

    # ── TAB 3: PUNTOS CLAVE ───────────────────────────────────────────────────
    with tab3:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Puntos clave**")
            for p in analisis.get("puntos_clave", []):
                st.markdown(f"• {p}")
            st.markdown("**Obligaciones**")
            for o in analisis.get("obligaciones", []):
                st.markdown(f"• {o}")
        with c2:
            st.markdown("**Afectados**")
            for a in analisis.get("afectados", []):
                st.markdown(f"• {a}")
            if analisis.get("ncms_condiciones"):
                st.markdown("**NCMs del Anexo**")
                for ncm, cond in list(analisis["ncms_condiciones"].items())[:20]:
                    st.markdown(f"• `{ncm}` — {cond or 'Sin condición adicional'}")

        with st.expander("Ver texto completo de la norma"):
            st.text(texto[:6000] + ("..." if len(texto) > 6000 else ""))

    # ── TAB 4: EXPORTAR ───────────────────────────────────────────────────────
    with tab4:
        st.markdown("#### 📥 Exportar resultados")
        c1, c2 = st.columns(2)

        with c1:
            st.markdown("**Excel con semáforo**")
            if st.session_state["resultados_cruce"]:
                df_exp = pd.DataFrame(st.session_state["resultados_cruce"])
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    df_exp.to_excel(writer, index=False, sheet_name="Análisis completo")
                    df_enc = df_exp[df_exp["estado"] == "ENCUADRA"]
                    df_no  = df_exp[df_exp["estado"] != "ENCUADRA"]
                    if not df_enc.empty:
                        df_enc.to_excel(writer, index=False, sheet_name="Encuadran")
                    if not df_no.empty:
                        df_no.to_excel(writer, index=False, sheet_name="No encuadran")
                buf.seek(0)
                st.download_button(
                    "⬇️ Descargar Excel",
                    data=buf,
                    file_name=f"analisis_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            else:
                st.info("Hacé el cruce primero para exportar el Excel.")

        with c2:
            st.markdown("**Memo ejecutivo**")
            if st.button("📝 Generar memo", use_container_width=True):
                with st.spinner("Redactando memo..."):
                    memo = generar_resumen_ejecutivo(
                        analisis,
                        st.session_state["resultados_cruce"],
                        organismo
                    )
                st.text_area("Memo", memo, height=350)
                st.download_button(
                    "⬇️ Descargar memo (.txt)",
                    data=memo.encode("utf-8"),
                    file_name=f"memo_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                    mime="text/plain"
                )
