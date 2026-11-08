from datetime import date

import pytest

from scraper.matching import classify, detect_start, place_rank
from scraper.models import Offer

TODAY = date(2026, 11, 8)


def mk(title, location="Paris", contract="", description="", country=""):
    return Offer(source_id="t", ext_id="1", title=title, url="https://x.test/1", location=location,
                 contract=contract, description=description, country=country)


@pytest.mark.parametrize("title,location,contract,expected", [
    # real titles seen on the official catalogues (Oct–Nov 2026)
    ("Stage H/F - Analyste Actions – Janvier 2027", "Paris", "", "cible"),
    ("Stage H/F - Assistant de Gestion Fixed Income – Janvier 2027", "Paris", "", "cible"),
    ("Stage H/F - Analyste Produits Structurés et Alternatifs – Mars 2027", "Paris", "", "proche"),
    ("Stage - Assistant gestion multi-asset H/F", "Paris 15 éme", "Stage", "cible"),
    ("Stage - Assistant spécialiste produit gestions actions H/F", "Paris", "Stage", "cible"),
    ("Stage - Analyste quantitatif H/F", "Paris", "Stage", "proche"),
    ("Stage 6 mois – Analyste Crédit", "Paris", "Internship", "proche"),
    ("Stage Analyste ESG – 6 mois à compter de janvier 2027", "Paris", "", "proche"),
    ("Stage Assistant de gestion (Quantitative, Finance, Data & IA) – 6 mois – S1 2027", "Paris", "", "cible"),
    ("Stage – 6 mois – Analyste Investissement F/H", "Paris", "Stage", "cible"),
    ("2027 Investment Management Off-cycle Internship – Fixed Income", "London", "", "cible"),
    ("Stage Analyste Financier", "Paris", "Full-time | Internship", "cible"),
    # excluded
    ("Stage - Communication visuelle – Formation en Epargne Salariale et Retraite H/F", "Paris", "Stage", "exclue"),
    ("Stagiaire Risques de Marché et Développement", "Paris", "Stage", "exclue"),
    ("Stage Juridique / Conformité / Secrétariat Général", "Paris", "Internship", "exclue"),
    ("Gérant obligataire H/F", "Paris", "CDI", "exclue"),
    ("2027 – Sales – Summer Internship - Paris", "Paris, France", "", "exclue"),
    ("2027 Full-Time Analyst Program - EMEA", "London, England", "", "exclue"),
    ("Deutsche Bank Graduate Programme - Investment Bank: Corporate Finance – Paris – 2027", "Paris, France", "", "exclue"),
    ("Vice President - Asset Managers & Funds Credit Risk", "LONDON, United Kingdom", "", "exclue"),
    ("Praktikum (all genders) im Bereich Marketing & Communication bei Asset Management", "Francfort, Hesse, Allemagne", "Stage", "exclue"),
    ("Stage - Octobre - Contrôleur des risques - Actifs Non Cotés - Dette Privée (F/H)", "PARIS (75)", "Stage (6 mois)", "exclue"),
    ("Real Estate Fund Manager (F/H) - Stage Data Controller", "Paris", "Stage", "exclue"),
    ("Stage Assistant gérant", "Genève", "Stage", "exclue"),
    ("Gestionnaire supports (F/H) - Alternance - Redacteur Technique", "Paris", "", "exclue"),
])
def test_real_titles(title, location, contract, expected):
    o = classify(mk(title, location, contract), today=TODAY)
    assert o.relevance == expected, (title, o.relevance, o.reasons)


def test_start_detection():
    assert detect_start("Stage – Janvier 2027", TODAY).label == "Janvier 2027"
    assert detect_start("6 mois à compter de janvier 2027", TODAY).month == 1
    assert detect_start("Stage - Octobre - Contrôleur", TODAY).label == "Octobre 2026"
    assert detect_start("Stage S1 2027", TODAY).label == "Janvier 2027"
    assert detect_start("Date de publication : 05/11/2026", TODAY) is None
    assert detect_start("Début du stage : 02/03/2027", TODAY).label == "Mars 2027"
    assert detect_start("Stage de 6 mois, démarrage en mars", TODAY).label == "Mars 2027"
    assert detect_start("2027 Off-cycle Internship", TODAY) is None
    assert detect_start("You may apply now", TODAY) is None


def test_start_outside_window_is_excluded():
    o = classify(mk("Stage Assistant gérant actions - Septembre 2027"), today=TODAY)
    assert o.relevance == "exclue" and "Septembre 2027" in o.reasons


def test_start_near_window_is_proche():
    o = classify(mk("Stage Assistant gérant actions - Février 2027"), today=TODAY)
    assert o.relevance == "proche"
    assert o.start_label == "Février 2027"


def test_unknown_start_does_not_downgrade():
    o = classify(mk("Stage Assistant gérant actions"), today=TODAY)
    assert o.relevance == "cible" and o.start_label == "Non précisé"


def test_places():
    assert place_rank(mk("x", "Paris 15 éme"), ["Paris", "Londres"])[0] == 1
    assert place_rank(mk("x", "La Défense"), ["Paris", "Londres"])[0] == 1
    assert place_rank(mk("x", "London, England"), ["Paris", "Londres"])[0] == 2
    assert place_rank(mk("x", "France"), ["Paris", "Londres"])[0] == 3
    assert place_rank(mk("x", ""), ["Paris", "Londres"])[0] == 5
    assert place_rank(mk("x", "New York"), ["Paris", "Londres"])[0] == 9
    # BlackRock lists London first and Paris among additional locations
    assert place_rank(mk("x", "London, England, Abu Dhabi, Paris, Riyadh"), ["Paris", "Londres"])[0] == 1


def test_source_criteria_keywords_and_city():
    crit = {"types": ["Private equity"], "cities": "Genève", "keywords": "infrastructure"}
    o = classify(mk("Stage analyste infrastructure", "Genève"), crit, today=TODAY)
    assert o.relevance == "cible"
    o = classify(mk("Stage analyste infrastructure", "Paris"), crit, today=TODAY)
    assert o.relevance == "exclue"


def test_assume_internship_when_catalogue_filtered():
    o = classify(mk("Analyste Private Equity Fonds de fonds F/H"), {"types": ["Private equity"]},
                 today=TODAY, assume_internship=True)
    assert o.relevance == "cible"
    o = classify(mk("Analyste Private Equity Fonds de fonds F/H"), today=TODAY)
    assert o.relevance == "exclue"   # nothing says it is an internship


def test_duration_downgrades():
    o = classify(mk("Stage assistant gérant actions - 12 mois"), today=TODAY)
    assert o.relevance == "proche"
