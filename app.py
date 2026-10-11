import os
import sys

import streamlit as st

# Les fichiers de src/ s'importent entre eux sans préfixe (from tools import ...),
# donc on ajoute src/ au chemin de recherche Python.
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)   # pour que "data/industrie.duckdb" soit trouvé

from agent import ask  # noqa: E402

st.set_page_config(page_title="Industrial Data Assistant", page_icon="🏭", layout="wide")
st.title("🏭 Industrial Data Assistant")
st.caption("Pose une question sur la production : TRS, rebuts, arrêts, livraisons, stocks...")

# Mémoire de conversation (F7) : la liste "history" est celle que ask() remplit
if "history" not in st.session_state:
    st.session_state.history = []
# Historique d'affichage (texte + graphiques + SQL)
if "chat" not in st.session_state:
    st.session_state.chat = []


def afficher_message(m):
    with st.chat_message(m["role"]):
        st.markdown(m["texte"])
        for fig in m.get("graphiques", []):
            try:
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                st.write(fig)
        if m.get("sql"):
            with st.expander(f"🔍 Requête(s) SQL exécutée(s) ({len(m['sql'])})"):
                for q in m["sql"]:
                    st.code(str(q), language="sql")
        if m.get("outils"):
            with st.expander("🛠️ Outils utilisés"):
                for a in m["outils"]:
                    st.write(f"**{a['outil']}**")
                    st.json(a["arguments"])


# ---- Barre latérale ----
with st.sidebar:
    st.header("Questions d'exemple")
    exemples = [
        "Quel est le TRS moyen par ligne ?",
        "Quelle ligne a le pire taux de rebuts en mars ?",
        "Donne-moi le Pareto des causes d'arrêt de la ligne L2",
        "Y a-t-il des anomalies sur L3 ?",
        "Y a-t-il des anomalies sur L5 ?",
        "Quel est le taux de service global ?",
    ]
    for ex in exemples:
        if st.button(ex, use_container_width=True):
            st.session_state["pending"] = ex
    st.divider()
    if st.button("🗑️ Nouvelle conversation", use_container_width=True):
        st.session_state.history = []
        st.session_state.chat = []
        st.rerun()

# ---- Historique ----
for m in st.session_state.chat:
    afficher_message(m)

# ---- Nouvelle question ----
question = st.chat_input("Pose ta question...") or st.session_state.pop("pending", None)
if question:
    st.session_state.chat.append({"role": "user", "texte": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Analyse en cours..."):
            res = ask(question, st.session_state.history)

    st.session_state.chat.append({
        "role": "assistant",
        "texte": res["reponse"],
        "graphiques": res["graphiques"],
        "sql": res["requetes_sql"],
        "outils": res["appels_outils"],
    })
    st.rerun()