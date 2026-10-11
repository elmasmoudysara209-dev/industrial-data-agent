from pathlib import Path

import pandas as pd

from agent import ask

Path("outputs").mkdir(exist_ok=True)
memoire, nb_graphiques = [], 0
redaction = input("Réponse rédigée par l'IA avec les chiffres (2e appel, plus lent) ? o/N : ").strip().lower() == "o"

print("Industrial Data Assistant v2 (tape 'quit' pour quitter)")
while True:
    question = input("\nVous > ").strip()
    if question.lower() in ("quit", "exit", "q"):
        break
    if not question:
        continue

    r = ask(question, memoire, redaction)
    print("\nAssistant >", r["reponse"])
    if r["sql"]:
        print("\n[SQL]", r["sql"])
    if r["lignes"]:
        print(pd.DataFrame(r["lignes"]).head(15).to_string(index=False))
    if r["figure"] is not None:
        chemin = f"outputs/graphique_agent_{nb_graphiques}.html"
        r["figure"].write_html(chemin)
        nb_graphiques += 1
        print("[graphique]", chemin)
    print(f"\n[{r['nb_appels_llm']} appel(s) LLM, {r['duree_s']} s]")