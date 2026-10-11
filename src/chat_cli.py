from pathlib import Path

from agent import ask

Path("outputs").mkdir(exist_ok=True)
historique = []        # mémoire de la conversation
nb_graphiques = 0

print("Industrial Data Assistant (tape 'quit' pour quitter)")
while True:
    question = input("\nVous > ").strip()
    if question.lower() in ("quit", "exit", "q"):
        break
    if not question:
        continue

    r = ask(question, historique)
    print("\nAssistant >", r["reponse"])

    for a in r["appels_outils"]:
        print("  [outil]", a["outil"], a["arguments"])
    for sql in r["requetes_sql"]:
        print("  [SQL exécuté]", sql)
    for g in r["graphiques"]:
        chemin = f"outputs/graphique_agent_{nb_graphiques}.html"
        g["figure"].write_html(chemin)
        nb_graphiques += 1
        print("  [graphique]", chemin)