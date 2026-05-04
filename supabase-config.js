// ============================================
// CONFIGURATION SUPABASE — COUP DE PATTE
// ============================================
// Remplacer ces valeurs avec vos vraies clés
// depuis https://supabase.com/dashboard
// ============================================

const SUPABASE_URL = 'https://mbqsaaxaglcemdxmfvkc.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1icXNhYXhhZ2xjZW1keG1mdmtjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc5MjAwMTQsImV4cCI6MjA5MzQ5NjAxNH0.lGK0LL5h-4N4DqMVy2Q_SKJgnzuy7BPQJEtSsc8plfk';

// Client Supabase global
const supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// ---- AUTH ----
async function checkSession() {
  const { data: { session } } = await supabase.auth.getSession();
  return session;
}

async function getCurrentUser() {
  const { data: { user } } = await supabase.auth.getUser();
  return user;
}

async function logout() {
  await supabase.auth.signOut();
  window.location.href = 'coup-de-patte-landing.html';
}

// ---- ANIMAUX ----
async function getAnimaux(filters = {}) {
  let query = supabase.from('Animal').select('*, refuge:Refuge(*)').eq('disponible', true);
  if (filters.espece) query = query.eq('espece', filters.espece);
  if (filters.enfin_moi) query = query.eq('enfin_moi', true);
  if (filters.refuge_id) query = query.eq('refuge', filters.refuge_id);
  const { data, error } = await query;
  if (error) console.error('Erreur animaux:', error);
  return data || [];
}

async function getAnimalById(id) {
  const { data, error } = await supabase.from('Animal').select('*, refuge:Refuge(*)').eq('id', id).single();
  if (error) console.error('Erreur animal:', error);
  return data;
}

// ---- REFUGES ----
async function getRefuges(filters = {}) {
  let query = supabase.from('Refuge').select('*');
  if (filters.partenaire) query = query.eq('est_partenaire', true);
  const { data, error } = await query;
  if (error) console.error('Erreur refuges:', error);
  return data || [];
}

async function getRefugeById(id) {
  const { data, error } = await supabase.from('Refuge').select('*').eq('id', id).single();
  if (error) console.error('Erreur refuge:', error);
  return data;
}

// ---- PROFIL ADOPTANT ----
async function getProfilAdoptant(userId) {
  const { data, error } = await supabase.from('ProfilAdoptant').select('*').eq('utilisateur', userId).single();
  if (error && error.code !== 'PGRST116') console.error('Erreur profil:', error);
  return data;
}

async function saveProfilAdoptant(userId, profil) {
  const existing = await getProfilAdoptant(userId);
  if (existing) {
    const { data, error } = await supabase.from('ProfilAdoptant').update(profil).eq('utilisateur', userId);
    if (error) console.error('Erreur update profil:', error);
    return data;
  } else {
    const { data, error } = await supabase.from('ProfilAdoptant').insert({ ...profil, utilisateur: userId });
    if (error) console.error('Erreur insert profil:', error);
    return data;
  }
}

// ---- MATCHING ----
async function getMatchs(userId) {
  const { data, error } = await supabase.from('Correspondre').select('*, animal:Animal(*, refuge:Refuge(*))').eq('utilisateur', userId).order('score_global', { ascending: false });
  if (error) console.error('Erreur matchs:', error);
  return data || [];
}

// ---- SIGNALEMENTS ----
async function creerSignalement(animalId, userId, type, commentaire = '') {
  const { data, error } = await supabase.from('Signalisation').insert({
    animal: animalId,
    utilisateur: userId,
    type_signalement: type,
    commentaire,
    traite: false
  });
  if (error) console.error('Erreur signalement:', error);
  return data;
}

// ---- ALGORITHME MATCHING (côté client) ----
function calculerScore(profil, animal) {
  let scores = { logement: 0, foyer: 0, disponibilite: 0, experience: 0, mode_vie: 0 };
  
  // Logement (30%)
  if (profil.type_logement === 'maison' && animal.gabarit !== 'petit') scores.logement = 100;
  else if (profil.type_logement === 'appartement' && animal.gabarit === 'petit') scores.logement = 100;
  else if (profil.type_logement === 'appartement' && animal.gabarit === 'moyen') scores.logement = 70;
  else scores.logement = 40;
  
  // Foyer (25%)
  let foyer = 100;
  if (profil.enfants_foyer === 'oui_moins13' && !animal.compat_enfants_moins13) foyer -= 50;
  if (profil.animaux_foyer === 'chien' && !animal.compat_chiens) foyer -= 50;
  if (profil.animaux_foyer === 'chat' && !animal.compat_chats) foyer -= 50;
  scores.foyer = Math.max(0, foyer);
  
  // Disponibilité (20%)
  if (profil.heures_seul <= 4) scores.disponibilite = 100;
  else if (profil.heures_seul <= 6) scores.disponibilite = 75;
  else if (profil.heures_seul <= 8) scores.disponibilite = 50;
  else scores.disponibilite = 25;
  
  // Expérience (15%)
  if (animal.experience_requise === 'debutant') scores.experience = 100;
  else if (animal.experience_requise === 'intermediaire' && profil.experience_animale !== 'aucune') scores.experience = 100;
  else if (animal.experience_requise === 'experimente' && profil.experience_animale === 'experimente') scores.experience = 100;
  else scores.experience = 40;
  
  // Mode de vie (10%)
  if (profil.activite === 'actif' && animal.energie === 'eleve') scores.mode_vie = 100;
  else if (profil.activite === 'modere' && animal.energie === 'moyen') scores.mode_vie = 100;
  else if (profil.activite === 'calme' && animal.energie === 'faible') scores.mode_vie = 100;
  else scores.mode_vie = 50;
  
  // Score global pondéré
  const global = Math.round(
    scores.logement * 0.30 +
    scores.foyer * 0.25 +
    scores.disponibilite * 0.20 +
    scores.experience * 0.15 +
    scores.mode_vie * 0.10
  );
  
  return { global, ...scores };
}

function getLabelScore(score) {
  if (score >= 85) return { label: 'Coup de Patte idéal', color: '#4A7C59' };
  if (score >= 70) return { label: 'Belle rencontre', color: '#7AAD89' };
  if (score >= 55) return { label: "On s'apprivoise ?", color: '#C49A1A' };
  return { label: 'Incompatible', color: '#C9704A' };
}
