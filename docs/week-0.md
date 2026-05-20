# Week 0 — Local setup

> **Status:** ✅ done (one-time onboarding). The canonical setup
> walkthrough — clone, GCP project, service account, Python env,
> dbt profile, `dbt debug`. Anyone joining the project starts here.
> Per-week files (`week-1.md`, `week-2.md`, …) cover the build work
> for each week and link back to this file for the underlying env.

One-time setup to get the project running locally. For what to actually
build week-by-week, see [plan.md](./plan.md).

> Assumes **BigQuery** as the warehouse. Snowflake instructions would
> replace steps 1-3 only.

## Prerequisites

- Python 3.11+
- Git
- A GCP account with billing enabled
  (the BigQuery free tier — 1 TB query/mo, 10 GB storage — covers this project)

---

## 1. GCP project (~15 min)

1. https://console.cloud.google.com → create a new project, e.g. `github-activity-pipeline`.
2. Note the **Project ID** (looks like `github-activity-pipeline-12345`).
3. Link a billing account. BigQuery requires billing enabled even for
   free-tier usage, but you won't be charged for this project's typical volume.

**Success check:** project visible in console, billing status = active.

## 2. Enable APIs (~2 min)

In the GCP console search bar, enable:
- **BigQuery API**
- **Cloud Storage API** (you'll need it for ingestion in Week 3)

> Some GCP UIs list both "Cloud Storage" (the product page, no Enable button)
> and "Cloud Storage API" (the actual API entry with an Enable button).
> The one you want is **Cloud Storage API** — search with "API" at the end.

## 3. Service account + key (~10 min)

1. IAM & Admin → Service Accounts → Create.
2. Name: `dbt-runner`.
3. Grant roles: **BigQuery User** + **BigQuery Job User** + **BigQuery Data Editor**.
4. Create a JSON key, download it.
5. Move it into the repo:
   ```bash
   mkdir -p credentials
   mv ~/Downloads/<the-key>.json credentials/dbt-runner.json
   ```
   The `credentials/` folder is already in `.gitignore`.

**Common gotcha:** if `dbt debug` later says `403 Access Denied`, it's almost
always missing the **Job User** role — easy to miss because the name sounds
redundant with "BigQuery User".

## 4. Local Python environment (~2-3 min with uv, ~10 min with pip)

This project uses [uv](https://github.com/astral-sh/uv) — a Rust-based
Python package manager that installs deps 10-50× faster than pip. For
this project's dependencies (Dagster + GCP libs), that's seconds vs.
minutes.

### Default path: uv

```bash
# Install uv (one-time, ~5 seconds)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Alternatives: pipx install uv  /  brew install uv  /  pip install uv

cd /path/to/github-activity-pipeline
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Fallback path: vanilla pip

If you don't want to install uv:

```bash
cd /path/to/github-activity-pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Success check (either path):** `dbt --version` prints `1.8.x` and lists `bigquery: 1.8.x`.

> **Why uv and not Poetry / pdm / hatch?** uv covers the same use case
> with one binary and zero config — `requirements.txt` works as-is.
> Migrating to a full `pyproject.toml` + `uv.lock` setup is a logical
> later step (good LEARNING_LOG candidate for Week 2), but not needed
> to start.

## 5. Environment variables (~5 min)

```bash
cp .env.example .env
```

Now **edit `.env` and replace every placeholder with a real value**. The
`.env.example` file contains illustrative paths like `/absolute/path/to/...`
which are **not** valid — they must be substituted with your actual paths.

A filled-in `.env` looks like this (with your username and project ID, not these):

```
GCP_PROJECT_ID=github-activity-pipeline-12345          # the immutable Project ID from Step 1, NOT the display name
GCS_BUCKET=                                            # leave blank until Week 3
GOOGLE_APPLICATION_CREDENTIALS=/home/you/Documents/projects/github-activity-pipeline/credentials/dbt-runner.json
GITHUB_TOKEN=                                          # leave blank until Week 3
DBT_PROFILES_DIR=/home/you/Documents/projects/github-activity-pipeline/transform
```

**Two values that catch people:**

- `DBT_PROFILES_DIR` is a **directory**, not a file. Do NOT append `/profiles.yml`.
- `DBT_PROFILES_DIR` **must be absolute**. A relative path like `./transform`
  breaks the moment you `cd` into `transform/` to run dbt — it resolves to
  `transform/transform/`. From the project root, run `pwd` to get the
  absolute path, then append `/transform`.

### Why hardcode an absolute path here?

This is a deliberate simplification for local dev — not how production dbt
projects usually handle this. The trade-off:

| Approach | Used by | Pros / cons |
|----------|---------|-------------|
| **Hardcoded absolute path in `.env`** (what we do) | Solo / portfolio projects | Simple, no extra tooling. Ugly; each dev fills in their own path. |
| **direnv** (`.envrc` auto-loads on cd) | Most experienced dbt devs | Dynamically computes `$(pwd)/transform` each time. Requires installing direnv. |
| **`~/.dbt/profiles.yml`** (dbt's default lookup) | Many production teams | Zero env vars needed. But profile lives outside the repo, so setup is less reproducible. |
| **Env vars injected by CI / Docker / Airflow** | Real production deployments | The runtime controls the working directory and secrets. No `.env` involved. |

For CI we already do the "production" version: `.github/workflows/dbt-ci.yml`
sets `DBT_PROFILES_DIR: ./transform` at the workflow level, and GitHub Actions
always runs from the repo root, so the relative path is safe.

For local dev, the absolute path is the lowest-friction option that doesn't
require extra tooling. If you adopt direnv later, drop `DBT_PROFILES_DIR` from
`.env` and create `.envrc` with:

```bash
export DBT_PROFILES_DIR=$(pwd)/transform
```

Then `direnv allow` once and forget about it.

### Load and verify

After editing `.env`, load it into your shell:

```bash
set -a && source .env && set +a
```

**Verify the values actually made it into your shell** (this is the #1 cause
of "I edited the file but dbt still shows the old path"):

```bash
echo $DBT_PROFILES_DIR              # should print your absolute path, not /absolute/path/to/...
echo $GOOGLE_APPLICATION_CREDENTIALS # should print your real credentials path
ls $GOOGLE_APPLICATION_CREDENTIALS   # should print the JSON file, not "No such file"
```

If any of those still show placeholder text, your shell has the old values
cached — re-run the `set -a && source .env && set +a` line. **Editing `.env`
does not retroactively update an already-open shell.**

> Tip: add a tiny `direnv` `.envrc` later if you don't want to source manually
> each session.

## 6. dbt profile (~3 min)

```bash
cp transform/profiles.yml.example transform/profiles.yml
```

No edits required — `profiles.yml` reads everything from env vars.

## 7. Verify (~5 min)

```bash
cd transform
dbt deps
dbt debug
```

**Success check:** ends with `All checks passed!`.

### Troubleshooting `dbt debug` failures

Match the error you see to one of these:

| What dbt says | What it actually means | Fix |
|---------------|------------------------|-----|
| `profiles.yml file [ERROR not found]` and the printed path contains `/absolute/path/to/` | Shell has the stale (placeholder) `DBT_PROFILES_DIR`; `.env` was edited but not re-sourced | `cd <project-root> && set -a && source .env && set +a` |
| `profiles.yml file [ERROR not found]` and the printed path ends in `/transform/transform/` | `DBT_PROFILES_DIR` is a relative path; you `cd`-ed into `transform/` so it resolved twice | Set it to an absolute path in `.env`, re-source |
| `profiles.yml file [ERROR not found]` and the printed path ends in `/profiles.yml` | `DBT_PROFILES_DIR` was set to the *file* instead of the *directory* | Remove `/profiles.yml` from the end of the env var |
| `[Errno 2] No such file or directory: '/absolute/path/to/service-account.json'` | `GOOGLE_APPLICATION_CREDENTIALS` is still the placeholder | Replace with absolute path to your real JSON key, re-source |
| `403 Access Denied` or `Forbidden` | Service account is missing an IAM role | Re-check step 3 — most commonly **BigQuery Job User** is missing |
| `Could not load credentials from file` (file exists) | Wrong/corrupted service account JSON | Re-download the key from GCP, replace the file |

The "re-source" step is the one that catches almost everyone the first
time. **Editing `.env` does not update your open shell** — you have to
re-run `set -a && source .env && set +a` after every edit.

## 8. GitHub SSH key for `git push` (~5 min)

`dbt debug` confirms your local build works. To **push commits** to
GitHub you also need an authenticated identity — by default a freshly
cloned HTTPS remote can't push, because GitHub deprecated password
auth and the URL has no credentials attached. SSH is the cleanest
fix: one-time setup, no token rotation.

> Why not the GitHub PAT we set in `week-3.md`? That one is
> fine-grained, scoped to **public repositories (read-only)** —
> intentionally weak, only for lifting the REST API rate limit. It
> cannot push to your repo.

### 8.1. Generate an ed25519 key

```bash
ssh-keygen -t ed25519 -C "<your-github-email>" -f ~/.ssh/id_ed25519 -N ""
```

- `-t ed25519` — the modern algorithm (smaller and faster than RSA).
- `-C` — a comment baked into the public key; GitHub displays it in
  your key list. Use your GitHub email.
- `-f` — output path. Default key name on Linux is `~/.ssh/id_ed25519`.
- `-N ""` — empty passphrase. Add one if you want extra security at
  the cost of typing it on every push (ssh-agent can cache it).

This writes two files:

```
~/.ssh/id_ed25519       # private key — never share, never commit
~/.ssh/id_ed25519.pub   # public key — safe to paste anywhere
```

### 8.2. Add the public key to GitHub

```bash
cat ~/.ssh/id_ed25519.pub
```

Copy the entire line of output. Then in the browser:

1. Open https://github.com/settings/keys.
2. Click **New SSH key**.
3. **Title:** describe the machine (e.g. `edwin-vivobook`). It's a
   label for you — pick something so you can revoke this specific
   key later if the laptop goes missing.
4. **Key type:** `Authentication Key` (the default).
5. **Key:** paste the entire `ssh-ed25519 …` line.
6. Click **Add SSH key**. GitHub may prompt you to confirm with your
   account password — that's a sudo-equivalent reauthentication, not
   the auth method we're setting up.

### 8.3. Switch the remote URL from HTTPS to SSH

```bash
cd /path/to/github-activity-pipeline
git remote set-url origin git@github.com:<you>/github-activity-pipeline.git
git remote -v   # both lines should now start with git@github.com:
```

### 8.4. Verify

```bash
ssh -T git@github.com
```

**Success check:** `Hi <you>! You've successfully authenticated, but
GitHub does not provide shell access.` That second clause is
expected — SSH on GitHub is for git only, not for opening a remote
shell.

The first time, SSH will also prompt:

```
The authenticity of host 'github.com (140.x.x.x)' can't be established.
ED25519 key fingerprint is SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Type `yes`. This adds GitHub's host key to `~/.ssh/known_hosts` so
future connections skip the prompt. The fingerprint above is
GitHub's published ed25519 — worth comparing it to
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
the first time to confirm you're not being MITM'd.

### 8.5. Push

```bash
git push origin main
```

If you have local commits ahead of `origin/main`, they'll all upload
in one round trip. From this point on, every `git push` /
`git pull` / `git fetch` uses your SSH key silently — no prompts,
no tokens to rotate.

### Troubleshooting

| What you see | What it means | Fix |
|---|---|---|
| `Permission denied (publickey)` | Either the key isn't loaded, or it isn't on GitHub | `ssh-add -l` shows loaded keys; if empty, run `ssh-add ~/.ssh/id_ed25519`. If the key is loaded, re-check step 8.2 — did you paste the **`.pub`** file? |
| `Permission to <user>/<repo>.git denied to <user>` on push | Remote is still HTTPS | `git remote -v` — if you see `https://`, redo step 8.3 |
| `Host key verification failed` | Someone (or something) is tampering, OR `known_hosts` got corrupted | `ssh-keygen -R github.com` then re-run `ssh -T git@github.com` and accept the new fingerprint |
| `ssh-keygen: command not found` | OpenSSH isn't installed | `sudo apt install openssh-client` (Debian/Ubuntu) or equivalent |

---

## You're done with Week 0 setup. What's next?

Once `dbt debug` says `All checks passed!`, your environment is fully
configured for Week 1. Continue to [`week-1.md`](./week-1.md) — the
first real model run. If you'd rather see the full project map first,
[`plan.md`](./plan.md) is the multi-week roadmap.

### Per-week files

Each subsequent week has its own file with both prereqs (new packages,
GCP surfaces, tokens to set) and the build work itself:

- [`week-1.md`](./week-1.md) — first dbt run end-to-end
- [`week-2.md`](./week-2.md) — flesh out the staging layer
- [`week-3.md`](./week-3.md) — GitHub REST API ingestion (GCS + BQ)
- Weeks 4-8: added as they land.
