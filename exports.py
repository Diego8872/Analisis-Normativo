"""
exports.py — Generación de Word, PDF y PowerPoint desde el análisis normativo
"""
import io
import re
from datetime import datetime


def _secciones(texto: str) -> dict:
    """Parsea el análisis en secciones numeradas."""
    secciones = {}
    patron = re.compile(r'\n?(\d+)\.\s+([A-ZÁÉÍÓÚ\s&]+)\n', re.MULTILINE)
    partes = patron.split(texto)
    i = 1
    while i + 2 < len(partes):
        num = partes[i].strip()
        titulo = partes[i+1].strip()
        contenido = partes[i+2].strip()
        secciones[titulo] = contenido
        i += 3
    if not secciones:
        secciones["ANÁLISIS COMPLETO"] = texto
    return secciones


def generar_word(analisis: dict, resultados_cruce: list = None) -> bytes:
    """Genera un documento Word profesional con el análisis."""
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # Estilos
    style = doc.styles['Normal']
    style.font.name = 'Arial'
    style.font.size = Pt(11)

    # Título principal
    titulo = doc.add_heading(level=0)
    run = titulo.add_run('⚖️ ANÁLISIS NORMATIVO')
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0x1a, 0x5f, 0xa8)

    # Metadata
    doc.add_paragraph(f"Norma: {analisis.get('titulo', 'N/D')}")
    doc.add_paragraph(f"Organismo: {analisis.get('organismo', 'N/D')} | Vigencia: {analisis.get('vigencia', 'N/D')}")
    doc.add_paragraph(f"Fecha de análisis: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    doc.add_paragraph('')

    # Análisis por secciones
    texto = analisis.get('analisis_completo', '')
    secciones = _secciones(texto)

    if secciones:
        for titulo_sec, contenido in secciones.items():
            h = doc.add_heading(titulo_sec, level=1)
            h.runs[0].font.color.rgb = RGBColor(0x1a, 0x5f, 0xa8)
            for linea in contenido.split('\n'):
                linea = linea.strip()
                if linea.startswith('- ') or linea.startswith('• '):
                    p = doc.add_paragraph(linea[2:], style='List Bullet')
                elif linea.startswith('**') and linea.endswith('**'):
                    p = doc.add_paragraph()
                    run = p.add_run(linea.strip('*'))
                    run.bold = True
                elif linea:
                    doc.add_paragraph(linea)
    else:
        doc.add_paragraph(texto)

    # Cruce de catálogo si existe
    if resultados_cruce:
        doc.add_heading('RESULTADOS DEL CRUCE', level=1)
        from docx.oxml.ns import qn
        enc = sum(1 for r in resultados_cruce if r["estado"] == "ENCUADRA")
        no  = sum(1 for r in resultados_cruce if r["estado"] == "NO ENCUADRA")
        aal = sum(1 for r in resultados_cruce if r["estado"] == "A ANALIZAR")
        doc.add_paragraph(f"Total: {len(resultados_cruce)} | 🟢 Encuadran: {enc} | 🔴 No encuadran: {no} | 🟡 A analizar: {aal}")

        table = doc.add_table(rows=1, cols=4)
        table.style = 'Table Grid'
        headers = ['Artículo', 'NCM', 'Estado', 'Fundamento']
        for i, h in enumerate(headers):
            table.rows[0].cells[i].text = h
            table.rows[0].cells[i].paragraphs[0].runs[0].bold = True

        for r in resultados_cruce[:50]:
            row = table.add_row()
            row.cells[0].text = r.get('articulo', '')
            row.cells[1].text = r.get('ncm', '')
            row.cells[2].text = f"{r.get('color','')} {r.get('estado','')}"
            row.cells[3].text = r.get('fundamento', '')

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def generar_pdf(analisis: dict, resultados_cruce: list = None) -> bytes:
    """Genera un PDF con el análisis."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import mm

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=20*mm, rightMargin=20*mm,
                             topMargin=20*mm, bottomMargin=20*mm)

    styles = getSampleStyleSheet()
    azul = HexColor('#1a5fa8')

    estilo_titulo = ParagraphStyle('titulo', parent=styles['Title'],
                                    fontSize=18, textColor=azul, spaceAfter=6)
    estilo_h1 = ParagraphStyle('h1', parent=styles['Heading1'],
                                fontSize=13, textColor=azul, spaceBefore=12, spaceAfter=4)
    estilo_body = ParagraphStyle('body', parent=styles['Normal'],
                                  fontSize=10, spaceAfter=4, leading=14)
    estilo_meta = ParagraphStyle('meta', parent=styles['Normal'],
                                  fontSize=9, textColor=HexColor('#666666'), spaceAfter=2)

    story = []

    story.append(Paragraph('⚖️ ANÁLISIS NORMATIVO', estilo_titulo))
    story.append(Paragraph(f"<b>Norma:</b> {analisis.get('titulo', 'N/D')}", estilo_meta))
    story.append(Paragraph(f"<b>Organismo:</b> {analisis.get('organismo', 'N/D')} | <b>Vigencia:</b> {analisis.get('vigencia', 'N/D')}", estilo_meta))
    story.append(Paragraph(f"<b>Análisis:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", estilo_meta))
    story.append(Spacer(1, 8*mm))

    texto = analisis.get('analisis_completo', '')
    secciones = _secciones(texto)

    if secciones:
        for titulo_sec, contenido in secciones.items():
            story.append(Paragraph(titulo_sec, estilo_h1))
            for linea in contenido.split('\n'):
                linea = linea.strip()
                if not linea:
                    story.append(Spacer(1, 2*mm))
                    continue
                linea = linea.replace('**', '<b>').replace('**', '</b>')
                if linea.startswith('- ') or linea.startswith('• '):
                    story.append(Paragraph(f"• {linea[2:]}", estilo_body))
                else:
                    story.append(Paragraph(linea, estilo_body))
    else:
        story.append(Paragraph(texto[:3000], estilo_body))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def generar_ppt(analisis: dict, resultados_cruce: list = None) -> bytes:
    """Genera un PowerPoint con el análisis en 7 slides."""
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    AZUL_OSC = RGBColor(0x1a, 0x5f, 0xa8)
    AZUL_CLAR = RGBColor(0xe8, 0xf4, 0xfd)
    GRIS = RGBColor(0x44, 0x44, 0x44)
    BLANCO = RGBColor(0xff, 0xff, 0xff)

    blank_layout = prs.slide_layouts[6]  # blank

    def add_slide(titulo_slide, contenido_slide, es_portada=False):
        slide = prs.slides.add_slide(blank_layout)
        w, h = prs.slide_width, prs.slide_height

        # Fondo
        bg = slide.shapes.add_shape(1, 0, 0, w, h)
        bg.fill.solid()
        bg.fill.fore_color.rgb = AZUL_CLAR if not es_portada else AZUL_OSC
        bg.line.fill.background()

        # Barra lateral izquierda
        barra = slide.shapes.add_shape(1, 0, 0, Inches(0.15), h)
        barra.fill.solid()
        barra.fill.fore_color.rgb = AZUL_OSC
        barra.line.fill.background()

        # Título
        txBox = slide.shapes.add_textbox(Inches(0.4), Inches(0.3), Inches(12.5), Inches(0.9))
        tf = txBox.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = titulo_slide
        run.font.size = Pt(28 if es_portada else 22)
        run.font.bold = True
        run.font.color.rgb = BLANCO if es_portada else AZUL_OSC

        # Contenido
        if contenido_slide:
            txBox2 = slide.shapes.add_textbox(Inches(0.4), Inches(1.4), Inches(12.5), Inches(5.7))
            tf2 = txBox2.text_frame
            tf2.word_wrap = True
            for i, linea in enumerate(contenido_slide.split('\n')[:18]):
                linea = linea.strip()
                if not linea:
                    continue
                p2 = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
                run2 = p2.add_run()
                if linea.startswith('- ') or linea.startswith('• '):
                    run2.text = f"  • {linea[2:]}"
                    run2.font.size = Pt(13)
                elif linea.startswith('**') and linea.endswith('**'):
                    run2.text = linea.strip('*')
                    run2.font.bold = True
                    run2.font.size = Pt(14)
                else:
                    run2.text = linea
                    run2.font.size = Pt(13)
                run2.font.color.rgb = BLANCO if es_portada else GRIS

        return slide

    # Parsear secciones
    texto = analisis.get('analisis_completo', '')
    secciones = _secciones(texto)

    # Slide 1: Portada
    titulo_norma = analisis.get('titulo', 'Análisis Normativo')
    organismo = analisis.get('organismo', '')
    fecha = datetime.now().strftime('%d/%m/%Y')
    portada_contenido = f"Organismo: {organismo}\nFecha: {fecha}\nVigencia: {analisis.get('vigencia','N/D')}"
    add_slide(titulo_norma, portada_contenido, es_portada=True)

    # Slides por sección
    iconos = {
        'RESUMEN EJECUTIVO': '📋',
        'PUNTOS CLAVE': '🔑',
        'ANÁLISIS OPERATIVO': '⚙️',
        'RIESGOS Y ZONAS GRISES': '⚠️',
        'EJEMPLO PRÁCTICO': '📌',
        'CHECKLIST ACCIONABLE': '✅',
        'DUDAS ABIERTAS': '❓',
    }

    for titulo_sec, contenido in list(secciones.items())[:7]:
        icono = iconos.get(titulo_sec, '📄')
        add_slide(f"{icono} {titulo_sec}", contenido[:800])

    # Slide de cruce si existe
    if resultados_cruce:
        enc = sum(1 for r in resultados_cruce if r["estado"] == "ENCUADRA")
        no  = sum(1 for r in resultados_cruce if r["estado"] == "NO ENCUADRA")
        aal = sum(1 for r in resultados_cruce if r["estado"] == "A ANALIZAR")
        cruce_texto = f"Total analizados: {len(resultados_cruce)}\n\n🟢 Encuadran: {enc}\n🔴 No encuadran: {no}\n🟡 A analizar: {aal}"
        add_slide("📊 RESULTADOS DEL CRUCE", cruce_texto)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf.read()
