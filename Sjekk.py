import pandas as pd

df = pd.read_csv("contracts_klassifisert.csv")
mangler = df[df["modell_kategori"].isna() | df["modell_begrunnelse"].astype(str).str.startswith("FEIL:")]
print(f"{len(mangler)} av {len(df)} kontrakter mangler fortsatt et gyldig svar.")