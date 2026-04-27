"""
app.py — Analizador Universal de Normativa Argentina
Sin sidebar · Con navegación · Detector IA
"""
import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime

from utils import buscar_norma, leer_archivo, leer_excel
from analyzer import (
    analizar_norma, detectar_organismo_con_ia, saludo_inicial,
    chat_inicial_respuesta, generar_pregunta_output, responder_en_dialogo,
    detectar_columnas, clasificar_articulos, generar_resumen_ejecutivo,
    evaluar_confianza_anexo
)

st.set_page_config(
    page_title="Analizador de Normativa AR",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
.stApp { background: #f8f7f4; }
.norma-card {
    background: white; border-radius: 12px; padding: 1.5rem;
    border: 1px solid #e8e6e0; margin-bottom: 1rem;
}
.chat-user { background:#e8f4fd; border-radius:10px; padding:0.8rem; margin:0.5rem 0; }
.chat-ai { background:white; border-radius:10px; padding:0.8rem; margin:0.5rem 0; border:1px solid #e8e6e0; }
.nav-bar { display:flex; gap:10px; margin-bottom:1.5rem; }
[data-testid="collapsedControl"] { display: none !important; }
</style>
""", unsafe_allow_html=True)


def init_state():
    defaults = {
        "texto_norma": "", "analisis": None, "organismo": "BOLETIN",
        "fuente": "", "historial_chat": [], "df_catalogo": None,
        "cols_catalogo": None, "resultados_cruce": None,
        "confianza_anexo": None, "norma_nombre": "",
        "chat_inicial": None, "detector_info": None,
        "_anexos_iniciales": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


def reiniciar():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()


def volver():
    st.session_state["texto_norma"] = ""
    st.session_state["analisis"] = None
    st.session_state["historial_chat"] = []
    st.session_state["resultados_cruce"] = None
    st.session_state["confianza_anexo"] = None
    st.session_state["df_catalogo"] = None
    st.session_state["cols_catalogo"] = None
    st.rerun()


# ── HEADER ────────────────────────────────────────────────────────────────────

col_titulo, col_btns = st.columns([5, 1])
with col_titulo:
    st.markdown("# ⚖️ Analizador de Normativa Argentina")
    st.caption("Consultá, analizá y cruzá cualquier normativa — BCRA, AFIP, DGI, Boletín Oficial y más.")

with col_btns:
    st.write("")
    if st.session_state["texto_norma"]:
        if st.button("← Volver", use_container_width=True):
            volver()
    if st.button("🔄 Nueva consulta", use_container_width=True):
        reiniciar()

st.markdown("---")


# ════════════════════════════════════════════════════════
# FASE 1: BÚSQUEDA
# ════════════════════════════════════════════════════════

if not st.session_state["texto_norma"]:

    st.markdown("### 💬 Contame qué necesitás")

    if st.session_state["chat_inicial"] is None:
        st.session_state["chat_inicial"] = [{
            "role": "assistant",
            "content": saludo_inicial()
        }]

    for msg in st.session_state["chat_inicial"]:
        css = "chat-user" if msg["role"] == "user" else "chat-ai"
        icono = "👤" if msg["role"] == "user" else "🤖"
        st.markdown(f'<div class="{css}">{icono} {msg["content"]}</div>', unsafe_allow_html=True)

    if consulta := st.chat_input("Escribí el número de norma o describí lo que necesitás..."):
        st.session_state["chat_inicial"].append({"role": "user", "content": consulta})
        with st.spinner("Analizando..."):
            respuesta = chat_inicial_respuesta(st.session_state["chat_inicial"])
        st.session_state["chat_inicial"].append({"role": "assistant", "content": respuesta})
        st.rerun()

    st.markdown("---")
    st.markdown("### O usá los formularios directamente")

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("#### 🔍 Buscar por número")
        numero = st.text_input(
            "Número de norma",
            placeholder="Res 5838/2026 · Com. A 8330 · RG 5424 · SPM 89/19...",
        )
        if st.button("🔎 Buscar", use_container_width=True, disabled=not numero):
            with st.spinner("Identificando organismo con IA..."):
                detector = detectar_organismo_con_ia(numero)
                organismo = detector.get("organismo", "BOLETIN")
                st.session_state["detector_info"] = detector

            with st.spinner(f"Buscando en fuentes oficiales ({organismo})..."):
                texto, fuente = buscar_norma(numero)

            if texto and len(texto) > 200:
                st.session_state.update({
                    "texto_norma": texto, "organismo": organismo,
                    "fuente": fuente, "norma_nombre": numero,
                })
                st.rerun()
            else:
                st.warning(
                    f"⚠️ No encontré **{numero}** automáticamente. "
                    f"{fuente if fuente.startswith('Error') else ''} "
                    "Podés subir el archivo o pegar el texto abajo."
                )

    with col2:
        st.markdown("#### 📎 Subir archivo")
        archivos = st.file_uploader(
            "PDF, Word o .txt — podés subir la norma + anexos juntos",
            type=["pdf", "docx", "doc", "txt"],
            accept_multiple_files=True
        )
        if archivos:
            st.info(f"📄 {len(archivos)} archivo(s) cargado(s): {', '.join(f.name for f in archivos)}")
            if st.button("⚖️ Analizar archivo(s)", use_container_width=True, type="primary"):
                with st.spinner("Leyendo archivo(s)..."):
                    # El primero es la norma principal; el resto son anexos
                    norma = archivos[0]
                    texto = leer_archivo(norma.read(), norma.name)
                    detector = detectar_organismo_con_ia(norma.name)
                    organismo = detector.get("organismo", "BOLETIN")
                    # Anexos adicionales subidos junto con la norma
                    anexos_usuario = []
                    for f in archivos[1:]:
                        contenido = leer_archivo(f.read(), f.name)
                        nombre_limpio = (
                            f.name.upper()
                            .replace(".PDF","").replace(".DOCX","").replace(".TXT","")
                            .replace("_"," ").replace("-"," ").strip()
                        )
                        anexos_usuario.append({"nombre": nombre_limpio, "contenido": contenido})
                if texto and len(texto) > 100:
                    st.session_state.update({
                        "texto_norma": texto, "organismo": organismo,
                        "fuente": f"Archivo: {norma.name}", "norma_nombre": norma.name,
                        "_anexos_iniciales": anexos_usuario,  # se usan en Fase 2
                    })
                    st.rerun()

    st.markdown("#### ✍️ O pegá el texto")
    texto_pegado = st.text_area("Texto de la norma", height=180,
                                 placeholder="Pegá el texto completo de la resolución...")
    if st.button("⚖️ Analizar texto", use_container_width=True,
                 type="primary", disabled=not texto_pegado):
        with st.spinner("Identificando norma..."):
            detector = detectar_organismo_con_ia(texto_pegado[:200])
            organismo = detector.get("organismo", "BOLETIN")
        st.session_state.update({
            "texto_norma": texto_pegado, "organismo": organismo,
            "fuente": "Texto ingresado manualmente", "norma_nombre": "Norma ingresada",
        })
        st.rerun()


# ════════════════════════════════════════════════════════
# FASE 2: ANÁLISIS
# ════════════════════════════════════════════════════════

else:
    texto = st.session_state["texto_norma"]
    organismo = st.session_state["organismo"]

    if not st.session_state["analisis"]:
        anexos_iniciales = st.session_state.pop("_anexos_iniciales", [])
        with st.spinner("🤖 Claude analizando la norma como experto senior..."):
            analisis = analizar_norma(texto, organismo, anexos_usuario=anexos_iniciales or None)
            confianza = evaluar_confianza_anexo(texto, analisis.get("ncms_condiciones", {}))
            st.session_state["analisis"] = analisis
            st.session_state["confianza_anexo"] = confianza

    analisis = st.session_state["analisis"]
    confianza = st.session_state["confianza_anexo"]

    st.markdown(f"""
    <div class="norma-card">
        <h3>📄 {analisis.get('titulo', st.session_state['norma_nombre'])}</h3>
        <p>
            <strong>Organismo:</strong> {analisis.get('organismo', organismo)} &nbsp;|&nbsp;
            <strong>Vigencia:</strong> {analisis.get('vigencia', 'N/D')} &nbsp;|&nbsp;
            <strong>Fuente:</strong> {st.session_state['fuente']}
        </p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["💬 Chat", "📊 Cruce con catálogo", "📋 Análisis completo", "📥 Exportar"])

    # ── TAB 1: CHAT ──────────────────────────────────────────────────────────
    with tab1:
        st.markdown("#### 💬 Consultá sobre esta norma")
        st.caption("Claude responde como experto senior en normativa argentina.")

        for msg in st.session_state["historial_chat"]:
            css = "chat-user" if msg["role"] == "user" else "chat-ai"
            icono = "👤" if msg["role"] == "user" else "🤖"
            st.markdown(f'<div class="{css}">{icono} {msg["content"]}</div>', unsafe_allow_html=True)

        if not st.session_state["historial_chat"]:
            bienvenida = generar_pregunta_output(analisis, [])
            st.markdown(f'<div class="chat-ai">🤖 {bienvenida}</div>', unsafe_allow_html=True)
            st.session_state["historial_chat"].append({"role": "assistant", "content": bienvenida})

        if pregunta := st.chat_input("Hacé tu consulta sobre esta norma..."):
            st.session_state["historial_chat"].append({"role": "user", "content": pregunta})
            with st.spinner("Analizando..."):
                respuesta = responder_en_dialogo(texto, analisis, st.session_state["historial_chat"], organismo)
            st.session_state["historial_chat"].append({"role": "assistant", "content": respuesta})
            st.rerun()

    # ── TAB 2: CRUCE ─────────────────────────────────────────────────────────
    with tab2:
        st.markdown("#### 📊 Cruzá la norma con tu catálogo")

        if confianza["nivel"] == "sin_anexo":
            st.error(confianza["mensaje"])
        elif confianza["nivel"] == "parcial":
            st.warning(confianza["mensaje"])
        elif confianza["nivel"] == "completo":
            st.success(confianza["mensaje"])
        else:
            st.info(confianza["mensaje"])

        archivo_cat = st.file_uploader("Subí tu Excel o CSV", type=["xlsx", "xls", "csv"], key="cat_upload")

        if archivo_cat:
            df = leer_excel(archivo_cat.read(), archivo_cat.name)
            if df is not None and not df.empty:
                st.session_state["df_catalogo"] = df
                st.success(f"✅ {len(df)} filas · {len(df.columns)} columnas")
                st.dataframe(df.head(5), use_container_width=True)

                if not st.session_state["cols_catalogo"]:
                    with st.spinner("Claude detectando columnas..."):
                        cols = detectar_columnas(list(df.columns), df.head(4).to_dict(orient="records"))
                    st.session_state["cols_catalogo"] = cols

                cols = st.session_state["cols_catalogo"]
                all_cols = [None] + list(df.columns)
                def idx(c): return all_cols.index(c) if c in all_cols else 0

                c1, c2, c3 = st.columns(3)
                with c1: cols["col_articulo"] = st.selectbox("Columna artículo", all_cols, index=idx(cols.get("col_articulo")))
                with c2: cols["col_ncm"] = st.selectbox("Columna NCM", all_cols, index=idx(cols.get("col_ncm")))
                with c3: cols["col_descripcion"] = st.selectbox("Columna descripción", all_cols, index=idx(cols.get("col_descripcion")))

                ncms = analisis.get("ncms_condiciones", {})
                if st.button("🚀 Iniciar cruce", use_container_width=True, type="primary"):
                    progress = st.progress(0)
                    status = st.empty()
                    def cb(pct):
                        progress.progress(pct)
                        status.text(f"Analizando fila {int(pct * len(df))} de {len(df)}...")
                    resultados = clasificar_articulos(df, cols, ncms, texto, organismo, cb)
                    st.session_state["resultados_cruce"] = resultados
                    progress.empty(); status.empty()
                    st.rerun()

        if st.session_state["resultados_cruce"]:
            resultados = st.session_state["resultados_cruce"]
            enc = [r for r in resultados if r["estado"] == "ENCUADRA"]
            no  = [r for r in resultados if r["estado"] == "NO ENCUADRA"]
            aal = [r for r in resultados if r["estado"] == "A ANALIZAR"]
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total", len(resultados))
            c2.metric("🟢 Encuadran", len(enc))
            c3.metric("🔴 No encuadran", len(no))
            c4.metric("🟡 A analizar", len(aal))
            df_r = pd.DataFrame(resultados)
            df_r["semaforo"] = df_r["color"] + " " + df_r["estado"]
            st.dataframe(df_r[["articulo","ncm","descripcion","semaforo","fundamento"]], use_container_width=True, height=400)

    # ── TAB 3: ANÁLISIS COMPLETO ──────────────────────────────────────────────
    with tab3:
        st.markdown("#### 📋 Análisis completo")

        faltantes = analisis.get("anexos_faltantes", [])
        encontrados = analisis.get("anexos_encontrados", [])

        if encontrados:
            st.success(f"✅ Anexos incorporados: {', '.join(a['nombre'] for a in encontrados)}")

        if faltantes:
            st.warning(
                f"⚠️ Esta norma menciona **{', '.join(faltantes)}** que no pudieron obtenerse automáticamente. "
                "Subí los PDFs para regenerar el análisis completo."
            )
            anexos_subidos = st.file_uploader(
                "Subí los Anexos faltantes (PDF, Word o txt)",
                type=["pdf", "docx", "txt"],
                accept_multiple_files=True,
                key="anexos_upload"
            )
            if anexos_subidos and st.button("📎 Incorporar Anexos y re-analizar", type="primary"):
                # Construir lista estructurada — NO concatenar al texto de la norma
                anexos_usuario = []
                for f in anexos_subidos:
                    contenido = leer_archivo(f.read(), f.name)
                    nombre_limpio = (
                        f.name.upper()
                        .replace(".PDF", "").replace(".DOCX", "").replace(".TXT", "")
                        .replace("_", " ").replace("-", " ").strip()
                    )
                    anexos_usuario.append({"nombre": nombre_limpio, "contenido": contenido})

                with st.spinner(f"Regenerando análisis con {len(anexos_usuario)} anexo(s)..."):
                    nuevo_analisis = analizar_norma(
                        st.session_state["texto_norma"],  # norma original, sin modificar
                        organismo,
                        anexos_usuario=anexos_usuario     # anexos separados y estructurados
                    )
                    nueva_confianza = evaluar_confianza_anexo(
                        st.session_state["texto_norma"],
                        nuevo_analisis.get("ncms_condiciones", {})
                    )
                    st.session_state["analisis"] = nuevo_analisis
                    st.session_state["confianza_anexo"] = nueva_confianza
                    st.session_state["historial_chat"] = []  # resetear chat

                st.success(f"✅ Análisis regenerado con {len(anexos_usuario)} anexo(s) incorporados.")
                st.rerun()

        st.markdown(analisis.get("analisis_completo", ""), unsafe_allow_html=False)

        if analisis.get("ncms_condiciones"):
            st.markdown("**NCMs del Anexo**")
            for ncm, cond in list(analisis["ncms_condiciones"].items())[:20]:
                st.markdown(f"• `{ncm}` — {cond or 'Sin condición adicional'}")

        with st.expander("Ver texto completo de la norma"):
            st.text(texto[:6000] + ("..." if len(texto) > 6000 else ""))

        # Debug de cobertura — útil para verificar que llegan los anexos
        debug = analisis.get("_debug", {})
        if debug:
            with st.expander("🔧 Debug — cobertura enviada al modelo"):
                st.json(debug)

    # ── TAB 4: EXPORTAR ───────────────────────────────────────────────────────
    with tab4:
        st.markdown("#### 📥 Exportar análisis")
        from exports import generar_word, generar_pdf

        nombre_base = f"analisis_{datetime.now().strftime('%Y%m%d_%H%M')}"
        resultados = st.session_state.get("resultados_cruce")

        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown("**📝 Word (.docx)**")
            if st.button("Generar Word", use_container_width=True):
                with st.spinner("Generando..."):
                    word_bytes = generar_word(analisis, resultados)
                st.download_button("⬇️ Descargar Word", data=word_bytes,
                    file_name=f"{nombre_base}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True)

        with c2:
            st.markdown("**📄 PDF**")
            if st.button("Generar PDF", use_container_width=True):
                with st.spinner("Generando..."):
                    pdf_bytes = generar_pdf(analisis, resultados)
                st.download_button("⬇️ Descargar PDF", data=pdf_bytes,
                    file_name=f"{nombre_base}.pdf",
                    mime="application/pdf",
                    use_container_width=True)

        with c3:
            st.markdown("**📊 Excel**")
            if resultados:
                df_exp = pd.DataFrame(resultados)
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    df_exp.to_excel(writer, index=False, sheet_name="Análisis completo")
                    df_enc = df_exp[df_exp["estado"] == "ENCUADRA"]
                    df_no  = df_exp[df_exp["estado"] != "ENCUADRA"]
                    if not df_enc.empty: df_enc.to_excel(writer, index=False, sheet_name="Encuadran")
                    if not df_no.empty:  df_no.to_excel(writer, index=False, sheet_name="No encuadran")
                buf.seek(0)
                st.download_button("⬇️ Descargar Excel", data=buf,
                    file_name=f"{nombre_base}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True)
            else:
                st.info("Hacé el cruce primero.")
