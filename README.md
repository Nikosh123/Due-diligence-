# Datarom — AI-dokumentklassifiserer for due diligence

En Streamlit-app som sorterer en dokumentbunke (PDF, DOCX, TXT) inn i ni faste due diligence-kategorier ved hjelp av Claude (Anthropic). Ingen egen modell er trent — klassifiseringen skjer gjennom prompting av en ferdig språkmodell. Bygget med Claude som utviklingsverktøy, fra første versjon til feilsøking og testing.

## Hvordan modellen fungerer

For hvert dokument sender appen enten uttrukket tekst eller selve PDF-filen til Claude sammen med en prompt som definerer de ni kategoriene og klassifiseringsreglene. Modellen returnerer:

- én primærkategori, valgt ut fra en hovedformål-test (hva dokumentet ER i sin kjerne)
- inntil to sekundærkategorier, valgt ut fra en materialitetstest (om en spesialist på det andre temaet faktisk ville trengt å se dokumentet)
- et konfidensnivå (høy/middels/lav)
- en kort begrunnelse (modellens resonnement bak valget — brukes i testscriptene for å vurdere feilklassifiseringer, men vises foreløpig ikke i appens resultattabell)

Kategoriene er: Selskapsdokumenter, Finansielle dokumenter, Ansettelse/HR, Immaterielle rettigheter, Kommersielle avtaler, Eiendom/leieavtaler, Tvister, Regulatorisk/compliance, og Annet/usikker som fallback. Full definisjon av hver kategori og grensene mellom dem ligger i `KATEGORI_BESKRIVELSER` og `SYSTEMREGLER` i `klassifiser.py`.

Resultatet vises i en tabell med fargekodet konfidens, og kan lastes ned som CSV eller som en ZIP der filene er sortert i mapper per kategori. En sjekkliste viser hvilke av de ni kategoriene som er representert i bunken.

### Tekstuttrekk fra dokumenter

`.docx` og `.txt` leses direkte. For PDF brukes `pypdf` til å trekke ut tekstlaget. Hvis tekstuttrekket gir under 10 tegn per side (skannede/bildebaserte PDF-er uten tekstlag), sendes PDF-filen i stedet direkte til Claude som et "document"-innholdsblokk, slik at modellen leser sidene visuelt. Claudes PDF-støtte har en grense på 100 sider / 32MB per forespørsel, så skannede PDF-er over 25 sider kuttes til de første 25 sidene før de sendes, med videre nedskalering hvis selv det første utdraget blir for stort i MB.

## Steg i utviklingen

1. Definerte de ni kategoriene og klassifiseringsreglene (hovedformål-test, materialitetstest) i `klassifiser.py`.
2. Bygget `app.py` med filopplasting, tekstuttrekk og resultattabell i Streamlit.
3. Evaluerte klassifiseringen mot CUAD (et offentlig datasett med reelle amerikanske kommersielle kontrakter).
4. Bygget et eget norsk testsett for å verifisere klassifisering på norskspråklige dokumenter.
5. Identifiserte at tekstuttrekk fra skannede PDF-er ga tilnærmet null tegn, og la til fallback der PDF-filen sendes direkte til Claude i stedet for uttrukket tekst.
6. La til sidebegrensning (25 sider) for å holde skannede PDF-er innenfor Claudes grense på 100 sider / 32MB per forespørsel, med ytterligere nedskalering ved behov og tydelig feilmelding for krypterte PDF-er.

## Oppsett

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # streamlit, anthropic, pypdf, cryptography, python-docx, pandas, openpyxl
```

Sett API-nøkkelen enten som miljøvariabel (`ANTHROPIC_API_KEY`) eller i `.streamlit/secrets.toml`:

```
ANTHROPIC_API_KEY = "sk-ant-..."
```

## Kjøre appen

```
streamlit run app.py
```

## Prøvedokumenter

Mappen `eksempeldokumenter/` inneholder ti PDF-er fra det norske testsettet. Knappen «Kjør prøvedokumentene» over opplastingsfeltet klassifiserer dem uten at brukeren laster opp noe. Egne opplastede filer erstatter prøvedokumentene.

## Publisering (Streamlit Community Cloud)

Appen publiseres fra GitHub-repoet med `app.py` som hovedfil. API-nøkkelen legges inn under Secrets i Streamlit (`ANTHROPIC_API_KEY = "..."`) og skal ikke ligge i repoet. `.streamlit/secrets.toml` er i `.gitignore`.

Ved endringer i `klassifiser.py` mens appen kjører: stopp prosessen (Ctrl+C) og start den på nytt. Streamlit kjører `app.py` på nytt automatisk ved lagring, men reimporterer ikke moduler som allerede er lastet inn i samme prosess.

## Testing

Klassifiseringen er testet underveis i utviklingen mot et selvbygget norsk testsett (40 dokumenter, fasit i `Norsk DD test.xlsx`). Siste målte treffsikkerhet: **92,5 % (37/40)**.

Kategoriseringslogikken er ikke norsk-spesifikk — samme hovedformål- og materialitetstest brukes uansett språk — så engelskspråklige dokumenter forventes å ha sammenlignbar treffsikkerhet, men dette er ikke verifisert mot dagens kode.

De tre avvikene gjaldt alle dokumenter fasiten merket "Annet/usikker". Gjennomgang av dokumentene i ettertid viser at to av tre har et rimelig argument for modellens valgte kategori:
- Måsøval AS strategi.pdf (modell: Selskapsdokumenter) — gjelder direkte eierstrukturen i selskapet, og treffer kjerneformål-definisjonen av Selskapsdokumenter direkte.
- Telenor kvartal strategi.pdf (modell: Finansielle dokumenter) — er i hovedsak en kvartalsresultatpresentasjon; "strategi" i filnavnet viser til utsiktsdelen, som er én av flere seksjoner.
- EAM informasjonsmøte.pdf (modell: Finansielle dokumenter) — dekker genuint flere kjernetema i ett dokument (selskapsstatus, finansiell/operasjonell status, tvistestatus og generalforsamling), så "Annet/usikker" er her en like rimelig vurdering som modellens valg.

## Begrensninger

- Kategoritaksonomien er bygget for M&A-/transaksjons-due diligence og dekker ikke alle dokumenttyper som kan forekomme i et datarom.
- Skannede PDF-er over 25 sider blir kuttet før klassifisering — informasjon lenger ut i dokumentet blir ikke vurdert.
- Ingen dokumenter lagres; alt skjer i minnet for den aktive økten.
- Dokumentene sendes til Claude (Anthropic) via API; appen viser derfor et varsel om ikke å laste opp konfidensielle dokumenter.
- Konfidensnivået er modellens egen vurdering ut fra instruksjonene i prompten, ikke en uavhengig eller kalibrert sannsynlighet — modellen vurderer i praksis sin egen klassifisering.

## Mappestruktur

```
app.py              # Streamlit-grensesnittet
klassifiser.py       # Klassifiseringslogikk (kategorier, prompt, Claude-kall)
categories.py / Sjekk.py / sjekkliste.py / DD.py / build_contracts_csv.py  # støtteskript
data/                # testdokumenter
kjor_siste_test.py   # frittstående script for å kjøre nøyaktighetsmåling mot det norske testsettet
```

## Gjenstående opprydding

- `app.py.bak_*` og `klassifiser.py.bak_*` er sikkerhetskopier fra feilsøking — kan slettes.
