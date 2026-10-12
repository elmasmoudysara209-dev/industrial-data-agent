"""
Évaluation de l'agent : 30 questions de référence.
Les réponses attendues sont calculées INDÉPENDAMMENT, en pandas, à partir des CSV
(sans passer par kpi.py ni par le SQL de l'agent).

Lancer depuis la racine du projet :   python src/eval_agent.py
(option : python src/eval_agent.py 12   -> pause de 12 s entre deux questions)
"""
import statistics
import sys
import time
import unicodedata
from pathlib import Path

import pandas as pd

from agent import ask

PAUSE_S = float(sys.argv[1]) if len(sys.argv) > 1 else 8     # ménage le quota gratuit

# ----------------------------------------------------------------------
# 1. DONNÉES SOURCES (CSV générés à l'Étape 1)
# ----------------------------------------------------------------------
prod = pd.read_csv("data/production.csv", parse_dates=["jour"])
arrets = pd.read_csv("data/arrets.csv", parse_dates=["jour"])
qualite = pd.read_csv("data/qualite.csv", parse_dates=["jour"])
cmd = pd.read_csv("data/commandes.csv",
                  parse_dates=["date_commande", "date_livraison_promise", "date_livraison_reelle"])
stocks = pd.read_csv("data/stocks.csv", parse_dates=["jour"])


def periode(df, d1, d2):
    return df[(df["jour"] >= d1) & (df["jour"] <= d2)]


def mois(df, m):
    return df[df["jour"].dt.month == m]


def kpis(df) -> dict:
    """Formules de référence : on additionne d'abord, on divise ensuite."""
    ouv, arret = df["temps_ouverture_min"].sum(), df["temps_arret_min"].sum()
    theo = ((df["temps_ouverture_min"] - df["temps_arret_min"]) / 60 * df["cadence_theorique"]).sum()
    produites, bonnes, rebuts = df["pieces_produites"].sum(), df["pieces_bonnes"].sum(), df["pieces_rebut"].sum()
    dispo, perf, qual = 1 - arret / ouv, produites / theo, bonnes / produites
    return {"trs": dispo * perf * qual, "disponibilite": dispo, "performance": perf,
            "qualite": qual, "taux_rebuts": rebuts / produites}


def l(df, ligne):
    return df[df["ligne"] == ligne]


def argmax(d):
    return max(d, key=d.get)


def argmin(d):
    return min(d, key=d.get)


# ----------------------------------------------------------------------
# 2. RÉFÉRENCES POUR LES ANOMALIES ET DÉRIVES
# ----------------------------------------------------------------------
def serie_jour(df, ligne, f):
    d = l(df, ligne).groupby("jour").apply(f, include_groups=False)
    return d


def derive_attendue(ligne, f) -> bool:
    """Dérive = moyenne des 30 derniers jours très différente (> 2 écarts-types) du reste."""
    s = serie_jour(prod, ligne, f)
    ancien, recent = s.iloc[:-30], s.tail(30)
    return bool(abs((recent.mean() - ancien.mean()) / ancien.std()) > 2)


def jours_rebuts_anormaux(ligne, d1, d2) -> list:
    s = serie_jour(prod, ligne, lambda g: g["pieces_rebut"].sum() / g["pieces_produites"].sum())
    z = (s - s.mean()) / s.std()
    return [d.strftime("%Y-%m-%d") for d in z.loc[d1:d2][z.loc[d1:d2] > 2].index]


# ----------------------------------------------------------------------
# 3. LES 30 QUESTIONS ET LEURS RÉPONSES ATTENDUES
# ----------------------------------------------------------------------
CAS = []


def cas(id_, categorie, question, kind, attendu, session=None):
    CAS.append({"id": id_, "categorie": categorie, "question": question,
                "kind": kind, "attendu": attendu, "session": session})


sept = periode(prod, "2026-09-01", "2026-09-30")
trs_sept = {k: kpis(g)["trs"] for k, g in sept.groupby("ligne")}
rebuts_ligne = {k: kpis(g)["taux_rebuts"] for k, g in prod.groupby("ligne")}
trs_equipe_juin = {k: kpis(g)["trs"] for k, g in mois(prod, 6).groupby("equipe")}
sem_dispo = lambda g: 1 - g["temps_arret_min"].sum() / g["temps_ouverture_min"].sum()

# --- KPI ---
cas("Q01", "KPI", "Quel est le TRS de la ligne L2 en septembre ?", "valeur", kpis(l(sept, "L2"))["trs"])
cas("Q02", "KPI", "Quelle est la disponibilité de L4 en août ?", "valeur", kpis(l(mois(prod, 8), "L4"))["disponibilite"])
cas("Q03", "KPI", "Quel est le taux de rebuts global sur toute la période ?", "valeur", kpis(prod)["taux_rebuts"])
cas("Q04", "KPI", "Quelle est la performance de L1 en juillet ?", "valeur", kpis(l(mois(prod, 7), "L1"))["performance"])
cas("Q05", "KPI", "Quel est le TRS de chaque ligne en septembre ?", "par_cle", trs_sept)
cas("Q06", "Classement", "Quelle ligne a le pire TRS en septembre ?", "texte_premier", argmin(trs_sept))
cas("Q07", "Classement", "Quelle ligne a le meilleur TRS en septembre ?", "texte_premier", argmax(trs_sept))
cas("Q08", "Classement", "Quelle ligne a le taux de rebuts le plus élevé sur toute la période ?", "texte_premier", argmax(rebuts_ligne))
cas("Q09", "Classement", "Quelle équipe a le meilleur TRS en juin ?", "texte_premier", argmax(trs_equipe_juin))

# --- Comptages et sommes ---
cas("Q10", "SQL libre", "Combien de pièces a produit L1 en juin ?", "valeur", int(l(mois(prod, 6), "L1")["pieces_produites"].sum()))
cas("Q11", "SQL libre", "Combien de pièces bonnes au total en septembre ?", "valeur", int(sept["pieces_bonnes"].sum()))
cas("Q12", "SQL libre", "Combien de minutes d'arrêt au total pour L2 en mai ?", "valeur", float(l(mois(prod, 5), "L2")["temps_arret_min"].sum()))
cas("Q13", "SQL libre", "Combien d'arrêts y a-t-il eu sur L3 en février ?", "valeur", int(len(mois(l(arrets, "L3"), 2))))
cas("Q14", "Arrêts", "Quelle est la cause d'arrêt la plus longue (en minutes) sur toute la période ?", "texte_premier", arrets.groupby("cause")["duree_min"].sum().idxmax())
cas("Q15", "Arrêts", "Quelles sont les 3 principales causes d'arrêt de L2 en minutes ?", "liste_ordre", l(arrets, "L2").groupby("cause")["duree_min"].sum().sort_values(ascending=False).head(3).index.tolist())
cas("Q16", "Arrêts", "Combien de minutes d'arrêt pour « Panne mécanique » en septembre ?", "valeur", float(periode(arrets[arrets["cause"] == "Panne mécanique"], "2026-09-01", "2026-09-30")["duree_min"].sum()))

# --- Qualité ---
cas("Q17", "Qualité", "Quel est le défaut qualité le plus fréquent ?", "texte_premier", qualite.groupby("defaut")["quantite"].sum().idxmax())
cas("Q18", "Qualité", "Combien de pièces défectueuses de type Soudure sur L5 ?", "valeur", int(qualite[(qualite["ligne"] == "L5") & (qualite["defaut"] == "Soudure")]["quantite"].sum()))

# --- Livraisons et stocks ---
a_heure = cmd["date_livraison_reelle"] <= cmd["date_livraison_promise"]
cas("Q19", "Livraisons", "Quel est l'OTD global des commandes ?", "valeur", float(a_heure.mean()))
cas("Q20", "Livraisons", "Quel est le taux de service global ?", "valeur", float(cmd["quantite_livree"].sum() / cmd["quantite_commandee"].sum()))
cas("Q21", "Livraisons (EN)", "What is the on-time delivery rate for product REF-A?", "valeur", float(a_heure[cmd["produit"] == "REF-A"].mean()))
cas("Q22", "Stocks", "Quel est le stock de REF-B au 30 septembre ?", "valeur", int(stocks[(stocks["produit"] == "REF-B") & (stocks["jour"] == "2026-09-30")]["stock_fin_jour"].iloc[0]))

# --- Comparaisons et évolutions ---
cas("Q23", "Évolution", "Compare le TRS de L3 en février et en mars.", "valeurs", [kpis(l(mois(prod, m), "L3"))["trs"] for m in (2, 3)])
cas("Q24", "Évolution", "Quelle est l'évolution mensuelle du TRS de L5 de janvier à septembre ?", "valeurs", [kpis(l(mois(prod, m), "L5"))["trs"] for m in range(1, 10)])

# --- Mémoire de conversation ---
cas("Q25", "Mémoire", "Quel est le TRS de L1 en septembre ?", "valeur", trs_sept["L1"], session="S1")
cas("Q26", "Mémoire", "Et pour L4 ?", "valeur", trs_sept["L4"], session="S1")

# --- Anomalies et dérives ---
cas("Q27", "Anomalies", "Y a-t-il des anomalies de rebuts sur L3 ?", "anomalie_dates", jours_rebuts_anormaux("L3", "2026-03-10", "2026-03-20"))
cas("Q28", "Anomalies", "Y a-t-il une dérive de la disponibilité sur L5 ?", "derive", derive_attendue("L5", sem_dispo))
cas("Q29", "Anomalies", "Y a-t-il une dérive de la disponibilité sur L1 ?", "derive", derive_attendue("L1", sem_dispo))

# --- Hors périmètre ---
cas("Q30", "Hors périmètre", "Quel temps fait-il à Meknès ?", "hors_perimetre", None)


# ----------------------------------------------------------------------
# 4. COMPARAISON : réponse de l'agent vs référence
# ----------------------------------------------------------------------
def _norm(s) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


def _nombres(lignes) -> list:
    sortie = []
    for ligne in lignes:
        for v in ligne.values():
            if isinstance(v, bool):
                continue
            try:
                sortie.append(float(v))
            except (TypeError, ValueError):
                pass
    return sortie


def _proche(x, attendu, entier=False) -> bool:
    if entier:
        return abs(x - attendu) < 0.5
    tol = max(0.0006, 0.001 * abs(attendu))
    return any(abs(c - attendu) <= tol for c in (x, x / 100))      # accepte aussi un pourcentage


def verifier(c: dict, r: dict) -> bool:
    kind, att, lignes = c["kind"], c["attendu"], r["lignes"]
    texte = r["reponse"]
    if texte.startswith("Erreur lors") or texte.startswith("Je n'ai pas réussi"):
        return False
    if kind == "hors_perimetre":
        return r["sql"] is None and not lignes
    if kind == "derive":
        return ("dérive DÉTECTÉE" in texte) if att else ("dérive non détectée" in texte)
    if not lignes:
        return False

    nombres = _nombres(lignes)
    if kind == "valeur":
        return any(_proche(x, att, isinstance(att, int)) for x in nombres)
    if kind == "valeurs":
        return all(any(_proche(x, a) for x in nombres) for a in att)
    if kind == "par_cle":
        for cle, val in att.items():
            if not any(_norm(cle) in [_norm(v) for v in ligne.values()]
                       and any(_proche(x, val) for x in _nombres([ligne])) for ligne in lignes):
                return False
        return True
    if kind == "texte_premier":
        return _norm(att) in [_norm(v) for v in lignes[0].values()]
    if kind == "liste_ordre":
        return len(lignes) >= len(att) and all(
            _norm(a) in [_norm(v) for v in lignes[i].values()] for i, a in enumerate(att))
    if kind == "anomalie_dates":
        if not att:
            return False
        trouvees = {str(v)[:10] for ligne in lignes for v in ligne.values()}
        return len(set(att) & trouvees) / len(att) >= 0.8
    return False


# ----------------------------------------------------------------------
# 5. EXÉCUTION
# ----------------------------------------------------------------------
Path("outputs").mkdir(exist_ok=True)
Path("tests").mkdir(exist_ok=True)

# On sauvegarde le jeu de test lui-même (livrable du projet, à versionner dans Git)
pd.DataFrame([{"id": c["id"], "categorie": c["categorie"], "question": c["question"],
               "attendu": str(c["attendu"])[:300]} for c in CAS]).to_csv(
    "tests/questions_reference.csv", index=False, encoding="utf-8")

resultats, sessions = [], {}
print(f"Évaluation de {len(CAS)} questions (pause de {PAUSE_S} s entre chaque)...\n")
for c in CAS:
    memoire = sessions.setdefault(c["session"], []) if c["session"] else []
    r = ask(c["question"], memoire)
    ok = verifier(c, r)
    resultats.append({
        "id": c["id"], "categorie": c["categorie"], "question": c["question"],
        "attendu": str(c["attendu"])[:300], "ok": ok, "duree_s": r["duree_s"],
        "appels": r["nb_appels_llm"], "erreur_api": r["reponse"].startswith("Erreur lors"),
        "sql": r["sql"], "extrait": str(r["lignes"][:3])[:300],
    })
    print(f"{'✅' if ok else '❌'} {c['id']} [{c['categorie']}] {c['question']} ({r['duree_s']} s)")
    pd.DataFrame(resultats).to_csv("outputs/eval_resultats.csv", index=False, encoding="utf-8")
    time.sleep(PAUSE_S)

# ----------------------------------------------------------------------
# 6. RAPPORT
# ----------------------------------------------------------------------
df = pd.DataFrame(resultats)
total, n_ok = len(df), int(df["ok"].sum())
med = statistics.median(df["duree_s"])
sous_10 = (df["duree_s"] <= 10).mean() * 100
par_cat = df.groupby("categorie")["ok"].agg(["sum", "count"])

lignes_md = [
    "# Résultats de l'évaluation",
    f"- Exactitude globale : **{n_ok}/{total} = {n_ok / total * 100:.0f} %** (objectif : 85 %)",
    f"- Erreurs techniques (API) parmi les échecs : {int(df['erreur_api'].sum())}",
    f"- Temps de réponse : médiane **{med:.1f} s**, {sous_10:.0f} % des réponses en 10 s ou moins",
    f"- Appels au modèle par question : {df['appels'].mean():.2f} en moyenne",
    "", "| Catégorie | Réussies | Total |", "|---|---|---|",
] + [f"| {cat} | {int(row['sum'])} | {int(row['count'])} |" for cat, row in par_cat.iterrows()]
Path("outputs/eval_resume.md").write_text("\n".join(lignes_md), encoding="utf-8")

print("\n" + "\n".join(lignes_md))
for _, row in df[~df["ok"]].iterrows():
    print(f"\n❌ {row['id']} {row['question']}\n   attendu : {row['attendu']}\n   SQL     : {row['sql']}\n   extrait : {row['extrait']}")
print("\nDétails : outputs/eval_resultats.csv | résumé : outputs/eval_resume.md")