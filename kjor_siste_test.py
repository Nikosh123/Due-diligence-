"""
Siste nøyaktighetsmåling mot det norske testsettet (Norsk DD test.xlsx).

Kjøres direkte i terminalen (IKKE gjennom Claude/Cowork-broen — den bruker en
nettverksproxy som blokkerer POST-kall til api.anthropic.com):

    source .venv/bin/activate
    python3 kjor_siste_test.py

Klassifiserer alle PDF-ene i data/norsk/ med den faktiske klassifiser.py (samme
kode som app.py bruker), sammenligner mot fasiten i "Norsk DD test.xlsx", og
skriver ut endelig treffsikkerhet. Resultatet lagres også som
siste_nokyaktighet_resultat.csv.
"""
import os, sys, io, time, unicodedata, difflib
import pypdf
from pypdf.errors import DependencyError
import pandas as pd
import openpyxl

PROJECT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

if "ANTHROPIC_API_KEY" not in os.environ:
    try:
        import toml
        with open(os.path.join(PROJECT, ".streamlit", "secrets.toml")) as f:
            secrets = toml.load(f)
        os.environ["ANTHROPIC_API_KEY"] = secrets["ANTHROPIC_API_KEY"]
    except Exception as exc:
        sys.exit(f"Fant ikke ANTHROPIC_API_KEY (verken i miljøet eller .streamlit/secrets.toml): {exc}")

from klassifiser import klassifiser

MIN_TEGN_PER_SIDE = 10
MAKS_SIDER_FOR_PDF_VEDLEGG = 25
MAKS_BYTES_FOR_PDF_VEDLEGG = 20 * 1024 * 1024


def bygg_pdf_utdrag(leser, antall_sider):
    skriver = pypdf.PdfWriter()
    for j in range(antall_sider):
        skriver.add_page(leser.pages[j])
    buffer = io.BytesIO()
    skriver.write(buffer)
    return buffer.getvalue()


def trekk_ut_innhold(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        leser = pypdf.PdfReader(io.BytesIO(raw))
        sider = len(leser.pages) or 1
        tekst = "\n".join(side.extract_text() or "" for side in leser.pages)
    except DependencyError as exc:
        raise RuntimeError(f"Kryptert PDF uten cryptography-pakke: {exc}") from exc
    tegn_per_side = len(tekst.strip()) / sider
    if tegn_per_side < MIN_TEGN_PER_SIDE:
        sider_sendt = min(sider, MAKS_SIDER_FOR_PDF_VEDLEGG)
        pdf_data = bygg_pdf_utdrag(leser, sider_sendt) if sider_sendt < sider else raw
        while len(pdf_data) > MAKS_BYTES_FOR_PDF_VEDLEGG and sider_sendt > 1:
            sider_sendt = max(1, sider_sendt // 2)
            pdf_data = bygg_pdf_utdrag(leser, sider_sendt)
        if len(pdf_data) > MAKS_BYTES_FOR_PDF_VEDLEGG:
            raise RuntimeError(f"PDF for stor selv med 1 side ({len(pdf_data)/1e6:.1f}MB)")
        return {"type": "pdf_bytes", "verdi": pdf_data}
    return {"type": "tekst", "verdi": tekst}


def main():
    data_dir = os.path.join(PROJECT, "data", "norsk")
    filer = sorted(f for f in os.listdir(data_dir) if f.lower().endswith(".pdf"))
    print(f"Klassifiserer {len(filer)} dokumenter ...")

    resultater = {}
    for i, navn in enumerate(filer):
        t0 = time.time()
        try:
            innhold = trekk_ut_innhold(os.path.join(data_dir, navn))
            if innhold["type"] == "pdf_bytes":
                resultat = klassifiser(pdf_bytes=innhold["verdi"])
            else:
                resultat = klassifiser(innhold["verdi"])
            resultater[navn] = resultat.get("kategori")
            status = resultat.get("kategori")
        except Exception as exc:
            resultater[navn] = "Feil"
            status = f"FEIL: {exc}"
        print(f"  [{i+1}/{len(filer)}] {navn} -> {status}  ({time.time()-t0:.1f}s)")

    pd.DataFrame(
        [{"Filnavn": k, "Kategori": v} for k, v in resultater.items()]
    ).to_csv("siste_nokyaktighet_resultat.csv", index=False)

    # ---- sammenlign mot fasit ----
    wb = openpyxl.load_workbook("Norsk DD test.xlsx", data_only=True)
    ws = wb["Sheet1"]
    fasit = {}
    for row in ws.iter_rows(min_row=4, values_only=True):
        navn, kat = row[1], row[2]
        if navn and kat:
            fasit[unicodedata.normalize("NFC", navn.strip())] = kat.strip()

    def norm_kat(k):
        repl = {
            "Ansettelse/ HR": "Ansettelse/HR",
            "Eiendom/ leieavtaler": "Eiendom/leieavtaler",
            "Imatrielle rettigheter (IP)": "Immaterielle rettigheter",
            "Regulatorisk/ Compliance": "Regulatorisk/compliance",
        }
        return repl.get(k.strip(), k.strip())

    fasit = {k: norm_kat(v) for k, v in fasit.items()}
    modell = {unicodedata.normalize("NFC", k.strip()): v for k, v in resultater.items()}

    manuell = {"Nye Aker sykehus.pdf": "Nye Aker sykehus tillatelse.pdf"}
    riktige, totalt, avvik = 0, 0, []
    for fn, fasit_kat in fasit.items():
        match = fn if fn in modell else manuell.get(fn) if manuell.get(fn) in modell else None
        if not match:
            close = difflib.get_close_matches(fn, modell.keys(), n=1, cutoff=0.8)
            match = close[0] if close else None
        if not match:
            print(f"  (ingen treff i resultatet for '{fn}' — hoppet over)")
            continue
        totalt += 1
        modell_kat = modell[match]
        if modell_kat == fasit_kat:
            riktige += 1
        else:
            avvik.append((fn, fasit_kat, modell_kat))

    print()
    print(f"ENDELIG TREFFSIKKERHET: {riktige}/{totalt} = {100*riktige/totalt:.1f}%")
    if avvik:
        print("Avvik:")
        for fn, fk, mk in avvik:
            print(f"  {fn}: fasit={fk!r}  modell={mk!r}")


if __name__ == "__main__":
    main()
