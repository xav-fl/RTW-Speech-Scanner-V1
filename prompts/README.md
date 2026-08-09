# Prompt archive

Snapshots of the extraction prompt for versions that left this machine — a trial
dataset sent to a supervisor, or a release.

**You do not need to add anything here while you are still tuning.** Every output
row already records `prompt_sha`, a hash of the prompt text, so which wording
produced which rows is tracked automatically.

Archive a version when someone else sees its output:

1. Set `PROMPT_VERSION` in `src/eps/extract.py` to a meaningful name.
2. Copy `EXTRACT_SYSTEM` and `JEL_SYSTEM` into `prompts/<PROMPT_VERSION>.md`.
3. Record the `prompt_sha` at the top, and one line on what changed and why.
4. Commit.

Section 9 of the field guide asks for a record of what changed between prompt
versions. This folder plus the git history is that record.
