"""Build order summaries using the existing persisted order and item prices."""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from local_time import format_paraguay_datetime


def build_order_pdf(order) -> BytesIO:
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Resumen del pedido #{order.id}", author="Wilson Samudio",
    )
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#176b4b")

    def paragraph(value, style="BodyText"):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])

    def money(value):
        return f"{int(value):,}".replace(",", ".") + " Gs."

    story = [
        paragraph("Wilson Samudio Representaciones", "Title"),
        paragraph(f"Resumen del pedido #{order.id}", "Heading2"),
        paragraph(f"Fecha: {format_paraguay_datetime(order.created_at)} (hora de Paraguay)"),
        paragraph(f"Estado: {order.status}"),
        Spacer(1, 5 * mm),
        paragraph("Datos del cliente", "Heading3"),
        paragraph(f"Nombre: {order.customer.name}"),
        paragraph(f"Teléfono: {order.customer.phone}"),
        paragraph(f"Ciudad: {order.customer.city}"),
    ]
    if order.customer.address:
        story.append(paragraph(f"Dirección: {order.customer.address}"))
    story.extend([Spacer(1, 5 * mm), paragraph("Detalle del pedido", "Heading3")])
    rows = [[paragraph(label) for label in ("Producto", "Cantidad", "Precio unitario", "Subtotal")]]
    for item in sorted(order.items, key=lambda item: item.id):
        rows.append([
            paragraph(item.product.name if item.product else "Producto no disponible"),
            paragraph(item.quantity), paragraph(money(item.unit_price)),
            paragraph(money(item.quantity * item.unit_price)),
        ])
    table = Table(rows, colWidths=[76 * mm, 20 * mm, 30 * mm, 30 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7f5eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce5df")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([
        table, Spacer(1, 5 * mm),
        paragraph(f"Total del pedido: {money(order.total)}", "Heading2"),
    ])
    if order.notes:
        story.extend([paragraph("Observaciones", "Heading3"), paragraph(order.notes)])
    story.extend([
        Spacer(1, 5 * mm),
        paragraph("Este resumen corresponde al pedido registrado; no acredita el pago."),
        paragraph("El pago y la entrega se coordinan directamente con el negocio."),
    ])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output
