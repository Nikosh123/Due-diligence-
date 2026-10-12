import anthropic
import json
import re
import base64
import pandas as pd

KATEGORI_BESKRIVELSER = """
Selskapsdokumenter: Kjerneformål: dokumentet handler om selskapets formelle eksistens og eierstruktur — stiftelsesdokumenter, vedtekter, aksjeeierbok, generalforsamlingsprotokoller, firmaattest/enhetsregister-utskrift. Grenser ofte mot: Finansielle dokumenter (tallmateriale) og Regulatorisk/compliance (tillatelser) — bruk hovedformål-testen.

Finansielle dokumenter: Kjerneformål: dokumentet gir tallmateriale om selskapets økonomiske stilling — årsregnskap, revisjonsberetninger, budsjetter, låneavtaler med bank. Grenser ofte mot: Kommersielle avtaler — en kontrakt har nesten alltid en pris, det gjør den ikke finansiell.

Ansettelse/HR: Kjerneformål: dokumentet regulerer forholdet mellom selskapet som arbeidsgiver og dets ansatte — individuelle arbeidsavtaler, tariff-/hovedavtaler, personalhåndbøker, pensjons- og bonusordninger, sluttavtaler. Grenser ofte mot: Kommersielle avtaler (innleide oppdragstakere er kommersielle, ikke ansatte) og Regulatorisk/compliance (HMS-dokumenter kan gå begge veier — bruk materialitetstesten).

Immaterielle rettigheter: Kjerneformål: dokumentet gjelder eierskap til eller bruksrett til en beskyttet rettighet — patenter, varemerkeregistreringer, designregistreringer, og lisensavtaler der selve IP-rettigheten er hovedytelsen. Grenser ofte mot: Kommersielle avtaler — en vanlig leveranseavtale som bare nevner et produktnavn er ikke IP; dukker ofte opp som sekundærkategori når en kommersiell avtale har en forhandlet IP-lisens.

Kommersielle avtaler: Kjerneformål: dokumentet regulerer kjøp, salg eller løpende leveranse av varer/tjenester mellom selskapet og en annen virksomhet — kunde- og leverandøravtaler, rammeavtaler, distribusjonsavtaler, IT-/tjenesteavtaler. Grenser ofte mot: Eiendom/leieavtaler (leieavtaler går alltid dit) og Immaterielle rettigheter (hvis IP-lisensen er hovedytelsen).

Eiendom/leieavtaler: Kjerneformål: fast eiendom er selve gjenstanden for avtalen eller dokumentet — leiekontrakter (bolig eller næring), skjøter, grunnboksutskrifter, reguleringsplaner. Grenser ofte mot: Kommersielle avtaler, men eiendom vinner alltid her, selv om leieforholdet i prinsippet er en type kommersiell avtale.

Tvister: Kjerneformål: dokumentet handler om en pågående eller avsluttet rettslig konflikt der selskapet er part — søksmål, voldgiftssaker, forlik, rettsavgjørelser. Grenser ofte mot: Regulatorisk/compliance — selve tillatelsen/pålegget hører dit, en uenighet/klage om vedtaket hører hit.

Regulatorisk/compliance: Kjerneformål: dokumentet gjelder en tillatelse, konsesjon eller et lovpålagt krav for lovlig drift — utslippstillatelser, driftskonsesjoner, sertifiseringer, interne compliance-retningslinjer (f.eks. personvern, antikorrupsjon). Grenser ofte mot: Tvister (hvis det beskriver en konflikt om vedtaket) og Ansettelse/HR (HMS kan gå begge veier).

Annet/usikker: Brukes når dokumentet ikke passer klart inn i noen av de andre kategoriene, eller du er usikker på hvilken kategori som passer best — bedre å flagge usikkerhet enn å tvinge frem en gjetning.
"""

SYSTEMREGLER = """
Primærkategori – hovedformål-testen: hva ER dette dokumentet, i sin kjerne, hvis du må beskrive det i én setning? Velg ÉN kategori ut fra det, uansett hvor mange tema dokumentet ellers berører.

Sekundærkategori(er) – materialitetstesten: ville en spesialist på det andre temaet faktisk trengt å se dette dokumentet for å gjøre jobben sin? Bare da teller det som en sekundærkategori. Maks to sekundærkategorier.

Ignorer standardklausuler som finnes i nesten alle kontrakter uansett type (force majeure, lovvalg, verneting, generell taushetsplikt) – de er ikke substansielle nok til å utløse en sekundærkategori.

"Annet/usikker" er reservert for "passer INGEN steder" – aldri for "passer for mange steder", det er nettopp det sekundærkategoriene er til for.
"""

KONFIDENSREGLER = """
Konfidensnivået skal gjenspeile hvor sikker du faktisk er på klassifiseringen, ikke et generelt inntrykk:

Høy: Primærkategorien er entydig ut fra tittel, struktur eller hovedklausuler alene, uten reell konkurranse fra andre kategorier. For "Annet/usikker" gjelder høy kun når det er klart hva dokumentet ER, og like klart at ingen av de åtte andre kategoriene dekker det.

Middels: Dokumentet passer godt i kategorien, men har betydelig sekundærinnhold som med rimelighet kunne pekt en annen vei, eller dokumenttypen er uvanlig. For "Annet/usikker" gjelder middels når du kan beskrive hva dokumentet er, men det er reelt tvilsomt om noen kategori dekker det.

Lav: Genuint tvetydig mellom to eller flere kategorier. Lav gjelder også – uavhengig av kategori – når det uttrukne innholdet er for sparsomt, tomt eller uleselig til å vurdere i det hele tatt. I så fall skal begrunnelsen si eksplisitt at innholdet mangler eller er utilstrekkelig, ikke late som om en vurdering er gjort.
"""

SVARFORMAT = """Svar KUN med gyldig JSON i dette formatet, uten noe annen tekst før eller etter:
{"kategori": "...", "sekundærkategorier": [...], "konfidens": "høy/middels/lav", "begrunnelse": "..."}"""


def lag_prompt(kontrakt_tekst: str) -> str:
    return f"""Du er en jurist som gjør due diligence og skal kategorisere dokumenter.

KATEGORIER:
{KATEGORI_BESKRIVELSER}

REGLER FOR FLERE KATEGORIER:
{SYSTEMREGLER}

REGLER FOR KONFIDENSNIVÅ:
{KONFIDENSREGLER}

{SVARFORMAT}

DOKUMENT SOM SKAL KLASSIFISERES:
{kontrakt_tekst}
"""


def lag_prompt_for_pdf_vedlegg() -> str:
    # Brukes når selve PDF-filen sendes med som et "document"-innholdsblokk
    # (f.eks. skannede/bildebaserte årsregnskap uten tekstlag). Modellen leser
    # da dokumentet visuelt/via OCR selv, i stedet for at vi sender ferdig
    # uttrukket tekst.
    return f"""Du er en jurist som gjør due diligence og skal kategorisere dokumenter.

KATEGORIER:
{KATEGORI_BESKRIVELSER}

REGLER FOR FLERE KATEGORIER:
{SYSTEMREGLER}

REGLER FOR KONFIDENSNIVÅ:
{KONFIDENSREGLER}

{SVARFORMAT}

DOKUMENTET SOM SKAL KLASSIFISERES ER VEDLAGT HER SOM PDF (det er skannet/bildebasert, uten tekstlag — les sidene visuelt, inkludert tabeller og tall, før du svarer).
"""


client = anthropic.Anthropic()  # leser nøkkelen automatisk fra miljøvariabelen ANTHROPIC_API_KEY


def klassifiser(kontrakt_tekst: str = None, pdf_bytes: bytes = None) -> dict:
    """Klassifiserer et dokument.

    Vanligvis sendes uttrukket tekst (kontrakt_tekst). Hvis dokumentet er en
    skannet/bildebasert PDF der tekstuttrekk ikke ga noe brukbart (se
    app.py sin terskel-sjekk), sendes i stedet selve PDF-filen (pdf_bytes) som
    et "document"-innholdsblokk, slik at modellen leser den visuelt selv.
    """
    if pdf_bytes is not None:
        b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        innhold = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": b64,
                },
            },
            {"type": "text", "text": lag_prompt_for_pdf_vedlegg()},
        ]
    else:
        innhold = lag_prompt(kontrakt_tekst or "")

    svar = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": innhold}]
    )
    tekst_svar = "".join(
        block.text for block in svar.content if block.type == "text"
    ).strip()

    if not tekst_svar:
        raise RuntimeError(f"Modellen ga ikke noe tekstsvar (stop_reason={svar.stop_reason})")

    # Modellen pakker noen ganger svaret i en ```json ... ```-blokk, til tross for
    # instruksen om å svare med kun JSON. Hent ut selve {...}-delen uansett hva
    # som måtte stå rundt den.
    match = re.search(r"\{.*\}", tekst_svar, re.DOTALL)
    if not match:
        raise RuntimeError(f"Fant ingen JSON i svaret: {tekst_svar!r}")

    return json.loads(match.group(0))


if __name__ == "__main__":
    kontrakter = pd.read_csv("contracts_klassifisert.csv")

    mangler = kontrakter["modell_kategori"].isna() | kontrakter["modell_begrunnelse"].astype(str).str.startswith("FEIL:")
    print(f"{mangler.sum()} av {len(kontrakter)} kontrakter mangler fortsatt et gyldig svar.")

    for i, rad in kontrakter[mangler].iterrows():
        print(f"({i + 1}/{len(kontrakter)}) {rad['filnavn']}")
        try:
            resultat = klassifiser(rad["tekst"])
            kontrakter.at[i, "modell_kategori"] = resultat.get("kategori")
            kontrakter.at[i, "modell_sekundaerkategorier"] = ", ".join(resultat.get("sekundærkategorier", []))
            kontrakter.at[i, "modell_konfidens"] = resultat.get("konfidens")
            kontrakter.at[i, "modell_begrunnelse"] = resultat.get("begrunnelse")
        except Exception as exc:
            print("  FEIL:", exc)
            kontrakter.at[i, "modell_begrunnelse"] = f"FEIL: {exc}"

        kontrakter.to_csv("contracts_klassifisert.csv", index=False)  # lagrer underveis, rad for rad

    print("Ferdig.")
    kontrakter = pd.read_csv("contracts_delt.csv")

    kategorier = []
    sekundaere = []
    konfidenser = []
    begrunnelser = []

    for i, rad in kontrakter.iterrows():
        print(f"({i + 1}/{len(kontrakter)}) {rad['filnavn']}")
        try:
            resultat = klassifiser(rad["tekst"])
            kategorier.append(resultat.get("kategori"))
            sekundaere.append(", ".join(resultat.get("sekundærkategorier", [])))
            konfidenser.append(resultat.get("konfidens"))
            begrunnelser.append(resultat.get("begrunnelse"))
        except Exception as exc:
            print("  FEIL:", exc)
            kategorier.append(None)
            sekundaere.append(None)
            konfidenser.append(None)
            begrunnelser.append(f"FEIL: {exc}")

    kontrakter["modell_kategori"] = kategorier
    kontrakter["modell_sekundaerkategorier"] = sekundaere
    kontrakter["modell_konfidens"] = konfidenser
    kontrakter["modell_begrunnelse"] = begrunnelser

    kontrakter.to_csv("contracts_klassifisert.csv", index=False)
    print("Ferdig. Lagret som contracts_klassifisert.csv")
