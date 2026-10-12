"""
Leser inn kontrakttekster fra to kilder og samler dem i contracts.csv:

- data/cuad/*.txt      (CUAD-datasettet, allerede rentekst)
- data/norsk/*.pdf      (norske testdokumenter, PDF)
- data/norsk/*.docx     (norske testdokumenter, Word)

Kjør med: python3 build_contracts_csv.py
"""

import pandas as pd
from pathlib import Path
import pdfplumber
from docx import Document


def les_pdf(sti):
    tekst = ""
    with pdfplumber.open(sti) as pdf:
        for side in pdf.pages:
            tekst += (side.extract_text() or "") + "\n"
    return tekst


def les_docx(sti):
    dok = Document(sti)
    return "\n".join(avsnitt.text for avsnitt in dok.paragraphs)


def main():
    rader = []

    # CUAD - txt-filer
    for fil in Path("data/cuad").glob("*.txt"):
        rader.append({"filnavn": fil.name, "tekst": fil.read_text(encoding="utf-8")})

    # Norske testdokumenter - pdf og docx
    for fil in Path("data/norsk").glob("*.pdf"):
        rader.append({"filnavn": fil.name, "tekst": les_pdf(fil)})

    for fil in Path("data/norsk").glob("*.docx"):
        rader.append({"filnavn": fil.name, "tekst": les_docx(fil)})

    tabell = pd.DataFrame(rader)
    tabell.to_csv("contracts.csv", index=False)
    print(f"Skrev {len(tabell)} rader til contracts.csv")


if __name__ == "__main__":
    main()
