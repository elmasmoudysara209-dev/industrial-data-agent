"""
Agent v2 (architecture « text-to-SQL », conseillée par un ami).

UN SEUL appel au LLM renvoie : la requête SQL + l'explication + le graphique voulu.
Ensuite Python exécute la requête (lecture seule) et affiche le résultat.
Le modèle écrit sa requête sans voir les données : il ne peut donc inventer aucun chiffre.
"""
import json
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from tools import chart_from_rows, detect_anomaly, run_sql

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
MAX_MEMOIRE = 4          # nombre d'échanges conservés dans le contexte
client = genai.Client()

SYSTEM_PROMPT = """Tu es « Industrial Data Assistant ». Tu réponds à des questions sur des données de production
industrielle en appelant TOUJOURS la fonction `repondre`, une seule fois.

== SCHÉMA (DuckDB, du 2026-01-01 au 2026-09-30, données simulées) ==
production(horodatage, jour DATE, ligne, equipe, produit, temps_ouverture_min, temps_arret_min,
           cadence_theorique, pieces_produites, pieces_bonnes, pieces_rebut)   -- 1 ligne = 1 heure d'une ligne
arrets(horodatage, jour DATE, ligne, equipe, cause, duree_min)
qualite(jour DATE, ligne, defaut, quantite)
commandes(id_commande, date_commande, produit, quantite_commandee, date_livraison_promise,
          date_livraison_reelle, quantite_livree)
stocks(jour DATE, produit, stock_fin_jour)
Valeurs : ligne = L1..L5 ; equipe = Matin, Apres-midi, Nuit ; produit = REF-A..REF-D ;
cause = Panne mécanique, Changement de série, Manque matière, Réglage, Panne électrique,
Attente maintenance, Nettoyage ; defaut = Rayure, Dimension hors tolérance, Défaut d'assemblage, Soudure, Autre.
« ce mois » / « le dernier mois » = septembre 2026 (2026-09-01 à 2026-09-30), sauf indication contraire.

== LOGIQUE MÉTIER : formules KPI (table production) ==
RÈGLE D'OR : toujours SUM() d'abord, puis diviser. JAMAIS de moyenne (AVG) de ratios.
disponibilite = 1 - SUM(temps_arret_min) * 1.0 / SUM(temps_ouverture_min)
performance   = SUM(pieces_produites) * 1.0 / SUM((temps_ouverture_min - temps_arret_min) / 60.0 * cadence_theorique)
qualite       = SUM(pieces_bonnes) * 1.0 / SUM(pieces_produites)
trs           = disponibilite * performance * qualite   (recopie les trois expressions, multipliées)
taux_rebuts   = SUM(pieces_rebut) * 1.0 / SUM(pieces_produites)
temps_arret   = SUM(temps_arret_min)   (table production)
Livraisons (table commandes ; période filtrée sur date_livraison_promise) :
otd           = SUM(CASE WHEN date_livraison_reelle <= date_livraison_promise THEN 1 ELSE 0 END) * 1.0 / COUNT(*)
taux_service  = SUM(quantite_livree) * 1.0 / SUM(quantite_commandee)
Regroupements : GROUP BY ligne / equipe / produit ; semaine = date_trunc('week', jour) ;
mois = date_trunc('month', jour).

== RÈGLES ==
1. Appelle `repondre` exactement une fois. Ne réponds jamais en texte libre.
2. mode = "sql" : fournis UNE requête SELECT (ou WITH ... SELECT) DuckDB, sans point-virgule.
   Arrondis les ratios avec ROUND(..., 4), ajoute un ORDER BY, et LIMIT 50 sauf si on demande tout.
   Filtre les dates avec jour BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'.
3. mode = "anomalie" : pour « y a-t-il une anomalie / un pic / une dérive ? ». Renseigne kpi_anomalie,
   et ligne_anomalie si une ligne est citée.
4. mode = "hors_perimetre" : si la question n'a aucun rapport avec ces données ou ne peut pas être
   traitée avec elles ; explique pourquoi dans `explication`.
5. `explication` : 1 à 2 phrases, dans la langue de la question (français ou anglais) : ce que calcule la
   requête (période, filtres, formule). Tu ne connais pas encore le résultat : n'écris AUCUN chiffre de résultat.
6. Graphique : si l'utilisateur en demande un, choisis type_graphique et donne les NOMS EXACTS des colonnes
   de ta requête (graphique_x, graphique_y, et graphique_couleur s'il y a plusieurs séries).
   Pareto : requête sur arrets, x = cause, y = minutes (SUM(duree_min)). Sinon type_graphique = "aucun".
7. Utilise le CONTEXTE fourni pour les questions de suivi (« et pour L5 ? » = même analyse, autre ligne).
"""

LIGNES = ["L1", "L2", "L3", "L4", "L5"]
KPI_ANOMALIE = ["trs", "disponibilite", "performance", "qualite", "taux_rebuts", "temps_arret"]

REPONDRE = {
    "name": "repondre",
    "description": "Unique façon de répondre : requête SQL à exécuter, explication, graphique éventuel.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["sql", "anomalie", "hors_perimetre"]},
            "sql": {"type": "string", "description": "UNE requête SELECT DuckDB (mode sql uniquement)."},
            "explication": {"type": "string",
                            "description": "1-2 phrases : ce que calcule la requête. AUCUN chiffre de résultat."},
            "type_graphique": {"type": "string",
                               "enum": ["aucun", "barres", "courbe", "pareto", "histogramme"]},
            "graphique_x": {"type": "string", "description": "Nom exact de la colonne en abscisse."},
            "graphique_y": {"type": "string", "description": "Nom exact de la colonne en ordonnée."},
            "graphique_couleur": {"type": "string", "description": "Colonne qui sépare les séries (optionnel)."},
            "graphique_titre": {"type": "string"},
            "kpi_anomalie": {"type": "string", "enum": KPI_ANOMALIE},
            "ligne_anomalie": {"type": "string", "enum": LIGNES},
            "seuil_anomalie": {"type": "number", "description": "En écarts-types. Défaut : 2."},
        },
        "required": ["mode", "explication"],
    },
}

CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=[REPONDRE])],
    # On FORCE le modèle à appeler `repondre` : un seul appel, pas de bavardage libre
    tool_config=types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(mode="ANY", allowed_function_names=["repondre"])
    ),
)


def _plan(prompt: str) -> dict:
    """UN appel LLM. Renvoie les arguments de la fonction `repondre`."""
    for tentative in range(3):
        try:
            resp = client.models.generate_content(model=MODEL, contents=prompt, config=CONFIG)
            break
        except errors.APIError as e:
            if e.code in (429, 503) and tentative < 2:      # quota gratuit atteint : on patiente
                time.sleep(15 * (tentative + 1))
                continue
            raise
    appels = resp.function_calls
    if not appels:
        raise ValueError("Le modèle n'a pas renvoyé de plan d'action.")
    return dict(appels[0].args)


def _contexte(memoire: list) -> str:
    """Contexte COMPACT : question + SQL + extrait du résultat des derniers échanges (pas tout l'historique)."""
    if not memoire:
        return ""
    lignes = ["CONTEXTE (derniers échanges, du plus ancien au plus récent) :"]
    for m in memoire[-MAX_MEMOIRE:]:
        lignes.append(f"- Question : {m['question']}\n  SQL : {m['sql'] or 'aucun'}\n  Résultat (extrait) : {m['resume']}")
    return "\n".join(lignes) + "\n\n"


def _rediger(question: str, sql: str, lignes: list) -> str:
    """OPTIONNEL (2e appel) : phrase rédigée à partir du résultat déjà EXÉCUTÉ."""
    prompt = (f"Question : {question}\nRequête exécutée : {sql}\n"
              f"Résultat (JSON, extrait) : {json.dumps(lignes[:30], ensure_ascii=False, default=str)}\n\n"
              "Rédige une réponse concise (3 phrases maximum) dans la langue de la question. "
              "Utilise UNIQUEMENT les chiffres du résultat ; ratios en % avec une décimale ; ne parle pas de SQL.")
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    return resp.text or ""


def _texte_anomalies(res: dict):
    """Met en forme le résultat de detect_anomaly sans appeler le LLM."""
    if "error" in res:
        return res["error"], []
    morceaux, tableau = [], []
    for r in res["resultats_par_ligne"]:
        d = r["derive_detail"]
        morceaux.append(
            f"{r['ligne']} : {r['nb_jours_anormaux']} jour(s) anormal(aux) ; "
            f"dérive {'DÉTECTÉE' if r['derive_detectee'] else 'non détectée'} "
            f"(30 derniers jours : {d['moyenne_30_derniers_jours']} contre {d['moyenne_avant']} avant)."
        )
        for j in r["jours_anormaux"]:
            tableau.append({"ligne": r["ligne"], **j})
    return ("\n".join(morceaux) or "Aucune anomalie détectée."), tableau


def ask(question: str, memoire: list | None = None, redaction: bool = False) -> dict:
    """
    Pose une question. `memoire` : liste réutilisée d'une question à l'autre (contexte compact).
    `redaction=True` : ajoute un 2e appel LLM pour rédiger la réponse avec les chiffres (plus lent).
    """
    t0 = time.time()
    memoire = memoire if memoire is not None else []
    sortie = {"reponse": "", "sql": None, "colonnes": [], "lignes": [], "figure": None,
              "nb_appels_llm": 0, "duree_s": 0.0}
    prompt = _contexte(memoire) + f"QUESTION ACTUELLE : {question}"

    try:
        plan = _plan(prompt)
        sortie["nb_appels_llm"] += 1
        mode = plan.get("mode", "sql")
        explication = plan.get("explication", "")

        if mode == "hors_perimetre":
            sortie["reponse"] = explication

        elif mode == "anomalie":
            res = detect_anomaly(kpi=plan.get("kpi_anomalie") or "taux_rebuts",
                                 ligne=plan.get("ligne_anomalie"),
                                 seuil=float(plan.get("seuil_anomalie") or 2.0))
            texte, tableau = _texte_anomalies(res)
            sortie["reponse"] = f"{explication}\n\n{texte}"
            sortie["lignes"] = tableau
            sortie["colonnes"] = list(tableau[0].keys()) if tableau else []
            sortie["sql"] = "(analyse statistique Python : z-score, seuil de 2 écarts-types)"

        else:
            res = run_sql(plan.get("sql") or "")
            if "error" in res:                                   # UNE seule tentative de réparation
                prompt2 = (prompt + f"\n\nTa requête précédente a échoué.\nRequête : {plan.get('sql')}\n"
                           f"Erreur : {res['error']}\nCorrige-la.")
                plan = _plan(prompt2)
                sortie["nb_appels_llm"] += 1
                explication = plan.get("explication", explication)
                res = run_sql(plan.get("sql") or "")
            sortie["sql"] = plan.get("sql")

            if "error" in res:
                sortie["reponse"] = f"Je n'ai pas réussi à exécuter la requête : {res['error']}"
            else:
                sortie["colonnes"], sortie["lignes"] = res["colonnes"], res["lignes"]
                n = res["nb_lignes_total"]
                if n == 0:
                    suite = "Aucune donnée ne correspond à ces critères."
                elif n == 1:
                    suite = "Résultat : " + ", ".join(f"{k} = {v}" for k, v in res["lignes"][0].items())
                else:
                    suite = f"{n} lignes de résultat : voir le tableau."
                sortie["reponse"] = f"{explication}\n\n{suite}"

                if redaction and n > 0:                          # option : 2e appel pour rédiger
                    try:
                        sortie["reponse"] = _rediger(question, sortie["sql"], res["lignes"]) or sortie["reponse"]
                        sortie["nb_appels_llm"] += 1
                    except Exception:
                        pass

                if plan.get("type_graphique", "aucun") != "aucun" and n > 0:
                    try:
                        sortie["figure"] = chart_from_rows(
                            res["lignes"], plan["type_graphique"], plan.get("graphique_x"),
                            plan.get("graphique_y"), plan.get("graphique_couleur"),
                            plan.get("graphique_titre", ""))
                    except Exception as e:
                        sortie["reponse"] += f"\n\n(Graphique non créé : {e})"

        # Gestion du contexte : on ne garde que l'essentiel des derniers échanges
        memoire.append({"question": question, "sql": sortie["sql"], "resume": str(sortie["lignes"][:5])[:400]})
        del memoire[:-MAX_MEMOIRE]

    except Exception as e:
        sortie["reponse"] = f"Erreur lors de l'appel au modèle : {e}"

    sortie["duree_s"] = round(time.time() - t0, 1)
    return sortie