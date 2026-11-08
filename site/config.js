// Configuration publique du site du tracker.
//
// La « publishable key » de Supabase (elle commence par sb_publishable_) est
// publique par conception : elle est envoyée au navigateur de chaque visiteur,
// donc la mettre ici ne révèle rien. Toute seule, elle ne donne accès à aucune
// donnée : les tables sont protégées par les règles RLS de Supabase
// (supabase/schema.sql). Seules les adresses e-mail inscrites dans la table
// allowed_users, connectées par lien magique, peuvent lire les offres et faire
// les quelques modifications autorisées depuis le site.
//
// Où la trouver : Supabase > Project Settings > API Keys > Publishable key.
//
// Ne mets JAMAIS ici la clé secrète (sb_secret_… ou service_role) : elle
// contourne les règles RLS et doit rester uniquement dans les secrets GitHub
// du robot (SUPABASE_SECRET_KEY).

export const SUPABASE_URL = "https://whitghcavsimmfuvziry.supabase.co";
export const SUPABASE_PUBLISHABLE_KEY = "REMPLACER_PAR_LA_PUBLISHABLE_KEY";
