# Actualisation DEV / PROD — 23 octobre 2026

Cette section remplace les constats historiques ci-dessous. Branche conservée :
`feat/c02-foundation`, HEAD `c903802`, dépôt initialement propre. Aucun commit,
push, apply, destroy, import, changement IAM, activation API ou migration de state.
Le projet gcloud actif reste `masterpoulet-dev`.

- Configuration déjà paramétrée : `network_name`, `subnet_name`, `subnet_cidr`.
  Aucun changement de main.tf, providers.tf, outputs.tf, backend.tf ou dev.tfvars.
  Seule la validation interdisant PROD est retirée ; le format des IDs reste validé.
- Ajout de `prd.tfvars` : projet `masterpoulet-prod`, région `europe-west3`, VPC
  `masterpoulet-prod-vpc`, subnet `masterpoulet-prod-vpc-subnet`, `10.0.2.0/24`.
- Bucket PROD unique listé dans le projet : `masterpoulet_prod_bucket`,
  `EUROPE-WEST1`, versioning, accès uniforme et prévention d'accès public activés.
  Liste récursive initiale vide. Configuration `backends/prd.hcl` : ce bucket,
  préfixe `foundation/prd`. Aucun bucket créé ou modifié.
- Bucket DEV confirmé : `masterpoulet_bucket`, préfixe `foundation/dev`.
  Seul le commentaire obsolète de `backends/dev.hcl` est corrigé.
- Inventaires Compute réussis : DEV possède le VPC/subnet attendus ; PROD possède
  seulement le réseau `default` et ses subnets, sans les deux cibles Masterpoulet.
  Les plages inventoriées ne chevauchent pas `10.0.2.0/24`. Réseau default intact.
- `terraform fmt -recursive`, `fmt -check -recursive`, `validate -no-color` : OK.
- Init DEV explicite avec `-reconfigure -backend-config="backends/dev.hcl"`
  puis plan `-var-file="dev.tfvars" -detailed-exitcode` : **aucun changement**,
  exit 0. State distant avant/après : génération `1792688481031642`,
  métagénération 1, MD5 `FRfJAw07TWedCjfpor60nA==`, inchangés.
- Init PROD explicite avec `-reconfigure -backend-config="backends/prd.hcl"` : OK,
  workspace `default`, aucune ressource dans `terraform state list`.
  Plan `-var-file="prd.tfvars" -detailed-exitcode -out="prd.tfplan"` :
  **2 créations, 0 modification, 0 suppression**, exit 2 attendu.
  Inspection JSON du plan enregistré : seules `google_compute_network.vpc` et
  `google_compute_subnetwork.subnet` ont une action `create`, dans le bon projet.
- Provider Google 7.46.1 réutilisé avec `-lockfile=readonly`. Lockfile conservé.
  Le backend local final est PROD ; réinitialiser explicitement DEV avant usage DEV.
- README actualisé avec les deux environnements et les commandes PowerShell.
- GitNexus exécuté avant édition : cibles foundation/variables/docs/backend non
  trouvées, risque UNKNOWN, appelants/processus indéterminés. Recherche textuelle
  complémentaire : les usages Terraform concernés restent dans cette fondation.
  Index rafraîchi avec `analyze --index-only` (459 nœuds, 995 relations, 17 flux).
  FTS indisponible sous Windows ; aucun UNKNOWN présenté comme risque faible.
- Les accès réseau Terraform et gcloud ont été relancés hors sandbox après
  échecs d'accès réseau/credentials locaux. Utilisation de `gcloud.cmd` pour le
  lanceur Windows ; aucune modification de la politique d'exécution PowerShell.

---

# Audit C02 Hands-on 1 — 22 octobre 2026

## Actualisation : diagnostic du backend et tentative autorisée

Cette actualisation remplace les conclusions historiques ci-dessous lorsqu'elles
diffèrent. L'utilisateur a autorisé la création du seul bucket de state dans dev,
après vérification qu'aucun bucket partagé n'y existe. Aucun apply, destroy,
commit, push, changement IAM ni commande sur prod n'a été effectué.

- Projet actif et projet interrogé : `masterpoulet-dev`, numéro `539044310096`,
  statut ACTIVE. Un compte gcloud actif ; obtention d'un jeton ADC réussie sans
  affichage du jeton. Inventaires GCS réussis et vides, y compris après la tentative.
- `backends/dev.hcl` désigne toujours le nom proposé
  `masterpoulet-dev-tfstate-539044310096`, préfixe `foundation/dev`, sans `gs://`.
  Aucun bucket de state n'est disponible dans dev ; aucun bucket n'a été réutilisé.
- Création tentée avec `--project=masterpoulet-dev --location=europe-west1
  --uniform-bucket-level-access --public-access-prevention`, puis arrêt immédiat
  sur HTTP 403 : « The billing account for the owning project is disabled in
  state absent ». Le versionnement n'a donc pas pu être activé. Aucun bucket créé.
- `gcloud billing projects describe masterpoulet-dev` confirme
  `billingAccountName: ""` et `billingEnabled: false`. Un compte de facturation
  ouvert est visible. Son rattachement n'est pas autorisé par la seule demande de
  création du bucket : accord distinct demandé, aucune modification effectuée.
- Compute Engine API reste désactivée ; les listes VPC et subnets échouent avec
  SERVICE_DISABLED. Leurs sorties `[]` ne prouvent pas un inventaire vide, car
  les commandes échouent. Activation demandée séparément, non effectuée.
- `terraform init -backend-config 'backends/dev.hcl' -input=false -no-color`
  reproduit réellement HTTP 404 hors du bac à sable. `terraform fmt` et
  `terraform fmt -check` réussissent (codes 0), ainsi que `terraform validate`.
  `terraform plan -var-file 'dev.tfvars' -input=false -lock-timeout=30s -no-color`
  échoue : backend initialization required. Aucun plan enregistré ou approuvé.
- La configuration vise dev, VPC global `masterpoulet-dev-vpc`, subnet régional
  `masterpoulet-dev-vpc-subnet` en `europe-west1`, CIDR `10.0.1.0/24`.
  Deux créations, zéro modification et zéro suppression restent une attente,
  pas un résultat de plan. L'absence de conflit avec l'équipe reste à vérifier.
- Scan heuristique des fichiers suivis : aucun motif de clé privée, compte de
  service JSON, refresh token, clé API Google, token GitHub ou clé AWS détecté ;
  aucun chemin de credentials, `.env`, state ou cache Terraform suivi détecté.
  Ce scan ne constitue pas un audit exhaustif de l'historique Git.
- `git check-ignore -v` confirme les exclusions `.terraform/`, `*.tfstate`,
  `*.tfstate.*` et `*.tfplan`. `.terraform.lock.hcl` reste non ignoré, présent
  parmi les fichiers non suivis à inclure dans une future revue. Pas de staging.
- Impact GitNexus exécuté avant ces modifications documentaires : cibles README
  et AUDIT absentes du graphe, risque UNKNOWN ; appelants et processus
  indéterminés. La recherche textuelle complémentaire n'a trouvé aucune
  dépendance exécutable vers ces documents. Seuls README et AUDIT ont été
  actualisés ; aucune correction HCL n'est nécessaire pour l'erreur observée.

Suite : obtenir le rattachement de facturation et l'activation Compute autorisés,
réinventorier dev, créer et sécuriser le bucket, vérifier les droits des trois
développeurs, initialiser le backend, puis produire et examiner le vrai plan.
L'application nécessitera toujours une autorisation explicite distincte.

## Résultat

Préparation locale terminée. Aucun apply, destroy, import, commit, push, changement
IAM, activation d'API ou création cloud n'a été exécuté. Aucune commande n'a ciblé
`masterpoulet-prod`. Aucun secret ni fichier d'authentification n'a été édité.

Le **plan réel n'est pas disponible** : le bucket distant manque et Compute
Engine API est désactivée. Le résultat attendu de la configuration, sous réserve
d'inventaire et de state vides, est deux créations, aucune modification ni
suppression. Ce n'est pas un résultat de plan exécuté.

## Dépôt et collaboration

- README.md, CONTRIBUTOR.md et AGENTS.md lus avant les ajouts.
- Dépôt initial propre sur `main`, commit `8f9c194` ; référence locale
  `origin/main` initialement à `70489eb`.
- `git ls-remote` puis `git fetch origin main` ont confirmé la référence GitHub
  `35a0cde54a5554f3f0a443de6f2d6ea95ff9e87f`.
- Branche créée : `feat/c02-foundation`, depuis cet `origin/main` à jour. La
  branche locale `main` n'a pas été avancée. Le checkout inclut naturellement les
  changements déjà publiés par l'équipe ; aucun fichier applicatif n'a été édité.
- Structure existante : backend Express/Prisma, frontend React/Vite, Compose,
  Nix/just et workflows GitHub Actions. Aucune fondation Terraform trouvée, ni
  dans le checkout initial, ni dans `origin/main` récupéré.
- Risques : modifications concurrentes de la fondation après cet instant,
  ressources cloud créées hors Terraform, adoption d'un même objet par plusieurs
  states, CIDR incompatible avec une future interconnexion. Une branche Git ne
  protège pas les ressources partagées GCP : coordination et state commun requis.

## GCP et outils observés

| Contrôle | Résultat observé |
| --- | --- |
| Git | 2.55.0.windows.5 |
| Terraform | 1.16.6, windows_amd64 |
| gcloud | Google Cloud SDK 590.0.0 |
| Projet actif | `masterpoulet-dev` ; configuration non modifiée |
| Projet dev | ACTIVE, numéro `539044310096` |
| Authentification gcloud | Un compte utilisateur actif |
| ADC Terraform | Obtention de jeton réussie ; jeton non affiché |
| Buckets dans dev | Liste JSON `[]` ; aucun bucket visible dans le projet |
| Compute API | Absente des API activées ; les deux inventaires réseau échouent avec SERVICE_DISABLED |
| VPC/subnets existants | Non déterminés, et non considérés absents |
| Compatibilité `10.0.1.0/24` | Non vérifiable tant que l'inventaire Compute échoue |

Un appel REST `projects/masterpoulet-dev:testIamPermissions` a confirmé, parmi
les permissions demandées :

```text
compute.networks.create
compute.networks.delete
compute.networks.list
compute.subnetworks.create
compute.subnetworks.delete
compute.subnetworks.list
serviceusage.services.enable
storage.buckets.create
storage.buckets.list
```

Les permissions demandées suivantes n'ont pas été retournées au niveau projet :
`storage.buckets.get`, `storage.buckets.update`, et `storage.objects.get/list/create/delete`.
Ce test ne donne pas la liste complète des rôles ou des droits effectifs d'un
futur bucket. Vérifier les droits au niveau du bucket après bootstrap ; un
administrateur peut devoir configurer les accès et le versioning. Les droits
Compute `get/use/update` nécessaires aux opérations futures n'ont pas tous été
testés. Aucun droit IAM n'a été accordé automatiquement.

## Vérifications exécutées

| Vérification | Résultat |
| --- | --- |
| `terraform fmt -recursive` | Réussite |
| `terraform fmt -check -recursive` | Réussite |
| `terraform init -backend=false -input=false` | Réussite après autorisation réseau ; Google 7.46.1 signé HashiCorp |
| `terraform validate -no-color` | Réussite |
| `./check.ps1 -LocalOnly` | Réussite après autorisation réseau |
| Parseur PowerShell sur `check.ps1` | Aucune erreur de syntaxe |
| `./check.ps1` | Arrêt attendu : bucket absent de dev, avant init distant |
| Init avec GCS | Non exécuté : prérequis absent ; le garde-fou refuse un backend non trouvé dans dev |
| `terraform plan '-var-file=dev.tfvars' -input=false -lock-timeout=60s -no-color` | Échec : Backend initialization required ; aucun plan produit |
| `git diff --check` | Réussite pour les différences suivies ; les nouveaux fichiers restent non suivis |

Les premiers essais dans le bac à sable ont échoué sur la base locale gcloud,
l'accès GitHub/npm et le registre Terraform. Les audits nécessaires ont été
relancés avec les autorisations d'accès correspondantes. Un premier essai de
plan sans guillemets sur `-var-file=dev.tfvars` a échoué avec « Too many command
line arguments » ; les commandes PowerShell du script et du guide ont été
corrigées avec des arguments entre guillemets, puis le plan a été relancé.

## Analyse d'impact

GitNexus 1.6.12 a d'abord signalé l'absence d'index local, puis
`npx --yes gitnexus@1.6.12 analyze --index-only` a indexé le dépôt à `35a0cde`
(423 nœuds, 960 relations, 17 flux). L'option `--index-only` a préservé les
instructions du dépôt. Cache et lanceur locaux créés sous `.gitnexus/`, ignorés
par Git. La recherche FTS est dégradée à cause d'une bibliothèque Windows
manquante ; les analyses d'impact ont néanmoins retourné leur résultat JSON.

Les impacts upstream sur `infra/foundation`, `masterpoulet-dev-vpc` et
`infra/foundation/check.ps1` ont retourné cible absente, risque **UNKNOWN**,
appelants/processus affectés indéterminés. Ce n'est pas un résultat LOW.
La recherche littérale complémentaire avant édition n'a trouvé aucune référence
Terraform/foundation dans les fichiers existants examinés. Les ajouts sont
isolés dans un nouveau dossier ; aucun symbole applicatif existant n'a changé.
Les fichiers de skill `.claude/skills/` référencés étaient absents : les guides
GitNexus impact et CLI livrés avec le paquet installé ont été consultés.
Avant tout futur commit, refaire l'analyse de changements prescrite par AGENTS.md.

Le contrôle final `node .gitnexus/run.cjs detect-changes --scope all --repo .`
a répondu « No changes detected ». Les douze fichiers nouveaux étant encore
non suivis, ce zéro ne démontre pas leur absence d'impact et n'est pas présenté
comme un contrôle de graphe complet. Aucun commit n'est effectué. Le contrôle
final confirme aussi que les fichiers existants suivis sont identiques à
`origin/main`, que les fichiers state/plan et `.terraform/` sont ignorés, et que
le lock provider reste visible parmi les fichiers à versionner.

## Commandes réellement exécutées

Les commandes ci-dessous regroupent les variantes et répétitions de l'audit ;
les chemins de travail étaient la racine du dépôt ou `infra/foundation`.
Les lectures ont utilisé `Get-Content`, `Get-ChildItem`, `Test-Path`, `rg --files`
et `rg -n` ; aucune lecture du contenu des fichiers de credentials.

```powershell
Get-Location
Get-Command git,terraform,gcloud -ErrorAction SilentlyContinue
Get-Command node,npx,bun,just -ErrorAction SilentlyContinue
Get-Command docker,podman -ErrorAction SilentlyContinue
git --version
terraform version
gcloud version
git status --short --branch
git status --porcelain=v1
git log --oneline -4
git log --oneline HEAD..origin/main
git log -1 --format='%h %s' origin/main
git rev-list --left-right --count HEAD...origin/main
git branch --list
git diff --stat HEAD..origin/main
git diff --name-only HEAD..origin/main
git ls-remote origin refs/heads/main
git fetch origin main
git show origin/main:CONTRIBUTOR.md
git show origin/main:README.md
git ls-tree -r --name-only origin/main -- infra .claude .github/workflows
git switch -c feat/c02-foundation origin/main
git diff --name-only origin/main
git diff --check
gcloud auth list --format='table(account,status)'
gcloud config get-value project
gcloud projects describe masterpoulet-dev --format='yaml(projectId,projectNumber,lifecycleState)'
gcloud services list --enabled --project=masterpoulet-dev --format='value(config.name)'
gcloud compute networks list --project=masterpoulet-dev --format='table(name,subnet_mode,routingConfig.routingMode)'
gcloud compute networks subnets list --project=masterpoulet-dev --format='table(name,region,network,ipCidrRange)'
gcloud storage buckets list --project=masterpoulet-dev --format='table(name,location,versioning.enabled,iamConfiguration.uniformBucketLevelAccess.enabled)'
gcloud storage buckets list --project=masterpoulet-dev --format='json(name,location,versioning,iamConfiguration)'
# Authentification normale en mémoire, sans affichage des jetons :
# gcloud auth print-access-token --project=masterpoulet-dev
# Invoke-RestMethod POST https://cloudresourcemanager.googleapis.com/v1/projects/masterpoulet-dev:testIamPermissions
# gcloud auth application-default print-access-token --project=masterpoulet-dev (sortie supprimée)
npx --yes gitnexus@latest impact 'infra/foundation' --direction upstream --repo .
npx --yes gitnexus@1.6.12 analyze --help
npx --offline gitnexus analyze --help
npx --yes gitnexus@1.6.12 analyze --index-only
node .gitnexus/run.cjs impact 'infra/foundation' --direction upstream --repo .
node .gitnexus/run.cjs impact 'masterpoulet-dev-vpc' --direction upstream --repo .
node .gitnexus/run.cjs impact 'infra/foundation/check.ps1' --direction upstream --repo .
node .gitnexus/run.cjs detect-changes --scope all --repo .
git ls-files --others --exclude-standard infra/foundation
git check-ignore infra/foundation/.terraform/ infra/foundation/dev.tfplan infra/foundation/terraform.tfstate
git diff --exit-code origin/main -- README.md CONTRIBUTOR.md AGENTS.md CLAUDE.md backend frontend .github .gitignore
# Depuis infra/foundation :
terraform fmt -recursive
terraform fmt -check -recursive
terraform init -backend=false -input=false
terraform validate -no-color
terraform plan '-var-file=dev.tfvars' -input=false -lock-timeout=60s -no-color
./check.ps1 -LocalOnly
./check.ps1
```

Le parseur `[System.Management.Automation.Language.Parser]::ParseFile` a aussi
été utilisé pour `check.ps1`. Certains appels Terraform depuis la racine ont
utilisé `'-chdir=infra/foundation'`, avec les mêmes résultats. `apply_patch` a
créé les fichiers et corrigé les arguments PowerShell.

## Suite après accord

1. Autoriser l'activation de Compute API et la création du bucket proposé,
   avec accès uniforme, prévention d'accès public et versioning. Commandes
   exactes dans README.md ; aucun changement IAM implicite.
2. Vérifier les accès bucket de l'équipe, puis réinventorier les réseaux et les
   CIDR. Revoir le besoin d'import si un coéquipier a déjà créé les ressources.
3. Lancer `./check.ps1` pour init GCS, validation et plan. Présenter ce plan réel.
4. Obtenir ensuite un accord distinct pour `terraform apply dev.tfplan`.
5. Vérifier les deux ressources et l'absence de dérive. La procédure de
   destruction/recréation après accord est dans README.md.

Le backend GCS est choisi pour le partage du state et son verrouillage natif.
Le versioning permet la récupération d'anciennes versions du state. Référence :
[documentation HashiCorp GCS](https://developer.hashicorp.com/terraform/language/backend/gcs).
