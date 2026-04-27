"""
exports.py — Exportación a Word, PDF y PowerPoint
Respeta el texto completo del análisis tal como aparece en pantalla.
"""
import io
import re
from datetime import datetime


def _limpiar_texto(texto: str) -> str:
    """Limpia markdown y caracteres especiales para exportación."""
    texto = re.sub(r'\*\*(.+?)\*\*', r'\1', texto)  # **bold** → bold
    texto = re.sub(r'\*(.+?)\*', r'\1', texto)        # *italic* → italic
    texto = re.sub(r'#{1,6}\s+', '', texto)            # headers
    texto = re.sub(r'<[^>]+>', '', texto)              # HTML tags
    texto = texto.replace('&', 'y').replace('<', '').replace('>', '')
    return texto.strip()


def _limpiar_para_reportlab(texto: str) -> str:
    """Limpieza extra estricta para ReportLab."""
    texto = _limpiar_texto(texto)
    # Escapar caracteres especiales de XML
    texto = texto.replace('&', '&amp;')
    texto = texto.replace('"', '&quot;')
    # Eliminar cualquier tag residual
    texto = re.sub(r'<[^>]*>', '', texto)
    return texto.strip()


def generar_word(analisis: dict, resultados_cruce: list = None) -> bytes:
    """Genera Word respetando el texto completo del análisis."""
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Arial'
    style.font.size = Pt(11)

    AZUL = RGBColor(0x1a, 0x5f, 0xa8)

    # Título
    h = doc.add_heading(level=0)
    r = h.add_run('ANÁLISIS NORMATIVO')
    r.font.size = Pt(20)
    r.font.color.rgb = AZUL

    # Metadata
    doc.add_paragraph(f"Norma: {analisis.get('titulo', 'N/D')}")
    doc.add_paragraph(f"Organismo: {analisis.get('organismo', 'N/D')} | Vigencia: {analisis.get('vigencia', 'N/D')}")
    doc.add_paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    doc.add_paragraph('')

    # Texto completo del análisis — línea por línea
    texto = _limpiar_texto(analisis.get('analisis_completo', ''))
    for linea in texto.split('\n'):
        linea = linea.strip()
        if not linea:
            doc.add_paragraph('')
            continue
        # Detectar títulos de sección (ej: "1. RESUMEN EJECUTIVO")
        if re.match(r'^\d+\.\s+[A-ZÁÉÍÓÚ\s]+$', linea):
            h2 = doc.add_heading(linea, level=1)
            h2.runs[0].font.color.rgb = AZUL
        elif linea.startswith('- ') or linea.startswith('• '):
            doc.add_paragraph(linea[2:], style='List Bullet')
        else:
            doc.add_paragraph(linea)

    # Cruce si existe
    if resultados_cruce:
        doc.add_heading('RESULTADOS DEL CRUCE', level=1)
        enc = sum(1 for r in resultados_cruce if r["estado"] == "ENCUADRA")
        no  = sum(1 for r in resultados_cruce if r["estado"] == "NO ENCUADRA")
        aal = sum(1 for r in resultados_cruce if r["estado"] == "A ANALIZAR")
        doc.add_paragraph(f"Total: {len(resultados_cruce)} | Encuadran: {enc} | No encuadran: {no} | A analizar: {aal}")
        tabla = doc.add_table(rows=1, cols=4)
        tabla.style = 'Table Grid'
        for i, h in enumerate(['Artículo', 'NCM', 'Estado', 'Fundamento']):
            tabla.rows[0].cells[i].text = h
        for r in resultados_cruce[:50]:
            fila = tabla.add_row()
            fila.cells[0].text = r.get('articulo', '')
            fila.cells[1].text = r.get('ncm', '')
            fila.cells[2].text = r.get('estado', '')
            fila.cells[3].text = r.get('fundamento', '')

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def generar_pdf(analisis: dict, resultados_cruce: list = None) -> bytes:
    """Genera PDF respetando el texto completo del análisis."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.units import mm

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)

    styles = getSampleStyleSheet()
    azul = HexColor('#1a5fa8')

    s_titulo = ParagraphStyle('titulo', parent=styles['Title'], fontSize=18, textColor=azul, spaceAfter=6)
    s_h1 = ParagraphStyle('h1', parent=styles['Heading1'], fontSize=13, textColor=azul, spaceBefore=10, spaceAfter=4)
    s_body = ParagraphStyle('body', parent=styles['Normal'], fontSize=10, spaceAfter=3, leading=14)
    s_meta = ParagraphStyle('meta', parent=styles['Normal'], fontSize=9, textColor=HexColor('#666666'), spaceAfter=2)
    s_bullet = ParagraphStyle('bullet', parent=styles['Normal'], fontSize=10, spaceAfter=3, leading=14, leftIndent=15)

    story = []
    story.append(Paragraph('ANALISIS NORMATIVO', s_titulo))
    story.append(Paragraph(f"Norma: {_limpiar_para_reportlab(analisis.get('titulo', 'N/D'))}", s_meta))
    story.append(Paragraph(f"Organismo: {analisis.get('organismo', 'N/D')} | Vigencia: {analisis.get('vigencia', 'N/D')}", s_meta))
    story.append(Paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}", s_meta))
    story.append(Spacer(1, 8*mm))

    # Texto completo línea por línea
    texto = _limpiar_texto(analisis.get('analisis_completo', ''))
    for linea in texto.split('\n'):
        linea = linea.strip()
        if not linea:
            story.append(Spacer(1, 2*mm))
            continue
        linea_limpia = _limpiar_para_reportlab(linea)
        if not linea_limpia:
            continue
        # Títulos de sección
        if re.match(r'^\d+\.\s+\S+', linea):
            story.append(Paragraph(linea_limpia, s_h1))
        elif linea.startswith('- ') or linea.startswith('• '):
            story.append(Paragraph(f"• {_limpiar_para_reportlab(linea[2:])}", s_bullet))
        else:
            story.append(Paragraph(linea_limpia, s_body))

    # Cruce si existe
    if resultados_cruce:
        story.append(Spacer(1, 6*mm))
        story.append(Paragraph('RESULTADOS DEL CRUCE', s_h1))
        enc = sum(1 for r in resultados_cruce if r["estado"] == "ENCUADRA")
        no  = sum(1 for r in resultados_cruce if r["estado"] == "NO ENCUADRA")
        aal = sum(1 for r in resultados_cruce if r["estado"] == "A ANALIZAR")
        story.append(Paragraph(f"Total: {len(resultados_cruce)} | Encuadran: {enc} | No encuadran: {no} | A analizar: {aal}", s_body))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def generar_ppt(analisis: dict, resultados_cruce: list = None) -> bytes:
    """Genera PPT con el texto completo del análisis, sección por sección."""
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor

    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    AZUL = RGBColor(0x1a, 0x5f, 0xa8)
    AZUL_CLAR = RGBColor(0xe8, 0xf4, 0xfd)
    GRIS = RGBColor(0x33, 0x33, 0x33)
    BLANCO = RGBColor(0xff, 0xff, 0xff)
    blank = prs.slide_layouts[6]

    def add_slide(titulo_s, lineas, portada=False):
        slide = prs.slides.add_slide(blank)
        w, h = prs.slide_width, prs.slide_height

        bg = slide.shapes.add_shape(1, 0, 0, w, h)
        bg.fill.solid()
        bg.fill.fore_color.rgb = AZUL if portada else AZUL_CLAR
        bg.line.fill.background()

        barra = slide.shapes.add_shape(1, 0, 0, Inches(0.12), h)
        barra.fill.solid()
        barra.fill.fore_color.rgb = AZUL
        barra.line.fill.background()

        tb = slide.shapes.add_textbox(Inches(0.3), Inches(0.2), Inches(12.7), Inches(1.0))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = _limpiar_texto(titulo_s)[:120]
        run.font.size = Pt(26 if portada else 20)
        run.font.bold = True
        run.font.color.rgb = BLANCO if portada else AZUL

        if lineas:
            tb2 = slide.shapes.add_textbox(Inches(0.3), Inches(1.3), Inches(12.7), Inches(5.8))
            tf2 = tb2.text_frame
            tf2.word_wrap = True
            primero = True
            for linea in lineas[:20]:
                linea = _limpiar_texto(linea.strip())
                if not linea:
                    continue
                p2 = tf2.paragraphs[0] if primero else tf2.add_paragraph()
                primero = False
                run2 = p2.add_run()
                if linea.startswith('- ') or linea.startswith('• '):
                    run2.text = f"  • {linea[2:]}"
                    run2.font.size = Pt(12)
                else:
                    run2.text = linea
                    run2.font.size = Pt(12)
                run2.font.color.rgb = BLANCO if portada else GRIS

    # Parsear secciones del análisis completo
    texto = _limpiar_texto(analisis.get('analisis_completo', ''))
    lineas_totales = texto.split('\n')

    # Slide portada
    add_slide(
        analisis.get('titulo', 'Análisis Normativo'),
        [
            f"Organismo: {analisis.get('organismo', '')}",
            f"Vigencia: {analisis.get('vigencia', 'N/D')}",
            f"Fecha: {datetime.now().strftime('%d/%m/%Y')}",
        ],
        portada=True
    )

    # Dividir en secciones por títulos numerados
    secciones = []
    seccion_actual_titulo = ""
    seccion_actual_lineas = []

    for linea in lineas_totales:
        if re.match(r'^\d+\.\s+\S+', linea.strip()):
            if seccion_actual_titulo:
                secciones.append((seccion_actual_titulo, seccion_actual_lineas))
            seccion_actual_titulo = linea.strip()
            seccion_actual_lineas = []
        else:
            seccion_actual_lineas.append(linea)

    if seccion_actual_titulo:
        secciones.append((seccion_actual_titulo, seccion_actual_lineas))

    # Si no detectó secciones, poner todo en slides de 20 líneas
    if not secciones:
        chunks = [lineas_totales[i:i+18] for i in range(0, len(lineas_totales), 18)]
        for j, chunk in enumerate(chunks[:8]):
            add_slide(f"Análisis ({j+1})", chunk)
    else:
        for titulo_s, lineas in secciones[:8]:
            add_slide(titulo_s, lineas)

    # Slide cruce si existe
    if resultados_cruce:
        enc = sum(1 for r in resultados_cruce if r["estado"] == "ENCUADRA")
        no  = sum(1 for r in resultados_cruce if r["estado"] == "NO ENCUADRA")
        aal = sum(1 for r in resultados_cruce if r["estado"] == "A ANALIZAR")
        add_slide("RESULTADOS DEL CRUCE", [
            f"Total analizados: {len(resultados_cruce)}",
            f"Encuadran: {enc}",
            f"No encuadran: {no}",
            f"A analizar: {aal}",
        ])

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf.read()
