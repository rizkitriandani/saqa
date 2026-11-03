import json
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE

def add_hyperlink(paragraph, url: str, text: str, color_rgb: str = "0B57D0", underline: bool = True):
    """Menambahkan tautan hyperlink native ke dalam paragraf WordprocessingML."""
    part = paragraph.part
    r_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)

    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), r_id)

    new_run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')

    if color_rgb:
        c = OxmlElement('w:color')
        c.set(qn('w:val'), color_rgb)
        rPr.append(c)

    if underline:
        u = OxmlElement('w:u')
        u.set(qn('w:val'), 'single')
        rPr.append(u)

    new_run.append(rPr)
    text_elem = OxmlElement('w:t')
    text_elem.text = text
    new_run.append(text_elem)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink

def build_docx_report(metadata_path: Path, drive_video_url: str = None) -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    doc = docx.Document()

    # Margin 1 inci
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # Header Judul
    title = doc.add_heading(f"Laporan Pengujian QA: {meta.get('test_case_id')} - {meta.get('title')}", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # Sub-header / Verdict Badge
    verdict = meta.get("verdict", "UNKNOWN")
    p_verdict = doc.add_paragraph()
    run_label = p_verdict.add_run(f"HASIL PENGUJIAN: {verdict}")
    run_label.bold = True
    run_label.font.size = Pt(14)
    if verdict == "PASSED":
        run_label.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32) # Dark green
    else:
        run_label.font.color.rgb = RGBColor(0xC6, 0x28, 0x28) # Red

    # Informasi Kasus Uji
    doc.add_heading("1. Informasi Eksekusi", level=1)
    table = doc.add_table(rows=7, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = 'Table Grid'

    video_val = drive_video_url if drive_video_url else "(Video tersimpan lokal di artifacts; siap diunggah ke Google Drive)"

    data = [
        ("ID Kasus Uji", meta.get("test_case_id", "-")),
        ("Judul Skenario", meta.get("title", "-")),
        ("Target URL", meta.get("target_url", "-")),
        ("Waktu Eksekusi", meta.get("timestamp", "-")),
        ("Durasi", f"{meta.get('execution_duration_seconds', 0)} detik"),
        ("Status Evaluasi (Verdict)", verdict),
        ("Tautan Bukti Video", video_val)
    ]

    for i, (k, v) in enumerate(data):
        row = table.rows[i]
        row.cells[0].text = k
        row.cells[0].paragraphs[0].runs[0].bold = True
        
        if k == "Tautan Bukti Video" and drive_video_url:
            p_cell = row.cells[1].paragraphs[0]
            p_cell.text = ""
            add_hyperlink(p_cell, drive_video_url, "▶ Buka / Putar Rekaman Video di Drive")
        else:
            row.cells[1].text = str(v)

    # Evaluasi Hasil
    doc.add_heading("2. Hasil Evaluasi & Asersi", level=1)
    doc.add_paragraph(f"Hasil yang Diharapkan: Pengguna berhasil login dan diarahkan ke dashboard Managed Care.")
    p_actual = doc.add_paragraph(f"Hasil Aktual: {meta.get('actual_result', '-')}")
    if meta.get("error_message"):
        p_err = doc.add_paragraph(f"Pesan Error: {meta.get('error_message')}")
        p_err.runs[0].font.color.rgb = RGBColor(0xC6, 0x28, 0x28)

    # Bukti Visual & Langkah
    doc.add_heading("3. Langkah Eksekusi & Bukti Visual", level=1)
    steps = meta.get("steps", [])

    for s in steps:
        step_num = s.get("step_number")
        action = s.get("action")
        notes = s.get("notes", "")
        doc.add_heading(f"Langkah {step_num}: {action}", level=2)
        if notes:
            doc.add_paragraph(f"Keterangan: {notes}")

        sc_rel = s.get("screenshot")
        if sc_rel:
            sc_abs = repo_root / sc_rel
            if sc_abs.exists():
                try:
                    doc.add_paragraph()
                    doc.add_picture(str(sc_abs), width=Inches(5.8))
                    caption = doc.add_paragraph(f"Gambar {step_num}: Tangkapan layar pada langkah {step_num}")
                    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    caption.runs[0].font.size = Pt(9)
                    caption.runs[0].font.italic = True
                except Exception as img_err:
                    doc.add_paragraph(f"[Gagal menyematkan screenshot: {img_err}]")

    output_path = metadata_path.parent / "report.docx"
    doc.save(str(output_path))
    return output_path

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        meta_p = Path(sys.argv[1])
        out = build_docx_report(meta_p)
        print("Generated docx at:", out)
    else:
        print("Usage: python3 docx_builder.py <path_to_metadata.json>")
