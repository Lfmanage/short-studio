# Short Studio

Une vidéo → un bouton → un Short vertical **1080×1920 de 60 s exactes**, prêt à poster sur TikTok, Reels et Shorts.

```
web/        l'appli (PWA) → GitHub Pages
worker/     le monteur automatique (Python + FFmpeg) → petit serveur Docker
supabase/   la base, le stockage et la sécurité → Supabase
```

## Ce que fait l'appli

1. Tu importes une vidéo ou tu colles un lien direct (Drive, Dropbox, MP4).
2. Le worker analyse : changements de plans, pics audio, transcription mot à mot.
3. L'IA note chaque passage et choisit un **hook** pour les 3 premières secondes, puis une histoire cohérente.
4. Montage automatique :
   - ta vidéo en haut, un fond satisfaisant en bas ;
   - cuts, punch-in un plan sur deux ;
   - sous-titres animés, bandeau d'accroche ;
   - voix française (ou sans voix) ;
   - musique optionnelle et son normalisé à −14 LUFS.
5. Tu obtiens un aperçu, un titre, une description et des hashtags à copier, puis tu exportes.
6. Si tu veux retoucher : touche les moments sur la frise, « Autre sélection » ou « Autre fond ».
7. Suppression automatique 3 h après le téléchargement (24 h au maximum si tu ne télécharges pas).

---

## Mise en route (≈ 30 min, une seule fois)

### 1. Supabase
1. Crée un projet sur supabase.com.
2. Va dans **SQL Editor**, colle le contenu de `supabase/schema.sql`, puis clique sur **Run**.
3. Dans **Storage > Settings**, règle la taille maximale par fichier. Le plan gratuit est limité à 50 Mo : une vidéo d'une minute filmée au téléphone peut dépasser cette limite, auquel cas il faut le plan Pro ou passer par un lien Drive.
4. Dans **Authentication > Sign In / Providers**, désactive « Allow new users to sign up » une fois ton compte créé, pour être le seul utilisateur.
5. Dans **Project Settings > API**, note :
   - `Project URL` ;
   - la clé `anon public` (pour l'appli) ;
   - la clé `service_role` (pour le worker, **secrète**).

### 2. Les clés API
- **OpenAI** (platform.openai.com) : sert au choix des moments, à la voix française et à la transcription. Compte quelques centimes par Short.
- **Pexels** (pexels.com/api, gratuit) : sert aux fonds satisfaisants. Sans cette clé, l'appli utilise des fonds dégradés animés, ou tes propres vidéos placées dans `worker/assets/backgrounds/`.

### 3. Le worker (le serveur qui monte les vidéos)
Il doit tourner en permanence. Deux options simples :

**A. Un petit VPS** (Hetzner, OVH… environ 5 €/mois, 2 vCPU et 4 Go conseillés) :
```bash
git clone <ton dépôt> && cd short-studio/worker
cp .env.example .env      # remplis les clés
docker build -t short-worker .
docker run -d --restart unless-stopped --env-file .env --name short-worker short-worker
docker logs -f short-worker   # doit afficher « Short Studio worker prêt. »
```

**B. Railway ou Render** (« Background Worker ») : connecte le dépôt, choisis le dossier `worker`, ajoute les variables du fichier `.env.example`, puis déploie.

### 4. L'appli
1. Dans `web/config.js`, mets `SUPABASE_URL` et `SUPABASE_ANON_KEY`.
2. Pousse le dossier `web/` dans un dépôt GitHub, par exemple `Lfmanage/short-studio`.
3. Va dans **Settings > Pages**, puis déploie la branche `main`.
4. Sur ton téléphone, ouvre le lien, puis **Partager > Sur l'écran d'accueil**. L'appli s'ouvre alors comme une vraie appli.

---

## Tester le worker seul, sur un ordinateur
```bash
cd worker && pip install -r requirements.txt   # + FFmpeg installé
export OPENAI_API_KEY=sk-...                    # facultatif
python cli.py ma_video.mp4                      # → sortie/short.mp4 + meta.json
python cli.py "https://www.dropbox.com/s/.../video.mp4?dl=0" --no-voice
```

## Personnaliser
- **Fonds** : dépose des `.mp4` libres de droits dans `worker/assets/backgrounds/`.
- **Musique** : dépose des `.mp3` libres de droits dans `worker/assets/music/`.
- **Voix** : `OPENAI_TTS_VOICE=onyx`, `ash`, `nova`, `coral`…
- **Durée** : `SHORT_DURATION=60` côté worker et `DURATION` dans `web/config.js`.
- **Transcription gratuite** : `TRANSCRIBE=local`, après avoir décommenté `faster-whisper` dans `requirements.txt`. C'est plus lent et demande un serveur plus costaud.

## Coûts estimés par Short (vidéo source de quelques minutes)
- Transcription : quelques centimes au maximum, à la minute de source.
- Choix des moments et texte (gpt-4o-mini) : moins d'un centime.
- Voix française (environ 130 mots) : environ un centime.
- Serveur : prix fixe du VPS, quel que soit le nombre de Shorts.

Ce sont des ordres de grandeur. Vérifie les tarifs à jour sur openai.com/pricing.

## Limites à connaître
- **Liens :** YouTube, TikTok et Instagram ne sont pas téléchargés, car leurs conditions l'interdisent. Importe le fichier fourni par le créateur.
- **Recadrage :** il est centré, sans suivi de visage. Le sujet peut être coupé s'il se trouve tout au bord de l'image.
- **Clipping :** garde une trace de l'accord du créateur. Content ID peut quand même réclamer un clip.
- **Temps de rendu :** compte 1 à 3 minutes par Short sur un petit serveur.
