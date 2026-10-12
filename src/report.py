"""
Rapport hebdomadaire (F6) et alertes (F5).
Tous les chiffres viennent de calculs Python (kpi.py). Le LLM, s'il est utilisé, ne fait que
rédiger le résumé à partir de chiffres déjà calculés.
"""
import io
from datetime import datetime

import pandas as pd

from kpi import _query, livraison_kpis, pareto_arrets, production_kpis

# (nom affiché, colonne, une hausse est-elle mauvaise ?)
KPI_ALERTES = [
    ("taux de rebuts", "taux_rebuts", True),
    ("disponibilité", "disponibilite", False),
    ("TRS", "trs", False),
]

METHODE = [
    "TRS = Disponibilité x Performance x Qualité ; chaque ratio est calculé sur des sommes (jamais en moyennant des ratios).",
    "Taux de rebuts = rebuts / pièces produites. OTD = commandes livrées à l'heure / commandes (période = date de livraison promise). "
    "Taux de service = quantité livrée / quantité commandée.",
    "Alertes : une valeur journalière est signalée si elle s'écarte de plus de 2 écarts-types de la moyenne, dans le mauvais sens.",
    "Données simulées et anonymisées : aucune donnée d'entreprise.",
]


# ----------------------------------------------------------------------
# Petits outils de mise en forme
# ----------------------------------------------------------------------
def _ok(x) -> bool:
    return x is not None and not pd.isna(x)


def _fmt(kind: str, v) -> str:
    if not _ok(v):
        return "n/d"
    if kind == "pct":
        return f"{v * 100:.1f} %"
    if kind == "pct2":
        return f"{v * 100:.2f} %"
    return f"{v:.1f} h"


def _delta(kind: str, v, p) -> str:
    if not (_ok(v) and _ok(p)):
        return "n/d"
    if kind == "pct":
        return f"{(v - p) * 100:+.1f} pt"
    if kind == "pct2":
        return f"{(v - p) * 100:+.2f} pt"
    return f"{v - p:+.1f} h"


def periodes(date_fin: str):
    """Semaine glissante de 7 jours se terminant à date_fin, et la semaine précédente."""
    fin = pd.Timestamp(date_fin)
    debut = fin - pd.Timedelta(days=6)
    fin_prec = debut - pd.Timedelta(days=1)
    debut_prec = fin_prec - pd.Timedelta(days=6)
    f = lambda t: t.strftime("%Y-%m-%d")
    return f(debut), f(fin), f(debut_prec), f(fin_prec)


# ----------------------------------------------------------------------
# Alertes (règle des 2 écarts-types)
# ----------------------------------------------------------------------
def alertes_periode(d1: str, d2: str, seuil: float = 2.0) -> list[dict]:
    """Jours de la période [d1, d2] dont un KPI s'est dégradé de plus de `seuil` écarts-types."""
    lignes = _query("SELECT DISTINCT ligne FROM production ORDER BY ligne")["ligne"].tolist()
    alertes = []
    for nom, col, hausse_mauvaise in KPI_ALERTES:
        for l in lignes:
            d = production_kpis(ligne=l, groupby="jour")
            d["jour"] = pd.to_datetime(d["jour"])
            s = d.set_index("jour")[col]
            z = (s - s.mean()) / s.std()
            z_periode = z.loc[d1:d2]
            mauvais = z_periode[z_periode > seuil] if hausse_mauvaise else z_periode[z_periode < -seuil]
            if len(mauvais):
                pire = mauvais.idxmax() if hausse_mauvaise else mauvais.idxmin()
                alertes.append({
                    "ligne": l, "kpi": nom, "nb_jours": int(len(mauvais)),
                    "pire_jour": pire.strftime("%Y-%m-%d"), "valeur": float(s.loc[pire]),
                    "z": float(z.loc[pire]), "moyenne": float(s.mean()),
                    "kind": "pct2" if col == "taux_rebuts" else "pct",
                })
    alertes.sort(key=lambda a: (-a["nb_jours"], -abs(a["z"])))
    return alertes


def _lignes_alertes(r: dict) -> list[dict]:
    sortie = []
    for a in r["alertes"]:
        texte = (f"{a['kpi']} dégradé sur {a['nb_jours']} jour(s) "
                 f"(pire jour {a['pire_jour']} : {_fmt(a['kind'], a['valeur'])}, "
                 f"moyenne habituelle {_fmt(a['kind'], a['moyenne'])})")
        sortie.append({"label": a["ligne"], "texte": texte})
    return sortie


# ----------------------------------------------------------------------
# Construction des données du rapport
# ----------------------------------------------------------------------
def construire_rapport(date_fin: str = "2026-09-30") -> dict:
    d1, d2, p1, p2 = periodes(date_fin)

    cur = production_kpis(date_debut=d1, date_fin=d2).iloc[0]
    prev = production_kpis(date_debut=p1, date_fin=p2).iloc[0]
    livr = livraison_kpis(date_debut=d1, date_fin=d2).iloc[0]
    livr_prev = livraison_kpis(date_debut=p1, date_fin=p2).iloc[0]

    kpis = [
        ("TRS", cur["trs"], prev["trs"], "pct"),
        ("Disponibilité", cur["disponibilite"], prev["disponibilite"], "pct"),
        ("Performance", cur["performance"], prev["performance"], "pct"),
        ("Qualité", cur["qualite"], prev["qualite"], "pct"),
        ("Taux de rebuts", cur["taux_rebuts"], prev["taux_rebuts"], "pct2"),
        ("Temps d'arrêt", cur["arret_min"] / 60, prev["arret_min"] / 60, "h"),
        ("OTD (livraisons à l'heure)", livr["otd"], livr_prev["otd"], "pct"),
        ("Taux de service", livr["taux_service"], livr_prev["taux_service"], "pct"),
    ]

    par_ligne = production_kpis(date_debut=d1, date_fin=d2, groupby="ligne")
    prec_ligne = production_kpis(date_debut=p1, date_fin=p2, groupby="ligne").set_index("ligne")
    lignes = []
    for _, row in par_ligne.iterrows():
        l = row["ligne"]
        lignes.append({
            "ligne": l, "trs": row["trs"],
            "trs_prec": prec_ligne.loc[l, "trs"] if l in prec_ligne.index else None,
            "dispo": row["disponibilite"], "rebuts": row["taux_rebuts"],
            "arret_h": row["arret_min"] / 60,
        })
    lignes.sort(key=lambda x: x["trs"])          # du moins bon au meilleur

    defauts = _query(
        "SELECT defaut, SUM(quantite) AS quantite FROM qualite "
        "WHERE jour BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) GROUP BY defaut ORDER BY quantite DESC",
        [d1, d2])
    defauts["pct"] = defauts["quantite"] / defauts["quantite"].sum() * 100

    return {
        "d1": d1, "d2": d2, "p1": p1, "p2": p2,
        "kpis": kpis, "lignes": lignes,
        "pareto": pareto_arrets(date_debut=d1, date_fin=d2),
        "defauts": defauts,
        "alertes": alertes_periode(d1, d2),
    }


# ----------------------------------------------------------------------
# Résumé : automatique (sans IA) ou rédigé par l'IA
# ----------------------------------------------------------------------
def resume_auto(r: dict) -> str:
    k = {nom: (v, p) for nom, v, p, _ in r["kpis"]}
    trs, trs_prec = k["TRS"]
    pire, meilleure = r["lignes"][0], r["lignes"][-1]
    phrases = [
        f"Du {r['d1']} au {r['d2']}, le TRS global est de {_fmt('pct', trs)} "
        f"({_delta('pct', trs, trs_prec)} par rapport à la semaine précédente).",
        f"La ligne la moins performante est {pire['ligne']} (TRS {_fmt('pct', pire['trs'])}), "
        f"la meilleure est {meilleure['ligne']} ({_fmt('pct', meilleure['trs'])}).",
    ]
    if len(r["pareto"]):
        c = r["pareto"].iloc[0]
        phrases.append(f"La première cause d'arrêt est « {c['cause']} » ({c['pct']:.0f} % du temps d'arrêt).")
    n = len(r["alertes"])
    phrases.append(f"{n} alerte(s) statistique(s) détectée(s) sur la période." if n
                   else "Aucune alerte statistique détectée sur la période.")
    return " ".join(phrases)


def resume_ia(r: dict) -> str:
    """1 appel au modèle : il rédige à partir de chiffres déjà calculés. En cas de souci : résumé automatique."""
    try:
        from agent import CONFIG_REDACTION, _generate
        faits = en_markdown(r, resume="(à rédiger)")
        prompt = ("Voici les chiffres d'un rapport hebdomadaire de production, déjà calculés :\n\n" + faits +
                  "\n\nRédige un résumé exécutif de 4 à 5 phrases en français pour un responsable de production : "
                  "situation globale, points d'attention, et une action prioritaire cohérente avec ces chiffres. "
                  "Utilise UNIQUEMENT les chiffres ci-dessus, n'en invente aucun.")
        texte = (_generate(prompt, CONFIG_REDACTION).text or "").strip()
        return texte or resume_auto(r)
    except Exception:
        return resume_auto(r)


# ----------------------------------------------------------------------
# Tableaux communs (Markdown et PDF)
# ----------------------------------------------------------------------
ENT_KPI = ["Indicateur", "Cette semaine", "Semaine précédente", "Évolution"]
ENT_LIGNES = ["Ligne", "TRS", "Évol. TRS", "Disponibilité", "Rebuts", "Arrêts (h)"]
ENT_PARETO = ["Cause d'arrêt", "Minutes", "Part", "Cumul"]
ENT_DEFAUTS = ["Défaut", "Quantité", "Part"]


def _tables(r: dict) -> dict:
    return {
        "kpis": [[nom, _fmt(k, v), _fmt(k, p), _delta(k, v, p)] for nom, v, p, k in r["kpis"]],
        "lignes": [[l["ligne"], _fmt("pct", l["trs"]), _delta("pct", l["trs"], l["trs_prec"]),
                    _fmt("pct", l["dispo"]), _fmt("pct2", l["rebuts"]), f"{l['arret_h']:.1f}"]
                   for l in r["lignes"]],
        "pareto": [[row["cause"], f"{row['minutes']:.0f}", f"{row['pct']:.1f} %", f"{row['pct_cumule']:.1f} %"]
                   for _, row in r["pareto"].head(5).iterrows()],
        "defauts": [[row["defaut"], f"{int(row['quantite'])}", f"{row['pct']:.1f} %"]
                    for _, row in r["defauts"].iterrows()],
    }


# ----------------------------------------------------------------------
# Export Markdown
# ----------------------------------------------------------------------
def _md_table(entetes, lignes) -> str:
    out = ["| " + " | ".join(entetes) + " |", "|" + "|".join(["---"] * len(entetes)) + "|"]
    out += ["| " + " | ".join(str(c) for c in l) + " |" for l in lignes]
    return "\n".join(out)


def en_markdown(r: dict, resume: str) -> str:
    t = _tables(r)
    alertes = _lignes_alertes(r)
    texte_alertes = ("\n".join(f"- **{a['label']}** : {a['texte']}" for a in alertes)
                     if alertes else "Aucune alerte sur la période.")
    return f"""# Rapport hebdomadaire de production

**Période : du {r['d1']} au {r['d2']}** (comparée à la période du {r['p1']} au {r['p2']})
Généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Résumé
{resume}

## Indicateurs clés
{_md_table(ENT_KPI, t['kpis'])}

## Performance par ligne (du moins bon au meilleur TRS)
{_md_table(ENT_LIGNES, t['lignes'])}

## Causes d'arrêt (Pareto, 5 premières)
{_md_table(ENT_PARETO, t['pareto'])}

## Défauts qualité
{_md_table(ENT_DEFAUTS, t['defauts'])}

## Alertes
{texte_alertes}

## Méthode
""" + "\n".join(f"- {m}" for m in METHODE) + "\n"


# ----------------------------------------------------------------------
# Export PDF
# ----------------------------------------------------------------------
def _latin(s: str) -> str:
    """Les polices PDF standard ne gèrent que le latin-1 : on remplace les caractères spéciaux."""
    remplacements = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
                     "→": "->", "≥": ">=", "≤": "<=", "σ": "sigma", "\u202f": " ", "\u00a0": " ",
                     "•": "-", "🚨": "", "⚠️": "", "✅": ""}
    for a, b in remplacements.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _graphique_pareto(pareto: pd.DataFrame):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.bar(pareto["cause"], pareto["minutes"], color="#1f77b4")
    ax.set_ylabel("Minutes d'arrêt")
    ax.tick_params(axis="x", rotation=30)
    ax2 = ax.twinx()
    ax2.plot(pareto["cause"], pareto["pct_cumule"], color="#d62728", marker="o")
    ax2.set_ylim(0, 105)
    ax2.set_ylabel("% cumulé")
    ax.set_title("Pareto des causes d'arrêt")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def en_pdf(r: dict, resume: str) -> bytes:
    from fpdf import FPDF

    t = _tables(r)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def ligne(txt, taille=10, gras=False, h=6):
        pdf.set_font("Helvetica", "B" if gras else "", taille)
        pdf.multi_cell(0, h, _latin(txt), new_x="LMARGIN", new_y="NEXT")

    def titre(txt):
        pdf.ln(3)
        ligne(txt, taille=12, gras=True, h=8)

    def tableau(entetes, lignes):
        pdf.set_font("Helvetica", "", 9)
        with pdf.table() as table:
            row = table.row()
            for e in entetes:
                row.cell(_latin(e))
            for l in lignes:
                row = table.row()
                for c in l:
                    row.cell(_latin(str(c)))

    ligne("Rapport hebdomadaire de production", taille=18, gras=True, h=10)
    ligne(f"Période : du {r['d1']} au {r['d2']} (comparée à la période du {r['p1']} au {r['p2']})")
    titre("Résumé")
    ligne(resume)
    titre("Indicateurs clés")
    tableau(ENT_KPI, t["kpis"])
    titre("Performance par ligne (du moins bon au meilleur TRS)")
    tableau(ENT_LIGNES, t["lignes"])
    titre("Causes d'arrêt (Pareto)")
    tableau(ENT_PARETO, t["pareto"])
    try:
        pdf.ln(2)
        pdf.image(_graphique_pareto(r["pareto"]), w=170)
    except Exception:
        pass                                     # le PDF reste valable sans le graphique
    titre("Défauts qualité")
    tableau(ENT_DEFAUTS, t["defauts"])
    titre("Alertes")
    alertes = _lignes_alertes(r)
    if alertes:
        for a in alertes:
            ligne(f"- {a['label']} : {a['texte']}")
    else:
        ligne("Aucune alerte sur la période.")
    titre("Méthode")
    for m in METHODE:
        ligne(f"- {m}", taille=9, h=5)

    return bytes(pdf.output())