from pathlib import Path

import pandas as pd

from report import construire_rapport, en_markdown, en_pdf, resume_auto

Path("outputs").mkdir(exist_ok=True)
r = construire_rapport("2026-09-30")
resume = resume_auto(r)
md = en_markdown(r, resume)
Path("outputs/rapport_test.md").write_text(md, encoding="utf-8")
Path("outputs/rapport_test.pdf").write_bytes(en_pdf(r, resume))
print(md)

# Independent check in pure pandas (TRS per line over the week)
df = pd.read_csv("data/production.csv", parse_dates=["jour"])
sem = df[(df["jour"] >= r["d1"]) & (df["jour"] <= r["d2"])].copy()
sem["theo"] = sem["temps_ouverture_min"] / 60 * sem["cadence_theorique"]
g = sem.groupby("ligne")
manuel = (g["pieces_bonnes"].sum() / g["theo"].sum()).round(4)

print("\n=== Check: TRS per line (report vs pandas) ===")
for l in r["lignes"]:
    ok = abs(l["trs"] - manuel[l["ligne"]]) < 0.001
    print(l["ligne"], "report:", round(l["trs"], 4), "| pandas:", manuel[l["ligne"]], "OK" if ok else "ERROR")