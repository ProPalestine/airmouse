# GitHub setup and publishing guide for Linux

This guide covers installing Git, setting up your GitHub identity on this computer, keeping credentials out of project files, and publishing the AirMouse project. The steps use the terminal and GitHub's website. GitHub CLI is optional.

## 1. Install Git

On Ubuntu or Debian:

```bash
sudo apt update
sudo apt install git
git --version
```

Git is a version-control program. It records project changes locally; it does not upload anything until you push to a remote repository.

## 2. Set your commit name and email

Choose the name and email that should appear on your commits. GitHub recommends using the private `noreply` address from **GitHub > Settings > Emails** if you do not want your personal email visible in commit history.

```bash
git config --global user.name "Your Name"
git config --global user.email "YOUR_GITHUB_NOREPLY_EMAIL"
git config --global init.defaultBranch main
```

These settings identify commits; they are not login credentials. Review them with:

```bash
git config --global --get user.name
git config --global --get user.email
```

Do not put passwords, personal access tokens, or SSH private keys in Git configuration or a project file.

## 3. Create a repository on GitHub

1. Sign in at [github.com](https://github.com).
2. Open **New repository** from the plus menu.
3. Name it `airmouse` (or choose another name).
4. Choose **Public** if you want anyone to see it, or **Private** if access should be restricted. Making a repository public exposes its source, documentation, and commit history to everyone.
5. Leave **Add a README**, **.gitignore**, and **license** unchecked when creating the repository, since AirMouse already has project files and a `.gitignore`.
6. Select **Create repository**. Keep the page open to copy the repository's HTTPS URL.

## 4. Review what will be published

Open a terminal in the project folder:

```bash
cd ~/Documents/Airmouse
git status --short
```

The project's `.gitignore` excludes the virtual environment, caches, local OpenWork/OpenCode attachments and state, the separate `ydotool` source checkout, social-media export graphics, `.env` files, and logs. Git does not upload ignored files.

Before staging, inspect any unexpected files. Do not publish credentials, private keys, `.env` files, webcam recordings, private documents, or generated build outputs. Check that `.gitignore` is protecting any private/local files you use. If a real credential was ever committed, removing it in a later commit does not erase it from earlier history: revoke or rotate it with its provider.

For an explicit review of the proposed project file list:

```bash
git add .gitignore README.md app.py install.sh run.sh requirements.txt templates static tests docs
git status --short
git diff --cached --stat
git diff --cached --check
```

This selects the app, tests, and documentation. The local `ydotool/` checkout and social-media export graphics are excluded because they are separate or personal material; AirMouse's README explains how to install the ydotool dependency. Review the staged file list before continuing. To remove an accidentally staged path without deleting its local copy, run `git restore --staged -- path/to/file`.

## 5. Create the first commit

After checking the staged paths:

```bash
git commit -m "Build local AirMouse gesture controller"
```

If Git asks for an identity, repeat step 2 with your chosen name and email.

## 6. Sign in securely and push with HTTPS

Set the remote to the HTTPS URL copied from the new GitHub repository. Replace the example URL with your own:

```bash
git remote add origin https://github.com/YOUR_USERNAME/airmouse.git
git remote -v
git push -u origin main
```

GitHub does not accept your account password for Git over HTTPS. When prompted, use a browser-based sign-in or a credential manager if available. If Git asks for a token, create one only through GitHub's settings, grant the minimum repository access needed, and enter it in the credential prompt. Never paste the token into a command, chat, project file, README, or screenshot. Do not save it in shell history.

If the project already has a remote, inspect it with `git remote -v` before changing anything. To correct an existing remote URL:

```bash
git remote set-url origin https://github.com/YOUR_USERNAME/airmouse.git
```

If the existing repository has commits that your local branch does not, stop and inspect the GitHub page and Git history before merging or pushing. Do not force-push as a shortcut.

## 7. Optional: use SSH instead of HTTPS

SSH avoids entering HTTPS credentials each time, but the private key must stay on this computer and must never be uploaded to GitHub or committed.

Create a key (use your GitHub `noreply` email, or omit the comment):

```bash
ssh-keygen -t ed25519 -C "YOUR_GITHUB_NOREPLY_EMAIL"
```

Accept the default file location. Choose a passphrase. Start the SSH agent and add the key:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```

Copy only the public key to the clipboard/output for adding under **GitHub > Settings > SSH and GPG keys > New SSH key**:

```bash
cat ~/.ssh/id_ed25519.pub
```

The file ending in `.pub` is public. Keep `~/.ssh/id_ed25519` private. Test the connection:

```bash
ssh -T git@github.com
```

Then use an SSH remote:

```bash
git remote set-url origin git@github.com:YOUR_USERNAME/airmouse.git
git push -u origin main
```

## 8. Publish future changes

After editing files:

```bash
cd ~/Documents/Airmouse
git status --short
git diff
git add path/to/changed-file
git diff --cached --check
git commit -m "Describe the change"
git push
```

Use explicit paths with `git add` when you want careful control over what gets committed. Check GitHub's repository page after pushing to confirm the files and README appear as expected.

## If the browser asks you to sign in

Complete sign-in, multi-factor authentication, or a passkey prompt directly in the browser. Do not share passwords, one-time codes, recovery codes, cookies, or tokens in chat. After the website confirms sign-in, return to the terminal and run the push command again if it did not complete.

## AirMouse-specific privacy note

AirMouse processes webcam frames and hand landmarks in the browser according to its README. Keep private recordings, credentials, and local OpenWork attachments outside the repository. The current README has been edited to use a generic project path instead of a machine-specific home directory.
