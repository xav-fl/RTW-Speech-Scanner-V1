# This branch is the Codex-native variant, not the main pipeline

**Branch `codex-native` and tags `codex-bundle-v1` to `codex-bundle-v4` hold a variant of the eps pipeline built to run on someone else's computer through their own Codex CLI.** They are not the original or main version of extract and build.

## What is different here

- **Who answers the model calls.** Every call (passage selection, JEL classification, the context stage and intention tagging) goes to an OpenAI model, chosen by the person running it, through `codex exec` under their ChatGPT sign-in. The main pipeline uses Anthropic models through the API.
- **How it is run.** A self-contained bundle (`scanner-code/eps-pipeline/eps/bundle/`, packaged by `tools/build_bundle.py`) is unpacked and launched by a Codex chat, or by hand, and runs extract and build in one command (`run_pipeline.py`).
- **What it adds to the package.** `src/eps/providers.py:CodexCLIProvider` and `src/eps/cli_schemas.py` (output schemas for the five prompts). The prompts, validation and assembly are the main pipeline's own, unchanged.

## What this means for the data

A dataset built with this variant is **not directly comparable** with one built on the main route: a different model made every judgement, including context and intention. Each row records the provider and model that produced it. See `DECISIONS.md`, H-102 to H-114, and H-109 in particular.

## Where the main pipeline is

The reference route is `eps extract`, `eps context` and `eps build` on Anthropic models, described in `scanner-code/eps-pipeline/eps/RUNNING.md`. This branch also carries a few changes that belong to the main pipeline too, notably the blockquote-marker fix (H-102). Those should reach the main line by their own review, not by merging this branch.
