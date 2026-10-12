import os
import streamlit as st
import pandas as pd
import zipfile
import io
import pypdf
from pypdf.errors import DependencyError
from docx import Document

if "ANTHROPIC_API_KEY" in st.secrets:
    os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]

from klassifiser import klassifiser

ALLE_KATEGORIER = [
    "Selskapsdokumenter", "Finansielle dokumenter", "Ansettelse/HR",
    "Immaterielle rettigheter", "Kommersielle avtaler", "Eiendom/leieavtaler",
    "Tvister", "Regulatorisk/compliance", "Annet/usikker",
]

# Terskel for å anse en PDF som skannet/bildebasert: for lite tekst per side
# til at klassifiseringen har noe å jobbe med. Vanlige tekst-PDF-er ligger på
# hundrevis til tusenvis av tegn per side; skannede årsregnskap uten OCR-lag
# ligger typisk på 0.
MIN_TEGN_PER_SIDE = 10

# Claude sin PDF-grense er 100 sider per forespørsel (for modeller med under 1M
# tokens kontekstvindu), og 32MB i forespørselsstørrelse. Skannede årsregnskap kan
# ha hundrevis av sider, men for klassifiseringsformål holder det rikelig med de
# første sidene (forside, resultatregnskap, balanse) — vi kutter med god margin
# for å unngå å treffe side-/størrelsesgrensen og for å holde kostnaden nede.
MAKS_SIDER_FOR_PDF_VEDLEGG = 25

# Grensen over gjelder bare antall sider. Noen skannede dokumenter har så
# høyoppløselige sider at selv et lite antall sider blir for mange MB — Claude sin
# grense på 32MB per forespørsel gjelder HELE forespørselen, og PDF-en sendes
# base64-kodet (øker størrelsen med ca. 33%). Vi holder oss derfor til 20MB rå
# PDF-størrelse (blir ca. 27MB i base64, med margin til resten av prompten).
MAKS_BYTES_FOR_PDF_VEDLEGG = 20 * 1024 * 1024

# ---------- Styling ----------
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;1,500&family=Public+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"] { font-family: 'Public Sans', sans-serif; }
h1, h2, h3 { font-family: 'Playfair Display', Georgia, serif !important; }
.block-container { max-width: 860px; padding-top: 2rem; }
.stButton button, .stDownloadButton button { background-color: #26302A; color: white; border-radius: 8px; font-weight: 600; }

/* Filopplasting - bare boksen stylet, ikke indre tekst/knapper (det var det som krasjet siden) */
[data-testid="stFileUploaderDropzone"] {
    border: 1px solid #DAD5C6 !important;
    border-radius: 10px !important;
    background: #F3F1EA !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown(
    "<div style='text-align:center'>"
    "<div style='font-family: Playfair Display, serif; font-style: italic; font-size: 26px; color:#26302A;'>Nikolai's</div>"
    # Bevisst en <div> og ikke en <h1>: Streamlit gjenkjenner <h1>-<h6> i
    # unsafe_allow_html-markdown og pakker dem automatisk inn i en egen
    # wrapper med et anker-lenke-ikon etter teksten. Ikonet er en del av den
    # sentrerte blokken og drar dermed selve "Datarom"-teksten synlig til
    # venstre for midten. En vanlig <div> med samme skrift/vekt/størrelse
    # får ikke denne wrapperen og sentreres korrekt.
    "<div style='font-size:56px; font-weight:700; font-family: \"Playfair Display\", Georgia, serif; letter-spacing:-0.01em; color:#26302A;'>Datarom</div>"
    "<p style='color:#6B7268;'>AI-basert dokumentklassifisering for due diligence. "
    "Last opp en dokumentbunke og få den sortert i kategorier, med varsel om hva som mangler.</p>"
    "</div>",
    unsafe_allow_html=True,
)


def _bygg_pdf_utdrag(leser, antall_sider):
    """Bygger en ny PDF med de første `antall_sider` sidene fra `leser`."""
    skriver = pypdf.PdfWriter()
    for j in range(antall_sider):
        skriver.add_page(leser.pages[j])
    buffer = io.BytesIO()
    skriver.write(buffer)
    return buffer.getvalue()


def trekk_ut_innhold(fil):
    """Finner ut hva som skal sendes til klassifiseringen for én opplastet fil.

    Returnerer en dict: {"type": "tekst", "verdi": str} for vanlige
    tekstbaserte dokumenter, eller {"type": "pdf_bytes", "verdi": bytes,
    "sider": int} for PDF-er der tekstuttrekket ga for lite til at modellen
    har noe å jobbe med (typisk skannede/bildebaserte dokumenter, f.eks.
    årsregnskap uten tekstlag). I det siste tilfellet sendes selve PDF-filen
    til Claude, som da leser sidene visuelt/via OCR selv.
    """
    navn = fil.name.lower()
    if navn.endswith(".pdf"):
        raw = fil.getvalue()
        try:
            leser = pypdf.PdfReader(io.BytesIO(raw))
            sider = len(leser.pages) or 1
            tekst = "\n".join(side.extract_text() or "" for side in leser.pages)
        except DependencyError as exc:
            raise RuntimeError(
                f"PDF-en er kryptert og mangler en pakke for å lese den ('{exc}'). "
                f"Kjør 'pip install cryptography' i terminalen og start appen på nytt."
            ) from exc
        tegn_per_side = len(tekst.strip()) / sider
        if tegn_per_side < MIN_TEGN_PER_SIDE:
            sider_sendt = min(sider, MAKS_SIDER_FOR_PDF_VEDLEGG)
            pdf_data = _bygg_pdf_utdrag(leser, sider_sendt) if sider_sendt < sider else raw

            # Sjekk faktisk størrelse, ikke bare sidetall — høyoppløselige skann kan
            # være for store i MB selv med få sider. Halver sidetallet til vi er under
            # grensen, eller gi opp med en tydelig feilmelding fremfor en kryptisk
            # 400-feil fra Claude sin API.
            while len(pdf_data) > MAKS_BYTES_FOR_PDF_VEDLEGG and sider_sendt > 1:
                sider_sendt = max(1, sider_sendt // 2)
                pdf_data = _bygg_pdf_utdrag(leser, sider_sendt)

            if len(pdf_data) > MAKS_BYTES_FOR_PDF_VEDLEGG:
                raise RuntimeError(
                    f"PDF-en er for stor til å sendes til Claude selv med bare 1 side "
                    f"({len(pdf_data) / 1e6:.1f}MB) — sannsynligvis svært høyoppløselige "
                    f"skannede sider."
                )

            return {"type": "pdf_bytes", "verdi": pdf_data, "sider": sider, "sider_sendt": sider_sendt}
        return {"type": "tekst", "verdi": tekst}
    elif navn.endswith(".docx"):
        dok = Document(fil)
        return {"type": "tekst", "verdi": "\n".join(avsnitt.text for avsnitt in dok.paragraphs)}
    elif navn.endswith(".txt"):
        return {"type": "tekst", "verdi": fil.read().decode("utf-8", errors="ignore")}
    return {"type": "tekst", "verdi": ""}


# ---------- Opplasting ----------
# file_uploader husker filene sine basert på "key". For å kunne tømme hele
# opplastingen med ett klikk (i stedet for å måtte trykke x på hver fil), gir
# vi den en ny key hver gang "Fjern alle filer" trykkes — det tvinger
# Streamlit til å lage en helt ny, tom opplaster i stedet for å beholde de
# gamle filene.
if "opplastings_nokkel" not in st.session_state:
    st.session_state["opplastings_nokkel"] = 0

opplastede_filer = st.file_uploader(
    "Last opp dokumenter (PDF, TXT eller DOCX)",
    accept_multiple_files=True,
    type=["pdf", "txt", "docx"],
    key=f"filopplaster_{st.session_state['opplastings_nokkel']}",
)

if opplastede_filer:
    if st.button("Fjern alle filer"):
        st.session_state["opplastings_nokkel"] += 1
        st.session_state.pop("klassifisering_signatur", None)
        st.session_state.pop("klassifisering_resultater", None)
        st.rerun()


def fil_signatur(filer):
    """En enkel 'fingeravtrykk' av det opplastede filsettet (navn + størrelse per
    fil), brukt til å avgjøre om vi faktisk trenger å klassifisere på nytt."""
    return tuple((fil.name, fil.size) for fil in filer)


if opplastede_filer:
    signatur = fil_signatur(opplastede_filer)
    antall_filer = len(opplastede_filer)

    # Streamlit kjører hele scriptet på nytt ved enhver interaksjon på siden —
    # også når man trykker en nedlastingsknapp. Uten denne sjekken ville det
    # trigget en helt ny klassifiseringsrunde (nye API-kall til Claude for
    # hvert dokument) bare fordi man lastet ned CSV-en. Vi klassifiserer
    # derfor kun på nytt når filsettet faktisk er endret.
    if st.session_state.get("klassifisering_signatur") != signatur:
        resultater = []
        fremdrift = st.progress(0)
        status = st.empty()

        for i, fil in enumerate(opplastede_filer):
            status.write(f"Analyserer {fil.name} ...")
            try:
                innhold = trekk_ut_innhold(fil)
                if innhold["type"] == "pdf_bytes":
                    if innhold["sider_sendt"] < innhold["sider"]:
                        status.write(
                            f"Analyserer {fil.name} (skannet PDF, {innhold['sider']} sider — "
                            f"viser de {innhold['sider_sendt']} første for Claude) ..."
                        )
                    else:
                        status.write(f"Analyserer {fil.name} (skannet PDF, {innhold['sider']} sider — leses visuelt) ...")
                    resultat = klassifiser(pdf_bytes=innhold["verdi"])
                else:
                    resultat = klassifiser(innhold["verdi"])
                resultater.append({
                    "Filnavn": fil.name,
                    "Kategori": resultat.get("kategori"),
                    "Konfidens": str(resultat.get("konfidens", "")).capitalize(),
                    "Sekundærkategori": ", ".join(resultat.get("sekundærkategorier", [])) or "—",
                })
            except Exception as exc:
                resultater.append({
                    "Filnavn": fil.name,
                    "Kategori": "Feil",
                    "Konfidens": "—",
                    "Sekundærkategori": f"Feil: {exc}",
                })
            fremdrift.progress((i + 1) / antall_filer)

        status.empty()
        fremdrift.empty()

        st.session_state["klassifisering_signatur"] = signatur
        st.session_state["klassifisering_resultater"] = resultater

    resultater = st.session_state["klassifisering_resultater"]

    df = pd.DataFrame(resultater)
    antall_feilet = int((df["Kategori"] == "Feil").sum())
    antall_klassifisert = antall_filer - antall_feilet
    if antall_feilet:
        st.warning(
            f"Klassifisering fullført — {antall_klassifisert} av {antall_filer} "
            f"dokumenter klassifisert, {antall_feilet} feilet (se Sekundærkategori-kolonnen for detaljer)"
        )
    else:
        st.success(f"Klassifisering fullført — {antall_klassifisert} av {antall_filer} dokumenter klassifisert")

    # ---------- Resultattabell ----------
    st.subheader("Klassifisering")

    def lag_zip(filer, kategorier):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for fil, kategori in zip(filer, kategorier):
                mappenavn = str(kategori).replace("/", "-")
                zf.writestr(f"{mappenavn}/{fil.name}", fil.getvalue())
        buffer.seek(0)
        return buffer

    with st.container(horizontal=True, horizontal_alignment="distribute"):
        st.download_button(
            "Last ned tabell (CSV)",
            df.to_csv(index=False).encode("utf-8"),
            "resultat.csv",
            "text/csv",
        )
        st.download_button(
            "Last ned sorterte filer (.zip)",
            lag_zip(opplastede_filer, df["Kategori"]),
            "due_diligence_sortert.zip",
            "application/zip",
        )

    def farge_niva(val):
        stiler = {
            "Høy": "background-color: #E3EFE6; color: #3C6E52; font-weight: 600;",
            "Middels": "background-color: #F5EBD3; color: #8C6A1E; font-weight: 600;",
            "Lav": "background-color: #F3E1DC; color: #8B3F2D; font-weight: 600;",
        }
        return stiler.get(val, "")

    def farge_sekundar(val):
        return "color: #9A9C8E; font-style: italic;"

    visning = df[["Filnavn", "Kategori", "Konfidens", "Sekundærkategori"]].copy()
    visning["Kategori"] = visning["Kategori"].apply(lambda v: [v])
    styled_df = (
        visning.style
        .map(farge_niva, subset=["Konfidens"])
        .map(farge_sekundar, subset=["Sekundærkategori"])
    )
    st.dataframe(
        styled_df,
        hide_index=True,
        alt="Klassifisering av opplastede dokumenter, med kategori og konfidensnivå",
        column_config={
            "Filnavn": st.column_config.TextColumn("Filnavn", width="large"),
            "Kategori": st.column_config.MultiselectColumn(
                "Kategori", options=ALLE_KATEGORIER + ["Feil"], color="auto"
            ),
            "Sekundærkategori": st.column_config.TextColumn("Sekundærkategori", width="large"),
        },
    )

    # ---------- Sjekkliste ----------
    st.subheader("Sjekkliste")

    def parse_sekundaer(verdi):
        if pd.isna(verdi) or str(verdi).strip() in ("", "—"):
            return []
        return [v.strip() for v in str(verdi).split(",") if v.strip()]

    check_svg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4F8F68" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8.5 12.3 2.3 2.3 4.7-4.7"/></svg>'
    advar_svg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#B5760A" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 2.5 18a1.8 1.8 0 0 0 1.6 2.6h15.8a1.8 1.8 0 0 0 1.6-2.6L13.7 3.9a1.8 1.8 0 0 0-3.4 0Z"/></svg>'

    rader = []
    for i, k in enumerate(ALLE_KATEGORIER):
        primaer = int((df["Kategori"] == k).sum())
        sekundaer = int(df["Sekundærkategori"].apply(lambda v: k in parse_sekundaer(v)).sum())
        bg = "#FBFAF6" if i % 2 else "#FFFFFF"
        if primaer > 0 or sekundaer > 0:
            detalj = f"{primaer} som primær" + (f", {sekundaer} som sekundær" if sekundaer else "")
            rader.append(
                f'<div style="display:flex;align-items:center;gap:12px;padding:12px 20px;background:{bg};">'
                f'{check_svg}<span style="font-size:14px;color:#26302A;">{k} — {detalj}</span></div>'
            )
        else:
            rader.append(
                f'<div style="display:flex;align-items:center;gap:12px;padding:12px 20px;background:#FBF2E4;">'
                f'{advar_svg}<span style="font-size:14px;color:#26302A;"><strong>{k}</strong> — ingen dokumenter funnet i denne kategorien</span></div>'
            )

    st.markdown(
        '<div style="border:1px solid #DAD5C6;border-radius:10px;overflow:hidden;">' + "".join(rader) + "</div>",
        unsafe_allow_html=True,
    )

    # ---------- Footer ----------
    st.markdown(
        "<p style='text-align:center; font-size:12.5px; color:#9A9C8E; margin-top:40px;'>"
        "Drevet av Claude (Anthropic) · Dokumenter lagres ikke</p>",
        unsafe_allow_html=True,
    )
