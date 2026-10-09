# Running the policy-statement extraction on your computer

## 1. What this is

This folder holds about 6,600 UK and US government documents from January to July 2026, and the program that reads them. It asks an OpenAI model, through your own Codex sign-in, to pick out the passages where a minister or secretary states a policy choice. You then send the results back, and we build the dataset from them.

## 2. What it touches, and what it does not

- It reads only this folder.
- It writes only to the `output` folder inside this folder.
- It calls Codex with shell commands, web search and connectors switched off, in a read-only sandbox, so the model can only read the text it is given and answer.
- It makes no other network connections.
- It uses your ChatGPT plan's Codex usage. If you reach a usage limit, the run stops cleanly. Run it again later and it carries on where it left off.

## 3. Install Python and Codex (once)

1. **Python 3.11 or newer** (it was tested with Python 3.14). Download it from [python.org/downloads](https://www.python.org/downloads/). On Windows, tick **"Add python.exe to PATH"** on the installer's first screen.
2. **The Codex CLI.** Follow OpenAI's install instructions for your system: [learn.chatgpt.com/docs/codex/cli](https://learn.chatgpt.com/docs/codex/cli).
3. Open a **new** terminal (Windows: PowerShell; Mac: Terminal) and sign in to Codex with your ChatGPT account:

   ```
   codex login
   ```

## 4. Unzip to a short path

Unzip the bundle so that its folder sits at:

- Windows: `C:\eps-bundle`
- Mac: `~/eps-bundle` (your home folder)

Check you have the right level: the folder should contain `README.md` and `run_extract.py` directly, not another folder of the same name.

## 5. Set up the environment (once)

These commands create a private Python environment inside the folder. Nothing is installed elsewhere on your computer.

**Windows (PowerShell):**

```
cd C:\eps-bundle
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**Mac (Terminal):**

```
cd ~/eps-bundle
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

This step downloads a few Python packages. It is the only step besides Codex that uses the internet.

## 6. Choose a model and a reasoning effort (before you run anything)

You make two choices, once, before the run starts. Use the same two for the whole run: the program refuses to continue a run with different settings, so the results are never a mixture.

- **Model.** OpenAI lists the Codex models at [learn.chatgpt.com/docs/models](https://learn.chatgpt.com/docs/models). Which ones you can use depends on your plan. To see yours, type `codex` in a terminal, then `/model`, note the model name exactly as it is listed, and leave with `/quit`.
- **Reasoning effort.** One of `low`, `medium`, `high`, `xhigh`, `max` or `ultra`. Higher effort thinks longer per document and uses more of your plan. Not every model offers every level; `/model` shows which levels yours offers.

Write both down. Below they appear as `MODEL` and `EFFORT`.

## 7. Run it

In the same terminal, from the bundle folder:

**Windows:**

```
.venv\Scripts\python run_extract.py --model MODEL --effort EFFORT
```

**Mac:**

```
.venv/bin/python run_extract.py --model MODEL --effort EFFORT
```

It checks the folder is intact and that you are signed in to Codex, then works through the documents, printing its progress. July 2026 documents go first. It does not ask you anything while it runs.

About 2,100 of the documents are sent to the model. The rest contain no passage it could select, and are skipped without a call.

## 8. If it stops

Run the **same command** again, with the same model and effort. Documents already finished are skipped, and any that failed are retried. This holds however it stopped: a usage limit, closing the window, Ctrl+C, the computer going to sleep, or a lost connection.

If it says you are signed out, run `codex login` first.

## 9. When it finishes

It prints `FINISHED`. Then:

1. Zip the `output` folder (Windows: right-click it → **Compress to ZIP file**; Mac: right-click → **Compress "output"**).
2. Upload the zip to the `returns` folder in the shared Google Drive folder this bundle came from.

If it finishes with some documents failed, it says so. Run the same command once more to retry them, then send the output whatever the result. The failures are recorded and are useful to us too.
