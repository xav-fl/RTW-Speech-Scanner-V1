# Instructions for Codex: set up and run the eps pipeline

You are helping a researcher run a research data pipeline on their own computer. The pipeline is already written and tested. Your job is only to set it up, start it, and help when it stops. Follow the steps below in order, and keep your messages to the user short and plain: they are not programmers.

## Rules

1. **Do not change the bundle.** Do not edit, move, rename, delete or "fix" any file in the bundle folder. The only things that may be created inside it are `.venv` (step 3) and `output` (which the pipeline writes itself).
2. **Run `run_pipeline.py` only as written below:** `--check` in step 4, and the launch command in step 6. Never add other options (no `--provider`, no `--limit`), except `--workers` as described under "When the user asks to restart the run". Never run the real run inside your own shell: it makes thousands of Codex calls over many hours, and needs the network and the user's Codex sign-in, which your sandbox blocks. It must run in its own terminal window (step 6).
3. **Never delete `output`.** It holds the finished work, and it is what the user sends back.
4. **When something fails,** tell the user in one or two plain sentences what the message says and what it suggests, and follow that suggestion. Do not improvise workarounds or change code.
5. **When a step needs more than your sandbox allows** (writing outside the current folder, downloading packages, opening a new window), ask for approval. Say what the step does in plain words.
6. **Do not read, summarise or open the documents in `harvests`.** It is not needed and wastes the user's usage.

Below, `BUNDLE` is `C:\eps-bundle` on Windows and `~/eps-bundle` on a Mac. Use PowerShell commands on Windows and shell commands on a Mac.

## Step 1: Unpack the bundle

If `BUNDLE` already contains `run_pipeline.py`, skip this step.

Otherwise, find the bundle in this order:

1. the `eps-bundle.zip` the user attached to this chat, if you were given a path to it;
2. the newest `eps-bundle*.zip` in the user's Downloads folder;
3. a folder in Downloads called `eps-bundle` that contains `run_pipeline.py` (or contains another `eps-bundle` folder that does).

Unpack or copy it so that `BUNDLE` directly contains `run_pipeline.py`:

- Windows, from a zip: `Expand-Archive -Path "<zip path>" -DestinationPath "C:\" -Force`
- Mac, from a zip: `unzip -q "<zip path>" -d ~`
- From a folder: copy that folder to `BUNDLE`.

Unpacking on Windows takes a minute or two. If you cannot find the bundle, ask the user to download `eps-bundle.zip` from the shared Google Drive folder into Downloads, then continue.

## Step 2: Check Python

The pipeline needs Python 3.11 or newer.

- Windows: `py -c "import sys; print(sys.version)"`
- Mac: `python3 -c "import sys; print(sys.version)"`

If Python is missing or older than 3.11:

- Windows: ask the user for approval, then run `winget install -e --id Python.Python.3.14 --source winget`. If it asks to accept terms, the user may need to type `Y`. Afterwards `py` may only be found in a new terminal; if so, ask the user to restart Codex and say "continue the eps setup".
- Mac: ask the user to install Python from https://www.python.org/downloads/ (the big yellow button, default options), then tell you when it is done.

## Step 3: Create the environment

This downloads a few Python packages, so it needs network access: ask for approval.

Windows:

```powershell
cd C:\eps-bundle
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Mac:

```bash
cd ~/eps-bundle
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Skip creating `.venv` if it already exists, but still run the `pip install` line. It ends with `Successfully installed …` or `Requirement already satisfied`.

## Step 4: Check the set-up

Windows: `cd C:\eps-bundle; .\.venv\Scripts\python run_pipeline.py --check`
Mac: `cd ~/eps-bundle && .venv/bin/python run_pipeline.py --check`

It takes about a minute and must end with `SETUP OK`. It starts nothing and writes no settings.

- If it says Codex is not signed in, run it again with approval to run outside your sandbox. If it still says so, ask the user to run `codex login` in a terminal, then check again.
- If it says files are missing or changed, delete nothing yourself. Ask the user whether `BUNDLE` can be deleted and unpacked again from the zip, then repeat from step 1.

## Step 5: Ask the user for the model and the reasoning effort

Do not choose these yourself. Tell the user, in about these words:

> The run makes several thousand separate Codex calls: about 2,100 documents, then the work of building the dataset. It uses your Codex plan, stops cleanly if it reaches a usage limit, and carries on later. Please choose:
>
> 1. **The model.** You can see the ones your plan offers in Codex's model picker, or by typing `/model`.
> 2. **The reasoning effort:** `low`, `medium`, `high`, `xhigh`, `max` or `ultra`. Higher effort takes longer and uses more of your plan for each call.

Wait for their answer. Use the model name in the exact form the Codex CLI's `-m` option accepts. If you are unsure of the exact name, ask the user to check it in the `/model` list.

## Step 6: Start the run in its own window

This needs approval: it opens a new terminal window that runs on its own, outside your sandbox. Replace `MODEL` and `EFFORT` with the user's choices.

Windows:

```powershell
Start-Process powershell -WorkingDirectory 'C:\eps-bundle' -ArgumentList '-NoExit', '-Command', '.\.venv\Scripts\python run_pipeline.py --model MODEL --effort EFFORT'
```

Mac (macOS may ask once whether Codex may control Terminal; the user should allow it):

```bash
osascript -e 'tell application "Terminal" to do script "cd ~/eps-bundle && .venv/bin/python run_pipeline.py --model MODEL --effort EFFORT"' -e 'tell application "Terminal" to activate'
```

About two minutes later, read the last 20 lines of `BUNDLE/output/logs/run.log`:

- `run started` followed by progress lines means it is working. Go to step 7.
- `STOPPED: the last 5 documents all failed` usually means the model or effort is not available on their plan. Show the user the error, ask for another choice, and start again with step 6. Settings only lock once a document has succeeded, so changing them now is fine.
- Any other `STOPPED` message: tell the user what it says and follow its advice.

## Step 7: Tell the user what happens next

Say, in about these words:

> It's running in its own window, which shows progress. It will take many hours, possibly more than a day. Keep the computer on and plugged in, and stop it from sleeping if you can. You can close this chat; closing the run window stops the run, but nothing is lost.
>
> If it stops (a usage limit, the computer sleeping, a closed window), open Codex and say **"restart the eps run"**. Or press the Up arrow and then Enter in the run window.
>
> When the window says **FINISHED**, come back and say **"the eps run has finished"**.

## When the user asks to restart the run

1. Read the last 20 lines of `BUNDLE/output/logs/run.log` and tell the user in one sentence why it stopped.
2. Read `BUNDLE/output/run_settings.json` for the model and effort used so far. Restart with exactly those values, using the step 6 command. A run with different settings is refused once documents are done, by design, so the results are never mixed.
3. The run makes 4 Codex calls at a time by default. If it keeps stopping at a usage limit soon after each restart, add `--workers 2` (or `--workers 1`) to the end of the command. This makes fewer calls at once and does not change the results.

## When the run has finished

1. Read the end of `BUNDLE/output/logs/run.log`.
   - `FINISHED:` means every document is extracted and both datasets are built.
   - `FINISHED EXTRACTING with … failed` or `FINISHED with some failed model calls` means some calls failed. Restart once (step 6, same settings). Whatever the result, continue to step 2.
2. Zip the output folder onto the Desktop:
   - Windows: `Compress-Archive -Path 'C:\eps-bundle\output' -DestinationPath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'eps-output.zip') -Force`
   - Mac: `cd ~/eps-bundle && rm -f ~/Desktop/eps-output.zip && zip -qr ~/Desktop/eps-output.zip output`
3. Tell the user: "Please upload eps-output.zip from your Desktop to the returns folder in the shared Google Drive folder." That is the last step.
