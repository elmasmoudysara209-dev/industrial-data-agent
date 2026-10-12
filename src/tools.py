"""
Les 4 outils de l'agent : run_sql, compute_kpi, make_chart, detect_anomaly.
Chaque outil renvoie un dictionnaire simple. En cas de problème : {"error": "..."}.
"""
import json
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from kpi import DB_PATH, _query, livraison_kpis, pareto_arrets, production_kpis

import duckdb

MAX_ROWS = 200

# Journaux consultés par l'interface (transparence, exigence F8)
QUERY_LOG: list[str] = []     # requêtes SQL exécutées
CHARTS: list[dict] = []       # graphiques créés


def clear_logs():
    QUERY_LOG.clear()
    CHARTS.clear()


def _rows(df: pd.DataFrame, max_rows: int = MAX_ROWS) -> list[dict]:
    """Convertit un tableau pandas en liste de dictionnaires 100 % simples (JSON)."""
    df = df.head(max_rows).copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
    return json.loads(df.to_json(orient="records"))


def _lignes() -> list[str]:
    return _query("SELECT DISTINCT ligne FROM production ORDER BY ligne")["ligne"].tolist()


# ======================================================================
# OUTIL 1 : run_sql
# ======================================================================
INTERDIT = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|install|load|"
    r"export|import|call|truncate|replace|set|glob|read_\w+|write_\w+)\b",
    re.IGNORECASE,
)


def run_sql(query: str) -> dict:
    """Exécute UNE requête SQL de lecture (SELECT ou WITH) sur la base de production."""
    q = query.strip().rstrip(";").strip()

    if not re.match(r"^(select|with)\b", q, re.IGNORECASE):
        return {"error": "Seules les requêtes SELECT (ou WITH ... SELECT) sont autorisées."}
    if ";" in q:
        return {"error": "Une seule requête à la fois, sans point-virgule au milieu."}
    mot = INTERDIT.search(q)
    if mot:
        return {"error": f"Mot interdit dans la requête : '{mot.group(0)}'. Lecture seule uniquement."}

    QUERY_LOG.append(q)
    try:
        con = duckdb.connect(str(DB_PATH), read_only=True)   # lecture seule : impossible de modifier
        try:
            df = con.execute(q).df()
        finally:
            con.close()
    except Exception as e:
        return {"error": f"Erreur SQL : {e}"}

    return {
        "colonnes": list(df.columns),
        "nb_lignes_total": len(df),
        "lignes_renvoyees": min(len(df), MAX_ROWS),
        "lignes": _rows(df),
    }


# ======================================================================
# OUTIL 2 : compute_kpi
# ======================================================================
FORMULES = {
    "trs": "TRS = Disponibilité x Performance x Qualité",
    "disponibilite": "(temps d'ouverture - temps d'arrêt) / temps d'ouverture",
    "performance": "pièces produites / (temps de marche x cadence théorique)",
    "qualite": "pièces bonnes / pièces produites",
    "taux_rebuts": "pièces rebut / pièces produites",
    "temps_arret": "somme des minutes d'arrêt",
    "otd": "commandes livrées à l'heure / nombre de commandes",
    "taux_service": "quantité livrée / quantité commandée",
}
KPI_PROD = {"trs": "trs", "disponibilite": "disponibilite", "performance": "performance",
            "qualite": "qualite", "taux_rebuts": "taux_rebuts", "temps_arret": "arret_min"}
KPI_LIVR = {"otd": "otd", "taux_service": "taux_service"}


def compute_kpi(kpi: str, ligne: str = None, date_debut: str = None,
                date_fin: str = None, groupby: str = None) -> dict:
    """Calcule un KPI. kpi : trs, disponibilite, performance, qualite, taux_rebuts,
    temps_arret, otd, taux_service. groupby : ligne, equipe, produit, jour, semaine, mois."""
    if kpi in KPI_PROD:
        df = production_kpis(ligne, date_debut, date_fin, groupby)
        colonnes = ([groupby] if groupby else []) + [KPI_PROD[kpi]]
        resultat = df[colonnes]
    elif kpi in KPI_LIVR:
        df = livraison_kpis(date_debut, date_fin, groupby)
        colonnes = ([groupby] if groupby else []) + [KPI_LIVR[kpi]]
        resultat = df[colonnes]
    else:
        return {"error": f"KPI inconnu : '{kpi}'. Choix : {list(FORMULES)}"}

    return {
        "kpi": kpi,
        "formule": FORMULES[kpi],
        "filtres": {"ligne": ligne, "date_debut": date_debut, "date_fin": date_fin, "groupby": groupby},
        "resultat": _rows(resultat),
    }


# ======================================================================
# OUTIL 3 : make_chart
# ======================================================================
def make_chart(type_graphique: str, kpi: str = "trs", ligne: str = None,
               date_debut: str = None, date_fin: str = None, periode: str = "semaine") -> dict:
    """Crée un graphique. type_graphique : 'pareto' (causes d'arrêt), 'tendance'
    (évolution d'un KPI dans le temps), 'histogramme' (répartition d'un KPI par jour)."""
    titre_filtre = f" - {ligne}" if ligne else " - toutes lignes"

    if type_graphique == "pareto":
        df = pareto_arrets(ligne, date_debut, date_fin)
        if df.empty:
            return {"error": "Aucun arrêt sur cette période."}
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_bar(x=df["cause"], y=df["minutes"], name="Minutes d'arrêt")
        fig.add_scatter(x=df["cause"], y=df["pct_cumule"], name="% cumulé",
                        mode="lines+markers", secondary_y=True)
        fig.update_yaxes(title_text="Minutes", secondary_y=False)
        fig.update_yaxes(title_text="% cumulé", range=[0, 105], secondary_y=True)
        fig.update_layout(title="Pareto des causes d'arrêt" + titre_filtre)
        apercu = _rows(df[["cause", "minutes", "pct", "pct_cumule"]], 10)

    elif type_graphique in ("tendance", "histogramme"):
        if kpi not in KPI_PROD:
            return {"error": f"KPI inconnu pour un graphique : '{kpi}'. Choix : {list(KPI_PROD)}"}
        col = KPI_PROD[kpi]
        lignes = [ligne] if ligne else _lignes()

        if type_graphique == "tendance":
            if periode not in ("jour", "semaine", "mois"):
                return {"error": "periode doit être 'jour', 'semaine' ou 'mois'."}
            fig = go.Figure()
            for l in lignes:
                d = production_kpis(l, date_debut, date_fin, periode)
                fig.add_scatter(x=d[periode], y=d[col], mode="lines", name=l)
            fig.update_layout(title=f"Tendance : {kpi}{titre_filtre} (par {periode})",
                              xaxis_title=periode, yaxis_title=kpi)
            apercu = f"Courbes tracées pour : {lignes}"
        else:
            d = pd.concat([production_kpis(l, date_debut, date_fin, "jour").assign(ligne=l)
                           for l in lignes])
            fig = px.histogram(d, x=col, color="ligne", nbins=30, barmode="overlay",
                               opacity=0.6, title=f"Répartition journalière : {kpi}{titre_filtre}")
            apercu = f"Histogramme de {len(d)} valeurs journalières."
    else:
        return {"error": "type_graphique doit être 'pareto', 'tendance' ou 'histogramme'."}

    CHARTS.append({"titre": fig.layout.title.text, "figure": fig})
    return {"graphique_cree": True, "id_graphique": len(CHARTS) - 1,
            "titre": fig.layout.title.text, "apercu_donnees": apercu}


# ======================================================================
# OUTIL 4 : detect_anomaly
# ======================================================================
ANOMALY_KPI = {"trs": "trs", "disponibilite": "disponibilite", "performance": "performance",
               "qualite": "qualite", "taux_rebuts": "taux_rebuts", "temps_arret": "arret_min"}
HAUSSE_MAUVAISE = {"taux_rebuts", "temps_arret"}   # pour ces KPI, une hausse est une dégradation


def detect_anomaly(kpi: str = "taux_rebuts", ligne: str = None, seuil: float = 2.0) -> dict:
    """Détecte (1) les jours dont le KPI s'écarte de plus de `seuil` écarts-types de la
    moyenne (pics) et (2) une dérive : moyenne des 30 derniers jours vs le reste."""
    if kpi not in ANOMALY_KPI:
        return {"error": f"KPI inconnu : '{kpi}'. Choix : {list(ANOMALY_KPI)}"}
    col = ANOMALY_KPI[kpi]
    lignes = [ligne] if ligne else _lignes()
    sortie = []

    for l in lignes:
        d = production_kpis(l, groupby="jour")
        s = d[col]
        moy, ecart_type = s.mean(), s.std()
        if pd.isna(ecart_type) or ecart_type == 0:
            continue

        d["z"] = (s - moy) / ecart_type
        pics = d[d["z"].abs() > seuil].copy()
        pics["sens"] = pics["z"].apply(
            lambda z: "dégradation" if (z > 0) == (kpi in HAUSSE_MAUVAISE) else "amélioration")
        pics = pics.reindex(pics["z"].abs().sort_values(ascending=False).index)

        # Dérive : 30 derniers jours vs le reste
        ancien, recent = s.iloc[:-30], s.tail(30)
        ecart_derive = (recent.mean() - ancien.mean()) / ancien.std()
        derive = abs(ecart_derive) > seuil

        sortie.append({
            "ligne": l,
            "moyenne": round(float(moy), 4),
            "ecart_type": round(float(ecart_type), 4),
            "nb_jours_anormaux": len(pics),
            "jours_anormaux": _rows(pics[["jour", col, "z", "sens"]].assign(
                **{col: pics[col].round(3), "z": pics["z"].round(3)}), 15),
            "derive_detectee": bool(derive),
            "derive_detail": {
                "moyenne_30_derniers_jours": round(float(recent.mean()), 4),
                "moyenne_avant": round(float(ancien.mean()), 4),
                "ecart_en_ecarts_types": round(float(ecart_derive), 2),
            },
        })

    return {"kpi": kpi, "seuil_ecarts_types": seuil, "resultats_par_ligne": sortie}


# ======================================================================
# DISTRIBUTEUR : l'agent appellera run_tool(nom, arguments)
# ======================================================================
TOOL_FUNCTIONS = {
    "run_sql": run_sql,
    "compute_kpi": compute_kpi,
    "make_chart": make_chart,
    "detect_anomaly": detect_anomaly,
}


def run_tool(name: str, args: dict) -> dict:
    """Exécute l'outil demandé. Ne plante jamais : renvoie {"error": ...} en cas de souci."""
    if name not in TOOL_FUNCTIONS:
        return {"error": f"Outil inconnu : '{name}'. Outils : {list(TOOL_FUNCTIONS)}"}
    try:
        return TOOL_FUNCTIONS[name](**(args or {}))
    except Exception as e:
        return {"error": f"{type(e).__name__} : {e}"}
    # ======================================================================
# v2 : graphique générique construit à partir du résultat d'UNE requête SQL
# ======================================================================
def chart_from_rows(lignes: list[dict], type_graphique: str, x: str = None, y: str = None,
                    couleur: str = None, titre: str = ""):
    """Dessine barres / courbe / pareto / histogramme à partir des lignes d'un résultat SQL."""
    df = pd.DataFrame(lignes)
    if df.empty:
        return None
    for col in (x, y, couleur):
        if col and col not in df.columns:
            raise ValueError(f"colonne '{col}' absente du résultat (colonnes : {list(df.columns)})")

    # Les dates arrivent en texte "AAAA-MM-JJ" : on les convertit pour un axe temporel propre
    if x and df[x].dtype == object and df[x].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}").all():
        df[x] = pd.to_datetime(df[x])

    if type_graphique == "barres":
        fig = px.bar(df, x=x, y=y, color=couleur, barmode="group", title=titre)
    elif type_graphique == "courbe":
        fig = px.line(df.sort_values(x), x=x, y=y, color=couleur, title=titre)
    elif type_graphique == "histogramme":
        fig = px.histogram(df, x=x or y, color=couleur, nbins=30, title=titre)
    elif type_graphique == "pareto":
        df = df.sort_values(y, ascending=False)
        cumul = df[y].cumsum() / df[y].sum() * 100
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_bar(x=df[x], y=df[y], name=y)
        fig.add_scatter(x=df[x], y=cumul, name="% cumulé", mode="lines+markers", secondary_y=True)
        fig.update_yaxes(title_text="% cumulé", range=[0, 105], secondary_y=True)
        fig.update_layout(title=titre)
    else:
        return None
    return fig