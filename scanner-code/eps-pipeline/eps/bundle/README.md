# Running the policy-statement pipeline on your computer

**What this is.** This bundle holds about 6,600 UK and US government documents from January to July 2026, and the program that turns them into the policy-statement dataset. Through your own Codex sign-in, it asks an OpenAI model to pick out the passages where a minister or secretary states a policy choice, then builds the finished UK and US datasets. You send the output back.

**What it touches.**

- It reads only its own folder and writes only to the `output` folder inside it.
- Its model calls go through Codex with shell commands, web search and connectors switched off, in a read-only sandbox, so the model can only read the text it is given and answer.
- It makes no other network connections.
- It uses your ChatGPT plan's Codex usage. If you reach a usage limit it stops cleanly, and running it again later carries on where it left off.

---

## The easy way: let Codex do it

1. **Install Codex and sign in** with your ChatGPT account, following OpenAI's instructions: [learn.chatgpt.com/docs/codex/cli](https://learn.chatgpt.com/docs/codex/cli). The Codex desktop app works too.
2. **Download `eps-bundle.zip`** from the shared Google Drive folder into your **Downloads** folder.
3. **Open a new Codex chat.** Attach `eps-bundle.zip` if Codex lets you (Codex also finds it in Downloads if not). Copy this message in whole and send it:

   ```
   Please set up and run the eps pipeline from the attached eps-bundle.zip. If you can't open the attachment, use eps-bundle.zip (or an eps-bundle folder) in my Downloads folder. Unpack it to C:\eps-bundle on Windows or ~/eps-bundle on a Mac, then read INSTRUCTIONS_FOR_CODEX.md inside it and follow it step by step. Ask me before choosing the model and reasoning effort.
   ```

4. **Answer Codex's questions and approve its requests.** It asks which model and reasoning effort to use. It asks permission to unpack the bundle, to download a few Python packages, and to open the window the run works in. These permission prompts are Codex's own safety checks; approving them is expected.
5. **Leave it running.** It takes many hours, possibly more than a day, in its own window. Keep the computer on and plugged in. If it stops, open Codex and say **"restart the eps run"**.
6. **When it finishes,** tell Codex **"the eps run has finished"**. It puts the results in `eps-output.zip` on your Desktop. Upload that file to the **`returns`** folder in the shared Google Drive folder.

That is all. The rest of this page is the same job done by hand, for anyone who prefers it or if Codex has trouble.

---

## By hand

**How to use these instructions.** Every grey box below is meant to be copied and pasted whole into a terminal, then run with Enter. Use the **Windows** box or the **Mac** box, not both.

- **Windows:** open **PowerShell** (Start menu, type `PowerShell`, press Enter).
- **Mac:** open **Terminal** (press Cmd+Space, type `Terminal`, press Enter).

---

### Step 1 — Install Python (once)

**Windows:** paste this. If it asks you to agree to terms, type `Y` and press Enter.

```powershell
winget install -e --id Python.Python.3.14 --source winget
```

**Mac:** download and run the installer from [python.org/downloads](https://www.python.org/downloads/) (the big yellow button), clicking through with the default options.

Then **close the terminal window and open a new one**, so it can find Python.

### Step 2 — Install Codex and sign in (once)

Install the Codex CLI by following OpenAI's instructions for your system: [learn.chatgpt.com/docs/codex/cli](https://learn.chatgpt.com/docs/codex/cli).

Then **close the terminal window, open a new one**, and paste this to sign in with your ChatGPT account (it opens your browser):

```
codex login
```

### Step 3 — Download the bundle

From the shared Google Drive folder, download **`eps-bundle.zip`** into your **Downloads** folder. If your computer unzips it for you, that is fine too: the next step handles either.

### Step 4 — Unpack it and set it up (once)

This unpacks the bundle and creates a private Python environment inside it. Nothing is installed anywhere else on your computer. It takes a few minutes. Paste the whole box at once, and wait for it to finish.

It finishes with **`SETUP COMPLETE`** in green. If something goes wrong, it stops and says what to do instead. You can paste the box again at any time; it carries on from wherever it got to.

**Windows:**

```powershell
& {
  $ErrorActionPreference = 'Stop'
  if (-not (Test-Path 'C:\eps-bundle\run_pipeline.py')) {
    $dl  = Join-Path $HOME 'Downloads'
    $zip = Get-ChildItem $dl -Filter 'eps-bundle*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $dir = Get-ChildItem $dl -Directory -Filter 'eps-bundle*' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($zip) {
      Write-Host "Unpacking $($zip.Name) ..."
      Expand-Archive -Path $zip.FullName -DestinationPath 'C:\' -Force
    } elseif ($dir -and (Test-Path (Join-Path $dir.FullName 'run_pipeline.py'))) {
      Copy-Item $dir.FullName 'C:\eps-bundle' -Recurse
    } elseif ($dir -and (Test-Path (Join-Path $dir.FullName 'eps-bundle\run_pipeline.py'))) {
      Copy-Item (Join-Path $dir.FullName 'eps-bundle') 'C:\eps-bundle' -Recurse
    } else {
      throw 'eps-bundle.zip is not in your Downloads folder. Download it from the shared Google Drive folder (Step 3), then paste this box again.'
    }
  }
  Set-Location 'C:\eps-bundle'
  if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -c "import sys; sys.exit(sys.version_info < (3, 11))"
    if ($LASTEXITCODE) { throw 'Python 3.11 or newer is needed. Install it (Step 1), open a new PowerShell window, and paste this box again.' }
    py -m venv .venv
    if ($LASTEXITCODE) { throw 'Could not create the Python environment. Check Python is installed (Step 1), open a new PowerShell window, and paste this box again.' }
  }
  .\.venv\Scripts\python -m pip install -r requirements.txt
  if ($LASTEXITCODE) { throw 'Installing the Python packages failed. Check your internet connection and paste this box again.' }
  Write-Host 'SETUP COMPLETE' -ForegroundColor Green
}
```

**Mac:**

```bash
(
  set -e
  if [ ! -f ~/eps-bundle/run_pipeline.py ]; then
    bundle_zip=$(find ~/Downloads -maxdepth 1 -name 'eps-bundle*.zip' | head -1)
    if [ -n "$bundle_zip" ]; then
      echo "Unpacking $bundle_zip ..."
      unzip -q "$bundle_zip" -d ~
    elif [ -f ~/Downloads/eps-bundle/run_pipeline.py ]; then
      cp -R ~/Downloads/eps-bundle ~/eps-bundle
    elif [ -f ~/Downloads/eps-bundle/eps-bundle/run_pipeline.py ]; then
      cp -R ~/Downloads/eps-bundle/eps-bundle ~/eps-bundle
    else
      echo "eps-bundle.zip is not in your Downloads folder. Download it from the shared Google Drive folder (Step 3), then paste this box again."
      exit 1
    fi
  fi
  cd ~/eps-bundle
  if [ ! -x .venv/bin/python ]; then
    if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
      echo "Python 3.11 or newer is needed. Install it from python.org (Step 1), open a new Terminal window, and paste this box again."
      exit 1
    fi
    python3 -m venv .venv
  fi
  .venv/bin/python -m pip install -r requirements.txt
  printf '\033[32mSETUP COMPLETE\033[0m\n'
)
```

A notice that a new version of pip is available may appear just before or after `SETUP COMPLETE`. Ignore it.

### Step 5 — Choose a model and a reasoning effort

Make both choices before the first run, and keep them for the whole run. The program refuses to continue a run with different settings, so the results are never a mixture.

To see which models and effort levels your plan offers, paste:

```
codex
```

Then type `/model` and press Enter. Note the **model name exactly as it is listed**, and the **effort level** you want: one of `low`, `medium`, `high`, `xhigh`, `max` or `ultra`. Higher effort thinks longer per document and uses more of your plan. Leave Codex by typing `/quit`.

OpenAI describes the models at [learn.chatgpt.com/docs/models](https://learn.chatgpt.com/docs/models).

### Step 6 — Run it

Copy the box for your system into a text editor (Notepad, TextEdit) first. Replace `MODEL_NAME` and `EFFORT_LEVEL` with your two choices from Step 5, then paste the result into the terminal.

**Windows:**

```powershell
cd C:\eps-bundle
.\.venv\Scripts\python run_pipeline.py --model MODEL_NAME --effort EFFORT_LEVEL
```

**Mac:**

```bash
cd ~/eps-bundle
.venv/bin/python run_pipeline.py --model MODEL_NAME --effort EFFORT_LEVEL
```

It checks the folder is intact and that you are signed in (about a minute), then works through the documents, printing its progress. July 2026 documents go first. About 2,100 documents are sent to the model; the rest contain nothing it could select and are skipped without a call. Once every document is done, it builds the UK and US datasets, which also makes model calls. It asks you nothing while it runs, and can take many hours.

**Keep your filled-in command.** You need it again if the run stops.

### Step 7 — If it stops

Paste **the same filled-in command** from Step 6 again. Finished documents are skipped and failed ones retried, however it stopped: a usage limit, closing the window, Ctrl+C, the computer sleeping, or a lost connection. In a terminal that is still open, pressing the Up arrow and then Enter does the same.

If it says you are signed out, paste `codex login` first.

### Step 8 — When it finishes

It prints `FINISHED`. Paste this to put the results in one zip file on your Desktop:

**Windows:**

```powershell
& {
  $out = Join-Path ([Environment]::GetFolderPath('Desktop')) 'eps-output.zip'
  Compress-Archive -Path 'C:\eps-bundle\output' -DestinationPath $out -Force -ErrorAction Stop
  Write-Host "Saved: $out" -ForegroundColor Green
}
```

**Mac:**

```bash
cd ~/eps-bundle && rm -f ~/Desktop/eps-output.zip && zip -qr ~/Desktop/eps-output.zip output && echo "Saved: ~/Desktop/eps-output.zip"
```

Upload **`eps-output.zip`** from your Desktop to the **`returns`** folder in the shared Google Drive folder.

If it reports failures, run the Step 6 command once more to retry them, then send the output whatever the result. The failures are recorded and are useful to us too.
