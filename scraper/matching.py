"""Decide whether an offer fits Luca's criteria.

Result for each offer:
  * relevance  "cible"  : matches métier, contract, place and start date
               "proche" : worth a look (adjacent métier, nearby start month...)
               "exclue" : not an internship, wrong place, wrong date or métier
  * start_label           : detected start ("Janvier 2027") or "Non précisé"
  * reasons               : short French explanations shown on the site

Default criteria (from Luca, 25/10/2026): 6-month internship in asset
management / equity research / investment specialist / investment analyst,
starting January or March 2027, Paris first, then London. A source can
override them (form "Ajouter une entreprise").
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .models import Offer, fold

# Bump when the rules change: the robot then re-sorts the offers already in the database.
MATCHING_VERSION = "2026-11-09.2"

DEFAULT_CRITERIA = {
    "types": ["Gestion d'actifs", "Equity research", "Investment specialist", "Investment analyst"],
    "starts": ["Janvier 2027", "Mars 2027"],
    "keywords": "",
    "cities": ["Paris", "Londres"],
}

# ---------------------------------------------------------------- métiers
# Every label the site's form can offer, with synonyms (accent-free, lower case).
TYPE_SYNONYMS: dict[str, list[str]] = {
    "Gestion d'actifs": [
        r"gestion d'?actifs?", r"asset manag", r"gestion de portefeuilles?", r"portfolio manag",
        r"assistant\(?e?\)?\s*(de\s+)?gerant", r"gerant", r"fund manag", r"gestion actions?",
        r"gestion obligataire", r"gestion (de )?taux", r"gestion multi", r"gestion diversifiee",
        r"multi[- ]?asset", r"cross[- ]?assets?", r"assistant\(?e?\)?\s*de gestion",
        r"investment management", r"gestion quantitative", r"gestion d'?actions",
        r"gestion (de )?fonds", r"gestion (de )?credit", r"allocation d'?actifs",
    ],
    "Equity research": [
        r"equity research", r"analyste actions?", r"analyste financier", r"financial analyst",
        r"research analyst", r"buy[- ]side", r"sell[- ]side", r"recherche actions?",
        r"equity analyst", r"analyste equity", r"analyste (sectoriel|fondamental)",
        r"stock[- ]?pick", r"recherche fondamentale",
    ],
    "Investment specialist": [
        r"investment specialist", r"product specialist", r"specialiste (de )?produits?",
        r"specialiste (en )?investissement", r"investment strategist", r"client portfolio manag",
        r"investment (product|solutions) specialist",
    ],
    "Investment analyst": [
        r"investment analyst", r"analyste (en |d'?)?investissements?", r"investment associate",
        r"analyst,? investment", r"investment research",
    ],
    "Private equity": [r"private equity", r"capital[- ]investissement", r"fonds de fonds",
                       r"capital developpement", r"buy[- ]?out", r"private assets", r"growth equity"],
    "Crédit / obligataire": [r"credit", r"high yield", r"fixed income", r"obligat", r"dette privee",
                             r"private debt", r"titrisation", r"securiti[sz]ation"],
    "Quant": [r"quant", r"quantitati"],
    "ESG / ISR": [r"\besg\b", r"\bisr\b", r"extra[- ]financ", r"sustainab", r"durab", r"stewardship"],
    "Sales / relations investisseurs": [r"\bsales\b", r"relations? investisseurs?", r"investor relations",
                                        r"client (solutions|service)", r"distribution"],
    "Marchés / trading": [r"global markets", r"\bmarkets?\b", r"marches financiers", r"trading",
                          r"structur", r"\betf\b", r"derive"],
}

# Adjacent: always worth a look when no target métier matched.
NEAR_TERMS = [
    r"analyste", r"analyst", r"investment", r"investissement", r"\bfund\b", r"\bfonds\b",
    r"portfolio", r"portefeuille", r"research", r"recherche", r"equity", r"actions",
    r"credit", r"fixed income", r"obligat", r"\btaux\b", r"multi", r"\betf\b", r"quant",
    r"\besg\b", r"\bisr\b", r"private equity", r"capital", r"markets?", r"marches",
    r"structur", r"\bsales\b", r"strategist", r"allocation", r"solutions?", r"\bocio\b",
    r"relations? investisseurs", r"investor relations", r"wealth", r"gestion",
]

# Métiers outside the search: exclusion wins over everything else.
EXCLUDED_METIERS = [
    (r"complian|conformite", "conformité"),
    (r"juridique|juriste|\blegal\b|\blawyer|paralegal", "juridique"),
    (r"\brh\b|ressources humaines|human resources|talent acquisition|recrutement|recruit|\bhr\b|"
     r"compensation|payroll|paie\b", "RH"),
    (r"marketing|communication (financiere|visuelle|interne|externe|digitale|corporate)|"
     r"charge\(?e?\)? de communication|stage communication|evenementiel|\bevent", "marketing / communication"),
    (r"\bit\b|informatique|developpeur|developer|software|engineer|ingenieur|devops|cyber|"
     r"cloud|machine learning|\bai\b research|data engineer", "informatique"),
    (r"middle[- ]office|back[- ]office|\bkyc\b|\baml\b|\blcb|lutte anti|onboarding", "middle / back office"),
    (r"controle|controleur|controller|controlling|\bcontrol\b|audit|inspection", "contrôle / audit"),
    (r"risques? de marche|risk manag|gestion des risques|market risk|credit risk|"
     r"model risk|\brisques?\b", "risques"),
    (r"comptab|accounting|fiscal|\btax\b|tresorerie|treasury", "comptabilité / fiscalité"),
    (r"m&a|m & a|mergers|fusions[- ]acquisitions|\bibd\b|corporate finance|"
     r"financement|leveraged finance|\becm\b|\bdcm\b|(debt|equity) capital markets?", "banque d'affaires / M&A"),
    (r"venture capital|\bvc\b", "venture capital"),
    (r"immobili|real estate|\breit\b", "immobilier"),
    (r"secretariat|assistant\(?e?\)? de direction|office manag|achats|procurement|"
     r"juridique|services generaux|facility", "fonctions support"),
]

# ---------------------------------------------------------------- contract
CONTRACT_EXCLUDED = [
    (r"\bcdi\b|permanent|\bcontrat a duree indeterminee", "CDI"),
    (r"\bcdd\b|fixed[- ]term|duree determinee", "CDD"),
    (r"alternan|alternant|apprenti|apprentice|work[- ]study|contrat pro", "alternance"),
    (r"volontariat international|\bv\.i\.e\b", "VIE"),
    (r"summer (intern|analyst|associate|programme|program)|summer internship|stage d'?ete", "summer"),
    (r"graduate|full[- ]time analyst|analyst program(me)?\b(?!.*intern)|jeune diplome", "graduate / CDI"),
    (r"spring (insight|week|intern|co-op)|insight (week|day|programme|program)|discovery day", "insight"),
    (r"industrial placement|placement year|year in industry|co[- ]op\b", "placement"),
    (r"\bthese\b|\bcifre\b|doctora|phd\b", "thèse"),
    (r"freelance|interim\b|consultant externe", "freelance"),
]
INTERNSHIP_TERMS = r"\bstage\b|stagiaire|\bintern\b|internship|off[- ]?cycle|seasonal|trainee|\bstages\b|praktikum"

# ---------------------------------------------------------------- places
PARIS_TERMS = (r"paris|ile[- ]de[- ]france|\bidf\b|la defense|puteaux|courbevoie|neuilly|boulogne|"
               r"levallois|saint[- ]cloud|issy|montrouge|nanterre|saint[- ]denis|charenton|clichy|"
               r"maisons[- ]alfort|val[- ]de[- ]marne|hauts[- ]de[- ]seine|seine[- ]saint[- ]denis|"
               r"\((75|92|93|94)\)|\b(75|92|93|94)\d{3}\b")
LONDON_TERMS = r"london|londres"
FRANCE_TERMS = r"^\s*france\s*$|\bfr\b$"
UK_TERMS = r"united kingdom|royaume[- ]uni|\bengland\b|\buk\b|\bgb\b"

# ---------------------------------------------------------------- months
MONTHS = {
    "janvier": 1, "january": 1, "janv": 1, "jan": 1,
    "fevrier": 2, "february": 2, "fevr": 2, "feb": 2, "fev": 2,
    "mars": 3, "march": 3,
    "avril": 4, "april": 4, "avr": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juin": 6, "june": 6,
    "juillet": 7, "july": 7, "juil": 7,
    "aout": 8, "august": 8,
    "septembre": 9, "september": 9, "sept": 9, "sep": 9,
    "octobre": 10, "october": 10, "oct": 10,
    "novembre": 11, "november": 11, "nov": 11,
    "decembre": 12, "december": 12, "dec": 12,
}
MONTH_NAMES_FR = ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août",
                  "Septembre", "Octobre", "Novembre", "Décembre"]
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
START_WORDS = (r"debut|demarrage|start(ing|s)?|a partir d[eu']?|a compter d[eu']?|des\b|from|"
               r"commenc|a pourvoir|prise de poste|beginning|begin|disponible|available")
NOT_START_WORDS = r"publi|posted|mise en ligne|date limite|deadline|candidature avant|closing|jusqu"


@dataclass
class Start:
    year: int | None
    month: int | None
    label: str
    explicit_year: bool = True


def _year(y: str | None) -> int | None:
    if not y:
        return None
    y = y.strip("'’ ")
    n = int(y)
    return n + 2000 if n < 100 else n


def detect_start(text: str, today: date | None = None, require_context: bool = False) -> Start | None:
    """Find the internship start month in free text.

    require_context=True (used for long descriptions): only dates right after a start word
    ("début", "à partir de", "starting"...) count, so that publication or update dates
    printed on an offer page are never taken for the start date.
    """
    today = today or date.today()
    t = fold(text)
    candidates: list[tuple[int, int, int | None, bool]] = []  # (score, month, year, explicit)

    def add(pos: int, month: int, year: int | None, base: int) -> None:
        ctx_before = t[max(0, pos - 45):pos]
        if re.search(NOT_START_WORDS, ctx_before):
            return
        has_start_word = bool(re.search(START_WORDS, ctx_before))
        if require_context and not has_start_word:
            return
        score = base + (10 if has_start_word else 0)
        candidates.append((score, month, year, year is not None))

    # "janvier 2027", "Jan 2027", "janvier", "mars 27"
    for m in re.finditer(rf"\b({_MONTH_RE})\.?\s*(?:de\s+l'annee\s+)?('?\d{{4}}|'\d{{2}})?\b", t):
        word, y = m.group(1), m.group(2)
        if word in ("may", "mai", "mar", "dec", "jan", "sep", "oct", "nov", "apr", "feb", "fev", "avr") and not y:
            continue  # too ambiguous without a year
        if word in ("mars",) and not y and not re.search(START_WORDS, t[max(0, m.start() - 45):m.start()]):
            # "Mars" alone may still be a month in a title: accept with low score
            add(m.start(), 3, None, 1)
            continue
        add(m.start(), MONTHS[word], _year(y), 5 if y else 2)
    # numeric month/year: 01/2027, 1-2027, 03.2027
    for m in re.finditer(r"(?<![\d/.\-])(0?[1-9]|1[0-2])[/.\-](20\d{2})\b", t):   # not the end of dd/mm/yyyy
        add(m.start(), int(m.group(1)), int(m.group(2)), 4)
    # full date dd/mm/yyyy only next to a start word
    for m in re.finditer(r"\b([0-3]?\d)[/.\-](0?[1-9]|1[0-2])[/.\-](20\d{2})\b", t):
        ctx = t[max(0, m.start() - 45):m.start()]
        if re.search(START_WORDS, ctx) and not re.search(NOT_START_WORDS, ctx):
            candidates.append((12, int(m.group(2)), int(m.group(3)), True))
    # semesters / quarters / seasons
    for m in re.finditer(r"\b(s1|h1|1er semestre|premier semestre|first half)\s*(20\d{2})", t):
        add(m.start(), 1, int(m.group(2)), 4)
    for m in re.finditer(r"\b(s2|h2|2nd semestre|second semestre|2e semestre|second half)\s*(20\d{2})", t):
        add(m.start(), 7, int(m.group(2)), 4)
    for m in re.finditer(r"\bq([1-4])\s*(20\d{2})", t):
        add(m.start(), (int(m.group(1)) - 1) * 3 + 1, int(m.group(2)), 3)
    for m in re.finditer(r"\b(winter|hiver)\s*(20\d{2})", t):
        add(m.start(), 1, int(m.group(2)), 3)
    for m in re.finditer(r"\b(spring|printemps)\s*(20\d{2})", t):
        add(m.start(), 3, int(m.group(2)), 3)
    for m in re.finditer(r"\b(autumn|fall|automne)\s*(20\d{2})", t):
        add(m.start(), 9, int(m.group(2)), 3)

    if not candidates:
        return None
    candidates.sort(key=lambda c: -c[0])
    score, month, year, explicit = candidates[0]
    if year is None:
        # month without a year: the next occurrence, allowing one month back
        year = today.year if month >= today.month - 1 else today.year + 1
    return Start(year, month, f"{MONTH_NAMES_FR[month]} {year}", explicit)


def parse_start_label(label: str) -> tuple[int, int] | None:
    """'Janvier 2027' -> (2027, 1)."""
    m = re.match(rf"\s*({_MONTH_RE})\w*\s+(20\d{{2}})", fold(label))
    if not m:
        return None
    return int(m.group(2)), MONTHS[m.group(1)]


def _months(ym: tuple[int, int]) -> int:
    return ym[0] * 12 + ym[1] - 1


# ---------------------------------------------------------------- places
_COUNTRY_WORDS = r"france|united kingdom|royaume[- ]uni|england|angleterre|\buk\b|\bgb\b|\bfr\b|europe|emea"


def _only_country(location: str) -> bool:
    """True when the location names a country but no city ("France", "United Kingdom")."""
    rest = re.sub(_COUNTRY_WORDS, " ", fold(location or ""))
    return not re.search(r"[a-z]{3,}", rest)


def place_rank(offer: Offer, cities: list[str]) -> tuple[int, str]:
    """(rank, label): 1 Paris/IDF, 2 London, 3 France/UK without a city, 9 elsewhere, 5 unknown."""
    loc = fold(" ".join(x for x in (offer.location, offer.country) if x))
    if not loc.strip():
        return 5, "lieu non précisé"
    wanted = [fold(c) for c in cities] or ["paris", "londres"]
    ranks: list[tuple[int, str]] = []
    for i, c in enumerate(wanted, start=1):
        if c in ("paris", "ile-de-france", "ile de france", "idf"):
            if re.search(PARIS_TERMS, loc):
                ranks.append((i, "Paris"))
            elif _only_country(offer.location) and (re.search(r"france", loc) or fold(offer.country) == "fr"):
                ranks.append((i + 2, "France"))
        elif c in ("londres", "london"):
            if re.search(LONDON_TERMS, loc):
                ranks.append((i, "Londres"))
            elif _only_country(offer.location) and (re.search(UK_TERMS, loc) or fold(offer.country) == "gb"):
                ranks.append((i + 2, "Royaume-Uni"))
        elif c and c in loc:
            ranks.append((i, c.title()))
    if ranks:
        return min(ranks)
    return 9, "hors des villes choisies"


# ---------------------------------------------------------------- main entry
def _terms_for(criteria: dict) -> list[str]:
    terms: list[str] = []
    for t in criteria.get("types") or []:
        terms += TYPE_SYNONYMS.get(t, [re.escape(fold(t))])
    kw = criteria.get("keywords") or ""
    if isinstance(kw, list):
        kw = ",".join(kw)
    for k in re.split(r"[,;\n]+", kw):
        k = fold(k).strip()
        if k:
            terms.append(re.escape(k))
    return terms


def merge_criteria(source_criteria: dict | None) -> dict:
    c = dict(DEFAULT_CRITERIA)
    for k, v in (source_criteria or {}).items():
        if v not in (None, "", []):
            c[k] = v
    if isinstance(c.get("cities"), str):
        c["cities"] = [x.strip() for x in re.split(r"[,;/]+|\bet\b|\bpuis\b", c["cities"]) if x.strip()]
    return c


def classify(offer: Offer, criteria: dict | None = None, today: date | None = None,
             assume_internship: bool = False) -> Offer:
    """Fill offer.relevance / start_label / reasons in place and return it."""
    c = merge_criteria(criteria)
    title = fold(offer.title)
    contract = fold(offer.contract)
    everything = fold(offer.text())
    reasons: list[str] = []
    excluded: list[str] = []

    # 1. contract
    head = f"{title} {contract}"
    for pat, label in CONTRACT_EXCLUDED:
        if re.search(pat, head):
            excluded.append(f"contrat : {label}")
            break
    if not excluded and re.search(r"\bV\.?I\.?E\b", f"{offer.title} {offer.contract}"):
        excluded.append("contrat : VIE")
    is_intern = bool(re.search(INTERNSHIP_TERMS, head)) or assume_internship
    if not excluded and not is_intern:
        excluded.append("pas un stage")

    # 2. métier
    for pat, label in EXCLUDED_METIERS:
        if re.search(pat, title):
            excluded.append(f"métier : {label}")
            break
    target = [p for p in _terms_for(c) if re.search(p, title)]
    near = [p for p in NEAR_TERMS if re.search(p, title)]
    if not target and not near:
        # look into the short description too, but only for target métiers
        target_desc = [p for p in _terms_for(c) if re.search(p, everything)]
        if target_desc:
            near = target_desc
        else:
            excluded.append("métier hors critères")

    # 3. place
    rank, place = place_rank(offer, c.get("cities") or [])
    if rank == 9:
        excluded.append(f"lieu : {offer.location or offer.country}")
    offer.extra["place_rank"] = rank

    # 4. start
    st = detect_start(f"{offer.title} \n{offer.contract}", today) or (
        detect_start(offer.description, today, require_context=True) if offer.description else None)
    wanted = [x for x in (parse_start_label(s) for s in c.get("starts") or []) if x]
    near_start = False
    if st and st.year and st.month:
        offer.start_label = st.label
        if wanted:
            m = _months((st.year, st.month))
            ws = [_months(w) for w in wanted]
            if m in ws:
                reasons.append(f"démarrage {st.label}")
            elif min(ws) - 1 <= m <= max(ws) + 1:
                near_start = True
                reasons.append(f"démarrage {st.label}, proche de tes dates")
            else:
                excluded.append(f"démarrage {st.label}")
    else:
        offer.start_label = "Non précisé"

    # 5. duration
    dm = re.search(r"\b(\d{1,2})\s*(mois|months?)\b", everything)
    odd_duration = False
    if dm:
        n = int(dm.group(1))
        if n < 4 or n > 7:
            odd_duration = True
            reasons.append(f"durée {n} mois")
    if re.search(r"\b1 an\b|\b12 mois\b|one year|1 year", everything):
        odd_duration = True
        reasons.append("durée 1 an")

    if excluded:
        offer.relevance = "exclue"
        offer.reasons = " · ".join(excluded)
        return offer

    if target:
        offer.relevance = "cible"
        reasons.insert(0, "métier visé")
    else:
        offer.relevance = "proche"
        reasons.insert(0, "métier voisin")
    if offer.relevance == "cible" and (near_start or odd_duration):
        offer.relevance = "proche"
    if rank in (1, 2):
        reasons.append(place)
    elif rank in (3, 4):
        reasons.append(f"{place}, ville à vérifier")
    else:
        reasons.append(place)
    offer.reasons = " · ".join(reasons)
    return offer
