"""
KPI industriels : formules documentées.

Règle d'or : on additionne d'abord les quantités (minutes, pièces),
puis on calcule les ratios. On ne fait JAMAIS la moyenne de ratios.
"""
from pathlib import Path

import duckdb
import pandas as pd

# Chemin absolu vers la base : fonctionne quel que soit le dossier d'où on lance le script
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "industrie.duckdb"

# Regroupements autorisés pour les KPI de production (liste blanche = sécurité)
GROUPBY_PROD = {
    "ligne": "ligne",
    "equipe": "equipe",
    "produit": "produit",
    "jour": "jour",
    "semaine": "date_trunc('week', jour)",
    "mois": "date_trunc('month', jour)",
}
# Regroupements autorisés pour les KPI de livraison
GROUPBY_LIVR = {
    "produit": "produit",
    "mois": "date_trunc('month', date_livraison_promise)",
}


def _query(sql: str, params: list | None = None) -> pd.DataFrame:
    """Exécute une requête en LECTURE SEULE et renvoie un tableau pandas."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


def _filtres(colonne_date: str, ligne=None, date_debut=None, date_fin=None):
    """Construit la clause WHERE et ses paramètres (requêtes paramétrées)."""
    where, params = ["1=1"], []
    if ligne:
        where.append("ligne = ?")
        params.append(ligne)
    if date_debut:
        where.append(f"{colonne_date} >= CAST(? AS DATE)")
        params.append(date_debut)
    if date_fin:
        where.append(f"{colonne_date} <= CAST(? AS DATE)")
        params.append(date_fin)
    return " AND ".join(where), params


# ----------------------------------------------------------------------
# KPI DE PRODUCTION : disponibilité, performance, qualité, TRS, rebuts
# ----------------------------------------------------------------------
def production_kpis(ligne=None, date_debut=None, date_fin=None, groupby=None) -> pd.DataFrame:
    """
    Calcule les KPI de production.

    Formules :
      Disponibilité = (ouverture - arrêt) / ouverture
      Performance   = pièces produites / (temps de marche x cadence théorique)
      Qualité       = pièces bonnes / pièces produites
      TRS           = Disponibilité x Performance x Qualité
      Taux rebuts   = rebuts / pièces produites

    Paramètres :
      ligne      : "L1" à "L5" (None = toutes les lignes)
      date_debut : "AAAA-MM-JJ" (None = depuis le début)
      date_fin   : "AAAA-MM-JJ" (None = jusqu'à la fin)
      groupby    : "ligne", "equipe", "produit", "jour", "semaine" ou "mois"
    """
    where, params = _filtres("jour", ligne, date_debut, date_fin)

    if groupby:
        if groupby not in GROUPBY_PROD:
            raise ValueError(f"groupby doit être parmi {list(GROUPBY_PROD)}")
        expr = GROUPBY_PROD[groupby]
        select_groupe = f"{expr} AS {groupby},"
        clause_groupe = f"GROUP BY {expr} ORDER BY {expr}"
    else:
        select_groupe, clause_groupe = "", ""

    sql = f"""
        SELECT {select_groupe}
            SUM(temps_ouverture_min) AS ouverture_min,
            SUM(temps_arret_min)     AS arret_min,
            SUM(pieces_produites)    AS produites,
            SUM(pieces_bonnes)       AS bonnes,
            SUM(pieces_rebut)        AS rebuts,
            SUM((temps_ouverture_min - temps_arret_min) / 60.0 * cadence_theorique) AS theorique
        FROM production
        WHERE {where}
        {clause_groupe}
    """
    df = _query(sql, params)

    df["disponibilite"] = 1 - df["arret_min"] / df["ouverture_min"]
    df["performance"] = df["produites"] / df["theorique"]
    df["qualite"] = df["bonnes"] / df["produites"]
    df["trs"] = df["disponibilite"] * df["performance"] * df["qualite"]
    df["taux_rebuts"] = df["rebuts"] / df["produites"]
    return df.drop(columns=["theorique"]).round(4)


# ----------------------------------------------------------------------
# PARETO DES CAUSES D'ARRÊT
# ----------------------------------------------------------------------
def pareto_arrets(ligne=None, date_debut=None, date_fin=None) -> pd.DataFrame:
    """Causes d'arrêt triées par durée décroissante, avec % et % cumulé (Pareto)."""
    where, params = _filtres("jour", ligne, date_debut, date_fin)
    df = _query(f"""
        SELECT cause, COUNT(*) AS nb_arrets, ROUND(SUM(duree_min), 1) AS minutes
        FROM arrets
        WHERE {where}
        GROUP BY cause
        ORDER BY minutes DESC
    """, params)
    df["pct"] = (df["minutes"] / df["minutes"].sum() * 100).round(1)
    df["pct_cumule"] = df["pct"].cumsum().round(1)
    return df


# ----------------------------------------------------------------------
# KPI DE LIVRAISON : OTD et taux de service
# ----------------------------------------------------------------------
def livraison_kpis(date_debut=None, date_fin=None, groupby=None) -> pd.DataFrame:
    """
    Formules :
      OTD            = commandes livrées à l'heure / nombre de commandes
                       (à l'heure = livraison réelle <= livraison promise)
      Taux de service = quantité livrée / quantité commandée

    Les dates filtrent sur la date de livraison promise.
    groupby : "produit" ou "mois" (None = global)
    """
    where, params = _filtres("date_livraison_promise", None, date_debut, date_fin)

    if groupby:
        if groupby not in GROUPBY_LIVR:
            raise ValueError(f"groupby doit être parmi {list(GROUPBY_LIVR)}")
        expr = GROUPBY_LIVR[groupby]
        select_groupe = f"{expr} AS {groupby},"
        clause_groupe = f"GROUP BY {expr} ORDER BY {expr}"
    else:
        select_groupe, clause_groupe = "", ""

    df = _query(f"""
        SELECT {select_groupe}
            COUNT(*) AS nb_commandes,
            SUM(CASE WHEN date_livraison_reelle <= date_livraison_promise THEN 1 ELSE 0 END) AS a_l_heure,
            SUM(quantite_livree)    AS livre,
            SUM(quantite_commandee) AS commande
        FROM commandes
        WHERE {where}
        {clause_groupe}
    """, params)

    df["otd"] = df["a_l_heure"] / df["nb_commandes"]
    df["taux_service"] = df["livre"] / df["commande"]
    return df.round(4)