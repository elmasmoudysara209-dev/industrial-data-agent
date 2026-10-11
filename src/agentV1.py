"""
Agent « Industrial Data Assistant » : boucle LLM (Gemini) + outils.
"""
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from tool_specs import TOOL_DECLARATIONS
from tools import CHARTS, QUERY_LOG, run_tool

load_dotenv()

# Le nom du modèle peut être changé dans .env avec GEMINI_MODEL=...
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
MAX_STEPS = 6          # nombre maximum d'allers-retours avec les outils (anti-boucle infinie)

client = genai.Client()   # lit GEMINI_API_KEY dans .env

SYSTEM_PROMPT = """Tu es « Industrial Data Assistant », un assistant d'analyse de données de production industrielle.

DONNÉES (base DuckDB, période du 2026-01-01 au 2026-09-30, données simulées) :
- production(horodatage, jour, ligne, equipe, produit, temps_ouverture_min, temps_arret_min,
  cadence_theorique, pieces_produites, pieces_bonnes, pieces_rebut) : une ligne = une heure d'une ligne.
- arrets(horodatage, jour, ligne, equipe, cause, duree_min)
- qualite(jour, ligne, defaut, quantite)
- commandes(id_commande, date_commande, produit, quantite_commandee, date_livraison_promise,
  date_livraison_reelle, quantite_livree)
- stocks(jour, produit, stock_fin_jour)
Valeurs : lignes L1 à L5 ; équipes Matin, Apres-midi, Nuit ; produits REF-A à REF-D ;
causes d'arrêt : Panne mécanique, Changement de série, Manque matière, Réglage, Panne électrique,
Attente maintenance, Nettoyage.
La dernière date disponible est le 2026-09-30 : « ce mois » ou « le dernier mois » signifie septembre 2026
(du 2026-09-01 au 2026-09-30), sauf indication contraire.

RÈGLES :
1. N'invente JAMAIS un chiffre. Tout chiffre doit venir du résultat d'un outil.
2. Pour un KPI (TRS, disponibilité, performance, qualité, taux de rebuts, temps d'arrêt, OTD, taux de service),
   utilise compute_kpi, jamais du SQL. Utilise run_sql pour le reste, make_chart pour les graphiques,
   detect_anomaly pour les anomalies et dérives.
3. Si un outil renvoie une erreur, corrige ta demande et réessaie.
4. Si les données ne permettent pas de répondre, dis-le clairement au lieu de deviner.
5. Réponds dans la langue de la question (français ou anglais), de façon concise : d'abord la réponse,
   puis une phrase d'explication utile (période, filtre utilisé, ordre de grandeur).
6. Écris les ratios en pourcentage avec une décimale (0,8123 devient 81,2 %).
7. Quand tu crées un graphique, dis simplement qu'il est affiché sous ta réponse et commente-le brièvement.
"""

CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
    # On gère la boucle nous-mêmes pour garder le contrôle et la transparence
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)


def _generate(contents):
    """Appelle Gemini, avec quelques nouvelles tentatives si le quota gratuit est atteint."""
    for tentative in range(3):
        try:
            return client.models.generate_content(model=MODEL, contents=contents, config=CONFIG)
        except errors.APIError as e:
            if e.code in (429, 503) and tentative < 2:
                time.sleep(15 * (tentative + 1))
                continue
            raise


def ask(question: str, history: list | None = None) -> dict:
    """
    Pose une question à l'agent.
    - history : liste qui conserve la conversation (mémoire). On la réutilise d'une question à l'autre.
    Renvoie un dictionnaire : reponse, appels_outils, requetes_sql, graphiques.
    """
    contents = history if history is not None else []
    taille_avant = len(contents)
    n_sql, n_graph = len(QUERY_LOG), len(CHARTS)
    appels = []

    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))

    try:
        response = _generate(contents)

        for _ in range(MAX_STEPS):
            if not response.function_calls:
                break                                           # Gemini a fini : réponse rédigée

            # 1. on garde la demande de Gemini telle quelle dans l'historique
            contents.append(response.candidates[0].content)

            # 2. on exécute chaque outil demandé
            reponses_outils = []
            for appel in response.function_calls:
                arguments = dict(appel.args) if appel.args else {}
                appels.append({"outil": appel.name, "arguments": arguments})
                resultat = run_tool(appel.name, arguments)
                reponses_outils.append(
                    types.Part.from_function_response(name=appel.name, response={"result": resultat})
                )

            # 3. on renvoie les résultats à Gemini
            contents.append(types.Content(role="user", parts=reponses_outils))
            response = _generate(contents)

        texte = response.text
        if response.candidates and response.candidates[0].content:
            contents.append(response.candidates[0].content)     # mémoire de la réponse finale
        if not texte:
            texte = "Je n'ai pas réussi à formuler une réponse. Peux-tu reformuler ta question ?"

    except Exception as e:
        del contents[taille_avant:]          # on annule ce tour pour ne pas casser l'historique
        texte = f"Erreur lors de l'appel au modèle : {e}"

    return {
        "reponse": texte,
        "appels_outils": appels,
        "requetes_sql": QUERY_LOG[n_sql:],
        "graphiques": CHARTS[n_graph:],
    }