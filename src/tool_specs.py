"""Description des outils pour Gemini (noms, rôles, paramètres)."""

LIGNES = ["L1", "L2", "L3", "L4", "L5"]
KPI_PRODUCTION = ["trs", "disponibilite", "performance", "qualite", "taux_rebuts", "temps_arret"]

TOOL_DECLARATIONS = [
    {
        "name": "run_sql",
        "description": (
            "Exécute une requête SQL de lecture (SELECT) sur la base de production DuckDB. "
            "À utiliser pour les questions que compute_kpi ne couvre pas : comptages, sommes, "
            "listes, stocks, défauts qualité, commandes, périodes précises, etc. "
            "Ne JAMAIS recalculer un KPI (TRS, disponibilité...) en SQL : utiliser compute_kpi."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Requête SQL SELECT (dialecte DuckDB)."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "compute_kpi",
        "description": (
            "Calcule un KPI industriel avec les formules officielles du projet. "
            "Toujours utiliser cet outil pour TRS, disponibilité, performance, qualité, taux de "
            "rebuts, temps d'arrêt, OTD (livraison à l'heure) et taux de service."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kpi": {
                    "type": "string",
                    "enum": KPI_PRODUCTION + ["otd", "taux_service"],
                    "description": "Le KPI à calculer.",
                },
                "ligne": {"type": "string", "enum": LIGNES,
                          "description": "Filtrer sur une ligne (ignoré pour otd et taux_service)."},
                "date_debut": {"type": "string", "description": "Début de période, format AAAA-MM-JJ."},
                "date_fin": {"type": "string", "description": "Fin de période, format AAAA-MM-JJ."},
                "groupby": {
                    "type": "string",
                    "enum": ["ligne", "equipe", "produit", "jour", "semaine", "mois"],
                    "description": "Regrouper le résultat. Pour otd et taux_service : seulement 'produit' ou 'mois'.",
                },
            },
            "required": ["kpi"],
        },
    },
    {
        "name": "make_chart",
        "description": (
            "Crée un graphique affiché à l'utilisateur. 'pareto' = causes d'arrêt, "
            "'tendance' = évolution d'un KPI dans le temps, 'histogramme' = répartition d'un KPI par jour."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "type_graphique": {"type": "string", "enum": ["pareto", "tendance", "histogramme"]},
                "kpi": {"type": "string", "enum": KPI_PRODUCTION,
                        "description": "KPI à tracer (tendance et histogramme). Défaut : trs."},
                "ligne": {"type": "string", "enum": LIGNES, "description": "Une ligne (sinon toutes)."},
                "date_debut": {"type": "string", "description": "Format AAAA-MM-JJ."},
                "date_fin": {"type": "string", "description": "Format AAAA-MM-JJ."},
                "periode": {"type": "string", "enum": ["jour", "semaine", "mois"],
                            "description": "Pas de temps pour une tendance. Défaut : semaine."},
            },
            "required": ["type_graphique"],
        },
    },
    {
        "name": "detect_anomaly",
        "description": (
            "Détecte les anomalies d'un KPI : jours dont la valeur s'écarte de plus de `seuil` "
            "écarts-types de la moyenne (pics), et dérive sur les 30 derniers jours. "
            "À utiliser pour « y a-t-il un problème / une anomalie / une dérive ? »."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kpi": {"type": "string", "enum": KPI_PRODUCTION},
                "ligne": {"type": "string", "enum": LIGNES, "description": "Une ligne (sinon toutes)."},
                "seuil": {"type": "number", "description": "Seuil en écarts-types. Défaut : 2."},
            },
            "required": ["kpi"],
        },
    },
]