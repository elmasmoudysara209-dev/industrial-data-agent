import time

import agent as agent_v2
import agent_v1

QUESTIONS = [
    "Quelle ligne a le pire TRS en septembre ?",
    "Montre-moi le Pareto des causes d'arrêt de L2",
    "Y a-t-il des anomalies de rebuts sur L3 ?",
    "Combien de pièces a produit L1 en juin ?",
    "What is the on-time delivery rate for each product?",
]

for q in QUESTIONS:
    t = time.time()
    r1 = agent_v1.ask(q, [])
    d1 = time.time() - t
    r2 = agent_v2.ask(q, [])
    print(f"\nQ : {q}")
    print(f"  v1 (outils)   : {d1:.1f} s, {len(r1['appels_outils'])} outil(s) appelé(s)")
    print(f"  v2 (text2SQL) : {r2['duree_s']} s, {r2['nb_appels_llm']} appel(s) LLM")
    print("  SQL v2 :", r2["sql"])
    time.sleep(3)      # ménage le quota gratuit