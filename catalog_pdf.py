"""Generate the public catalog without changing the store's models or templates."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import warnings
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape

from PIL import Image as PillowImage, ImageOps
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


def _image_bytes(image_url: str, upload_folder: str, static_folder: str) -> bytes:
    """Read local photos or existing public image URLs, with bounded downloads."""
    parsed = urlsplit(image_url)
    limit = 5 * 1024 * 1024
    if not parsed.scheme and not parsed.netloc:
        for prefix, folder in (("/uploads/", upload_folder), ("/static/", static_folder)):
            if parsed.path.startswith(prefix):
                root = Path(folder).resolve()
                path = (root / unquote(parsed.path[len(prefix):])).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("Invalid image path")
                with path.open("rb") as source:
                    data = source.read(limit + 1)
                break
        else:
            raise ValueError("Unknown image path")
    else:
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Invalid image URL")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in {80, 443} or parsed.username or parsed.password:
            raise ValueError("Invalid image URL")
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise ValueError("Image host must be public")
        address = addresses[0][4][0]
        connection_type = (
            http.client.HTTPSConnection if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_type(parsed.hostname, port, timeout=3)
        # Pin the validated address while preserving the hostname for HTTPS/TLS.
        connection._create_connection = lambda *args, **kwargs: socket.create_connection(
            (address, port), timeout=3
        )
        try:
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request("GET", target, headers={"User-Agent": "CatalogoPDF/1.0"})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("Image unavailable")
            data = response.read(limit + 1)
        finally:
            connection.close()
    if len(data) > limit:
        raise ValueError("Image too large")
    return data


def _photo(image_url: str, upload_folder: str, static_folder: str, style):
    if image_url:
        try:
            data = _image_bytes(image_url, upload_folder, static_folder)
            with warnings.catch_warnings():
                warnings.simplefilter("error", PillowImage.DecompressionBombWarning)
                with PillowImage.open(BytesIO(data)) as original:
                    photo = ImageOps.exif_transpose(original).convert("RGB")
                    photo.thumbnail((600, 600))
                    normalized = BytesIO()
                    photo.save(normalized, format="JPEG", quality=85)
                    normalized.seek(0)
                    scale = min(36 * mm / photo.width, 36 * mm / photo.height)
                    return Image(normalized, width=photo.width * scale,
                                 height=photo.height * scale)
        except (OSError, ValueError, SyntaxError, http.client.HTTPException,
                PillowImage.DecompressionBombError, PillowImage.DecompressionBombWarning):
            pass
    return Paragraph("Imagen no disponible", style)


def build_catalog_pdf(products, upload_folder: str, static_folder: str) -> BytesIO:
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Catálogo de productos | Wilson Samudio", author="Wilson Samudio",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "CatalogTitle", parent=styles["Title"], textColor=colors.HexColor("#176b4b"),
        fontSize=22, leading=26, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "PhotoPlaceholder", parent=styles["BodyText"], alignment=TA_CENTER,
        textColor=colors.HexColor("#66736b"),
    ))
    styles.add(ParagraphStyle(
        "ProductPrice", parent=styles["Heading2"], textColor=colors.HexColor("#176b4b"),
    ))
    story = [
        Paragraph("Wilson Samudio Representaciones", styles["CatalogTitle"]),
        Paragraph("Catálogo de productos", styles["Heading2"]),
        Paragraph(f"{len(products)} productos", styles["BodyText"]),
        Spacer(1, 8 * mm),
    ]
    if not products:
        story.append(Paragraph("No hay productos disponibles en este momento.", styles["BodyText"]))
    for product in products:
        price = f"{product.price:,}".replace(",", ".") + " Gs."
        details = [
            Paragraph(escape(product.name), styles["Heading2"]),
            Paragraph(escape(product.category.name), styles["BodyText"]),
            Paragraph(price, styles["ProductPrice"]),
        ]
        heading = Table(
            [[_photo(product.image_url, upload_folder, static_folder,
                     styles["PhotoPlaceholder"]), details]],
            colWidths=[44 * mm, document.width - 44 * mm],
        )
        heading.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        heading.keepWithNext = True
        description = escape(product.description or "Sin descripción.")
        description = description.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")
        story.extend([
            heading, Paragraph(description, styles["BodyText"]),
            Spacer(1, 5 * mm),
            HRFlowable(width="100%", color=colors.HexColor("#d5ddd7")),
            Spacer(1, 6 * mm),
        ])

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#66736b"))
        canvas.drawString(18 * mm, 10 * mm, "Wilson Samudio Representaciones")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    output.seek(0)
    return output
