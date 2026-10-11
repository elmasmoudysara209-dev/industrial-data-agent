import pandas as pd
from kpi import production_kpis, pareto_arrets, livraison_kpis

print("=== 1. KPI par ligne ===")
print(production_kpis(groupby="ligne"))

print("\n=== 2. L3 pendant l'anomalie (10-20 mars) ===")
print(production_kpis(ligne="L3", date_debut="2026-03-10", date_fin="2026-03-20"))

print("\n=== 3. TRS par mois ===")
print(production_kpis(groupby="mois")[["mois", "trs"]])

print("\n=== 4. Pareto des causes d'arrêt ===")
print(pareto_arrets())

print("\n=== 5. Livraison (global) ===")
print(livraison_kpis())

# ---- VÉRIFICATION INDÉPENDANTE avec pandas pur, à partir du CSV ----
print("\n=== 6. Vérification manuelle (TRS de L1) ===")
df = pd.read_csv("data/production.csv")
l1 = df[df["ligne"] == "L1"]
# Autre formule équivalente : TRS = pièces bonnes / (ouverture x cadence théorique)
trs_manuel = l1["pieces_bonnes"].sum() / (l1["temps_ouverture_min"] / 60 * l1["cadence_theorique"]).sum()
trs_fonction = production_kpis(ligne="L1")["trs"].iloc[0]
print("TRS manuel   :", round(trs_manuel, 4))
print("TRS fonction :", trs_fonction)
print("OK" if abs(trs_manuel - trs_fonction) < 0.001 else "ERREUR : les deux valeurs diffèrent")