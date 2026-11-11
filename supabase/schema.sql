-- Schéma du tracker de stages (Supabase / PostgreSQL)
-- À exécuter une fois dans Supabase : SQL Editor > New query > coller > Run.
-- Le fichier est rejouable : il ne supprime aucune donnée.

-- ---------------------------------------------------------------- tables
create table if not exists public.allowed_users (
  email text primary key
);

create table if not exists public.sources (
  id            text primary key,                 -- slug : "amundi"
  company       text not null,
  rank          int,
  kind          text not null default 'auto',     -- lecteur (scraper/parsers)
  params        jsonb not null default '{}'::jsonb,
  catalog_url   text,                             -- catalogue officiel (bouton « Ouvrir »)
  read_urls     text[] not null default '{}',     -- URL configurées
  filters       text,                             -- filtres du site utilisés, en clair
  criteria      jsonb,                            -- critères propres à l'entreprise
  status        text not null default 'a_configurer',
  reason        text,                             -- pourquoi le site résiste
  fix           text,                             -- ce que tu peux faire
  note          text,
  enabled       boolean not null default true,
  last_checked  timestamptz,
  last_method   text,
  last_error    text,
  last_count    int,
  last_urls     jsonb,                            -- URL réellement lues au dernier passage
  page_hash     text,
  priority_url  text,                             -- « Lien à lire » collé par toi, lu en plus du catalogue
  added_from_site boolean not null default false,
  created_at    timestamptz not null default now()
);

create table if not exists public.offers (
  id              text primary key,               -- "amundi:116937"
  source_id       text not null references public.sources(id) on delete cascade,
  ext_id          text,
  url             text,
  url_key         text,
  title           text not null,
  company         text,
  location        text,
  country         text,
  contract        text,
  published       date,
  published_label text,
  description     text,
  start_label     text,
  relevance       text,                           -- cible / proche / exclue
  reasons         text,
  note            text,                           -- ta note perso
  status          text not null default 'nouvelle', -- ton suivi : nouvelle, a_postuler, postule...
  manual          boolean not null default false, -- jamais fermée automatiquement
  first_seen      timestamptz not null default now(),
  last_seen       timestamptz not null default now(),
  closed          boolean not null default false,
  closed_on       date
);
create index if not exists offers_source_idx on public.offers(source_id);
create index if not exists offers_relevance_idx on public.offers(relevance) where not closed;

create table if not exists public.runs (
  id          bigint generated always as identity primary key,
  started_at  timestamptz,
  finished_at timestamptz,
  trigger     text,
  totals      jsonb,
  report      jsonb
);

create table if not exists public.run_requests (
  id           bigint generated always as identity primary key,
  requested_at timestamptz not null default now(),
  requested_by uuid default auth.uid(),
  sources      text[],                            -- null = toutes les sources
  done_at      timestamptz,
  note         text
);

create table if not exists public.meta (
  key   text primary key,
  value jsonb
);

-- colonnes ajoutées après la création (le fichier reste rejouable)
alter table public.sources add column if not exists priority_url text;

-- ---------------------------------------------------------------- accès
-- Seules les adresses de allowed_users voient et modifient les données.
-- Le robot utilise la clé secrète (contourne ces règles) depuis GitHub Actions.
create or replace function public.is_allowed() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.allowed_users
    where lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;
revoke all on function public.is_allowed() from public;
grant execute on function public.is_allowed() to authenticated;

alter table public.allowed_users enable row level security;
alter table public.sources       enable row level security;
alter table public.offers        enable row level security;
alter table public.runs          enable row level security;
alter table public.run_requests  enable row level security;
alter table public.meta          enable row level security;

-- personne de l'extérieur (clé publique seule, sans connexion) : aucun accès
revoke all on public.allowed_users, public.sources, public.offers, public.runs,
              public.run_requests, public.meta from anon;
revoke all on public.allowed_users from authenticated;

-- lecture
drop policy if exists "lecture sources" on public.sources;
create policy "lecture sources" on public.sources for select to authenticated using (public.is_allowed());
drop policy if exists "lecture offres" on public.offers;
create policy "lecture offres" on public.offers for select to authenticated using (public.is_allowed());
drop policy if exists "lecture passages" on public.runs;
create policy "lecture passages" on public.runs for select to authenticated using (public.is_allowed());
drop policy if exists "lecture demandes" on public.run_requests;
create policy "lecture demandes" on public.run_requests for select to authenticated using (public.is_allowed());
drop policy if exists "lecture meta" on public.meta;
create policy "lecture meta" on public.meta for select to authenticated using (public.is_allowed());

-- écriture depuis le site : ajouter / régler une entreprise, suivre une offre, demander un passage
drop policy if exists "ajout entreprise" on public.sources;
create policy "ajout entreprise" on public.sources for insert to authenticated with check (public.is_allowed());
drop policy if exists "modif entreprise" on public.sources;
create policy "modif entreprise" on public.sources for update to authenticated
  using (public.is_allowed()) with check (public.is_allowed());
drop policy if exists "suppression entreprise" on public.sources;
create policy "suppression entreprise" on public.sources for delete to authenticated using (public.is_allowed());
drop policy if exists "suivi offre" on public.offers;
create policy "suivi offre" on public.offers for update to authenticated
  using (public.is_allowed()) with check (public.is_allowed());
drop policy if exists "demande passage" on public.run_requests;
create policy "demande passage" on public.run_requests for insert to authenticated with check (public.is_allowed());

-- colonnes modifiables depuis le site (le reste appartient au robot)
revoke insert, update, delete on public.offers from authenticated;
grant select on public.offers to authenticated;
grant update (status, note) on public.offers to authenticated;
revoke insert, update, delete on public.sources from authenticated;
grant select, delete on public.sources to authenticated;
grant insert (id, company, rank, kind, params, catalog_url, read_urls, filters, criteria, status,
              note, enabled, added_from_site) on public.sources to authenticated;
grant update (company, rank, catalog_url, criteria, note, enabled, status, priority_url) on public.sources to authenticated;
revoke insert, update, delete on public.runs, public.meta from authenticated;
grant select on public.runs, public.meta to authenticated;
revoke insert, update, delete on public.run_requests from authenticated;
grant select, insert (sources) on public.run_requests to authenticated;
