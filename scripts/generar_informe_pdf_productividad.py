from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "datos" / "analisis_productividad.db"
OUT = ROOT / "output" / "pdf" / "informe_analisis_carga_picking.pdf"
TMP = ROOT / "tmp" / "pdfs"
REF = Path(r"C:\Users\207189\AppData\Local\Temp\codex-clipboard-22838277-cb9e-4740-a206-9d61353066de.jpg")
PAGE_W, PAGE_H = A4
BLUE = colors.HexColor("#00549F")
BLUE_DARK = colors.HexColor("#003B70")
GREEN = colors.HexColor("#1F7A4D")
ORANGE = colors.HexColor("#B25F00")
RED = colors.HexColor("#C8102E")
PURPLE = colors.HexColor("#6B3FC6")
LIGHT = colors.HexColor("#F1F5F8")
GRID = colors.HexColor("#D8E1E8")
TEXT = colors.HexColor("#18354D")


def fmt(value, decimals=0):
    if value is None:
        return "N/D"
    if decimals:
        return f"{float(value):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{float(value):,.0f}".replace(",", ".")


def pct(value, base):
    return (value / base - 1) * 100 if base else None


def load_rows():
    db = sqlite3.connect(DB)
    result = {}
    for operation, bultos_key, eq_key in (("CARGA", "bultos_carga", "eq_carga"), ("PICKING", "bultos_armado", "eq_armado")):
        rows = []
        query = "SELECT mes, payload_json FROM ap_tendencia_mensual WHERE operacion=? AND grupo_productivo=0 AND mes<=202607 ORDER BY mes"
        for mes, payload in db.execute(query, (operation,)):
            row = json.loads(payload)
            row["mes"] = int(mes)
            row["bultos"] = float(row.get(bultos_key) or 0)
            row["eq_accion"] = float(row.get(eq_key) or 0)
            rows.append(row)
        result[operation] = rows
    db.close()
    return result


def avg(rows, key):
    return sum(float(row.get(key) or 0) for row in rows) / len(rows) if rows else 0


def period(rows, start, end):
    return [row for row in rows if start <= row["mes"] <= end]


def p(text, style):
    return Paragraph(text, style)


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=BLUE_DARK, alignment=TA_LEFT, spaceAfter=8),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="Helvetica", fontSize=12, leading=16, textColor=TEXT),
        "h": ParagraphStyle("h", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=BLUE_DARK, spaceAfter=7),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=TEXT),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica", fontSize=7.8, leading=10, textColor=TEXT),
        "callout": ParagraphStyle("callout", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=BLUE_DARK),
        "cover": ParagraphStyle("cover", parent=base["Title"], fontName="Helvetica", fontSize=25, leading=30, textColor=colors.white),
        "cover_small": ParagraphStyle("cover_small", parent=base["Normal"], fontName="Helvetica", fontSize=10, leading=14, textColor=colors.white),
        "center": ParagraphStyle("center", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=TEXT, alignment=TA_CENTER),
    }


def header(c, title, page):
    c.setFillColor(BLUE_DARK)
    c.rect(0, PAGE_H - 15 * mm, PAGE_W, 15 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(18 * mm, PAGE_H - 9.5 * mm, "AUDITORIA DE PRODUCTIVIDAD")
    c.setFont("Helvetica", 8)
    c.drawRightString(PAGE_W - 18 * mm, PAGE_H - 9.5 * mm, title.upper())
    c.setStrokeColor(GRID)
    c.line(18 * mm, 12 * mm, PAGE_W - 18 * mm, 12 * mm)
    c.setFillColor(colors.HexColor("#60788A"))
    c.setFont("Helvetica", 7.5)
    c.drawString(18 * mm, 7 * mm, "Fuente: análisis histórico de productividad | Grupo operativo general")
    c.drawRightString(PAGE_W - 18 * mm, 7 * mm, f"Página {page}")


def draw_text(c, text, x, y, width, style):
    para = Paragraph(text, style)
    _, h = para.wrap(width, PAGE_H)
    para.drawOn(c, x, y - h)
    return y - h


def table(c, data, x, y, widths, row_heights=None, font=8):
    t = Table(data, colWidths=widths, rowHeights=row_heights)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), font), ("LEADING", (0, 0), (-1, -1), font + 2),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]), ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    _, h = t.wrapOn(c, PAGE_W, PAGE_H)
    t.drawOn(c, x, y - h)
    return y - h


def line_chart(c, rows, specs, x, y, w, h, title, percent=False):
    c.setFillColor(colors.white); c.roundRect(x, y, w, h, 3 * mm, fill=1, stroke=0)
    c.setFillColor(BLUE_DARK); c.setFont("Helvetica-Bold", 10); c.drawString(x + 7 * mm, y + h - 9 * mm, title)
    px, py, pw, ph = x + 15 * mm, y + 14 * mm, w - 23 * mm, h - 27 * mm
    values = [float(row.get(key) or 0) for key, _, _ in specs for row in rows]
    vmax = max(values or [1]); vmax = max(1, vmax * 1.12)
    c.setStrokeColor(GRID); c.setFont("Helvetica", 6.5); c.setFillColor(colors.HexColor("#60788A"))
    for i in range(4):
        yy = py + ph * i / 3
        c.line(px, yy, px + pw, yy); c.drawRightString(px - 2, yy - 2, fmt(vmax * i / 3, 0 if not percent else 1) + ("%" if percent else ""))
    if len(rows) > 1:
        for i in [0, len(rows) // 2, len(rows) - 1]: c.drawCentredString(px + pw * i / (len(rows) - 1), py - 9, str(rows[i]["mes"]))
    for key, label, color in specs:
        c.setStrokeColor(color); c.setLineWidth(1.8); pts=[]
        for i, row in enumerate(rows):
            xx = px + (pw / 2 if len(rows) == 1 else pw * i / (len(rows) - 1)); yy = py + ph * float(row.get(key) or 0) / vmax; pts.append((xx, yy))
        for a, b in zip(pts, pts[1:]): c.line(a[0], a[1], b[0], b[1])
        c.setFillColor(color)
        for xx, yy in pts: c.circle(xx, yy, 1.3, fill=1, stroke=0)
    lx = x + 8 * mm; ly = y + 4 * mm
    for _, label, color in specs:
        c.setFillColor(color); c.rect(lx, ly, 3 * mm, 1.2 * mm, fill=1, stroke=0); c.setFillColor(TEXT); c.setFont("Helvetica", 6.5); c.drawString(lx + 4 * mm, ly - 1, label); lx += 29 * mm


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = load_rows(); carga, picking = data["CARGA"], data["PICKING"]
    shift_c = period(carga, 202506, 202509); shift_p = period(picking, 202506, 202509)
    oct_c = period(carga, 202510, 202512); oct_p = period(picking, 202510, 202512)
    c = canvas.Canvas(str(OUT), pagesize=(PAGE_W, PAGE_H)); st = styles(); page = 1

    # Página 1: resumen ejecutivo en formato hoja.
    header(c, "Informe de productividad", page); y = PAGE_H - 25 * mm
    y = draw_text(c, "Informe de productividad - CARGA y PICKING", 18 * mm, y, PAGE_W - 36 * mm, st["title"])
    y = draw_text(c, "Consolidación, equivalencias y acceso al premio", 18 * mm, y + 2 * mm, PAGE_W - 36 * mm, st["subtitle"])
    y = draw_text(c, "Objetivo: determinar si una mayor concentración de consolidación en PICKING coincide con una pérdida de equivalencias disponibles para CARGA.", 18 * mm, y - 7 * mm, PAGE_W - 36 * mm, st["body"])
    cards = [("Jornadas con premio CARGA", "73,5% -> 48,0%", "base 2024 vs. ene-jul 2026", RED), ("Nivel promedio CARGA", "2,30 -> 1,60", "variación -30,6%", ORANGE), ("Consolidación PICKING", "+37%", "bultos jun-sep vs. oct-dic 2025", GREEN), ("Equivalencias PICKING", "+50%", "jun-sep vs. oct-dic 2025", PURPLE)]
    cx, cy = 18 * mm, y - 15 * mm
    for i, (title, value, foot, color) in enumerate(cards):
        x = cx + (i % 2) * 89 * mm; yy = cy - (i // 2) * 28 * mm
        c.setFillColor(colors.white); c.setStrokeColor(GRID); c.roundRect(x, yy - 22 * mm, 82 * mm, 22 * mm, 2 * mm, fill=1, stroke=1); c.setFillColor(color); c.rect(x, yy, 82 * mm, 1.5 * mm, fill=1, stroke=0); c.setFillColor(BLUE_DARK); c.setFont("Helvetica-Bold", 8); c.drawString(x + 4 * mm, yy - 7 * mm, title); c.setFont("Helvetica-Bold", 15); c.drawString(x + 4 * mm, yy - 14 * mm, value); c.setFont("Helvetica", 7); c.setFillColor(TEXT); c.drawString(x + 4 * mm, yy - 19 * mm, foot)
    c.setFillColor(colors.HexColor("#EAF2F8")); c.roundRect(18 * mm, 44 * mm, PAGE_W - 36 * mm, 49 * mm, 3 * mm, fill=1, stroke=0)
    draw_text(c, "Conclusión ejecutiva", 25 * mm, 86 * mm, PAGE_W - 50 * mm, st["h"])
    draw_text(c, "La evidencia disponible es compatible con un desplazamiento de consolidación desde CARGA hacia PICKING. CARGA pierde bultos y equivalencias mientras PICKING aumenta ambos indicadores. Esto ofrece una explicación operativa para la caída de escala de los cargadores, aunque el cambio exacto debe contrastarse con la evolución histórica de las funciones y reglas de trabajo.", 25 * mm, 76 * mm, PAGE_W - 50 * mm, st["callout"])
    c.showPage(); page += 1

    # Página 2: CARGA.
    header(c, "Evolución de CARGA", page)
    line_chart(c, carga, [("prod_real", "Producción real", BLUE), ("eq_total", "Equivalente total", PURPLE)], 18 * mm, 177 * mm, 174 * mm, 75 * mm, "Producción mensual")
    line_chart(c, carga, [("pct_premio", "Jornadas con premio", RED), ("nivel_prom", "Nivel promedio", ORANGE)], 18 * mm, 94 * mm, 174 * mm, 72 * mm, "Acceso a la escala")
    line_chart(c, carga, [("eq_carga", "Consolidación", ORANGE), ("eq_traslado", "Traslado", colors.HexColor("#D89B00")), ("eq_carreteo", "Carreteo", GREEN)], 18 * mm, 15 * mm, 174 * mm, 72 * mm, "Componentes de la equivalencia")
    c.showPage(); page += 1

    # Página 3: comparación visual.
    header(c, "CARGA y PICKING", page)
    draw_text(c, "Evolución de la consolidación por operación", 18 * mm, PAGE_H - 25 * mm, PAGE_W - 36 * mm, st["title"])
    line_chart(c, carga, [("bultos", "CARGA - bultos", BLUE)], 18 * mm, 177 * mm, 174 * mm, 67 * mm, "Bultos consolidados CARGA")
    line_chart(c, picking, [("bultos", "PICKING - bultos", GREEN)], 18 * mm, 101 * mm, 174 * mm, 67 * mm, "Bultos consolidados PICKING")
    line_chart(c, carga, [("eq_accion", "CARGA - equivalencias", ORANGE)], 18 * mm, 25 * mm, 84 * mm, 65 * mm, "Equivalencias CARGA")
    line_chart(c, picking, [("eq_accion", "PICKING - equivalencias", PURPLE)], 108 * mm, 25 * mm, 84 * mm, 65 * mm, "Equivalencias PICKING")
    c.showPage(); page += 1

    # Página 4: tabla de variaciones.
    header(c, "Variaciones porcentuales", page); y = PAGE_H - 25 * mm
    y = draw_text(c, "El cambio se concentra en el reparto de la consolidación", 18 * mm, y, PAGE_W - 36 * mm, st["title"])
    rows = [["Indicador", "CARGA\nJun-sep", "CARGA\nOct-dic", "Cambio", "PICKING\nJun-sep", "PICKING\nOct-dic", "Cambio"]]
    for label, key in (("Bultos consolidados", "bultos"), ("Equivalencias", "eq_accion")):
        cv1, cv2, pv1, pv2 = sum(r[key] for r in shift_c), sum(r[key] for r in oct_c), sum(r[key] for r in shift_p), sum(r[key] for r in oct_p)
        rows.append([label, fmt(cv1), fmt(cv2), f"{pct(cv2,cv1):+.1f}%", fmt(pv1), fmt(pv2), f"{pct(pv2,pv1):+.1f}%"])
    y = table(c, rows, 18 * mm, y - 7 * mm, [38 * mm, 26 * mm, 26 * mm, 22 * mm, 26 * mm, 26 * mm, 22 * mm], font=7.3)
    share_b = sum(r["eq_accion"] for r in shift_p) / (sum(r["eq_accion"] for r in shift_p) + sum(r["eq_accion"] for r in shift_c)) * 100
    share_o = sum(r["eq_accion"] for r in oct_p) / (sum(r["eq_accion"] for r in oct_p) + sum(r["eq_accion"] for r in oct_c)) * 100
    c.setFillColor(colors.HexColor("#EAF2F8")); c.roundRect(18 * mm, 108 * mm, PAGE_W - 36 * mm, 52 * mm, 3 * mm, fill=1, stroke=0)
    draw_text(c, "Lectura gerencial", 25 * mm, 151 * mm, PAGE_W - 50 * mm, st["h"])
    draw_text(c, f"La participación de PICKING en las equivalencias pasó de {share_b:.1f}% a {share_o:.1f}%. En el mismo intervalo, CARGA perdió 28% de sus bultos consolidados y 37,6% de sus equivalencias, mientras PICKING aumentó 36,7% y 49,7%. La coincidencia temporal y la dirección opuesta de las variaciones hacen consistente la hipótesis de traslado.", 25 * mm, 140 * mm, PAGE_W - 50 * mm, st["callout"])
    c.setFillColor(BLUE); c.rect(18 * mm, 36 * mm, PAGE_W - 36 * mm, 17 * mm, fill=1, stroke=0)
    draw_text(c, "La consolidación total no desaparece: cambia la operación en la que genera escala.", 25 * mm, 48 * mm, PAGE_W - 50 * mm, st["cover_small"])
    c.showPage(); page += 1

    # Página 5: alcance y limitaciones, sin lenguaje técnico.
    header(c, "Alcance del análisis", page); y = PAGE_H - 25 * mm
    y = draw_text(c, "Alcance, interpretación y próximos controles", 18 * mm, y, PAGE_W - 36 * mm, st["title"])
    points = [
        "Se compararon meses completos de actividad y se excluyó agosto de 2026 por encontrarse en curso.",
        "La consolidación se midió por cantidad de bultos y por los equivalentes que aporta a cada operación.",
        "La caída de CARGA no se explica por una mayor cantidad de legajos: el promedio mensual de legajos bajó 15,7% frente a la base de 2024.",
        "La evidencia más fuerte comienza en junio de 2025. Antes de esa fecha no aparecen registros comparables de consolidación con la clasificación actualmente utilizada.",
        "Para una definición sindical final debe verificarse si antes de junio de 2025 las mismas tareas estaban identificadas con otros nombres o asignadas a otra operación.",
    ]
    for item in points:
        y = draw_text(c, "- " + item, 23 * mm, y - 6 * mm, PAGE_W - 48 * mm, st["body"])
    c.setFillColor(BLUE); c.rect(18 * mm, 38 * mm, PAGE_W - 36 * mm, 25 * mm, fill=1, stroke=0)
    draw_text(c, "Mensaje para la decisión", 25 * mm, 57 * mm, PAGE_W - 50 * mm, st["cover_small"])
    draw_text(c, "El próximo control debe reconstruir la historia de las funciones para confirmar cuándo y cómo se produjo el cambio de imputación entre CARGA y PICKING.", 25 * mm, 49 * mm, PAGE_W - 50 * mm, st["cover_small"])
    c.save(); print(OUT)


if __name__ == "__main__":
    main()
