import pandas as pd

# De 8 faste DD-kategoriene fra Fase 2, pluss "Annet/usikker"
ALLE_KATEGORIER = [
    "Selskapsdokumenter",
    "Finansielle dokumenter",
    "Ansettelse/HR",
    "Immaterielle rettigheter",
    "Kommersielle avtaler",
    "Eiendom/leieavtaler",
    "Tvister",
    "Regulatorisk/compliance",
    "Annet/usikker",
]

df = pd.read_csv("contracts_klassifisert.csv")

funnet = set(df["modell_kategori"].dropna().unique())
mangler = [k for k in ALLE_KATEGORIER if k not in funnet]

print("Kategorier funnet i dokumentbunken:")
for k in ALLE_KATEGORIER:
    antall = (df["modell_kategori"] == k).sum()
    status = f"{antall} dokumenter" if antall > 0 else "INGEN DOKUMENTER FUNNET"
    print(f"  - {k}: {status}")

print()
if mangler:
    print("Manglende kategorier i denne dokumentbunken:")
    for k in mangler:
        print(f"  Ingen dokumenter funnet i kategorien {k}")
else:
    print("Alle kategorier er representert i dokumentbunken.")