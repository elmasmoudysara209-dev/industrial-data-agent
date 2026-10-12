"""
Interface web de l'Industrial Data Assistant.
Lancer avec :  streamlit run app.py
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Permet d'importer les modules du dossier src/
sys.path.append(str(Path(__file__).resolve().parent / "src"))

st.set_page_config(page_title="Industrial Data Assistant", page_icon="🏭", layout="wide")

# --- Vérifications au démarrage -----------------------------------------
DB = Path(__file__).resolve().parent / "data" / "industrie.duckdb"
if not DB.exists():
    st.error("Base de données introuvable. Lance d'abord dans le terminal : python src/generate_data.py")
    st.stop()

try:
    from agent import ask
    from kpi import livraison_kpis, production_kpis
    from report import alertes_periode
except Exception as e:
    st.error(f"Impossible de démarrer l'agent : {e}\n\nVérifie ton fichier .env (GEMINI_API_KEY).")
    st.stop()


# --- Indicateurs de la vue d'ensemble (calculés en Python, sans appel à l'IA) ---
@st.cache_data
def vue_ensemble():
    def prod(d1, d2):
        return production_kpis(date_debut=d1, date_fin=d2).iloc[0]

    def livr(d1, d2):
        return livraison_kpis(date_debut=d1, date_fin=d2).iloc[0]

    sep, aou = prod("2026-09-01", "2026-09-30"), prod("2026-08-01", "2026-08-31")
    ls, la = livr("2026-09-01", "2026-09-30"), livr("2026-08-01", "2026-08-31")
    return {
        "trs": (float(sep["trs"]), float(aou["trs"])),
        "dispo": (float(sep["disponibilite"]), float(aou["disponibilite"])),
        "rebuts": (float(sep["taux_rebuts"]), float(aou["taux_rebuts"])),
        "otd": (float(ls["otd"]), float(la["otd"])),
    }


# --- Alertes des 7 derniers jours (règle des 2 écarts-types, sans IA) ---
@st.cache_data
def alertes_recentes():
    return alertes_periode("2026-09-24", "2026-09-30")


# --- Mémoire de la session ----------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []      # ce qui est AFFICHÉ dans le chat
if "memoire" not in st.session_state:
    st.session_state.memoire = []       # le contexte compact envoyé à l'agent (F7)

EXEMPLES = [
    "Quelle ligne a le pire TRS ce mois ?",
    "Montre le Pareto des causes d'arrêt",
    "Y a-t-il des anomalies de rebuts sur L3 ?",
    "Évolution du TRS par semaine pour chaque ligne",
    "What is the on-time delivery rate for each product?",
]

# --- Barre latérale -------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Options")
    redaction = st.toggle("Réponse rédigée par l'IA (plus lent)", value=False,
                          help="Ajoute un 2e appel au modèle pour formuler une phrase avec les chiffres.")
    if st.button("🗑️ Nouvelle conversation"):
        st.session_state.messages = []
        st.session_state.memoire = []
        st.rerun()

    st.header("💡 Exemples de questions")
    for i, ex in enumerate(EXEMPLES):
        if st.button(ex, key=f"ex{i}"):
            st.session_state.pending = ex

    with st.expander("📐 Formules des KPI"):
        st.markdown(
            "- **Disponibilité** = (ouverture − arrêts) / ouverture\n"
            "- **Performance** = pièces produites / (temps de marche × cadence)\n"
            "- **Qualité** = pièces bonnes / pièces produites\n"
            "- **TRS** = Disponibilité × Performance × Qualité\n"
            "- **Taux de rebuts** = rebuts / pièces produites\n"
            "- **OTD** = commandes livrées à l'heure / commandes\n"
            "- **Taux de service** = quantité livrée / commandée"
        )
    st.caption("Données simulées, aucune donnée d'entreprise.")

# --- En-tête et indicateurs -------------------------------------------------
st.title("🏭 Industrial Data Assistant")
st.caption("Pose tes questions en langage naturel sur des données de production simulées (janvier à septembre 2026).")

v = vue_ensemble()
c1, c2, c3, c4 = st.columns(4)
c1.metric("TRS (sept.)", f"{v['trs'][0] * 100:.1f} %", f"{(v['trs'][0] - v['trs'][1]) * 100:+.1f} pt vs août")
c2.metric("Disponibilité (sept.)", f"{v['dispo'][0] * 100:.1f} %",
          f"{(v['dispo'][0] - v['dispo'][1]) * 100:+.1f} pt vs août")
c3.metric("Taux de rebuts (sept.)", f"{v['rebuts'][0] * 100:.2f} %",
          f"{(v['rebuts'][0] - v['rebuts'][1]) * 100:+.2f} pt vs août", delta_color="inverse")
c4.metric("OTD (sept.)", f"{v['otd'][0] * 100:.1f} %", f"{(v['otd'][0] - v['otd'][1]) * 100:+.1f} pt vs août")

alertes = alertes_recentes()
if alertes:
    with st.expander(f"🚨 {len(alertes)} alerte(s) sur les 7 derniers jours (24 au 30 sept.)", expanded=True):
        for a in alertes[:8]:
            val = f"{a['valeur'] * 100:.2f} %" if a["kind"] == "pct2" else f"{a['valeur'] * 100:.1f} %"
            st.markdown(f"- **{a['ligne']}** : {a['kpi']} dégradé sur {a['nb_jours']} jour(s) "
                        f"(pire jour : {a['pire_jour']}, {val})")
else:
    st.success("✅ Aucune alerte sur les 7 derniers jours.")
st.divider()


# --- Affichage d'un message -------------------------------------------------
def afficher(message: dict, index: int):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] != "assistant":
            return
        if message.get("figure") is not None:
            st.plotly_chart(message["figure"], key=f"fig_{index}")
        if message.get("lignes"):
            st.dataframe(pd.DataFrame(message["lignes"]), hide_index=True)
        if message.get("sql"):
            with st.expander("🔍 Requête exécutée (transparence)"):
                st.code(message["sql"], language="sql")
        if message.get("meta"):
            st.caption(message["meta"])


# 1. On réaffiche tout l'historique
for i, m in enumerate(st.session_state.messages):
    afficher(m, i)

# 2. On traite une nouvelle question (saisie ou bouton d'exemple)
question = st.chat_input("Pose ta question (français ou anglais)...")
if "pending" in st.session_state:
    question = st.session_state.pop("pending")

if question:
    msg_user = {"role": "user", "content": question}
    afficher(msg_user, len(st.session_state.messages))

    with st.spinner("Analyse en cours..."):
        r = ask(question, st.session_state.memoire, redaction)

    msg_ia = {
        "role": "assistant",
        "content": r["reponse"],
        "sql": r["sql"],
        "lignes": r["lignes"],
        "figure": r["figure"],
        "meta": f"{r['nb_appels_llm']} appel(s) au modèle · {r['duree_s']} s",
    }
    afficher(msg_ia, len(st.session_state.messages) + 1)
    st.session_state.messages += [msg_user, msg_ia]