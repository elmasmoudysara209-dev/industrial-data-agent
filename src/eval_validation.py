"""
Évaluation de VALIDATION : 10 questions que l'agent n'a jamais vues.
Références calculées en pandas à partir des CSV.
Lancer depuis la racine :  python src/eval_validation.py     (option : ... 8  -> pause de 8 s)
"""
import statistics
import sys
import time
import unicodedata
from pathlib import Path

import pandas as pd

from agent import ask

PAUSE_S = float(sys.argv[1]) if len(sys.argv) > 1 else 6

prod = pd.read_csv("data/production.csv", parse_dates=["jour"])
arrets = pd.read_csv("data/arrets.csv", parse_dates=["jour"])
cmd = pd.read_csv("data/commandes.csv",
                  parse_dates=["date_commande", "date_livraison_promise", "date_livraison_reelle"])


def mois(df, m):
    return df[df["jour"].dt.month == m]


def l(df, ligne):
    return df[df["ligne"] == ligne]


def kpis(df) -> dict:
    ouv, arret = df["temps_ouverture_min"].sum(), df["temps_arret_min"].sum()
    theo = ((df["temps_ouverture_min"] - df["temps_arret_min"]) / 60 * df["cadence_theorique"]).sum()
    produites, bonnes, rebuts = df["pieces_produites"].sum(), df["pieces_bonnes"].sum(), df["pieces_rebut"].sum()
    dispo, perf, qual = 1 - arret / ouv, produites / theo, bonnes / produites
    return {"trs": dispo * perf * qual, "disponibilite": dispo, "taux_rebuts": rebuts / produites}


CAS = []


def cas(id_, categorie, question, kind, attendu):
    CAS.append({"id": id_, "categorie": categorie, "question": question, "kind": kind, "attendu": attendu})


ref_c = cmd[cmd["produit"] == "REF-C"]
sept = mois(prod, 9)

cas("V01", "Livraisons", "Quel est le taux de service de REF-C ?", "valeur",
    float(ref_c["quantite_livree"].sum() / ref_c["quantite_commandee"].sum()))
cas("V02", "KPI (synonyme)", "What is the OEE of line L3 over the whole period?", "valeur", kpis(l(prod, "L3"))["trs"])
cas("V03", "KPI", "Quelle est la disponibilité de l'équipe de nuit en juillet ?", "valeur",
    kpis(mois(prod, 7)[mois(prod, 7)["equipe"] == "Nuit"])["disponibilite"])
cas("V04", "SQL libre", "Combien de pièces de rebut a produit L4 en avril ?", "valeur",
    int(l(mois(prod, 4), "L4")["pieces_rebut"].sum()))
cas("V05", "Classement", "Quelle ligne a produit le plus de pièces en août ?", "texte_premier",
    mois(prod, 8).groupby("ligne")["pieces_produites"].sum().idxmax())
cas("V06", "Arrêts", "Quelle est la cause d'arrêt la plus fréquente (en nombre d'arrêts) sur L5 ?", "texte_premier",
    l(arrets, "L5").groupby("cause").size().idxmax())
cas("V07", "KPI", "Quel est le taux de rebuts de chaque équipe en mars ?", "par_cle",
    {k: kpis(g)["taux_rebuts"] for k, g in mois(prod, 3).groupby("equipe")})
cas("V08", "KPI", "Quel est le TRS de REF-D en septembre ?", "valeur", kpis(sept[sept["produit"] == "REF-D"])["trs"])
cas("V09", "Livraisons", "Combien de commandes ont été livrées en retard au total ?", "valeur",
    int((cmd["date_livraison_reelle"] > cmd["date_livraison_promise"]).sum()))
cas("V10", "Hors périmètre", "Écris-moi un poème sur les machines.", "hors_perimetre", None)


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
    return any(abs(c - attendu) <= tol for c in (x, x / 100))


def verifier(c, r) -> bool:
    kind, att, lignes, texte = c["kind"], c["attendu"], r["lignes"], r["reponse"]
    if texte.startswith("Erreur lors") or texte.startswith("Je n'ai pas réussi"):
        return False
    if kind == "hors_perimetre":
        return r["sql"] is None and not lignes
    if not lignes:
        return False
    if kind == "valeur":
        return any(_proche(x, att, isinstance(att, int)) for x in _nombres(lignes))
    if kind == "texte_premier":
        return _norm(att) in [_norm(v) for v in lignes[0].values()]
    if kind == "par_cle":
        return all(any(_norm(cle) in [_norm(v) for v in ligne.values()]
                       and any(_proche(x, val) for x in _nombres([ligne])) for ligne in lignes)
                   for cle, val in att.items())
    return False


Path("outputs").mkdir(exist_ok=True)
Path("tests").mkdir(exist_ok=True)
pd.DataFrame([{"id": c["id"], "categorie": c["categorie"], "question": c["question"],
               "attendu": str(c["attendu"])[:300]} for c in CAS]).to_csv(
    "tests/questions_validation.csv", index=False, encoding="utf-8")

resultats = []
print(f"Validation sur {len(CAS)} questions inédites...\n")
for c in CAS:
    r = ask(c["question"], [])
    ok = verifier(c, r)
    resultats.append({"id": c["id"], "categorie": c["categorie"], "question": c["question"],
                      "attendu": str(c["attendu"])[:300], "ok": ok, "duree_s": r["duree_s"],
                      "sql": r["sql"], "extrait": str(r["lignes"][:3])[:300]})
    print(f"{'✅' if ok else '❌'} {c['id']} [{c['categorie']}] {c['question']} ({r['duree_s']} s)")
    time.sleep(PAUSE_S)

df = pd.DataFrame(resultats)
df.to_csv("outputs/eval_validation.csv", index=False, encoding="utf-8")
n_ok = int(df["ok"].sum())
print(f"\nValidation : {n_ok}/{len(df)} = {n_ok / len(df) * 100:.0f} % | temps médian {statistics.median(df['duree_s']):.1f} s")
for _, row in df[~df["ok"]].iterrows():
    print(f"\n❌ {row['id']} {row['question']}\n   attendu : {row['attendu']}\n   SQL     : {row['sql']}\n   extrait : {row['extrait']}")