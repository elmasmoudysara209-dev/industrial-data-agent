from pathlib import Path
from tools import run_tool, run_sql, CHARTS, QUERY_LOG

print("=== 1. run_sql : requête valide ===")
r = run_sql("SELECT ligne, SUM(pieces_produites) AS total FROM production GROUP BY ligne ORDER BY ligne")
print(r["colonnes"], r["lignes"])

print("\n=== 2. run_sql : tentatives interdites (toutes doivent être refusées) ===")
for q in ["DROP TABLE production",
          "SELECT 1; DROP TABLE production",
          "DELETE FROM production",
          "SELECT * FROM read_csv('data/production.csv')"]:
    print(q, "->", run_sql(q))

print("\n=== 3. compute_kpi ===")
print(run_tool("compute_kpi", {"kpi": "trs", "groupby": "ligne"}))
print(run_tool("compute_kpi", {"kpi": "otd"}))
print(run_tool("compute_kpi", {"kpi": "n_importe_quoi"}))

print("\n=== 4. detect_anomaly : pic de rebuts de L3 ===")
res = run_tool("detect_anomaly", {"kpi": "taux_rebuts", "ligne": "L3"})["resultats_par_ligne"][0]
print("Jours anormaux :", res["nb_jours_anormaux"])
for j in res["jours_anormaux"][:6]:
    print("  ", j)

print("\n=== 5. detect_anomaly : dérive de disponibilité de L5 ===")
res = run_tool("detect_anomaly", {"kpi": "disponibilite", "ligne": "L5"})["resultats_par_ligne"][0]
print("Dérive détectée :", res["derive_detectee"], res["derive_detail"])

print("\n=== 6. make_chart : 3 graphiques ===")
Path("outputs").mkdir(exist_ok=True)
print(run_tool("make_chart", {"type_graphique": "pareto"}))
print(run_tool("make_chart", {"type_graphique": "tendance", "kpi": "trs", "periode": "semaine"}))
print(run_tool("make_chart", {"type_graphique": "histogramme", "kpi": "taux_rebuts", "ligne": "L3"}))
for i, c in enumerate(CHARTS):
    c["figure"].write_html(f"outputs/graphique_{i}.html")
print("Graphiques enregistrés dans le dossier outputs/")

print("\n=== 7. Requêtes enregistrées (F8) ===")
print(len(QUERY_LOG), "requête(s) SQL dans le journal")