import asyncio
from pathlib import Path
from services.extractor import extractor


async def main():
    pdfs = ["sample1.pdf", "sample2.pdf", "sample3.pdf", "sample4.pdf", "sample5.pdf","sample6.pdf", "sample7.pdf", "sample8.pdf", "sample9.pdf", "sample10.pdf","sample11.pdf", "sample12.pdf", "sample13.pdf", "sample14.pdf", "sample15.pdf","sample16.pdf", "sample17.pdf", "sample18.pdf", "sample19.pdf", "sample20.pdf","sample21.pdf", "sample22.pdf", "sample23.pdf", "sample24.pdf", "sample25.pdf"]
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    for pdf_path in pdfs:
        print(f"Processing {pdf_path}...")
        result = await extractor.extract(
            Path(pdf_path),
            use_ocr=False,
            output_root=output_dir,
        )

        # Build markdown report
        lines = []
        lines.append(f"# Extraction Result: {pdf_path}")
        lines.append("")
        lines.append(f"- Sections: {len(result.sections)}")
        lines.append(f"- Needs review: {result.needs_review}")
        lines.append(f"- Tables: {len(result.tables)}")
        lines.append(f"- Images: {len(result.images)}")
        lines.append("")

        lines.append("## Sections")
        lines.append("")
        for s in result.sections:
            lines.append(f"### {s.heading or '(no heading)'} (page {s.page})")
            lines.append("")
            lines.append(s.text)
            lines.append("")

        if result.tables:
            lines.append("## Tables")
            lines.append("")
            for t in result.tables:
                lines.append(f"### {t.token} (page {t.page})")
                lines.append("")
                lines.append("```markdown")
                lines.append(t.markdown)
                lines.append("```")
                lines.append("")

        if result.images:
            lines.append("## Images")
            lines.append("")
            for img in result.images:
                lines.append(f"- {img.token} (page {img.page}): `{img.path}`")
            lines.append("")

        # Write to file
        stem = Path(pdf_path).stem
        out_path = output_dir / f"{stem}_extracted.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  -> Saved to {out_path}")

    print("\nDone!")


asyncio.run(main())
