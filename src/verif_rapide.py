from kpi import production_kpis, livraison_kpis

print(production_kpis(groupby="ligne", date_debut="2026-09-01", date_fin="2026-09-30")[["ligne", "trs"]])
print(livraison_kpis(groupby="produit")[["produit", "otd"]])