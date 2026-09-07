import io
import math
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

RANK_COLORS = ["#FF2A6D", "#FFB703", "#00B8C4", "#9D4EDD", "#38BDF8", "#10B981"]


def _fmt(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%MZ")
    if isinstance(v, str) and len(v) >= 19 and v[10] == "T":
        return v[:16].replace("T", " ") + "Z"
    return "—" if v is None else str(v)


def render_map_png(geometries: dict) -> bytes:
    feats = geometries.get("features", [])
    fig, ax = plt.subplots(figsize=(7.2, 5.2), dpi=130)
    fig.patch.set_facecolor("#0A0E17")
    ax.set_facecolor("#0d1522")
    for f in feats:
        g, p = f["geometry"], f["properties"]
        layer = p.get("layer")
        if layer == "corridor":
            xs, ys = zip(*g["coordinates"][0])
            ax.plot(xs, ys, color="#00F0FF", lw=0.8, ls="--", alpha=0.8)
        elif layer == "spill":
            rings = g["coordinates"] if g["type"] == "Polygon" else [r for poly in g["coordinates"] for r in poly]
            for ring in rings:
                xs, ys = zip(*ring)
                ax.fill(xs, ys, color="#FF2A6D", alpha=0.45)
                ax.plot(xs, ys, color="#FF2A6D", lw=1.4, ls="--")
    for f in feats:
        g, p = f["geometry"], f["properties"]
        col = RANK_COLORS[min((p.get("rank") or 1) - 1, len(RANK_COLORS) - 1)]
        if p.get("layer") == "track":
            xs, ys = zip(*g["coordinates"])
            ax.plot(xs, ys, color=col, lw=1.6, alpha=0.9, label=f"#{p['rank']} {p.get('vessel_name') or p['mmsi']}")
        elif p.get("layer") == "closest_fix":
            ax.scatter([g["coordinates"][0]], [g["coordinates"][1]], s=40, color=col, edgecolors="white", linewidths=0.6, zorder=5)
        elif p.get("layer") == "backprojected_centroid":
            ax.scatter([g["coordinates"][0]], [g["coordinates"][1]], s=22, facecolors="none", edgecolors=col, linewidths=1.2, zorder=5)
    ymid = sum(ax.get_ylim()) / 2
    ax.set_aspect(1 / max(math.cos(math.radians(ymid)), 0.1))
    ax.tick_params(colors="#94A3B8", labelsize=7)
    for s in ax.spines.values():
        s.set_color("#334155")
    ax.set_xlabel("Longitude", color="#94A3B8", fontsize=8)
    ax.set_ylabel("Latitude", color="#94A3B8", fontsize=8)
    ax.grid(color="#1E293B", lw=0.5)
    if ax.get_legend_handles_labels()[0]:
        leg = ax.legend(loc="upper left", fontsize=6.5, facecolor="#111827", edgecolor="#334155", labelcolor="#F8FAFC")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def build_pdf(bundle: dict) -> bytes:
    case, spill = bundle["case"], bundle["source_references"]["spill_observation"]
    scene, calc = bundle["source_references"].get("scene"), bundle.get("calculations")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=18, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#0B3B4F"))
    body = ParagraphStyle("b", parent=styles["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#475569"))
    mono = ParagraphStyle("m", parent=body, fontName="Courier", fontSize=7.5, leading=9.5)

    def table(rows, widths=None, header=True):
        t = Table([[Paragraph(str(c), body) if not isinstance(c, Paragraph) else c for c in r] for r in rows], colWidths=widths, repeatRows=1 if header else 0)
        st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        if header:
            st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0"))]
        t.setStyle(TableStyle(st))
        return t

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Evidence package {case['case_number']}", author="SentinelMar")
    W = A4[0] - 32 * mm
    el = [Paragraph(f"Evidence Package — {case['case_number']}", h1),
          Paragraph(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}Z by SentinelMar · {bundle.get('generated_by', 'system')}", small),
          Paragraph(f"<b>Disclaimer.</b> {bundle['disclaimer']}", small), Spacer(1, 6)]

    el.append(Paragraph("1. Case summary", h2))
    el.append(table([
        ["Case number", case["case_number"], "Attribution status", case["attribution_status"]],
        ["Automated status", _fmt(case.get("automated_status")), "Confidence band", _fmt(case.get("confidence_band"))],
        ["Review state", case["review_state"], "Confirmed vessel MMSI", _fmt(case.get("confirmed_vessel_mmsi"))],
        ["Acquisition (UTC)", _fmt(case["acquisition_time"]), "Result version", str(case.get("latest_result_version", 0))],
        ["Degraded (no drift inputs)", _fmt(case.get("degraded")), "Case status", case["status"]],
        ["Primary jurisdiction", f"{case['primary_jurisdiction']['code']} — {case['primary_jurisdiction']['authority']}" if case.get("primary_jurisdiction") else "unassigned",
         "Other zones intersected", ", ".join(z["code"] for z in (case.get("jurisdictions") or []) if not case.get("primary_jurisdiction") or z["code"] != case["primary_jurisdiction"]["code"]) or "—"],
    ], [W * 0.2, W * 0.3, W * 0.22, W * 0.28], header=False))

    el.append(Paragraph("2. Spill observation & source references", h2))
    el.append(table([
        ["Observation ID", spill["id"], "Source", spill["source"]],
        ["Processing version", spill["processing_version"], "Detection confidence", f"{spill['detection_confidence']:.2f}"],
        ["Estimated area", f"{spill['estimated_area_km2']} km²", "Quality flags", ", ".join(spill.get("quality_flags") or []) or "none"],
        ["Centroid (lat, lon)", f"{spill['centroid']['coordinates'][1]:.4f}, {spill['centroid']['coordinates'][0]:.4f}", "Estimated age", _fmt(spill.get("estimated_age_hours"))],
        ["Scene", f"{scene['provider']} · {scene['provider_scene_id']}" if scene else "— (external polygon)", "Storage reference", _fmt(bundle["source_references"].get("storage_ref"))],
        ["Wind (FROM)", f"{spill['wind']['speed_ms']} m/s @ {spill['wind']['direction_deg']}°" if spill.get("wind") else "—", "Current (TOWARD)", f"{spill['current']['speed_ms']} m/s @ {spill['current']['direction_deg']}°" if spill.get("current") else "—"],
        ["Environment source", _fmt((spill.get("environment") or {}).get("source")), "AIS fixes referenced", str(len(bundle["source_references"].get("ais_fix_ids", [])))],
    ], [W * 0.2, W * 0.3, W * 0.22, W * 0.28], header=False))

    el.append(Paragraph("3. Map snapshot", h2))
    try:
        png = render_map_png(bundle["geometries"])
        el.append(KeepTogether([Image(io.BytesIO(png), width=W * 0.9, height=W * 0.9 * 5.2 / 7.2),
                                Paragraph("Crimson dashed: spill polygon · cyan dashed: search corridor · coloured lines: candidate AIS tracks (by rank) · filled dots: closest approach · rings: drift back-projection of slick centroid", small)]))
    except Exception as e:  # noqa: BLE001
        el.append(Paragraph(f"Map rendering failed: {e}", small))

    if calc:
        el.append(Paragraph("4. Correlation calculations", h2))
        env = calc.get("environment") or {}
        el.append(table([
            ["Algorithm version", calc["algorithm_version"], "Input hash", Paragraph(calc["input_hash"], mono)],
            ["Corridor / window", f"{calc['params']['corridor_km']} km · −{calc['params']['window_hours_before']}h / +{calc['params']['window_hours_after']}h", "Weights", ", ".join(f"{k}={v}" for k, v in calc["params"]["weights"].items())],
            ["Wind used", f"{env['wind']['speed_ms']} m/s @ {env['wind']['direction_deg']}°" if env.get("wind") else "none", "Current used", f"{env['current']['speed_ms']} m/s @ {env['current']['direction_deg']}°" if env.get("current") else "none"],
            ["Degraded", str(calc["degraded"]), "Spill axis bearing", f"{calc['spill_axis_bearing']}°"],
        ], [W * 0.2, W * 0.3, W * 0.18, W * 0.32], header=False))
        el.append(Spacer(1, 6))
        el.append(Paragraph("Ranked candidates", ParagraphStyle("h3", parent=body, fontSize=10, spaceAfter=3, fontName="Helvetica-Bold")))
        rows = [["#", "Vessel", "MMSI / IMO", "Type", "Score", "Status", "Dist km", "Gap h", "Fixes"]]
        for c in calc["candidates"]:
            rows.append([c["rank"], c.get("vessel_name") or "UNKNOWN", f"{c['mmsi']}{' / ' + c['imo'] if c.get('imo') else ''}", c.get("vessel_type") or "—", f"{c['score']:.3f}", c["status"],
                         c["evidence"]["distance_km"], c["evidence"]["time_gap_hours"], c["evidence"]["fix_count"]])
        el.append(table(rows, [W * 0.04, W * 0.2, W * 0.18, W * 0.1, W * 0.08, W * 0.17, W * 0.08, W * 0.07, W * 0.08]))
        for c in calc["candidates"]:
            el.append(Spacer(1, 6))
            el.append(Paragraph(f"#{c['rank']} {c.get('vessel_name') or c['mmsi']} — factor breakdown", ParagraphStyle("h4", parent=body, fontName="Helvetica-Bold")))
            frows = [["Factor", "Score", "Weight", "Contribution", "Detail"]]
            for k, f in c["factors"].items():
                frows.append([k, f"{f['score']:.3f}", f["weight"], f"{f['contribution']:.3f}", f["detail"]])
            el.append(table(frows, [W * 0.14, W * 0.09, W * 0.09, W * 0.12, W * 0.56]))
            if c.get("notes"):
                el.append(Paragraph("Notes: " + " · ".join(c["notes"]), small))
            if c.get("ais_flags"):
                el.append(Paragraph("AIS flags: " + ", ".join(c["ais_flags"]), small))
        el.append(Spacer(1, 6))
        el.append(Paragraph("Processing log", ParagraphStyle("h3b", parent=body, fontName="Helvetica-Bold")))
        for l in calc.get("processing_log", []):
            el.append(Paragraph(f"{l['t'][11:19]} [{l['level']}] {l['msg']}", mono))

    el.append(Paragraph("5. Result versions", h2))
    vrows = [["Version", "Created", "Algorithm", "Overall status", "Degraded", "Input hash"]]
    for v in bundle.get("result_versions", []):
        vrows.append([v["version"], _fmt(v["created_at"]), v["algorithm_version"], v["overall_status"], str(v["degraded"]), Paragraph(v["input_hash"][:24] + "…", mono)])
    el.append(table(vrows, [W * 0.08, W * 0.17, W * 0.14, W * 0.2, W * 0.1, W * 0.31]))

    el.append(Paragraph("6. Analyst decisions (immutable)", h2))
    if bundle.get("reviews"):
        rrows = [["When", "Analyst", "Decision", "Vessel", "Reason codes", "Notes"]]
        for r in bundle["reviews"]:
            rrows.append([_fmt(r["created_at"]), f"{r.get('analyst')}{' (' + r['analyst_role'] + ')' if r.get('analyst_role') else ''}", r["decision"], _fmt(r.get("vessel_mmsi")), ", ".join(r.get("reason_codes") or []), r.get("notes") or ""])
        el.append(table(rrows, [W * 0.14, W * 0.18, W * 0.1, W * 0.1, W * 0.2, W * 0.28]))
    else:
        el.append(Paragraph("No analyst decisions recorded.", body))

    el.append(Paragraph("7. Audit history", h2))
    arows = [["When", "Actor", "Action", "Entity", "Payload"]]
    for e in bundle.get("audit_history", [])[-60:]:
        arows.append([_fmt(e["created_at"]), e["actor"], e["action"], f"{e['entity_type']} {e['entity_id'][:8]}", Paragraph(str(e.get("payload", {}))[:220], small)])
    el.append(table(arows, [W * 0.14, W * 0.18, W * 0.16, W * 0.16, W * 0.36]))

    if bundle.get("attachments"):
        el.append(Paragraph("8. Attached source imagery & evidence files", h2))
        frows = [["Uploaded", "Kind", "File", "Caption", "By", "Size"]]
        for a in bundle["attachments"]:
            frows.append([_fmt(a["created_at"]), a["kind"], a["original_filename"], a.get("caption") or "—", a["uploaded_by"], f"{a['size'] / 1024:.0f} KB"])
        el.append(table(frows, [W * 0.14, W * 0.12, W * 0.24, W * 0.24, W * 0.18, W * 0.08]))
        for img in bundle.get("attachment_images", []):
            if not img.get("bytes"):
                el.append(Paragraph(f"{img['caption']} — {img['meta']}", small))
                continue
            try:
                pil = PILImage.open(io.BytesIO(img["bytes"]))
                ratio = pil.height / pil.width
                w = W * 0.9
                h = min(w * ratio, 150 * mm)
                el.append(Spacer(1, 6))
                el.append(KeepTogether([Image(io.BytesIO(img["bytes"]), width=h / ratio, height=h), Paragraph(f"<b>{img['caption']}</b> · {img['meta']}", small)]))
            except Exception as e:  # noqa: BLE001
                el.append(Paragraph(f"{img['caption']} — image could not be rendered: {e}", small))
    doc.build(el)
    return buf.getvalue()
