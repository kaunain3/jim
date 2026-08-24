import asyncio
from pathlib import Path

from services.extractor import extractor


async def main() -> None:
    pdf_path = Path("sample.pdf")

    result = await extractor.extract(
        pdf_path,
        use_ocr=False,
    )

    for section in result.sections:
        print(f"Page: {section.page}")
        print(f"Heading: {section.heading}")
        print(section.text)
        print("---")


if __name__ == "__main__":
    asyncio.run(main())