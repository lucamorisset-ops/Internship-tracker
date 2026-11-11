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
- Sites officiels uniquement : pas de JobTeaser, LinkedIn, Indeed ni autres intermédiaires.

## Ajouter une entreprise

Sur le site, onglet **Ajouter une entreprise** : nom, lien de la page carrières officielle (conseillé),
types de stage, démarrage, villes, mots-clés. Le robot passe dans les 15 minutes : il reconnaît les
portails courants (SmartRecruiters, Oracle, Talentsoft, Workday, Greenhouse, Lever, Recruitee…), sinon
il lit la page de façon générique et le dit dans l'onglet Sites qui résistent.

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

## Organisation du code

- `scraper/runner.py` : un passage complet (lecture, tri, enregistrement, notifications).
- `scraper/http.py`, `scraper/browser.py` : accès poli aux sites (robots.txt, délais, navigateur sans tête).
- `scraper/matching.py` : critères, synonymes des métiers, détection de la date de démarrage.
- `scraper/parsers/` : un lecteur par portail (voir le contrat dans `parsers/base.py`).
- `docs/probes.md` : structure réelle de chaque site, relevée le 08/11/2026.
- `site/` : le site (HTML + JavaScript, sans compilation).
- `supabase/schema.sql` : tables et règles d'accès (seule ton adresse voit les données).
