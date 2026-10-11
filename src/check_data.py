import duckdb

con = duckdb.connect("data/industrie.duckdb", read_only=True)

print("=== KPI par ligne (calcul manuel en SQL) ===")
print(con.execute("""
    SELECT ligne,
      ROUND(1 - SUM(temps_arret_min) / SUM(temps_ouverture_min), 3) AS disponibilite,
      ROUND(SUM(pieces_produites) /
            SUM((temps_ouverture_min - temps_arret_min) / 60.0 * cadence_theorique), 3) AS performance,
      ROUND(SUM(pieces_bonnes) * 1.0 / SUM(pieces_produites), 3) AS qualite
    FROM production GROUP BY ligne ORDER BY ligne
""").df())

print("\n=== Taux de rebuts de L3 par mois (anomalie en mars) ===")
print(con.execute("""
    SELECT date_trunc('month', jour) AS mois,
           ROUND(SUM(pieces_rebut) * 100.0 / SUM(pieces_produites), 2) AS taux_rebut_pct
    FROM production WHERE ligne = 'L3' GROUP BY 1 ORDER BY 1
""").df())

print("\n=== Pareto des causes d'arrêt ===")
print(con.execute("""
    SELECT cause, COUNT(*) AS nb, ROUND(SUM(duree_min), 0) AS minutes
    FROM arrets GROUP BY cause ORDER BY minutes DESC
""").df())