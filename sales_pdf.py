"""A4 commercial summary from immutable order snapshots, never a tax invoice."""
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from local_time import paraguay_datetime


def build_commercial_pdf(commercial):
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=17*mm, rightMargin=17*mm,
                                topMargin=17*mm, bottomMargin=18*mm, title=f"Pedido comercial #{commercial.order_id}", author="Samudio Hnos.")
    styles = getSampleStyleSheet()
    styles["Title"].fontSize = 18
    styles["Title"].leading = 23
    styles["Title"].textColor = colors.HexColor("#102c57")
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 13

    def p(value, style="BodyText"):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])

    def money(value):
        return f"{int(value):,}".replace(",", ".") + " Gs."

    order, store = commercial.order, commercial.store_snapshot
    story = [p("SAMUDIO HNOS. REPRESENTACIONES", "Title"), p(f"Resumen comercial #{order.id}", "Heading2"),
             p(f"Fecha y hora: {paraguay_datetime(order.created_at).strftime('%d/%m/%Y %H:%M:%S')} (Paraguay)"),
             p(f"Estado: {order.status}"), Spacer(1, 4*mm), p(f"Vendedor: {commercial.seller_name}"), p(f"Comercio: {commercial.store_name}")]
    for key, title in [("responsible", "Responsable"), ("phone", "Teléfono del comercio"), ("city", "Ciudad"), ("address", "Dirección")]:
        if store.get(key):
            story.append(p(f"{title}: {store[key]}"))
    story.append(Spacer(1, 5*mm))
    rows = [[p(label) for label in ("Producto", "Cantidad", "Precio unitario", "Subtotal")]]
    for item in commercial.items_snapshot:
        rows.append([p(item["name"]), p(item["quantity"]), p(money(item["unit_price"])), p(money(item["subtotal"]))])
    table = Table(rows, colWidths=[77*mm, 19*mm, 31*mm, 49*mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8edf5")), ("VALIGN", (0,0), (-1,-1), "TOP"),
                              ("LINEBELOW", (0,0), (-1,-1), .4, colors.HexColor("#c8d0dd")),
                              ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 8)]))
    story += [table, Spacer(1, 5*mm), p(f"TOTAL: {money(order.total)}", "Heading2")]
    if order.notes:
        story += [p("Observaciones", "Heading3"), p(order.notes)]
    story += [Spacer(1, 6*mm), p("Teléfono comercial: 0983620676"),
              p("Resumen comercial. No es una factura legal ni un comprobante de pago o entrega.")]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#536078"))
        canvas.drawString(17*mm, 10*mm, "Samudio Hnos. | Resumen de pedido comercial")
        canvas.drawRightString(A4[0]-17*mm, 10*mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output
