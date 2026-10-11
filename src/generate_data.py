"""
Génère un jeu de données industrielles SIMULÉ (aucune donnée réelle).
Tables créées : production, arrets, qualite, commandes, stocks.
Lancer depuis la racine du projet :  python src/generate_data.py
"""
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)   # graine fixe : on obtient toujours les mêmes données

# ------------------------------------------------------------------
# 1. PARAMÈTRES
# ------------------------------------------------------------------
DEBUT, FIN = "2026-01-01", "2026-09-30"

# cadence = pièces/heure théoriques | perf = performance moyenne
# lam = nombre moyen d'arrêts par heure | rebut = taux moyen de rebuts
LIGNES = {
    "L1": {"cadence": 120, "perf": 0.92, "lam": 0.25, "rebut": 0.015},
    "L2": {"cadence": 100, "perf": 0.90, "lam": 0.30, "rebut": 0.020},
    "L3": {"cadence": 140, "perf": 0.88, "lam": 0.35, "rebut": 0.025},
    "L4": {"cadence": 90,  "perf": 0.93, "lam": 0.20, "rebut": 0.012},
    "L5": {"cadence": 110, "perf": 0.89, "lam": 0.30, "rebut": 0.022},
}
PRODUITS = ["REF-A", "REF-B", "REF-C", "REF-D"]
CAUSES = ["Panne mécanique", "Changement de série", "Manque matière", "Réglage",
          "Panne électrique", "Attente maintenance", "Nettoyage"]
POIDS_CAUSES = [0.30, 0.22, 0.15, 0.12, 0.10, 0.07, 0.04]      # somme = 1
DEFAUTS = ["Rayure", "Dimension hors tolérance", "Défaut d'assemblage", "Soudure", "Autre"]
POIDS_DEFAUTS = [0.30, 0.25, 0.20, 0.15, 0.10]


def equipe(heure: int) -> str:
    """Matin 6h-14h, Après-midi 14h-22h, Nuit 22h-6h."""
    if 6 <= heure < 14:
        return "Matin"
    if 14 <= heure < 22:
        return "Apres-midi"
    return "Nuit"


jours = pd.date_range(DEBUT, FIN)
heures = pd.date_range(DEBUT, FIN + " 23:00", freq="h")

# Un produit fabriqué par ligne et par jour
produit_du_jour = {(l, j.date()): str(rng.choice(PRODUITS)) for l in LIGNES for j in jours}

# ------------------------------------------------------------------
# 2. PRODUCTION + ARRÊTS (heure par heure)
# ------------------------------------------------------------------
prod_rows, arret_rows = [], []

for nom, p in LIGNES.items():
    for t in heures:
        jour = t.date()
        eq = equipe(t.hour)

        # fréquence des arrêts
        lam = p["lam"]
        if eq == "Nuit":
            lam *= 1.2                                   # la nuit, un peu plus d'arrêts
        if nom == "L5" and jour >= date(2026, 8, 1):     # ANOMALIE : dérive de L5
            lam *= 1 + (jour - date(2026, 8, 1)).days / 40

        # arrêts de cette heure
        n = rng.poisson(lam)
        durees = rng.gamma(2.0, 8.0, n)                  # durées en minutes
        if durees.sum() > 55:                            # on ne dépasse pas l'heure
            durees = durees * 55 / durees.sum()
        causes = rng.choice(CAUSES, n, p=POIDS_CAUSES)
        for c, d in zip(causes, durees):
            arret_rows.append((t, jour, nom, eq, str(c), round(float(d), 1)))

        # production de cette heure
        arret_min = float(durees.sum())
        marche = 60 - arret_min
        perf = float(np.clip(rng.normal(p["perf"], 0.04), 0.5, 1.0))
        produites = int(round(p["cadence"] * marche / 60 * perf))

        taux_rebut = p["rebut"]
        if nom == "L3" and date(2026, 3, 10) <= jour <= date(2026, 3, 20):
            taux_rebut *= 4                              # ANOMALIE : pic de rebuts L3
        rebuts = int(rng.binomial(produites, taux_rebut))

        prod_rows.append((t, jour, nom, eq, produit_du_jour[(nom, jour)], 60,
                          round(arret_min, 1), p["cadence"], produites,
                          produites - rebuts, rebuts))

production = pd.DataFrame(prod_rows, columns=[
    "horodatage", "jour", "ligne", "equipe", "produit", "temps_ouverture_min",
    "temps_arret_min", "cadence_theorique", "pieces_produites",
    "pieces_bonnes", "pieces_rebut"])
arrets = pd.DataFrame(arret_rows, columns=[
    "horodatage", "jour", "ligne", "equipe", "cause", "duree_min"])

# ------------------------------------------------------------------
# 3. QUALITÉ : on répartit les rebuts de chaque jour entre types de défauts
# ------------------------------------------------------------------
rebuts_jour = production.groupby(["jour", "ligne"])["pieces_rebut"].sum().reset_index()
q_rows = []
for r in rebuts_jour.itertuples():
    if r.pieces_rebut > 0:
        repartition = rng.multinomial(int(r.pieces_rebut), POIDS_DEFAUTS)
        for defaut, qte in zip(DEFAUTS, repartition):
            q_rows.append((r.jour, r.ligne, defaut, int(qte)))
qualite = pd.DataFrame(q_rows, columns=["jour", "ligne", "defaut", "quantite"])

# ------------------------------------------------------------------
# 4. COMMANDES (pour OTD et taux de service)
# ------------------------------------------------------------------
N_CMD = 3000
commandes = pd.DataFrame({
    "id_commande": np.arange(1, N_CMD + 1),
    "date_commande": pd.to_datetime(rng.choice(pd.date_range(DEBUT, "2026-09-10").values, N_CMD)),
    "produit": rng.choice(PRODUITS, N_CMD),
    "quantite_commandee": rng.integers(200, 2000, N_CMD),
})
delai = pd.to_timedelta(rng.integers(5, 15, N_CMD), unit="D")
retard = pd.to_timedelta(rng.choice([0, 1, 2, 3, 5], N_CMD, p=[0.80, 0.08, 0.06, 0.04, 0.02]), unit="D")
commandes["date_livraison_promise"] = commandes["date_commande"] + delai
commandes["date_livraison_reelle"] = commandes["date_livraison_promise"] + retard
taux_livre = rng.choice([1.0, 0.95, 0.90], N_CMD, p=[0.85, 0.10, 0.05])
commandes["quantite_livree"] = (commandes["quantite_commandee"] * taux_livre).astype(int)

# ------------------------------------------------------------------
# 5. STOCKS (marche aléatoire bornée)
# ------------------------------------------------------------------
stock_rows = []
for prod in PRODUITS:
    stock = 5000
    for j in jours:
        stock = int(np.clip(stock + rng.integers(-600, 650), 500, 10000))
        stock_rows.append((j.date(), prod, stock))
stocks = pd.DataFrame(stock_rows, columns=["jour", "produit", "stock_fin_jour"])

# ------------------------------------------------------------------
# 6. SAUVEGARDE : CSV + base DuckDB
# ------------------------------------------------------------------
Path("data").mkdir(exist_ok=True)
tables = {"production": production, "arrets": arrets, "qualite": qualite,
          "commandes": commandes, "stocks": stocks}

con = duckdb.connect("data/industrie.duckdb")
for nom, df in tables.items():
    df.to_csv(f"data/{nom}.csv", index=False)
    con.register("tmp_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {nom} AS SELECT * FROM tmp_df")
    con.unregister("tmp_df")
    print(f"{nom:<12}{len(df):>8} lignes")
con.close()
print("Terminé : fichiers dans le dossier data/")