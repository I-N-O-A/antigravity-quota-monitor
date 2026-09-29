---
name: git-commit-push
description: >-
  Automated, non-interactive Git staging, committing, and pushing to GitHub or remote repositories using local credentials (Git Credential Manager) and best practices. Use whenever the user asks to commit, push, create git commits, or publish code changes to Git/GitHub without interactive login prompts.
---

# Git Commit and Push Automation

This skill guides Antigravity agents in performing safe, automated, and non-interactive Git operations (inspecting status, staging, committing, and pushing to remote repositories such as GitHub) without requiring manual login credentials.

---

## 1. How Non-Interactive Authentication Works

On this machine (and Windows developer environments in general), Git does not require interactive password prompts during agent runs because:
1. **Git Credential Manager (GCM)**: Configured via `credential.helper = manager` in Git's system/global config.
2. **Windows Credential Vault**: When the user first logs in or authenticates with GitHub, Windows securely saves the OAuth token or Personal Access Token (PAT) under Generic Windows Credentials.
3. **Silent Passthrough**: Every subsequent `git push` or `git fetch` automatically queries the Windows Credential Vault in the background, authenticating the push seamlessly without launching a browser or blocking on CLI input.
4. **Git Identity**: The user identity (`user.name` and `user.email`) is preconfigured in `.git/config` or `~/.gitconfig`, allowing `git commit` to produce properly attributed commits without prompting.

---

## 2. Standard Workflow for Agents

### Step 1: Inspect Status and Diffs First
Always review the working tree before taking any action. Never stage blindly.

```powershell
git status
git diff
```

Checklist before staging:
- [ ] Ensure only intentional code modifications are modified.
- [ ] Confirm no temporary files, test images (`*.png`, `*.tmp`), API keys, or `.env` files are unstaged or untracked.
- [ ] If temporary files exist, delete them or add them to `.gitignore`.

### Step 2: Verify Git Identity and Remote
Ensure the repository has an identity and remote set up:

```powershell
git remote -v
git branch --show-current
git config user.name
git config user.email
```

If `user.name` or `user.email` are missing, notify the user or configure them locally:
```powershell
git config user.name "username"
git config user.email "email@example.com"
```

### Step 3: Targeted Staging
Stage specific modified files rather than using broad commands whenever possible:

```powershell
git add path/to/file1.py path/to/file2.json
```

Verify staged changes:
```powershell
git diff --staged
```

### Step 4: Create a Clear, Descriptive Commit
Format the commit message according to repository conventions:
- Use imperative/present tense (e.g. `Harmonize outer window chassis...`, `Fix crash on startup...`, `Add feature...`).
- Provide context on what was changed and why.

```powershell
git commit -m "Descriptive summary of changes"
```

### Step 5: Push Non-Interactively
Push the current branch to the upstream remote:

```powershell
# For existing tracked branches:
git push origin <branch-name>

# For newly created branches setting upstream:
git push -u origin <branch-name>
```

### Step 6: Verify Clean State
Ensure the branch is up to date and clean:

```powershell
git status
```

---

## 3. Troubleshooting & Safety Guidelines

- **Protected branches**: If `git push` fails due to remote branch protection rules (e.g. PR required), inform the user and suggest creating a feature branch: `git checkout -b feature/name`, `git push -u origin feature/name`.
- **Remote has new commits (reject - non-fast-forward)**:
  Run `git pull --rebase origin <branch>` to incorporate remote changes before retrying the push.
- **Credential issues**:
  Verify the credential helper is active: `git config credential.helper`. It should be `manager` on Windows.
- **Never force push** (`--force` or `-f`) unless explicitly requested by the user.
