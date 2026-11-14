# Tracker de stages

Veille automatique des offres de stage sur les **sites carrières officiels** de sociétés de gestion
et de banques (Amundi, Lazard Frères Gestion, DNCA, Mirova, BNP Paribas, Morgan Stanley…), avec un site
pour suivre les offres et une notification sur le téléphone quand une offre intéressante apparaît.

```
GitHub Actions (3 fois par jour + à la demande)      Supabase (base privée)       GitHub Pages (site)
  robot Python ── lit les catalogues officiels ──▶  sources / offres / passages ◀── connexion par lien e-mail
        │                                                                          bouton « Mettre à jour »
        └── ntfy ──▶ notification sur le téléphone
```

## Ce que fait le robot

1. Pour chaque entreprise, il lit le catalogue d'offres du **site officiel** avec les filtres du site
   (contrat, pays, métier) quand ils existent, par l'API publique du portail quand il y en a une.
2. Il garde les offres qui correspondent aux critères (stage de 6 mois en gestion d'actifs, equity research,
   investment specialist ou investment analyst, démarrage janvier ou mars 2027, Paris puis Londres) :
   **ciblée**, **à vérifier** (métier voisin, date proche) ou **exclue** (avec la raison).
3. Il note la **date de publication**, ouvre la fiche des nouvelles offres pour la compléter,
   marque comme **fermées** celles qui ont disparu du catalogue.
4. Il enregistre **chaque URL lue** (visible sur le site, onglet Sources) et explique en clair, dans
   l'onglet **Sites qui résistent**, pourquoi un site ne se laisse pas lire et quoi faire.
5. Il envoie une notification pour chaque nouvelle offre ciblée, pour les offres à vérifier,
   et dès qu'un site se met à résister.

### Règles de lecture

- `robots.txt` de chaque site est lu et respecté (y compris `Crawl-delay`) ; une page interdite n'est jamais lue.
- Le robot se présente honnêtement (`tracker-stages-bot`, avec le lien de ce dépôt) et ne contourne
  aucune protection anti-robot : un site qui refuse est signalé comme « résiste ».
- Lecture seule : aucune connexion à un compte, aucun formulaire envoyé, aucune candidature.
- Sites officiels uniquement : pas de JobTeaser, LinkedIn, Indeed ni autres intermédiaires. Le robot ne les
  contacte **jamais** (même pas pour surveiller un changement) : une entreprise qui n'y publie que là est
  signalée avec un rappel clair (« ouvre la page toi-même », ou colle l'adresse de sa page officielle dans
  « Lien à lire »).

## Ajouter une entreprise

Sur le site, onglet **Ajouter une entreprise** : nom, lien de la page carrières officielle (conseillé),
types de stage, démarrage, villes, mots-clés. Dès l'ajout, une demande de passage est envoyée : le robot
passe dans les 15 minutes, **cherche et scanne le site carrières** de l'entreprise (il reconnaît les
portails courants — SmartRecruiters, Oracle, Talentsoft, Workday, Greenhouse, Lever, Recruitee… — sinon
il lit la page de façon générique) et le dit dans l'onglet Sites qui résistent. Les entreprises ajoutées
depuis le site ces 14 derniers jours sont regroupées par le filtre **« Nouvellement ajoutées »** de
l'onglet Sources, avec une pastille **Nouvelle**.

## Lien à lire

Onglet **Sources et catalogues**, champ **Lien à lire** de chaque entreprise : colle l'adresse exacte
d'une page d'offres (une liste filtrée, une autre page du site officiel…). Le robot la lit à chaque passage
en plus du catalogue habituel (portail reconnu ou lecture générique) et ajoute les offres qu'il y trouve.
Les règles de lecture restent les mêmes : un site qui interdit les robots ou refuse la lecture continue de résister.

## Inventaire complet

Le robot enregistre **toutes** les offres lues, même hors critères. Un stage écarté pour le métier,
le lieu ou la date apparaît comme **Hors critères** ; s'il est repéré après la date `inventory_since`
(table `meta`), il compte aussi dans **Non traitées**. CDI, alternance et VIE restent **Exclus**.
Les notifications ne concernent que les offres ciblées et à vérifier.

## Installation (une seule fois)

1. **Supabase** : SQL Editor → coller le fichier `setup.sql` fourni (schéma + entreprises + offres déjà
   repérées + ton adresse autorisée) → Run. Le schéma seul est dans `supabase/schema.sql`.
2. **Supabase → Authentication → URL Configuration** : Site URL =
   `https://lucamorisset-ops.github.io/Internship-tracker/`, et la même adresse dans Redirect URLs.
3. **GitHub → Settings → Secrets and variables → Actions → New repository secret** :
   - `SUPABASE_SECRET_KEY` : la *Secret key* de Supabase (Project Settings → API Keys). Elle ne doit
     jamais apparaître ailleurs (ni dans le code, ni dans le site, ni dans un message).
   - `NTFY_TOPIC` : le nom du canal de notification (à recopier aussi dans l'application ntfy).
4. **GitHub → Settings → Pages** : Source = **GitHub Actions**.
5. Téléphone : application **ntfy** → s'abonner au canal `NTFY_TOPIC`.
6. Onglet **Actions** → « Veille des stages » → **Run workflow** pour le premier passage.

## Lancer le robot à la main

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m scraper --local data/local.json --dry-run          # sans Supabase, sans notification
SUPABASE_URL=… SUPABASE_SECRET_KEY=… python -m scraper --only amundi,dnca
python -m pytest -q
```

## Suivre un métier voisin

Sur une offre **à vérifier** (onglet Offres), le bouton **« Suivre ce métier »** propose un mot-clé
(tiré du titre, modifiable) à ajouter aux critères de l'entreprise, après une **confirmation**. Une fois
ajouté, les prochaines offres de l'entreprise contenant ce mot sont classées **ciblées**. C'est un choix
explicite et traçable (pas d'apprentissage automatique) : chaque offre garde un « pourquoi » clair.

## Critères en français et en anglais

Beaucoup de sites carrières (BlackRock, Morgan Stanley, J.P. Morgan…) publient en anglais. Les métiers
cochés ont déjà leurs synonymes anglais ; un **mot-clé libre** tapé en français est en plus recherché en
anglais, et l'inverse (ex. `actions` ⇄ `equities`, `obligataire` ⇄ `fixed income`, `crédit` ⇄ `credit`).
La table de correspondance est dans `scraper/matching.py` (`KEYWORD_TRANSLATIONS`).

## Organisation du code

Le projet a trois morceaux indépendants qui communiquent par la base Supabase : le **robot** (Python,
sur GitHub Actions) écrit ; le **site** (HTML/JS, sur GitHub Pages) lit et laisse régler le suivi ; la
**base** (Supabase/PostgreSQL) garde tout et applique les droits d'accès.

```
scraper/ (le robot)
├── __main__.py / runner.py   Un passage complet : charge les sources, lit chacune, trie les offres,
│                             enregistre (nouvelles / fermées), envoie les notifications, écrit le bilan.
├── http.py                   Accès réseau poli : respecte robots.txt et Crawl-delay, se présente
│                             honnêtement, réessaie, repère les pages anti-robot (FetchError/RobotsDisallowed).
├── browser.py                Navigateur sans écran (Playwright), à la demande, pour les sites 100 % JavaScript.
├── robots.py                 Lecture du robots.txt (règles RFC 9309).
├── models.py                 Types partagés : Offer, SourceResult, normalisation d'URL (url_key), fold().
├── matching.py               Le tri : critères par défaut, synonymes des métiers (FR/EN), métiers exclus,
│                             contrats exclus, lieux, détection de la date de démarrage, traduction des mots-clés.
│                             classify(offer) remplit relevance (cible/proche/exclue), start_label et reasons.
├── store.py                  Lecture/écriture Supabase (ou fichier JSON local avec --local).
├── notify.py                 Notifications ntfy (téléphone).
└── parsers/                  Un lecteur par type de catalogue. base.py définit le contrat commun ;
                              __init__.py associe sources.kind → module (le registre REGISTRY).

site/ (le site)
├── index.html                Mise en page, styles, et les quatre onglets (Offres, Sources, Sites qui
│                             résistent, Ajouter une entreprise).
├── app.js                    Toute la logique : connexion (lien e-mail Supabase), chargement, rendu des
│                             onglets, suivi des offres, ajout d'entreprise, « Suivre ce métier », mode démo.
└── config.js                 Adresse Supabase + clé publique (publishable). Jamais la clé secrète.

supabase/
├── schema.sql                Tables (sources, offers, runs, run_requests, meta, allowed_users) et
│                             règles d'accès (RLS) : seule une adresse autorisée voit et modifie les données.
└── sources_seed.json         Les entreprises de départ.

tests/                        pytest : matching, parsers (par portail, sur des pages réelles figées dans
                              fixtures/), passage complet de bout en bout (test_integration_seed.py).
docs/probes.md                Structure réelle de chaque site, relevée à la main.
```

### Comment une entreprise est lue

1. `runner.run()` charge les `sources` et, pour chacune, prend le lecteur indiqué par `sources.kind`.
2. Le lecteur (`parsers/<kind>.py`) renvoie une liste d'`Offer` depuis le catalogue officiel.
3. `matching.classify()` trie chaque nouvelle offre et écrit *pourquoi*.
4. Les offres disparues d'une lecture **complète** et réussie sont marquées **fermées** ; les nouvelles sont
   enregistrées ; `notify.py` prévient pour les offres ciblées / à vérifier et les sites qui se mettent à résister.

### Ajouter un nouveau portail (pour un développeur)

Le lecteur `auto` (`parsers/auto.py`) reconnaît déjà SmartRecruiters, Oracle HCM, Talentsoft, Workday,
Greenhouse, Lever, Recruitee, Sainoo, TalentBrew ; sinon il lit la page de façon **générique**
(`parsers/generic.py` : les liens qui ressemblent à des offres + les données JSON-LD). Pour un portail
vraiment nouveau : créer `parsers/mon_portail.py` avec une classe `Parser(BaseParser)` (voir le contrat en
tête de `parsers/base.py`), l'ajouter au `REGISTRY` de `parsers/__init__.py`, et ajouter un test avec une
page figée dans `tests/fixtures/`. Pour qu'`auto` le détecte tout seul, ajouter son motif d'URL dans
`auto._detect`.
