# Intention codebook

Human-readable copy of Sections 4 and 5 of `INTENTION_TAG_BRIEF_v1.md`, as
amended by the project lead for prompt versions `I2` and `I3` (see "I2 amendments" and "I3 amendments"
below). Used by the intention tagger (`scanner-code/eps-pipeline/eps/src/eps/intention.py`).
The same rules are in the tagger prompt, `INTENTION_PROMPT`. Do not edit one
without the other; a change to either is a new prompt version.


## I2 amendments (2026-09-25)

Made by the project lead after reading the I1 trial on the v7 quotes. The
sections below already include them.

1. Question 1 fires only on words in the QUOTE, and only for a request still
   open. A request whose results are already in counts as "Reports existing
   action". Enforced in code: the label cue must come from the QUOTE, not the
   CONTEXT (failure reason `label_cue_not_in_quote`; `unclear` is exempt).
2. "States view without action" applies only if the quote mentions no action
   at all, including actions referred to indirectly ("these changes", "this
   investment", "cutting X"). Otherwise continue down the questions.
3. Calls on others are classified by who is asked to act, not by who is
   mentioned.
4. New subcategory `states_view_without_action` / `causal_belief` ("States
   view without action: causal belief"). Release values go from 16 to 17.
5. Purpose clauses ("to…", "so that…") set `claims_causal_effect` only when
   they name a specific outcome. "to better support compliance" moves from the
   Yes to the No examples.

## I3 amendments (2026-09-25)

Made after the I2 subset trial, where the I2 wording of question 3 was not
followed: five quotes naming an action (a ban, "these changes", a cut, "these
missions", tax cuts) stayed in "States view without action".

1. Question 3 opens with an explicit test: does the quote name or refer to any
   action? If so, skip it. There is a carve-out for an action mentioned only as
   an abstract option inside a judgment.
2. Question 6: the present continuous ("we are investing") means an action is
   already under way (`ongoing_implementation`), unless the document itself
   announces it.

---

## 4. The labels (fixed)

Each quote receives one **broad** code and, where the table lists subcategories, one **sub** code. The stored codes are snake_case. The release shows the display text.

| Broad code | Broad display | Sub code | Sub display |
|---|---|---|---|
| `commits_to_action` | Commits to action | `announces_decision` | announces decision |
| | | `pledges_future_action` | pledges future action |
| | | `makes_conditional_commitment` | makes conditional commitment |
| `reports_existing_action` | Reports existing action | `completed_action` | completed action |
| | | `outcome` | outcome |
| | | `ongoing_implementation` | ongoing implementation |
| `considers_open_option` | Considers open option | `preferred_option` | preferred option |
| | | `no_stated_preference` | no stated preference |
| `rules_out_option` | Rules out option | *(none)* | — |
| `calls_on_others` | Calls on others | `evidence` | evidence |
| | | `other_states` | other states |
| | | `private_actors` | private actors |
| `states_view_without_action` | States view without action | `describes_problem` | describes problem |
| | | `value_judgement` | value judgement |
| | | `causal_belief` | causal belief |
| `unclear` | Unclear | *(none)* | — |

**Release value of the `intention` column:**

- `"<Broad display>: <sub display>"` when a sub code exists, e.g. `Commits to action: pledges future action`
- `"<Broad display>"` alone for `rules_out_option` and `unclear`, i.e. `Rules out option`, `Unclear`
- `Not tagged` when tagging failed (Section 6.3). The failure reason goes to the log, not the release.

That gives exactly 17 permitted release values: 14 broad–sub pairs, `Rules out option`, `Unclear` and `Not tagged`, plus nothing else. (I1 had 16; `causal_belief` was added in I2.)

**Internal-only fields** (log, not release):

- `evidence_type`: one of `public_consultation`, `expert_referral`, `research_or_data`. Required when sub = `evidence`, and must be null otherwise.
- `secondary_broad` / `secondary_sub`: another intention the passage also expresses but which the question order overrode (nullable; same valid pairs as above, excluding `unclear`).

**Flags** (release, Yes/No):

- `has_quantified_target`
- `claims_causal_effect`

---

## 5. Coding rules (fixed)

Copy this section, together with Section 4, into `INTENTION_CODEBOOK.md`. The prompt in Section 7 contains the same rules. Add a test that fails if any broad or sub code in the data model is missing from the prompt text.

### 5.1 Question order

Label the QUOTE. Use the CONTEXT only to decide tense, actor and status. Ask the questions in order and stop at the first "yes".

1. **Do the words of the QUOTE itself ask others to supply evidence, views, data or advice, in a request that is still open?** → `calls_on_others` / `evidence`. This includes public or stakeholder consultations, commitments to seek views, referrals to advisory or regulatory bodies (e.g. Ofcom, the JCVI, the Financial Policy Committee), and requests for research, data or evaluation. Set `evidence_type`. This question takes precedence over all others; record any other intention in `secondary_*`. A consultation or referral mentioned only in the CONTEXT does not count. A request whose results are already in is not open: continue down the order, usually to `reports_existing_action`.
2. **Does the speaker ask someone other than their own government to act?** → `calls_on_others` / `other_states` (foreign governments, international bodies, "the international community") or `private_actors` (firms, platforms, households, the public). Classify by who is asked to act, not by who is mentioned. *Exception:* if the passage also states the speaker's own government's response should the others not comply, use `commits_to_action` / `makes_conditional_commitment` instead.
3. **Does the QUOTE name or refer to any action, policy, change, programme, investment, mission, ban, cut, scheme or decision, by anyone?** This includes an action as the subject of a sentence, in a gerund ("Banning X", "Cutting X") or by a pointer ("these changes", "this investment", "these missions"). If yes, skip this question and continue to question 4: a sentence that evaluates or explains an action is still about that action (e.g. "Banning X is totemic because…", "These vital changes will mean…", "Cutting X means faster Y…"). Carve-out: a course of action mentioned only in the abstract, as a general option inside a judgment that nobody is doing, has done or plans to do, does not count ("it's better to spend taxpayer's cash building new homes than subsidising buy-to-let landlords" stays a value judgement). If no → `states_view_without_action` / `describes_problem` (describes a problem or state of affairs), `value_judgement` (a value, fairness or trade-off judgment) or `causal_belief` (a claim that one thing causes or leads to another, with no action attached).
4. **Does the speaker rule an option out, or decline to adopt it?** → `rules_out_option`.
5. **Is the option still undecided?** → `considers_open_option` / `preferred_option` (a preference is stated: "minded to", "strongly minded to", "our intention, subject to consultation", "we have proposed") or `no_stated_preference` ("considering", "exploring", "looking at", "reviewing whether").
6. **Was the action taken, or already under way, before this document?** → `reports_existing_action` / `completed_action` (a completed action), `outcome` (a claimed result or effect, e.g. figures achieved) or `ongoing_implementation` (implementation of an existing policy is in progress: "we are rolling out", "is implementing"). The present continuous ("we are investing", "we are rolling out", "we are deploying") describes an action already under way → `ongoing_implementation`, unless the document itself announces it ("today", "I can announce") → `announces_decision`.
7. **Otherwise** → `commits_to_action` / `announces_decision` (the decision is taken or made public in this document: "today", "I can announce", "I can confirm", "this week", or a press release's own announcement such as "Today's action" or "This investment") or `pledges_future_action` (a promise of future action with no decision made in this document: "we will", "I will", "legislation will be brought forward").

If the quote and context together do not settle the label, use `unclear`. Do not guess.

### 5.2 Boundary rules

- **Consultation on details of a decided policy:** question 1 applies → `calls_on_others` / `evidence`. Record the decided policy as `secondary_*` if the quote states it.
- **The speaker's own organisation reviewing something without asking anyone else** (e.g. "take a deeper dive into the services provided") is *not* an evidence request. Skip question 1 and continue down the order.
- **Ambiguous "we":** if the actor is not identifiably the speaker's own government (e.g. "we" meaning the international community), treat it as others acting → question 2, `other_states`.
- **Press-release effect statements** ("This investment will…", "The new digital ID will…"): the action is announced in the document → `commits_to_action` / `announces_decision`. The effect claim sets `claims_causal_effect` = Yes.
- **Fragments with no tense** (lists such as "Expanding free school meals, rolling out…"): decide from the context. If the context does not settle it → `unclear`.
- **Mixed passages:** apply the question order; the first "yes" wins. Record the most important other intention in `secondary_*`.

### 5.3 Flag rules

**`has_quantified_target` = Yes** if the quote commits to a measurable outcome with a number or a deadline.
- Yes: "cut the disadvantage gap in half"; "our goal of 1 million apprentices"; "a target of 10,000 homes a year by the end of this Parliament"; "clean power by 2030".
- No: spending amounts alone ("£200 million"); figures already achieved ("net migration fall by nearly 70%"); deadlines for process steps rather than outcomes ("within months", "from September").

**`claims_causal_effect` = Yes** if the quote links an action, policy or condition to a specific outcome, whether as a result, an intended effect or an explanation.
- Yes: "because of the changes that I have made"; "to bring borrowing costs down"; "capping ground rent – helping millions of leaseholders by saving them money"; "so that parents can get the support they need".
- No: the quote names actions without effects, or the only outcome is a vague aim ("securing a safer future for the next generation", "to get the job done", "to better support compliance", "to strengthen coordination and preparedness"). Purpose clauses ("to…", "so that…") count only when they name a specific outcome.

Each flag set to Yes needs a cue: the exact words that justify it.

### 5.4 Examples from the v7 prototype

| Label | Example quote (abridged where marked …) | Flags |
|---|---|---|
| Commits to action: announces decision | "Today, I can announce that I am suspending certain visa routes for a further 4 countries…" | — |
| Commits to action: announces decision | "So I can confirm today, that we will open two SFI application windows this year." | — |
| Commits to action: pledges future action | "we will ban social media companies providing their services to under 16s" | — |
| Commits to action: pledges future action | "I will cut the disadvantage gap in half." | Target: Yes |
| Commits to action: makes conditional commitment | "I expect all platforms to abide by Ofcom ’s new Violence Against Women and Girls (VAWG) guidance and if they do not, I am prepared to go further." | — |
| Reports existing action: completed action | "we created an Independent Prevent Commissioner." | — |
| Reports existing action: completed action | "I repaired the public finances, whilst setting out a path of fiscal consolidation to bring borrowing costs down" | Causal: Yes |
| Reports existing action: outcome | "our largest pension funds invested an additional £10bn into private markets because of the changes that I have made" | Causal: Yes |
| Reports existing action: ongoing implementation | "We’re rolling out Best Start Family Hubs so that parents can get the support they need." | Causal: Yes |
| Considers open option: preferred option | "Our intention, subject to consultation, is that the point at which settlement is possible will now vary." | — |
| Considers open option: preferred option | "I am also strongly minded to bring in default overnight curfews and breaks in infinite scrolling for 16- and 17-year-olds." | — |
| Considers open option: no stated preference | "So, we’re considering ways to address this such as an agreement value cap." | — |
| Rules out option | "As for a flat-rate scheme that would cost up to £10.3 billion and would simply not be right or fair, given it would be paid to the vast majority who were aware of the changes." | — |
| Calls on others: evidence (expert_referral; secondary: pledges future action) | "So we will introduce more highly effective age assurance measures to better support compliance, and I have asked Ofcom to share proposals on these within months." | — |
| Calls on others: evidence (public_consultation) | "this government is consulting on whether to remove children’s access to social media entirely." | — |
| Calls on others: other states | "arms restrictions need to be enforced and extended" | — |
| Calls on others: other states (ambiguous "we") | "We need to redouble our efforts to ensure countries can mobilise their own finance, spend well, borrow responsibly and manage shocks effectively, to build sustainable economies." | Causal: Yes |
| Calls on others: private actors | "American households must prioritize whole, nutrient-dense foods…and dramatically reduce highly processed foods." | — |
| States view without action: describes problem | A passage consisting only of a sentence such as "Right now, a quarter of the money goes to just 4% of farms." | — |
| States view without action: value judgement | "it’s better to spend taxpayer’s cash building new homes than subsidising buy-to-let landlords" | — |
| Unclear | "Expanding free school meals, rolling out new free breakfast clubs, ending the two-child limit, fighting the disgrace of child poverty." (when the context does not settle whether these are promises or achievements) | — |
