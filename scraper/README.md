# Module de collecte d'offres (`scraper/`)

Le robot lit les catalogues d'offres des **sites carrières officiels** et renvoie des offres
normalisées (alignées sur schema.org `JobPosting`) vers Supabase. Ce document décrit le moteur de
collecte : la hiérarchie des méthodes d'extraction, les règles de collecte polie et les garde-fous.

## Hiérarchie des méthodes d'extraction

Pour une entreprise, le robot essaie les méthodes **dans cet ordre** et s'arrête à la première qui
renvoie des offres (`scraper/parsers/auto.py`) :

1. **API de l'ATS** — Greenhouse, Lever, SmartRecruiters, **Ashby**, Recruitee, Workday, Oracle HCM,
   Talentsoft, Sainoo, TalentBrew. L'ATS est détecté depuis l'URL ou le HTML de la page carrières.
2. **Endpoint JSON découvert** (`scraper/discover.py`) — quand aucun ATS n'est reconnu : un navigateur
   sans tête repère la requête JSON qui charge les offres, on la généralise (sans filtre, avec
   pagination) puis on la rappelle **sans navigateur** aux passages suivants. *Activé seulement si
   `ENABLE_BROWSER=1`.*
3. **Données structurées + liens d'offres** (`scraper/structured.py`, `scraper/parsers/generic.py`) —
   `JobPosting` en JSON-LD, Microdata, RDFa/Microformats (RDFa/Microformats via `extruct` si installé),
   plus les liens de la page qui ressemblent à des offres.
4. **LLM sur le texte de la page** (`scraper/llm_extract.py`) — dernier recours, **stub désactivé par
   défaut** (`SCRAPER_LLM`).

La méthode qui a marché est **mémorisée** dans `sources.params` (`ats`, `endpoint`…), pour ne pas refaire
la détection à chaque passage. Toutes les méthodes renvoient le même objet `Offer`
(`scraper/models.py`) ; la déduplication et le suivi des changements (nouvelle / fermée) se font dans
`runner.py` par clé `(source_id, identifiant externe / url)` avec `first_seen` / `last_seen` / `closed`.

## Règles de collecte polie

Toutes les requêtes passent par un seul client (`scraper/http.py`, `scraper/browser.py`,
`scraper/discover.py`) :

1. **User-Agent identifiable**, avec une adresse de contact optionnelle lue dans `SCRAPER_CONTACT`
   (jamais écrite en dur).
2. **`robots.txt` lu et respecté** avant chaque URL (RFC 9309), ainsi que le **`Crawl-delay`** ; au
   minimum `MIN_DELAY` secondes entre deux requêtes au même hôte.
3. **Cache HTTP optionnel** (`requests-cache`) : désactivé par défaut, activé par `SCRAPER_CACHE_TTL`
   (secondes, p. ex. `21600` = 6 h) pour ne pas recharger deux fois la même page.
4. **API publiques en priorité** (étape 1 de la hiérarchie).
5. **Nouvelle tentative** avec attente croissante seulement sur 429 / 5xx.
6. **Abandon** sur 403 ou page anti-robot / captcha : la source est signalée, **sans aucune tentative
   de contournement**.

## Découverte d'endpoint et jetons de session

`scraper/discover.py` (étape 2) :

- **Capture** les réponses JSON de la page dans Chromium, **score** les listes selon leur ressemblance
  avec des offres (présence de `title`, `location`, `postedOn`…), garde la meilleure.
- **Généralise** la requête capturée : vide les filtres (`appliedFacets: {}`, `q=""`, facettes dans
  l'URL) et détecte le paramètre de pagination (`offset`, `page`, `start`, `skip`…).
- **Rappelle** l'endpoint directement. Les **jetons anonymes** donnés à tout visiteur (cookie de
  session, CSRF) peuvent être réutilisés. Un en-tête/cookie **anti-robot** (`cf_clearance`, `__cf_bm`,
  `datadome`, `_px*`, `akamai`…) n'est **jamais reproduit** : la source est abandonnée.

## Garde-fous

1. User-Agent identifiable avec contact (`SCRAPER_CONTACT`).
2. Limite de débit par domaine et respect de `Crawl-delay`.
3. Cache HTTP (optionnel).
4. API publiques en priorité ; l'endpoint Workday interne est utilisé avec modération.
5. `robots.txt` respecté ; une URL interdite est sautée et journalisée.
6. **Aucun contournement** de captcha, de challenge anti-bot ou d'authentification par compte. Seuls les
   jetons anonymes donnés à tout visiteur sont réutilisés.
7. Pas de collecte de données personnelles (noms ou e-mails de recruteurs) au-delà du nécessaire.
8. **Sites officiels uniquement** : JobTeaser, LinkedIn, Indeed et autres intermédiaires ne sont jamais
   lus (`scraper/parsers/generic.py`, `is_intermediary`).

## Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY` | base de données | — |
| `NTFY_TOPIC`, `SITE_URL` | notifications | — |
| `SCRAPER_CONTACT` | adresse de contact ajoutée au User-Agent | vide |
| `SCRAPER_CACHE_TTL` | durée du cache HTTP en secondes (0 = désactivé) | `0` |
| `ENABLE_BROWSER` | autorise le navigateur (rendu JS + découverte d'endpoint) | désactivé |
| `PW_EXECUTABLE_PATH` | binaire Chromium si le téléchargement Playwright est absent | auto |
| `SCRAPER_LLM` | active l'étape LLM (stub) | désactivé |
| `CAPTURE_DIR` | dossier où sauver les pages lues (débogage) | — |

## Dépendances

`requests`, `requests-cache`, `beautifulsoup4`, `lxml`, `playwright` (voir `requirements.txt`).
`extruct` + `w3lib` sont **optionnels** (RDFa / Microformats) : le module `structured.py` marche sans
eux (repli JSON-LD + Microdata + OpenGraph en pur lxml).

## Lancer / tester

```bash
pip install -r requirements.txt
python -m playwright install chromium          # pour le navigateur (facultatif)
python -m scraper --local data/local.json --dry-run
python -m pytest -q                            # tous les tests, sur fixtures, sans réseau
```
