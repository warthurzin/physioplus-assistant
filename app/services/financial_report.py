"""In-memory report from the authenticated API; never creates a public file."""

from calendar import monthrange
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.exceptions import UpstreamUnavailableError
from app.tools.formatting import MONTHS, date_br, money, time_hm


def build_financial_pdf(summary: dict, month: int, year: int) -> bytes:
    if not all(
        key in summary
        for key in (
            "total_received",
            "total_pending",
            "paid_sessions",
            "pending_sessions",
        )
    ):
        raise UpstreamUnavailableError("Resumo financeiro incompleto")
    paid, pending = summary["paid_sessions"], summary["pending_sessions"]
    # Fail closed if the API's totals and detail disagree; the model never computes money.
    for items, key, status in (
        (paid, "total_received", "paid"),
        (pending, "total_pending", "pending"),
    ):
        if any(
            str(item.get("date", ""))[:7] != f"{year}-{month:02d}"
            or item.get("payment_status") != status
            for item in items
        ):
            raise UpstreamUnavailableError("Período financeiro inconsistente")
        total = sum((Decimal(str(item["session_value"])) for item in items), Decimal(0))
        if total.quantize(Decimal("0.01")) != Decimal(str(summary[key])).quantize(
            Decimal("0.01")
        ):
            raise UpstreamUnavailableError("Totais financeiros inconsistentes")

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="Relatório financeiro PhysioPlus",
        author="PhysioPlus",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportCell",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            wordWrap="CJK",
        )
    )
    styles["Title"].textColor = colors.HexColor("#193ce0")

    def cell(text):
        return Paragraph(escape(str(text)), styles["ReportCell"])

    period = f"{MONTHS[month - 1].capitalize()} de {year}"
    story = [
        Paragraph("PhysioPlus", styles["Title"]),
        Paragraph("Relatório financeiro", styles["Heading1"]),
        Paragraph(period, styles["Heading2"]),
        Paragraph(
            f"Período: 01/{month:02d}/{year} a {monthrange(year, month)[1]:02d}/{month:02d}/{year}",
            styles["Normal"],
        ),
        Spacer(1, 7 * mm),
    ]
    totals = Table(
        [
            ["RECEBIDO", "PENDENTE", "SESSÕES"],
            [
                money(summary["total_received"]),
                money(summary["total_pending"]),
                str(len(paid) + len(pending)),
            ],
        ],
        colWidths=[58 * mm] * 3,
    )
    totals.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf0ff")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#193164")),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend(
        [
            totals,
            Spacer(1, 6 * mm),
            Paragraph(
                "Valores agrupados pela data da sessão e pelo estado atual do pagamento. "
                "A API não registra a data de recebimento.",
                styles["Normal"],
            ),
            Spacer(1, 6 * mm),
        ]
    )
    rows = [
        [
            cell(value)
            for value in ("Paciente", "Data da sessão", "Horário", "Estado", "Valor")
        ]
    ]
    for item in sorted(
        paid + pending,
        key=lambda row: (str(row["date"]), str(row.get("start_time", ""))),
    ):
        rows.append(
            [
                cell(value)
                for value in (
                    (item.get("patient") or {}).get("full_name") or "Não informado",
                    date_br(item["date"]),
                    time_hm(item.get("start_time")),
                    "Pago" if item["payment_status"] == "paid" else "Pendente",
                    money(item["session_value"]),
                )
            ]
        )
    if len(rows) == 1:
        story.append(
            Paragraph("Nenhuma sessão registrada no período.", styles["Normal"])
        )
    else:
        table = Table(
            rows,
            colWidths=[59 * mm, 33 * mm, 22 * mm, 27 * mm, 33 * mm],
            repeatRows=1,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe6ff")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f6f8fc")],
                    ),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#193ce0")),
                ]
            )
        )
        story.append(table)

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#596579"))
        canvas.drawString(
            18 * mm,
            12 * mm,
            "PhysioPlus | Relatório confidencial do profissional autenticado",
        )
        canvas.drawRightString(192 * mm, 12 * mm, f"Página {_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
