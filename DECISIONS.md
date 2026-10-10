# eps Pipeline — Decisions

Append-only. New entries go at the end; existing entries are never edited in
place. Entry IDs continue the sequence in `DECISIONS_REPORT.md`, which runs to
H-33 for the harvest section, so US collection starts at H-34.

`DECISIONS_REPORT.md` remains the report *about* the decisions taken up to the
UK harvest. This file is where decisions taken from the US collection onwards
are recorded as they are made.

---

## 1. Harvest — US collection

### H-34 — The US collector records speaker evidence and filters on none of it

- **Location:** `[harvest_us.py:speaker_evidence()]`,
  `[harvest_us.py:SPEAKER_EVIDENCE]`, `[harvest_us.py:LOG_COLUMNS]`
- **Decision:** The UK log's `speaker_match` column is replaced, in the US code
  only, by `speaker_evidence`, taking one of `attributed_quote`,
  `name_in_body`, `name_in_title`, `other_speaker`, `none`. Every document
  found is written to the screening log with its evidence value. **No row is
  dropped on this basis, and no length rule is applied either** — `word_count`
  is recorded so any threshold can be applied downstream and documented.
- **Rationale:** The UK harvester decides eligibility from GOV.UK's
  `links.speaker` metadata field (H-12: only `linked` reaches the queue). No US
  agency publishes an equivalent. Attribution on a US page has to be inferred
  from quotation marks and speech verbs, which is weaker evidence than a
  metadata link, and applying an eligibility rule to it at collection time
  would bake a guess into a corpus that would then have to be re-harvested to
  revise. Recording the evidence keeps the decision reversible.
- **Status:** Pending PI decision — *does `name_in_body` count as eligible?*
  The same question is already open on the UK side for 106 documents. The US
  collector is built so that either answer can be applied downstream without
  re-collecting anything.
- **Context:** The ladder is evaluated strongest-first:
  `attributed_quote > name_in_body > name_in_title > other_speaker > none`.
  The brief's table defines `other_speaker` as "quotes exist, all attributed to
  someone else" and `name_in_body` as "named in the body, no attributed quote";
  both can hold at once, so an order had to be chosen. `other_speaker` sits
  below the name values because a document that names the officeholder carries
  more evidence than one that does not; it therefore means "quotes were found,
  none of them are theirs, and they are not named anywhere". The detected
  speakers themselves are written to `linked_speakers` — the UK column, reused
  with its meaning intact — so nothing is lost by the ordering.
  Name comparison reuses the UK rule (H-11, I-10): every distinctive token must
  appear, because surname-only matching was B-01.

### H-35 — Every adapter reports how it obtained the publication date

- **Location:** `[sources/base.py:DATE_SOURCES]`,
  `[sources/base.py:DocumentRef.date_source]`, `[harvest_us.py:LOG_COLUMNS]`
- **Decision:** `date_source` is a column in the US screening log and a field on
  every record, taking one of `metadata` (a machine-readable field on the
  document itself), `listing` (a machine-readable field on the index that led
  to it), `body` (parsed out of the document's prose), or `inferred` (derived
  from a URL, a filename or a neighbour). A document with no date at all is
  kept, with an empty `date`, rather than dropped.
- **Rationale:** Several US agency sites carry no machine-readable date. A date
  read from prose is not the same evidence as a date read from a `<time>`
  element, and a corpus that cannot tell the two apart cannot report its own
  reliability. The UK side never needed this because the Content API always
  supplied `public_timestamp` (H-15), and its absence would have been an error
  rather than a normal case. Tracking inferred dates separately also keeps them
  excludable from any date-sensitive analysis without re-harvesting.
- **Status:** Settled
- **Context:** The two reference adapters both reach `metadata` on the document
  page and fall back to `listing`. `body` and `inferred` are declared but not
  yet exercised; they exist because agencies in the `awkward` tier are expected
  to need them. `eligible_on()` treats a document with no date as matching every
  officeholder recorded for that agency rather than guessing one, so an undated
  document produces a wider `expected_officeholder` rather than a fabricated
  narrow one.

### H-36 — Two columns are renamed to de-anglicise the schema, in US code only

- **Location:** `[harvest_us.py:LOG_COLUMNS]`
- **Decision:** The US screening log uses the UK log's 16 columns with
  `govuk_slug` renamed to `source_slug` and `govuk_document_type` renamed to
  `source_document_type`, plus `date_source` (H-35) and `speaker_evidence` in
  place of `speaker_match` (H-34). Seventeen columns in total. **Nothing is
  renamed in the UK harvester**, whose log, queue and documents are untouched.
- **Rationale:** The column names encoded the assumption that GOV.UK was the
  only source. Two corpora that differ only in the names of columns holding the
  same thing would force every downstream consumer to special-case a country.
  Renaming the UK side as well would have meant editing fenced files and
  invalidating a harvest that is already frozen and cited, so the rename is
  one-directional and the mapping is recorded here.
- **Status:** Settled
- **Context:** Mapping, for anything that has to read both:
  `govuk_slug` ↔ `source_slug`, `govuk_document_type` ↔ `source_document_type`,
  `speaker_match` ↔ `speaker_evidence` (different value sets — see H-34).
  In the US log `source_slug` holds the `institution_id` from
  `config/us_agencies.csv`, which is the same role GOV.UK's department slug
  played: it says which source bucket the row belongs to.
  The text-file header follows the same rule: `GOVUK_TYPE` becomes
  `SOURCE_TYPE` and `DATE_SOURCE` is added, so six header lines rather than the
  UK's five (H-16). The `---` rule that terminates the header is unchanged, so
  `strip_header()` works on both corpora.

### H-37 — The speaker moves onto the block, and a second detector fills it

- **Location:** `[sources/blocks.py:Block]`,
  `[sources/blocks.py:detect_us_quotes()]`,
  `[sources/blocks.py:detect_blockquotes()]`
- **Decision:** The UK converter's `[(kind, text)]` becomes
  `Block(kind, text, speaker, method)`, where `method` records which rule
  decided the speaker: `blockquote`, `speech_verb`, `structural`, or `none`. Two
  detectors fill it. `detect_blockquotes()` is the GOV.UK rule. `detect_us_quotes()`
  finds quoted spans inside ordinary paragraphs and attributes them from an
  adjacent speech verb. Explicit attribution always beats inherited attribution.
- **Rationale:** GOV.UK marks a ministerial quotation with `<blockquote>` and no
  quotation marks. US agencies do the opposite. Run the UK detector over a US
  press release and you get zero quote blocks, which would make every US
  document unattributable. Deciding attribution at collection time, and
  recording which rule fired, means the weaker rules can be audited or
  discounted later instead of being indistinguishable from the strong one.
- **Status:** Settled
- **Context:** Rendering is unchanged — `> ` in front of quote blocks, exactly
  as the UK rewriter emits (B-06, I-12) — so both corpora look identical to
  whatever reads them next. Two consequences worth knowing:
  (a) a US paragraph containing both a quotation and its attribution is split
  into two or three blocks, so the rendered paragraph structure differs from
  the page while the words do not;
  (b) `mark_attribution()` (I-09) requires a frame paragraph ending in `:`
  immediately above a `> ` block, and US attribution reads "said Secretary
  Smith." with a full stop, so the US corpus will not attribute under the
  current ingest rule. Nothing is synthesised to work around this: inventing a
  frame line would put words in the corpus that the agency never published.
  The fix belongs in ingest, using `Block.speaker`, and is flagged at the
  review gate rather than patched here.

### H-38 — A quoted span under four words is not promoted to a quote block

- **Location:** `[sources/blocks.py:MIN_QUOTE_WORDS]`,
  `[sources/blocks.py:_paragraph_blocks()]`
- **Decision:** A span between quotation marks shorter than four words stays
  inline in its surrounding text block, with its quotation marks restored,
  rather than becoming a `> ` quote block.
- **Rationale:** US agency prose uses quotation marks for scare quotes and for
  naming things — *what it called "administrative bloat"* — several times per
  document. Promoting those would put speakerless quote blocks into most
  documents and make the quote-block count useless as an audit signal.
- **Status:** Settled
- **Context:** This is a detection floor, not an eligibility filter, and it is
  the only length rule anywhere in the US collector (H-34 forbids the other
  kind). No words are dropped: a span below the floor is folded back into the
  text block with its marks. The threshold is a single named constant so the
  audit can be re-run at a different value.

### H-39 — Testimony is collected and labelled, never folded into statement

- **Location:** `[config/us_agencies.csv:label_map]`,
  `[sources/us/treasury.py:refine_type()]`,
  `[sources/base.py:SourceAdapter.normalise_type()]`
- **Decision:** Source labels naming testimony map to the normalised label
  `testimony`. Where an agency files testimony under a general heading instead
  of its own, an adapter-level title rule recovers it. An agency label with no
  `label_map` entry becomes `other` **and is counted and reported**, so an
  unmapped label cannot disappear silently.
- **Rationale:** Section 4 of the RA guide lists official testimony among the
  eligible source types and `testimony` is one of the eight normalised labels.
  Treasury and Labor both publish testimony on their own newsrooms. Folding it
  into `statement` or `speech` would destroy a document type the study is meant
  to be able to count.
- **Status:** Settled
- **Context:** The UK corpus contains no testimony at all, because select
  committee evidence sits on parliament.uk rather than GOV.UK. The two
  countries will therefore differ systematically on this document type. That
  asymmetry is a real finding about source availability, not a collection
  fault, and the descriptives should be able to show it. Going to GovInfo to
  find testimony an agency did not itself post is a later wave and is out of
  scope here. `refine_type()` is a documented per-agency hook, used once so
  far, for Treasury's "Statements & Remarks" heading, which covers delivered
  remarks and written statements under one label; the raw label is preserved in
  `source_document_type`, so any refinement is reversible without
  re-harvesting.

### H-40 — Agency slugs follow the brief; the officeholders CSV is aliased, not edited

- **Location:** `[harvest_us.py:OFFICEHOLDER_SLUG_ALIASES]`,
  `[config/us_agencies.csv]`
- **Decision:** `config/us_agencies.csv` uses the 24 `institution_id` values
  fixed by Section 3 of the brief, verbatim. Four of them differ from the slugs
  already in `officeholders_2026.csv` — `us-usda`/`us-agriculture`,
  `us-dod`/`us-defense`, `us-doj`/`us-justice`, `us-dot`/`us-transportation` —
  and the difference is bridged by an alias table in the collector.
- **Rationale:** The brief fixes the slugs and the officeholders file is fenced.
  Aliasing at the point of lookup satisfies both, and follows the precedent set
  by `OFFICEHOLDER_ALIASES` on the UK side (H-10), which exists for the same
  reason: a lookup alias is not a data edit.
- **Status:** Settled — but the divergence should be resolved in one direction
  before the remaining 22 adapters are written, since every one of them will
  have to agree with both files.
- **Context:** The officeholders file carries 28 United States rows covering all
  24 agencies, including two-holder sequences for DHS, DOJ, Labor and NRC, and
  a vacant row for USAID. The US officeholder table proper is out of scope here
  — it needs the acting-head rule settled first — so the collector reads that
  file read-only and never writes to it.

### H-41 — An office title in front of a surname counts as naming the officeholder

- **Location:** `[sources/blocks.py:name_appears()]`,
  `[sources/blocks.py:_OFFICE_TITLES]`
- **Decision:** A person is "named" in a title or body if **either** every
  distinctive token of their name appears (the UK rule, I-10) **or** their
  surname appears directly after an office word — `Secretary McMahon`,
  `Administrator Zeldin`. A bare surname on its own never matches.
- **Rationale:** US agencies write their principals as office-plus-surname and
  almost never give the forename. Under the all-tokens rule alone, a document
  titled "Secretary McMahon's Remarks to 1,000 High School Students" recorded
  `speaker_evidence = none`, which reads as "no trace of the officeholder" and
  is simply false. Requiring the office word in front is what stops this
  becoming B-01 again: that bug was caused by matching a bare token.
- **Status:** Settled
- **Context:** Found by inspecting the first complete run rather than by
  reasoning: 51 of 401 documents changed value, 45 of them from `other_speaker`
  to `name_in_body` where the release quotes a deputy but the body still says
  "Secretary McMahon". Every change was checked against the stored text before
  the rule was kept. The office list deliberately excludes honorifics and
  connectors, so "Dr Smith" and "of Smith" do not license a surname match.

### H-42 — Four collection faults found by running the collector, not by review

- **Location:** `[sources/us/treasury.py:_TITLE]`,
  `[sources/us/treasury.py:_is_section_landing()]`,
  `[sources/base.py:looks_like_testimony()]`,
  `[sources/blocks.py:name_appears()]`
- **Decision:** Recorded here because each was invisible until real pages were
  fetched, and each would have silently corrupted a column:
  1. Treasury's title came from the navigation mega-menu, not the page
     heading, because `field--name-title` matches both and the menu comes
     first. Every Treasury document was titled "About Treasury", which also
     disabled every title-based rule downstream of it.
  2. Treasury's press-release index lists its own section landing pages —
     Readouts, Statements & Remarks, Testimonies — as documents dated
     2026-01-13. The Testimonies one would have been the only `testimony` in
     the corpus for the window.
  3. Testimony was reaching the log as `statement` and `speech`. Five Treasury
     items titled "Statement from Secretary … Before the United States Senate
     Finance Committee" and one Education item titled "Secretary McMahon
     Testifies on …" were affected.
  4. The name rule reported `none` for documents that name the officeholder by
     office and surname (H-41).
- **Rationale:** None of these is visible in a code review, and three of the
  four produce plausible-looking output. This is the argument for the audit
  being a standing per-agency gate rather than a one-off: 22 more adapters will
  each have their own version of faults 1 and 2.
- **Status:** Settled
- **Context:** Fault 3's fix is deliberately narrow. "Before the …" alone is
  also Treasury's normal phrasing for an audience — before the Petroleum Club
  of Houston, before the EXIM Annual Conference, before the Financial Literacy
  and Education Commission — so a loose rule would have relabelled 13 speeches
  as testimony. A congressional body must be named. Replayed over all 401
  harvested titles the rule changed exactly the 6 intended rows and nothing
  else.

---

## 2. Ingest attribution

### H-43 — `officeholders_2026.csv` is authoritative for `institution_id`

- **Location:** `[config/us_agencies.csv]`, `[harvest_us.py:eligible_on()]`
- **Decision:** The four slugs invented for the foundations brief — `us-usda`,
  `us-dod`, `us-doj`, `us-dot` — are replaced by the ones already in
  `officeholders_2026.csv`: `us-agriculture`, `us-defense`, `us-justice`,
  `us-transportation`. The alias table introduced by H-40 is **deleted**. All
  24 config slugs and all 28 US officeholder rows now agree in both directions,
  and a test asserts it.
- **Rationale:** Ingest joins the block speaker against the expected
  officeholder on `institution_id`, so the join is now on the critical path
  rather than a reporting convenience. Two spellings bridged by a lookup table
  is one silent failure away from an agency that quietly resolves to no
  officeholder and therefore produces no observations. The reference file has
  28 rows and predates the config's 24; the reference file wins.
- **Status:** Settled — supersedes H-40.
- **Context:** Four agencies carry two officeholder rows covering a transition
  inside the window: DHS (Noem → Mullin, 2026-03-24), Justice (Bondi → Blanche,
  2026-04-02), Labor (Chavez-DeRemer → Sonderling, 2026-04-20) and NRC (Wright
  → Nieh, 2026-01-08). `eligible_on()` filters on the document date and returns
  every holder whose tenure covers it, rather than taking the first match —
  `end_date` inclusive, so both appear on the handover day, consistent with the
  UK harvest (H-14). `us-usaid` carries a vacant row recording the 2025
  dissolution; it correctly resolves to no officeholder, which is the expected
  state and not missing data.

### H-44 — The US text file carries no metadata header

- **Location:** `[harvest_us.py:write_document()]`
- **Decision:** A US `.txt` now contains the rendered blocks and nothing else.
  The six-line header specified by H-36 is removed. Every field it carried is
  in the sidecar and in the screening log.
- **Rationale:** Two reasons, either sufficient. The UK files ingest actually
  consumes — `documents_v2/`, written by the rewriter — carry no header, so a
  header made the US corpus the odd one out at the exact point the two are
  supposed to be indistinguishable. And the sidecar is indexed against
  `render()` output: a header puts paragraphs in the text with no block to pair
  them with, which would defeat the length check in I-13.
- **Status:** Settled — supersedes the header paragraph of H-36. The column
  renames recorded in H-36 stand.
- **Context:** Nothing is lost, and the metadata is now machine-readable rather
  than parsed back out of prose. `strip_header()` in the audit is retained so
  it can still read a corpus harvested before this change.

### H-45 — `speaker_is_document`, the sixth evidence value

- **Location:** `[harvest_us.py:SPEAKER_EVIDENCE]`,
  `[harvest_us.py:SPEAKER_IS_DOCUMENT_TYPES]`,
  `[harvest_us.py:speaker_evidence()]`
- **Decision:** A sixth value, `speaker_is_document`, sits at the top of the
  ladder and is assigned when the document type is one where the officeholder
  is the sole author. Applied to `speech` and `testimony`.
- **Rationale:** The five values from Section 8 of the foundations brief had no
  way to say "this document is entirely the speaker's own words". Eight
  speeches and one testimony recorded `none` — indistinguishable from a press
  release that never mentions the officeholder, and the exact opposite of the
  truth, since a speech is the strongest evidence available. Leaning on
  `normalised_document_type` downstream would have worked but puts the
  inference in every consumer instead of in the collector.
- **Status:** Settled — extends H-34, which otherwise stands unchanged.
- **Context:** Deliberately narrower than the UK's `SPEAKER_ONLY_TYPES`, which
  also contains `statement`, `op_ed` and `letter`. A US "statement" is
  frequently issued in the agency's name rather than the Secretary's, so
  including it would assert authorship the source does not. **The two corpora
  therefore disagree on `statement`**, and widening the US set is a PI
  decision. Two US documents are affected today.

### I-13 — Attribution has two paths, selected by the presence of a sidecar

- **Location:** `[ingest/normalise.py:mark_attribution()]`,
  `[ingest/normalise.py:_mark_from_blocks()]`,
  `[ingest/normalise.py:speaker_names_match()]`,
  `[ingest/harvest/local.py:load_block_sidecar()]`
- **Decision:** `mark_attribution()` takes an optional `blocks` argument. When
  it is `None` — every existing caller, and every UK document — the GOV.UK
  colon-frame rule (I-09) runs exactly as before. When a `<name>.blocks.json`
  sidecar sits beside the `.txt`, attribution is read from `Block.speaker`
  instead. A block is attributable when it is a quote, carries a speaker, and
  that speaker matches the expected officeholder by name comparison.
- **Rationale:** US agencies put the attribution after the quote and end it
  with a full stop, so the colon-frame rule finds nothing and the entire US
  corpus yields no observations. The collector already computed the speaker;
  this carries it through rather than re-deriving it from punctuation
  downstream, where the HTML is long gone.
- **Status:** Settled
- **Context:** Four properties worth stating, because each was a live choice:
  1. **Nothing is synthesised.** No frame line is invented. A block with no
     speaker is not attributable — the rule fails closed exactly as I-09 does.
  2. **The speaker never enters the `.txt`.** The text file is verbatim against
     the published page and anchor-phrase verification (E-08) matches against
     it; an annotation would be text the agency never published. The sidecar is
     a separate file, and the UK corpus gets none.
  3. **Length disagreement is a hard error**, not a warning. A sidecar off by
     one attributes every quote to the wrong person and nothing downstream
     would notice. The sidecar also carries `text_sha256` of the rendered body,
     so a sidecar that has drifted from its text is rejected before it can
     mis-attribute rather than after.
  4. **Name comparison, not all-tokens-present.** `frame_names_speaker()` asks
     whether every token of a name appears in a paragraph of prose, which is
     right for a frame line and wrong for comparing two names: "Secretary
     McMahon" and "Linda McMahon" share one token and are the same person.
     `speaker_names_match()` strips office titles, honorifics and possessives,
     then requires the surname to match with no conflicting forename.
  A third party is attributed to the third party, not to the agency head: the
  sidecar carries the union leader's name, and the block is attributable only
  when the expected officeholder is that union leader. Rows are never dropped;
  eligibility stays a downstream decision (H-34).
  The UK path was proved unmoved by re-ingesting all 868 queued UK documents
  before and after the change — see the review-gate report.

---

## 3. Harvest — the 22-agency survey

### H-46 — `transport` is a column, because reachability is not a site shape

- **Location:** `[config/us_agencies.csv:transport]`
- **Decision:** A twelfth column, `transport`, taking one of `http` (a plain
  request returns the listing), `browser` (the site serves the listing to a
  real browser but 403s every HTTP client tried) or `blocked` (no automated
  client reached it at all). Fifteen agencies are `http`, six are `browser`,
  three are `blocked`.
- **Rationale:** `tier` describes what a site's index *is* — a feed, a listing,
  something awkward. It cannot describe whether the collector can obtain that
  index, and the survey found the two are independent. USDA, DOL, HHS, NRC and
  SSA have among the cleanest listings of the 24 and are unreachable by
  `Fetcher`; NSF and DOE are reachable and awkward. Folding reachability into
  `tier` would have marked five well-structured sites `awkward` and lost the
  distinction that matters for planning: an `awkward` site needs adapter
  thought, a `browser` site needs a different HTTP client.
- **Status:** Settled
- **Context:** The block is not a robots policy and was not treated as one.
  For the six `browser` agencies `robots.txt` itself returns 403, so there is
  no published crawl rule to read; where robots *is* readable no agency
  disallows its newsroom path, and the two that set a crawl-delay (Justice 10s,
  Interior 1s) are recorded in their notes so the collector can honour them.
  The block is on client fingerprint: `urllib` and `curl` were both refused
  with a browser User-Agent, so it is TLS/HTTP-level, not UA string matching.

### H-47 — Three agencies cannot be collected and are recorded as `blocked`

- **Location:** `[config/us_agencies.csv]` rows `us-commerce`,
  `us-transportation`, `us-epa`
- **Decision:** Commerce, Transportation and EPA are marked `tier=blocked`,
  `transport=blocked`, with `date_filter` and `pagination` left `unknown` and
  `label_map` empty. Their structure was not determined and is not guessed at.
- **Rationale:** EPA serves an interactive human-verification CAPTCHA;
  Commerce a Cloudflare interstitial that did not clear in a real browser;
  Transportation an outright Access Denied to browser and HTTP client alike.
  Working around a CAPTCHA was out of bounds, so the honest record is that
  three of 24 agencies are not automatable by this pipeline as built. Writing a
  plausible-looking `label_map` for a site nobody has seen the inside of would
  be the H-42 failure mode in advance: output that looks right and is not.
- **Status:** Open — needs a PI decision on the route. Three options, none
  requiring pipeline changes: a manual export from each press office, an agreed
  feed, or documenting the three as an explicit coverage gap in the corpus.
- **Context:** Roughly one agency in eight. EPA and Transportation both carry
  economics-relevant portfolios, so this is a substantive gap rather than a
  cosmetic one, and it should be stated in the corpus documentation whichever
  route is taken.

### H-48 — The pagination vocabulary grows by three values

- **Location:** `[sources/base.py:SourceAdapter.pagination]`,
  `[config/us_agencies.csv:pagination]`
- **Decision:** `pagination` gains `path_segment`, `none` and `ajax` alongside
  `page_param`, `offset` and `unknown`. Distribution across the 24:
  `page_param` 9, `none` 6, `offset` 3, `ajax` 2, `path_segment` 1,
  `unknown` 3.
- **Rationale:** Each value was forced by a site the original three could not
  describe. `path_segment`: State paginates at `/press-releases/page/3/`
  because CloudFront strips its query string entirely. `none`: six agencies —
  GSA, NRC, OPM, SSA, HUD, USAID — put a whole year, or the whole list, on one
  page, and calling that `page_param` with one page would misdescribe it.
  `ajax`: NSF and DOE emit no pager hrefs at all, so a plain fetch can never
  reach item 13; recording that as `unknown` would hide a known fact.
- **Status:** Settled
- **Context:** `none` is the useful surprise. Six agencies need no paging loop,
  and three more (Interior, GSA, DOL) expose a server-side year facet, so nine
  of the 21 non-blocked agencies can have the window applied without the
  client-side descend-until-out-of-window logic `education.py` needs.

### H-49 — Two agencies are `feed` tier on an open WordPress REST API

- **Location:** `[config/us_agencies.csv]` rows `us-va`, `us-nasa`
- **Decision:** VA and NASA are `tier=feed`, `date_filter=server`, collected
  from `/wp-json/wp/v2/<type>?after=&before=` — `news-releases` for VA,
  `press-release` for NASA — with `page`/`per_page` offset paging and
  `X-WP-Total` for the count.
- **Rationale:** Both were verified to honour the window rather than merely
  accept it: NASA's `press-release` falls from 9,287 items to 153 and VA's
  `news-releases` from 4,492 to 46, both returned in date order. That is a
  genuine server-side filter, which is what `feed` means, and it makes these
  the two cheapest adapters of the 22.
- **Status:** Settled
- **Context:** The control query mattered and should be standard practice for
  any future REST-API source. State.gov *also* runs WordPress and *also*
  answers `/wp-json/wp/v2/state_press_release` with HTTP 200, but its
  CloudFront strips the query string, so `after`, `before`, `page`, `per_page`
  and `orderby` are all silently discarded and every request returns the same
  newest ten rows. Taken at face value that API would have produced a corpus of
  ten documents with no error anywhere. It is caught only by asking whether the
  filtered count differs from the unfiltered one.
  VA carries a second split worth a decision: `news-releases` holds 46 items in
  the window but the ordinary `post` type holds 522. Whether the wider stream is
  in scope is a PI question, not a collection one.

### H-50 — Four collection facts that will silently corrupt a column if missed

- **Location:** `[config/us_agencies.csv]` notes for `us-defense`,
  `us-interior`, `us-sba`, `us-state`
- **Decision:** Recorded per-agency in `notes` rather than left for whoever
  writes each adapter to rediscover:
  1. **defense.gov is now war.gov.** The Department of War rebrand moved the
     domain, and its pager is `?Page=N` with a capital P. Dates are AP-style
     text only — "Sept. 3, 2026" — with no `<time>` anywhere, so the date
     parser must handle AP month abbreviations or every Defense document
     arrives undated.
  2. **Interior's listing dates are `MM/DD/YYYY`.** They are present in the
     rows, but neither ISO nor `<time>`, and a first pass reported Interior as
     having no dates at all. Its documents also live under `/pressreleases/`
     while the listing is `/news`, and `/pressreleases` as an index now 404s.
  3. **SBA's content moved to `legacy.sba.gov`.** The redesigned `www.sba.gov`
     newsroom links out to `legacy.sba.gov/article/YYYY/MM/DD/<slug>`, and the
     usable listing is `legacy.sba.gov/articles?article_type=N`.
  4. **State mixes Public Schedule entries into `state_press_release`.** They
     are daily diary items, not press releases, and must map to `other`.
- **Rationale:** H-42 predicted that 22 more adapters would each carry their
  own version of the Treasury faults, and the survey found four before any
  adapter was written. Each is invisible in code review and three of the four
  produce plausible output: a Defense corpus with no dates, an Interior corpus
  with no dates, an SBA corpus with no documents, a State corpus padded with
  diary entries.
- **Status:** Settled
- **Context:** The survey is index-only — no document body was fetched from any
  of the 22, the same rule `list_documents()` imposes — so per-agency body
  faults of the Treasury mega-menu kind (H-42 fault 1) are still ahead. The
  standing per-agency audit gate is not replaced by this survey.

### H-51 — SBA's `article_type` facet is the type vocabulary the project wanted

- **Location:** `[config/us_agencies.csv]` row `us-sba`
- **Decision:** SBA's `label_map` is taken directly from its own
  `article_type` taxonomy: 137 News release, 279 Archived news release, 383 OIG
  news release, 134 Disaster news release, 133 Congressional testimony, 253
  Memo, 136 Op-ed, 138 Speech.
- **Rationale:** It is the only index of the 24 that separates op-ed and
  testimony at the listing, which means SBA needs no title heuristics of the
  kind H-42 fault 3 required for Treasury. Where a source states the type, the
  source is used.
- **Status:** Settled
- **Context:** DOL is the other agency whose facets do real work, for a
  different reason: `?agency=osec` isolates the Office of the Secretary from
  the sub-agency newsrooms (whd, osha, eta, ebsa), which is precisely the
  Secretary-level subset this project collects. Every other agency mixes
  departmental and bureau output in one stream — Interior's listing carries
  Fish and Wildlife releases alongside the Secretary's — and will need that
  separation made downstream instead.

### H-52 — What was tried to recover Commerce, EPA and Transportation

- **Location:** `[config/us_agencies.csv]` rows `us-commerce`, `us-epa`,
  `us-transportation`
- **Decision:** Seven recovery routes were tested before accepting the gap.
  Recorded so none is retried blind, and so the two that remain live are
  distinguished from the five that are closed.
  1. **A different TLS/HTTP stack.** The .NET client (`Invoke-WebRequest`) has
     a different fingerprint from `urllib` and `curl` and does reach parts of
     EPA that both refuse. It does not help Commerce or Transportation.
  2. **A real browser.** Clears the block for six other agencies (H-46) but
     not these: Transportation returns Access Denied, Commerce a Cloudflare
     verification that did not clear in 20s, EPA an interactive CAPTCHA.
     Solving the CAPTCHA was out of bounds and was not attempted.
  3. **Sitemaps.** None of the three serves `/sitemap.xml` or any variant.
  4. **GovDelivery.** All four agency accounts redirect to a login. Closed.
  5. **Sub-agency newsrooms.** NOAA, NIST and trade.gov are reachable, but
     publish their own heads rather than the Secretary; most of the
     Transportation family (railroads, maritime, phmsa, fmcsa) is blocked too.
  6. **Internet Archive as an enumeration source.** Works for EPA, fails for
     the other two — see below.
  7. **Internet Archive as a corpus source.** Rejected on provenance for all
     three, and independently unworkable: of 2,043 Transportation documents
     captured during the window, a random sample of 12 found 11 published
     between 2016 and 2025.
- **Rationale:** The three are not one problem. EPA's *shape* is now known and
  only its *reachability* is missing; Transportation's block is demonstrably
  not blanket; Commerce has hardened against everything including the Archive.
  Reporting them as a single three-agency gap would have hidden the fact that
  two of the three have a live route and one probably does not.
- **Status:** Open — two tests belong to the PI, and neither is a code change.
- **Context:** The decisive evidence is what the Internet Archive is getting
  today, because it is a well-behaved crawler on an address that is not ours.
  Between June and September 2026: **Transportation** returned 200 on 200
  sampled captures against 6 blocks, the newest on 2026-09-07; **EPA** returned
  200 on 13 captures with **zero** 403s; **Commerce** returned 403 on 115
  captures against 5 successes, the last on 2026-07-20. Transportation and EPA
  therefore serve automated clients that are not us, which points at address or
  fingerprint reputation rather than a policy against collection, and makes
  *try it from the project network* the highest-value next step for both. Both
  agencies' newsrooms are also read by ordinary users daily, which is difficult
  to reconcile with a deliberate bar on reading them.
  For EPA the fallback is already proven in outline: an archived capture of
  `/newsreleases/search` is a 146KB **server-rendered** page carrying 15
  release links, a date per row and a working `?page=N` pager, and the listing
  was captured on 96 separate days across the window. Enumeration from those
  captures plus live body fetches would preserve the verbatim guarantee, since
  only the index would come from the Archive. That fallback has now been measured rather than
  estimated. Replaying all 78 distinct captures of `/newsreleases/search` in
  the window, with no fetch failures, yields **423 documents published between
  2026-01-01 and 2026-07-31**, across 133 publication days, with no gap between
  consecutive covered days longer than five. Against the 152 business days in
  the window that is **86% of business days covered, 22 uncovered**, several of
  which are public holidays (1 January, Presidents' Day, Memorial Day week,
  Independence Day week) on which EPA would not have published anyway. The
  per-snapshot yield decays from 15 new documents to 2-4 by the end of the run,
  which is the saturation signature of a nearly-closed set.
  The archive route is therefore substantially complete but demonstrably not
  complete, and its real defect is that **it cannot say which documents are
  missing**. A corpus built this way would have to state that: EPA present,
  coverage approximately 86% of publication days, completeness unverifiable.
  Acceptable as a documented fallback, clearly worse than reaching the live
  listing, which is why the network test comes first.
  Commerce is the one to plan around rather than solve. If it stays closed the
  honest options are a request to its press office, or an explicit,
  documented coverage gap of one agency in 24.

---

## 4. Harvest — the first ten adapters

### H-53 — A REST API is not trusted to have applied its own date filter

- **Location:** `[sources/us/_wordpress.py:WordPressAdapter._verify_window()]`,
  `[sources/us/state.py]`
- **Decision:** `WordPressAdapter` asks, before collecting, for one item dated
  strictly *before* the requested window. An API that filters returns nothing;
  one that discards the query string returns its newest item, which is inside
  the window and therefore proof the filter never ran. If that happens the
  adapter raises `WordPressWindowError` rather than collecting.
- **Rationale:** state.gov runs WordPress, answers
  `/wp-json/wp/v2/state_press_release` with HTTP 200, and looks exactly like
  the NASA and VA case. Its CloudFront strips the query string, so `after`,
  `before`, `page`, `per_page` and `orderby` are all silently discarded and
  every request returns the same newest ten rows. An adapter built on that API
  would have produced a ten-document corpus, with no error anywhere and no way
  to tell from the output that anything was wrong. HTTP 200 is not evidence of
  filtering, and the only thing that distinguishes the two cases is asking a
  question whose answer differs.
- **Status:** Settled
- **Context:** The control query is cheap -- one request per agency per run --
  and it is the reason NASA and VA can be trusted at `date_filter: server`.
  Both were verified to genuinely narrow: NASA's `press-release` type from
  9,287 items to 153, VA's `news-releases` from 4,492 to 46, both in date
  order. State is collected through path pagination instead and does not
  inherit from `WordPressAdapter` at all.

### H-54 — One agency gets a User-Agent override, and it still says who we are

- **Location:** `[sources/base.py:SourceAdapter.user_agent]`,
  `[sources/base.py:Fetcher.__init__]`, `[sources/us/state.py]`
- **Decision:** `SourceAdapter` gains an optional `user_agent`. When set, the
  adapter builds its own `Fetcher` rather than mutating the shared one, so an
  override cannot leak into the other 23. State is the only agency that sets
  one:
  `Mozilla/5.0 (compatible; eps-research/0.1; academic research; contact via institution)`
- **Rationale:** state.gov returns a flat 403 to the project's default
  `eps-research/0.1 (academic research; contact via institution)` on every
  path, and 200 to the string above. Without an override State contributes
  nothing, and it is the third-largest agency in the corpus at 818 documents.
  The override was chosen to keep the project identified rather than to
  impersonate a browser: `Mozilla/5.0 (compatible; ...)` is the conventional
  compatibility prefix rather than a claim to be Chrome, and the token still
  names `eps-research` and how to make contact. A bare
  `eps-research/0.1 (+url)` was also tried and refused, which is what shows the
  filter is keying on the prefix and not on the disclosure.
- **Status:** Settled, but it is a **PI-visible** choice. Reverting it is one
  line, at the cost of the whole State corpus.
- **Context:** The default is deliberately not changed. Twenty-three agencies
  accept it, including every other one written so far, and swapping the project
  default to a browser string to solve one agency would trade the transparency
  of all 24 for the convenience of one.

### H-55 — A truncated index walk raises instead of returning what it has

- **Location:** `[sources/base.py:ListingIncomplete]`, and the `list_documents`
  of all ten new adapters
- **Decision:** When an index page cannot be fetched after `Fetcher`'s four
  retries, the adapter raises `ListingIncomplete` rather than returning the
  refs collected so far. `harvest_us.py` already logs a raised listing as
  `listing_unreachable`, which is a different screening-log row from
  `no_documents_in_window`.
- **Rationale:** Found by hitting it. State needs roughly forty index pages to
  reach the far end of a seven-month window, and a transient failure on page
  two returned an empty list that was indistinguishable from an agency with
  nothing to report -- the run printed a clean zero for an agency that has 818
  documents. Section 5 of the RA guide requires a logged zero to be
  distinguishable from an agency nobody checked; a silently truncated walk
  violates that more quietly than either.
- **Status:** Settled for the new adapters. `education.py` and `treasury.py`
  still return on failure and were left alone: they are fenced, and changing
  them would invalidate a harvest already collected and cited.
- **Context:** The threshold is deliberately after retries, not before.
  `Fetcher` retries four times with exponential backoff, so reaching the raise
  means the page is persistently unavailable rather than briefly slow. The cost
  is that one hard failure near the end of a long walk discards that agency's
  run; the alternative cost is a corpus that is quietly missing half an agency
  and says nothing about it.

### H-56 — Five body-extraction faults, each invisible in review

- **Location:** `[sources/us/dhs.py:_MAIN]`, `[sources/us/hud.py:_CONTENT]`,
  `[sources/us/gsa.py]`, `[sources/us/opm.py]`, `[sources/us/state.py:_COMMENT]`
- **Decision:** Recorded because H-42 predicted exactly this and it happened
  five more times:
  1. **DHS** serves `field--name-body` twice. The first, 14KB into the page, is
     a site-wide block whose content is a `<style>` payload. The slice is
     anchored to `block-mainpagecontent` first, or every DHS document would
     have been a page of CSS.
  2. **HUD** serves it **six** times, five of them theme blocks. The article is
     the one inside `div.content`, so the adapter takes the longest candidate
     found after a `div.content` opener.
  3. **GSA**'s `#gsa-body` opens with the `<time>` stamp and the `<h1>`, so
     slicing it whole put "July 31, 2026" and the headline into the document
     text as though the agency had written them as prose. Everything up to the
     first `</h1>` is trimmed. **OPM** needed the same trim.
  4. **State**'s listing row ships a commented-out placeholder,
     `<!-- <span>date</span> -->`. Parsed naively, the literal word "date"
     became the recorded speaker on all 818 rows.
  5. **DHS has no speeches section and no testimony section.** The survey's
     `label_map` listed both because the brief did; the newsroom offers only
     press-releases, blog and featured, and requests for the other two fail.
     The adapter now walks one section and says so.
- **Rationale:** Four of the five produce plausible output rather than an
  error: a corpus of stylesheets, a corpus with headlines as sentences, a
  speaker column reading "date", and two silently empty sections. None is
  visible without fetching a real page and reading what came back.
- **Status:** Settled
- **Context:** Fault 5 is the one worth generalising. A `label_map` derived
  from an agency's published document taxonomy is a statement about what the
  agency *publishes*, not about what its website *exposes as a section*, and
  the two came apart here. Sections are now verified by request before an
  adapter walks them.

### H-57 — SBA's 523 documents are not 523 Administrator statements

- **Location:** `[sources/us/sba.py:ARTICLE_TYPES]`,
  `[config/us_agencies.csv]` row `us-sba`
- **Decision:** All seven of SBA's public `article_type` facets are collected,
  and the raw label is preserved on every row. Nothing is filtered at
  collection time.
- **Rationale:** SBA returns 523 documents in the window, which would make it
  the second-largest agency in the corpus, but the composition is lopsided:
  **399 Disaster news releases**, 55 OIG news releases, 62 ordinary news
  releases, 6 op-eds and 1 congressional testimony. Disaster notices are
  regional operational announcements, and the OIG is the independent Inspector
  General rather than the Administrator, so on a plain reading neither is a
  statement by the agency head. Filtering at collection time would nonetheless
  bake that reading into the corpus, which is what H-34 exists to prevent, so
  the labels are recorded and the decision is left downstream where it is
  reversible.
- **Status:** Open — a PI decision on scope, not a collection problem. The
  filter is one predicate on `source_document_type` whenever it is taken.
- **Context:** The same shape recurs elsewhere and should be handled the same
  way: Interior's listing carries Fish and Wildlife and BLM releases alongside
  departmental ones, and State's carries items issued by the Office of the
  Spokesperson rather than the Secretary. SBA is simply the case where the
  source labels the distinction clearly enough to act on later.

---

## 5. Harvest — congressional hearings

### H-58 — Testimony is collected from Congress, not only from agency newsrooms

- **Location:** `[sources/congress.py]`, `[sources/blocks.py:split_hearing_turns()]`,
  `[sources/blocks.py:hearing_blocks()]`, `[sources/blocks.py:METHODS]`
- **Decision:** A second collector reads GPO hearing transcripts (`CHRG`),
  matches the printed witness list against `officeholders_2026.csv`, and emits
  one document per (hearing x matched officeholder), typed `testimony`.
  `METHODS` gains a fifth value, `hearing_turn`.
- **Rationale:** The eleven agency adapters found **15** testimony documents in
  2026-01-01..2026-07-31. GPO published **170** hearing transcripts dated inside
  the same window, 26 of them listing a witness titled "Secretary". Agencies
  publish some of their head's testimony and there is no way to tell which
  some, so testimony taken only from newsrooms is a biased sample of the most
  substantive material the project has. The scale of what is missed is the
  argument: the HUD oversight hearing of 2026-01-21 alone carries **389 turns
  and 13,502 words in Secretary Turner's own voice**, more of one officeholder's
  speech than any press release in the corpus.
- **Status:** Built and unit-tested. **Not yet run** — see the key below.
- **Context:** `hearing_turn` is the strongest of the five attribution methods
  and deserves saying why: the speaker is named by the official reporter at the
  head of each turn, for a bounded span of text. Every other method infers a
  speaker from punctuation, a speech verb, or an adjacent block. Nothing about
  a hearing has to be guessed.

### H-59 — A hearing is not an agency, so the collector is not a `SourceAdapter`

- **Location:** `[sources/congress.py:CongressionalHearings]`
- **Decision:** `CongressionalHearings` does not subclass `SourceAdapter` and is
  not in `ADAPTERS`. It runs the join the other way round: find the hearing,
  read the witness list, and derive `institution_id` from whoever testified.
- **Rationale:** `SourceAdapter` is one agency per class — `institution_id` is a
  class attribute and the adapter walks that agency's newsroom. A hearing has no
  such owner; it is published by Congress and counts for whichever agency's head
  appeared. Forcing it into the adapter contract would have meant either 24
  near-identical hearing adapters or an adapter that lies about which agency it
  represents.
- **Status:** Settled
- **Context:** One consequence worth stating: a single hearing can legitimately
  produce two documents when two tracked officeholders share a panel. They are
  separate rows because they are separate speakers; de-duplication is on
  (package_id, institution_id), not on the hearing alone.

### H-60 — Three collection facts about GPO, two of them found by being wrong

- **Location:** `[sources/congress.py:witness_name()]`,
  `[sources/congress.py:list_hearings()]`, `[sources/congress.py:lag_warning()]`
- **Decision:** Recorded because two produced a silent zero rather than an
  error:
  1. **The witness line is name-first, then office, then organisation** —
     "Hon. Scott Turner, Secretary, Department of Housing and Urban
     Development". Passing the whole line to `names_match` fails, because
     `name_tokens` reads "Housing", "Urban" and "Development" as forenames and
     the token sets conflict. The first run returned **zero documents from a
     hearing whose only witness was a tracked Secretary**. Only the first
     comma-clause is the person.
  2. **A turn marker must not be allowed to run into the speech.** Permitting a
     full stop inside the name token let "Chairman Hill. Good morning" parse as
     the speaker "Chairman Hill. Good", and 52 of 112 apparent speakers in one
     transcript were fragments of that kind. With the stop excluded the count
     falls to the correct 46.
  3. **`/published` filters on the hearing date, `/collections` does not.**
     The collections endpoint filters on last-modified and answers a 2026 query
     with packages from 2024. `dateIssued` on a CHRG package is the date the
     hearing was held, which is the date this project wants.
- **Rationale:** Faults 1 and 2 are the H-42 pattern again: both produce
  plausible output — an empty result and a speaker list — rather than an error.
- **Status:** Settled

### H-61 — Hearing coverage is incomplete at the recent end, by construction

- **Location:** `[sources/congress.py:lag_warning()]`
- **Decision:** The collector reports which months of a window are thin rather
  than leaving the caller to infer completeness from counts.
- **Rationale:** Transcripts are printed months after the hearing. The window's
  monthly counts run 15, 17, 15, 14, 15, 19, **5** — July is not a quiet month,
  it is an unfinished one. A corpus assembled today under-reports the end of the
  window and a re-run later will find more, so the figure has to be stated
  rather than discovered.
- **Status:** Settled
- **Context:** **Discovery needs an api.data.gov key and the run has not
  happened.** The shared `DEMO_KEY` returns HTTP 429 after a handful of
  requests: enough to verify the endpoint, useless for a run. Set
  `GOVINFO_API_KEY`; the key is free and issued instantly, and obtaining it is a
  PI action rather than something to be done on the project's behalf.
  Transcripts and MODS come from the public content service with no key at all,
  so only discovery is metered — the collector was validated end to end against
  a real hearing through that unmetered path.

### H-62 — The hearing collector ran, and the window is not ready

- **Location:** `[sources/congress.py]`, `[config/us_agencies.csv]`
- **Decision:** The collector was run over the full window with a real
  api.data.gov key on 2026-09-08. It scanned **170 published transcripts**,
  matched **2**, and produced **2 documents**: Secretary Turner before House
  Financial Services on 2026-01-21 (389 turns, 13,502 words) and Secretary Noem
  before House Judiciary on 2026-03-04 (450 turns, 10,737 words). 24,239
  attributed words in total.
- **Rationale for reporting it as a near-miss rather than a success:** the
  H-58 estimate was **too optimistic and is corrected here**. It reasoned from
  "26 of 170 transcripts list a witness whose title contains Secretary", but
  those are overwhelmingly Under Secretaries, Deputy Secretaries, corporate
  officers and commissioners. Of 490 distinct witnesses across the window,
  exactly two are Cabinet heads this project tracks. The join is not at fault —
  it is doing what it should — the population is simply thin.
- **Status:** Settled as to mechanism. **Re-run required**, see below.
- **Context:** The reason is publication lag, and it is now measured rather
  than asserted. Published CHRG transcripts for the same January-to-July window
  in successive years:

      2026 (this window)   170
      2025                 595
      2024                 720
      2023                 916

  The 2026 window is at roughly **19-29% of eventual coverage**, and transcripts
  keep accruing for years. The two documents found today are a floor, not a
  total; on the 2023 ratio the finished window would hold something closer to
  ten. **This collection should be re-run in 12-24 months**, and the corpus
  should record which run it came from. Nothing needs to change in the code for
  that; the same command returns more as GPO prints more.

### H-63 — A wrapped line looked exactly like a speaker turn

- **Location:** `[sources/blocks.py:_TURN]`
- **Decision:** A turn marker must be **indented**. GPO wraps transcript lines
  at about 72 characters, so a name landing at the start of a wrapped line is
  indistinguishable from a turn unless indentation is required. Real turns
  carry a four-space indent; continuation lines start at column zero. The
  pattern also stops treating `\s` as valid inside a name, since that let a
  marker span a line break and join two speakers into one.
- **Rationale:** Caught in the collected output, not in review, and it was the
  worst kind of fault: in CHRG-119hhrg63054 the Ranking Member says "Welcome, /
  Secretary Noem. We are glad to meet you, even though it has been 13 months
  since you took office", and the collector split that at the line break and
  **attributed the committee's welcome to the Secretary**. The document would
  have recorded a Cabinet officer saying words that were spoken to her, in a
  corpus whose entire purpose is who said what.
- **Status:** Settled, with a regression test built from the exact wrapped text.
- **Context:** Effect on the two documents: Noem falls from 451 turns/11,069
  words to 450/10,737, and the speaker count from 43 to 41; Turner is unchanged
  at 389/13,502 but loses three false speakers, "Mr. Chairman", "Mr. Secretary"
  and "Ranking Member Waters", which are forms of address rather than turns.
  Both documents now open with the witness actually speaking. This is the third
  time in this section that a transcript convention produced plausible output
  rather than an error, after H-60's witness line and turn-marker faults.

---

## 6. Harvest — the browser-tier transport

### H-64 — TLS impersonation, not a browser, is what unblocks seven agencies

- **Location:** `[sources/transport.py:ImpersonatingFetcher]`,
  `[sources/browser.py:BrowserFetcher]`
- **Decision:** The seven agencies that 403 every stdlib HTTP client are
  collected with `curl_cffi` reproducing Chrome's TLS and HTTP/2 handshake.
  `BrowserFetcher` (Playwright) is kept, but only for the two agencies that
  need JavaScript or a human.
- **Rationale:** A browser was authorised and tried first, and it is the wrong
  tool. **Headless Chromium is itself detected**: Chromium headless, Chrome via
  `channel="chrome"`, and the headless shell all returned 403 from USDA,
  Defense, HHS, Labor, Transportation and Commerce; only NRC and SSA passed.
  **Headed Chromium could not be run at all** in a non-interactive environment
  -- the full binary fails with `spawn UNKNOWN`, and `channel="chrome"` headed
  launches but the page detaches immediately. `curl_cffi` passes seven of the
  nine from an ordinary Python process, against two for headless Chromium, and
  costs 5MB rather than 300MB.
- **Status:** Settled. Playwright remains installed and is not wasted: Commerce
  and EPA have no other route.
- **Context:** Both transports present the same four methods as `base.Fetcher`,
  so no adapter knows which one it is holding. That is the payoff of separating
  `tier` from `transport` in H-46: USDA, Defense, HHS, Labor, SSA and
  Transportation are ordinary listing adapters that differ from DHS only in the
  object passed to their constructor.
  On identification: the User-Agent has to match the handshake, or the mismatch
  is itself a signal, so it is Chrome's. The project identifies itself in an
  `X-Research-Contact` header on every request instead. That is a deliberate
  trade and it is recorded rather than buried.

### H-65 — Two agencies need a person, and no client will change that

- **Location:** `[config/us_agencies.csv]` rows `us-commerce`, `us-epa`
- **Decision:** Commerce and EPA are not collected by `ImpersonatingFetcher`
  and are not to be retried with it.
- **Rationale:** Their barriers are not handshake-shaped. **Commerce** serves a
  Cloudflare JavaScript challenge -- the client must execute the challenge, which
  a TLS-impersonating HTTP client does not do. **EPA** serves an interactive
  CAPTCHA, which is a request for a human and the only legitimate answer is a
  human. Both were confirmed reachable from the project network by the PI on
  2026-09-08, EPA after completing the verification by hand.
- **Status:** Open — needs a headed session on the project network, which this
  environment cannot provide.
- **Context:** `BrowserFetcher` uses `launch_persistent_context`, so a profile
  directory carries cookies between runs. The intended sequence is that a person
  clears the challenge once in a headed window and later runs reuse the session.
  Nothing in the code attempts to answer a CAPTCHA, and `ChallengePresented` is
  raised rather than retried precisely so a run stops instead of silently
  collecting challenge pages as though they were documents.

### H-66 — Two survey notes were wrong, and both would have collected nothing

- **Location:** `[sources/us/labor.py]`, `[sources/us/agriculture.py:_BODY]`
- **Decision:** Recorded because both came from the survey's own notes and both
  fail silently:
  1. **Labor's `?agency=osec` facet does not filter, it empties.** The survey
     recorded it as a server-side filter isolating the Office of the Secretary.
     Requesting it returns a page with ZERO release links against twenty for the
     unfiltered listing: `osec` is a path segment on the document URL, not a
     value that parameter accepts. The adapter now walks the listing unfiltered
     and reads the sub-agency from the URL path.
  2. **USDA's body class is `field--body`, one dash.** Drupal's usual
     `field--name-body` also appears on a USDA page, seven times, and the first
     of them is the site's "About Food" navigation blurb. Slicing it produced a
     document of menu text.
- **Rationale:** A survey note is a hypothesis about a site, not a fact about
  it, and neither of these announced itself. Fault 1 yields an empty agency that
  looks like a quiet news period; fault 2 yields a full document of the wrong
  words.
- **Status:** Settled
- **Context:** This is now the eighth and ninth body-or-filter fault of exactly
  this shape across the US work (H-42, H-50, H-56, H-60, H-63). The pattern is
  stable enough to state as a rule: **on a new agency, verify the body selector
  against fetched prose before trusting it, and verify that a facet narrows the
  result set rather than merely being accepted.**

### H-67 — Defense is written but not registered, and NRC needs a decision

- **Location:** `[sources/us/defense.py]`, `[sources/us/__init__.py:_CLASSES]`,
  `[config/us_agencies.csv]` row `us-nrc`
- **Decision:** `DefenseAdapter` exists and is **deliberately absent from
  `ADAPTERS`**. NRC keeps its adapter slot empty pending a dependency decision.
- **Rationale, Defense:** war.gov's listing is Vue-rendered. The markup contains
  `<time :data-dateago="publishDateJss">` -- a template binding, not a value --
  so an HTML parse finds 3 static rows where a browser renders 31. Registering
  it would collect roughly a tenth of Defense and report success, which is the
  silent-partial failure `ListingIncomplete` was added to prevent (H-55). Not
  collecting an agency is recoverable; collecting a tenth of it and not knowing
  is not. It is reclassified `tier: awkward`, alongside Energy and NSF, which
  fail the same way.
- **Rationale, NRC:** every 2026 news release is a **PDF** -- 141 of them, no
  HTML alternative. The listing is a clean per-year table and is reachable, so
  titles and dates could be harvested today; only the bodies need a text
  extractor, which is a further non-stdlib dependency for one small agency
  whose output is mostly technical licensing notices.
- **Status:** Defense settled as deregistered. **NRC open** -- PI decision
  between a PDF dependency and a documented gap. The recommendation is the gap.
- **Context:** `transport` gains a third value, `impersonate`, because
  `browser` had quietly been doing two jobs: "needs a non-stdlib client" and
  "needs an actual browser". Only Commerce and EPA need the second. Collapsing
  them would have put a 300MB Playwright install on the critical path for seven
  agencies that are served fine by a 5MB HTTP client. Distribution across the
  24 is now `http` 14, `impersonate` 7, `browser` 2, `blocked` 1.

---

## 7. Harvest — the first full US run

### H-68 — The first full run collected 2,687 documents and exposed two faults

- **Location:** `[harvest_us.py:TransportPool]`, `[sources/us/state.py:_BODY_START]`,
  `[sources/us/sba.py]`
- **Decision:** The harvest was run end to end over the seventeen registered
  adapters on 2026-09-08. It wrote **2,687 documents** with sidecars, every one
  dated, median 448 words, no zero-word files. Two faults were found in its
  output and fixed, and the run was repeated.
- **Rationale for recording the numbers before the fixes:** they are the
  argument for the audit gate. The run looked successful -- it completed, wrote
  a corpus, and reported per-agency counts that matched the verification pass.
  Both faults were only visible by reading the log afterwards.
- **Status:** Settled as to mechanism; the corrected run supersedes these
  figures.
- **Context, fault 1 -- STATE LOST 520 OF 818 DOCUMENTS.** state.gov has two
  body layouts and the adapter knew one. Newer posts use `wp-block-paragraph`
  divs; older ones use a single `classic-block-wrapper` / `wp-block-classic`
  holding plain `<p>` tags. The 520 were logged honestly as `no_body`, so
  nothing was silently wrong -- but the loss was **not random**. It fell on
  Press Statements (167), Media Notes (161) and Readouts (118), which is to say
  on the document types the project most wants, because those are the older
  template. An agency-level count would have looked plausible; only the
  exclusion breakdown showed it.
- **Context, fault 2 -- 512 DOCUMENTS TYPED `other`.** SBA's document page
  classifies a release as "Disaster news release OK-20026-05 (21092)". The
  release number was being stripped by a rule that only removed a trailing run
  of digits, so the identifier stayed attached, every document carried a unique
  `source_document_type`, none matched `label_map`, and all fell through to
  `other`. The fix strips from the first state-code or digit onward.
- **Also recorded:** `TransportPool` had to be added before the run was possible
  at all. `harvest_us.py` built one global `Fetcher`, which would have 403'd all
  seven impersonate-tier agencies mid-run; the audit path needed the same
  change, or every one of them would have reported `fetch failed` and read as a
  corpus problem rather than a transport one.

### H-69 — Labor loses 27 documents to URLs that do not resolve

- **Location:** `[sources/us/labor.py]`, screening log `no_body` rows
- **Decision:** Recorded as a known 15% loss for Labor rather than fixed.
- **Rationale:** The 27 are sub-agency releases, mostly ETA. Their listing URLs
  return a 547KB page with no `<title>`, no `<h1>` and none of the body classes
  a Labor document carries -- it is not a document page. The equivalent
  Office-of-the-Secretary URL returns a normal 71KB document. Since the loss
  falls entirely on sub-agency output, which H-57's scope question would
  probably exclude anyway, it is not worth chasing ahead of the four agencies
  that have no adapter at all.
- **Status:** Open, low priority. The rows are logged as `no_body`, so the loss
  is visible in the corpus rather than hidden.

---

## 7. Harvest — the first full run and its audit

### H-70 — The corpus is written: 3,153 documents from 15 agencies

- **Location:** `[harvest-code/us-harvest/screening_log.csv]`,
  `[harvest-code/us-harvest/documents/]`
- **Decision:** The window 2026-01-01..2026-07-31 is collected and on disk.
  3,192 log rows, 3,153 collected documents, one `.txt` and one
  `.blocks.json` sidecar each. Every document is dated -- `metadata` 2,780,
  `listing` 348, `body` 25, **`inferred` zero, undated zero**. Median length
  423 words, shortest 12, longest 11,786, none empty.
- **Rationale:** Recorded as a decision rather than a statistic because the run
  fixes the corpus the rest of the pipeline will be built on, and because two
  earlier runs of the same command produced materially different corpora and
  neither announced it. Run 1 wrote 2,687 documents with 547 `no_body`
  exclusions concentrated in State. Run 2 fixed the body extraction and lost
  all 810 State documents to a connection reset. Run 3 is the one on disk.
- **Status:** Settled for this window. Re-running will change counts at the
  margin as agencies publish and as transcripts print.
- **Context:** Composition: `press_release` 2,569, `statement` 264,
  `other` 200, `speech` 84, **`testimony` 15**, `interview_transcript` 15,
  `op_ed` 6. The three exclusion classes stay distinguishable as Section 5 of
  the RA guide requires -- `adapter_not_implemented` 7,
  `listing_unreachable` 2 (USAID and Energy), `no_body` 29, `fetch_failed` 1.

### H-71 — The audit found one fault, and it was in the code the audit exists to test

- **Location:** `[sources/us/_wordpress.py:WordPressAdapter._post_id()]`
- **Decision:** `fetch_document` no longer depends on `list_documents` having
  run first. The post id is resolved from the URL slug when the listing cache
  is empty.
- **Rationale:** The audit refetches a sample and re-derives the text. Thirteen
  agencies reported `0/8 documents show welded words`. NASA and VA reported
  **`0/0`** -- not a clean result, an empty one. Both are WordPress agencies,
  and `_post_id()` read a side table populated during listing, so a ref rebuilt
  from the screening log resolved to no id and every refetch failed with "post
  id not resolvable". The harvest itself was unaffected, because it lists and
  fetches in one pass. Anything else -- the audit, a repair pass, a re-run
  against an existing log, any downstream tool -- got nothing.
- **Status:** Fixed and verified on VA: a ref built from a bare URL now refetches
  3,824 bytes and 3,370 characters of text with a `metadata` date.
- **Context:** This is the argument for the audit being a standing gate rather
  than a one-off, made by the gate itself. The fault was invisible in the
  harvest output, invisible in the 184-test suite, and invisible in review; it
  showed up as two agencies reporting a denominator of zero while every other
  agency reported eight. **A passing audit line and an empty audit line look
  alike at a glance, and only one of them means anything.**

### H-72 — Text fidelity holds across every agency the audit could reach

- **Location:** `[harvest_us.py:audit()]`
- **Decision:** Recorded as the positive result it is: **0 welded words in 102
  sampled documents across 13 agencies**, against the B-05/B-06 fault that
  broke the UK harvest and forced `text.py` to exist.
- **Rationale:** The rule that every tag becomes a space, not an empty string,
  was inherited by fifteen adapters written by a different route from the two
  that first proved it. That it survived the inheritance is worth stating,
  because the failure mode is silent: welded words do not raise, they just stop
  the frozen text matching the page it cites.
- **Status:** Settled for 13 of 15 agencies.
- **Context:** NASA's audit is **pending, not passed**. nasa.gov began
  returning 403 to this host -- to the project User-Agent and to Chrome
  impersonation alike -- after the harvest had already taken its 153 documents.
  That is rate limiting rather than a policy change, and the honest record is
  that NASA's 153 documents are collected but unaudited. Re-run the audit for
  `--only us-nasa` once the host has cooled off. State audited 6 of 8; the two
  misses were the same throttling, at a much lower rate.

---

## 8. Harvest — the archived index

### H-73 — Five agencies are one problem, not five

- **Location:** `[sources/us/_archived_index.py:ArchivedIndexAdapter]`,
  `[sources/us/epa.py]`, `[sources/us/nsf.py]`, `[sources/us/justice.py]`,
  `[sources/us/defense.py]`, `[sources/us/energy.py]`
- **Decision:** EPA, NSF, Justice, Defense and Energy are collected by
  enumerating from archived captures of their listing and fetching every
  document body from the live site.
- **Rationale:** The survey recorded these as five separate obstacles — a
  CAPTCHA, an AJAX pager, an Akamai interstitial, a Vue-rendered listing, a
  client-side faceted search — and two of them (Commerce, Transportation) as a
  third category again. They are one obstacle wearing five costumes: **the
  index cannot be walked, but the documents can be fetched.** Every one of the
  five serves individual document pages to an ordinary TLS-impersonating
  client; only the page that lists them is closed. And for every one, the
  Internet Archive holds server-rendered captures of that listing.
- **Status:** Settled
- **Context:** The split is what preserves the guarantee the corpus rests on:

      enumeration    <- archived captures of the listing
      document text  <- the live page, fetched now

  Nothing archival reaches the text. Every `.txt` is verbatim against the page
  the agency publishes today, which anchor-phrase verification (E-08) requires.
  What comes from the Archive is a list of URLs, and a URL is not evidence
  about what was said. That distinction is the whole design; a route that took
  the *text* from the Archive was considered and rejected in H-52.

### H-74 — Archived enumeration is a documented partial, per agency

- **Location:** `[sources/us/_archived_index.py]` module docstring,
  `[config/us_agencies.csv]` notes for the five
- **Decision:** Coverage from this route is reported per agency and never
  presented as complete.
- **Rationale:** Coverage is the union of whatever the captures happened to
  show. For EPA it was measured at 415–423 documents across 77 captures, about
  **86% of the window's business days**. The shortfall is not the real defect.
  The real defect is that **this route cannot say which documents are
  missing**, so a corpus built from it is complete-looking and unverifiable.
  Stating the figure is the difference between a known limitation and a silent
  one.
- **Status:** Settled
- **Context:** Paging the Archive would close most of the gap and is not
  available: the Archive captures page 1 of a listing many times and deeper
  pages almost never — 3 captures of `?page=N` against 96 of page 1 for EPA.
  **NSF is the weak case and is labelled as such**: 192 captures yield only 45
  documents, 15 of them undated, with uneven month coverage, because its
  `/news` page is curated rather than chronological. Its count is a floor, not
  a corpus.

### H-75 — Three survey conclusions this overturned

- **Location:** `[config/us_agencies.csv]` rows `us-justice`, `us-defense`,
  `us-energy`
- **Decision:** Recorded because each was stated confidently and was wrong, and
  the manner of being wrong is instructive:
  1. **Justice was not capped at ~11 documents.** `/opa/speeches` looked like
     the only reachable surface. In fact `justice.gov/news` has **196 archived
     captures** while `justice.gov/opa/pr` has **zero** — the first check used
     the path the documents live under rather than the path the listing lives
     at, found nothing, and concluded the agency was unreachable.
  2. **Defense is collectable after all.** H-67 refused to register it because
     the live listing is Vue-rendered, yielding 2 article links where a browser
     sees 31. That was correct about the live page and wrong about the agency:
     the Archive captured the same listing server-rendered, 186 times.
  3. **Energy needed no browser.** It was going to be routed through a headed
     desktop session; it is reachable through the Archive like the others.
- **Rationale:** All three failures share a shape — a negative result from one
  probe generalised into a conclusion about a whole agency. A listing being
  absent from the Archive under one path is not evidence it is absent under
  another, and a live page being unparseable is not evidence the page was
  always unparseable.
- **Status:** Settled — supersedes the `blocked`/`awkward` findings for these
  three in H-47 and H-67.

### H-76 — Energy's page date is a trap, and is ignored

- **Location:** `[sources/us/energy.py:fetch_document()]`
- **Decision:** The Energy adapter never reads a date from the document page.
  `date_source` stays `listing` and is never upgraded to `metadata`, which is
  the opposite of every other adapter.
- **Rationale:** An energy.gov article page carries a `<time>` element showing
  **the current date** — 2026-09-08 on a document published in April. It is a
  "last reviewed" stamp. Read as a publication date it would have stamped the
  entire Energy corpus with the day of the run, and that is a fault that
  arrives looking like data rather than like an error: every document dated,
  every date plausible, every date wrong.
- **Status:** Settled
- **Context:** The general rule elsewhere is that the document page is stronger
  evidence than the index (H-35). Energy is the exception, and the exception is
  in code with the reason attached rather than left for the next reader to
  rediscover by noticing an implausibly tidy date column.

### H-77 — Defense fails the archived route too, and stays unregistered

- **Location:** `[sources/us/defense.py]`, `[sources/us/__init__.py]`,
  `[config/us_agencies.csv]` row `us-defense`
- **Decision:** The Defense adapter was written on the archived-index pattern,
  run, and **not registered**. H-67 stands for a second, independent reason.
- **Rationale:** The archived captures of `/News/Releases/` are the same Vue
  shell as the live page. An April capture holds three `/Article/` links and
  they are Contracts and Transcripts. Across **181 captures the adapter
  enumerates 69 documents and ZERO press releases** — from the page that *is*
  the press-release listing. Registering that would put an agency in the corpus
  represented by 69 advisories and transcripts, dated and plausible and wrong
  about what Defense published.
- **Status:** Settled. Written, not registered; a browser session or a war.gov
  feed remains the only route.
- **Context:** This is the third time the same judgement has been made — Defense
  twice and SBA's 399 disaster notices once — and the rule behind it is worth
  stating plainly: **an agency present with the wrong documents is worse than an
  agency absent**, because absence is visible in a coverage table and wrongness
  is not.

### H-78 — Justice's January is missing from the Archive, not from Justice

- **Location:** `[config/us_agencies.csv]` row `us-justice`
- **Decision:** Justice is collected (713 documents) with January recorded as a
  known hole: 11 documents against 97–139 in every other month.
- **Rationale:** Every one of the 31 archived captures of `justice.gov/news` in
  January was classified: **30 are Akamai interstitials and 1 is content**. The
  Internet Archive's own crawler was being challenged by justice.gov through
  that month, so there is nothing in the Archive to enumerate from. The single
  capture that got through is the source of all 11 January documents.
  February is partial for the same reason (7 interstitials, 21 content); March
  and April are clean.
- **Status:** Settled as a measured gap. It is not fixable from here — it is a
  fact about what the Archive holds — and it must travel with the corpus.
- **Context:** This is the sharpest instance of the H-74 caveat. The route
  cannot say which documents are missing, but here it *can* say **when**, and a
  month-by-month capture classification is cheap enough to be worth running for
  any agency collected this way before its counts are quoted.

### H-79 — A lazy href prefix manufactured twenty 404s

- **Location:** `[sources/us/energy.py:_LINK]`, `[sources/us/justice.py:_LINK]`,
  `[sources/us/nsf.py:_LINK]`
- **Decision:** Link patterns anchor the href to the agency's origin or the
  Archive's replay prefix. A lazy `[^"]*?` before the captured path is
  forbidden in this family of adapters.
- **Rationale:** `href="[^"]*?(/articles/...)"` captures
  `/cio/articles/vulnerability-disclosure-policy` as
  `/articles/vulnerability-disclosure-policy`, which 404s. That accounted for
  **all 20 of Energy's failed fetches** across two runs: documents enumerated,
  counted, requested and lost, with the screening log recording `fetch_failed`
  as though energy.gov were at fault. The same shape was present in the Justice
  and NSF patterns and was fixed before it bit.
- **Status:** Settled
- **Context:** The failure is instructive because the log was honest and still
  misleading. `fetch_failed` was true — the fetch did fail — but it pointed at
  the network rather than at the URL the adapter had invented. A systematic
  count is the tell: twenty failures that recur identically across two runs are
  not a flaky host.

### H-80 — The config's `label_map` overrides the class, and silently

- **Location:** `[harvest_us.py:harvest()]`, `[config/us_agencies.csv]` row
  `us-energy`
- **Decision:** Recorded because it cost a full re-run. `harvest_us.py` passes
  `parse_label_map(row["label_map"])` into every adapter, so the **CSV wins over
  the class attribute**. An adapter whose own `label_map` is correct still
  produces `other` for every document if the config's map disagrees.
- **Rationale:** The Energy adapter emits the source label `Article`. The
  config, written during the survey, mapped the plural `Articles`. All 102
  Energy documents were therefore typed `other` rather than `press_release` —
  a clean run, a full corpus, and the wrong column.
- **Status:** Settled
- **Context:** The override is the right design: it lets a label mapping be
  revised without a code change, which is what H-36 wanted. The hazard is that
  the two can disagree with nothing to notice it. `unknown_labels` already
  reports labels the map had no entry for and is the place a check belongs; a
  label that maps to `other` is not currently distinguishable from one that
  legitimately *is* other.

---

## 9. Harvest — what the ingest gate found

### H-81 — Energy's article bodies are not in the HTML; the adapter is unregistered

- **Location:** `[sources/us/energy.py]`, `[sources/us/__init__.py]`,
  `[config/us_agencies.csv]` row `us-energy`
- **Decision:** The Energy adapter is written, its archived-index enumeration
  works, and it is **not registered**. Its 102 collected documents were removed
  from the corpus and quarantined under `documents/_empty_energy/`.
- **Rationale:** energy.gov article pages are client-rendered. The article prose
  appears in the fetched HTML **only inside `<meta>` tags** — description,
  `og:description`, `twitter:description` — and the single `field--name-body`
  div on the page is a 288-byte sidebar promo. The adapter sliced that promo
  102 times. Every one of the 102 documents contained exactly two words:
  **"Funding Opportunities"**. Median, minimum and maximum word count were all
  2.
- **Status:** Settled. Unregistered until it runs through `BrowserFetcher`,
  which does render energy.gov — headless Chromium returned 190KB for
  `/newsroom` on the project machine.
- **Context:** The enumeration half is sound and stays in the file: 170 archived
  captures yield 102 in-window documents with dates. It is only the body fetch
  that fails, which is why this is a transport problem rather than an adapter
  design problem. Note the trap that made it survive review: the *listing* is
  server-rendered and the *articles* are not, so every signal short of reading a
  document's text said the agency was collectable.

### H-82 — All 713 Justice documents were the same 64 words of navigation

- **Location:** `[sources/us/justice.py:_BODY]`
- **Decision:** Justice's body selector is `node-body`, not `usa-prose`.
- **Rationale:** justice.gov puts `usa-prose` on its **menus** — the main
  navigation at about 7.7KB (`id=doj-menu`) and the news sidebar at about 59KB.
  Neither is an article. Slicing the first match returned 18KB of navigation,
  and all 713 Justice documents came out as the identical 64 words: *"DOJ Menu /
  About / The Attorney General / Organizational Chart / Budget & Performance
  ..."*. After the fix the same 713 documents have **524 distinct word counts**,
  a median of 582, and contribute 1,709 selectable units against zero before.
- **Status:** Fixed, re-harvested and merged.
- **Context:** This was the largest single defect in the corpus and it survived
  every gate that existed: the harvest reported 713 successful collections, the
  screening log showed no exclusions, the 184-test suite passed, and the
  text-fidelity audit passed. **The audit could not catch it**: it refetches a
  document and compares the re-derived text against the stored text, and
  extraction that is consistently wrong matches itself perfectly. An audit that
  asks "is the stored text faithful to what this selector produces?" cannot ask
  "is this selector pointed at the article?".

### H-83 — Word-count variance within an agency is the cheapest defect test there is

- **Location:** to be added to `[harvest_us.py:audit()]`
- **Decision:** Before an agency's output is trusted, check the number of
  DISTINCT word counts across its documents. A healthy agency has nearly as
  many distinct counts as documents; a broken selector produces one.
- **Rationale:** Four body-extraction failures were found this way and none was
  found any other way:

      us-energy    102 documents, 1 distinct word count  (sidebar promo)
      us-justice   713 documents, 1 distinct word count  (navigation menu)
      us-dhs       caught pre-harvest: first of two `field--name-body` divs
      us-hud       caught pre-harvest: first of SIX, five of them theme CSS

  After the fixes the corpus shows 414 distinct counts for State's 810
  documents, 524 for Justice's 713, 263 for SBA's 523, and so on down to 17 of
  17 for SSA. Nothing else in the pipeline distinguishes "every document is the
  same wrong thing" from "every document collected successfully" — the counts,
  the exclusion reasons, the tests and the fidelity audit all read clean in both
  cases.
- **Status:** Settled and implemented. `report_uniformity()` runs at the START
  of `--audit`, before any refetch, and is reported again at the end; a suspect
  agency now makes the audit exit non-zero exactly as welded words do. Verified
  in both directions: the corrected corpus passes all 19 agencies, and the
  quarantined Energy documents are still caught (102 docs, 1 distinct length,
  median 2 words).
- **Context:** It costs nothing: no network, no refetch, one pass over the
  frozen corpus. It should run before `extract`, because the failure it catches
  is the one that otherwise gets discovered by paying a model to read 713 copies
  of a navigation menu.

### H-84 — Ingest rejects undated documents, and they are dropped rather than dated

- **Location:** `[scripts/manifest_from_log.py]`
- **Decision:** A collected document with no date is excluded from the ingest
  manifest and reported as its own category. Ten Energy documents were the
  first case.
- **Rationale:** `eps ingest` refuses a manifest row with no date, because it
  needs one to decide which officeholder was eligible. Dating them was
  attempted and abandoned: `article:published_time` was **identical across
  different articles** (a bulk-import stamp), the first `<time>` on the page
  carries the current date, and the remaining candidates disagreed with the
  displayed date by up to four days. There was no defensible date to assign.
- **Status:** Settled. They remain in the screening log as collected-and-undated
  so the evidence is preserved and the decision is reversible.
- **Context:** The manifest script now prints `dropped, undated` as a named
  line rather than a footnote, because the first version reported the count in
  passing and the ingest then failed on exactly those rows.

### H-85 — Energy's article body is assembled in the browser, and the selector that appeared to work was a sidebar

- **Location:** `[src/eps/sources/us/energy.py]`, `[src/eps/harvest_us.py]`,
  `[config/us_agencies.csv]` (`transport=browser`)
- **Decision:** Energy is collected through `BrowserFetcher` with
  `wait_until="networkidle"`, and its body is `field--name-field-text`. H-81
  unregistered the adapter; this registers it.
- **Rationale:** Two faults were stacked, and each one hid the other.

  The first is that energy.gov assembles the article body client-side. It is
  not in the served HTML, not in a JSON island, not in a feed, and not in the
  Wayback capture — the archived-index pattern that rescued EPA, NSF and
  Justice fails here, because what the archive stored is the same empty shell.
  A browser is not a convenience for this agency; it is the only way the prose
  exists.

  The second is that the adapter did not report zero. It reported 102
  documents, all of which said `Funding Opportunities` — a sidebar promo that
  the body selector happened to match because it was the only thing in the
  served markup that looked like a body. A regex written against a page that
  never contained the target will still match something.

  The container was settled by asking the rendered DOM what wrapped the prose,
  not by pattern-matching more carefully at the markup. Energy now shows 82
  distinct word counts across 88 documents, median 384 (H-83).
- **Status:** Settled and implemented. Registered in `ADAPTERS`.
- **Context:** A third fault surfaced on the way and is worth recording
  separately: the link pattern used a lazy `[^"]*?`, so `/cio/articles/x` was
  captured as `/articles/x` and twenty URLs that no agency ever published were
  requested and logged as `fetch_failed`. The pattern is now anchored, and the
  same anchoring was applied pre-emptively to `justice.py` and `nsf.py`, which
  had the identical shape and had not yet been bitten.

### H-86 — Attribution follows the source's byline, not the document's type

- **Location:** `[src/eps/normalise.py]` (`COUNTRY_SPEAKER_ONLY_TYPES`,
  `SPEAKER_IS_DOCUMENT_EVIDENCE`), `[src/eps/harvest/local.py]`,
  `[src/eps/harvest_us.py]` (`speaker_evidence(..., bylines=...)`)
- **Decision:** `SPEAKER_ONLY_TYPES` is country-aware — the US set is
  `{speech, testimony}`, excluding `statement` — and a document is attributed
  whole to the officeholder only when the **source named them as its author**,
  recorded per document as `speaker_evidence=speaker_is_document`.
- **Rationale:** The two halves of the pipeline disagreed. H-45 had already
  decided the narrower US set for the collector, but ingest applied the UK set,
  so every one of 262 State Press Statements was marked as Rubio speaking —
  including 243 that carried `speaker_evidence=none`, meaning the collector had
  found no trace of him in them at all. Many are the institutional voice: "The
  Department of State will impose visa restrictions...".

  Bringing ingest into line fixed the over-attribution and created a second
  error in the opposite direction, because roughly a third of those statements
  genuinely are the Secretary's. A type rule cannot separate them; a byline
  can. State is the only one of the 24 agencies whose index prints an author as
  a person — "Marco Rubio, Secretary of State" on 19 of a 22-row sample,
  "Thomas 'Tommy' Pigott, Principal Deputy Spokesperson" on 3 — and that is the
  Department's own assertion of authorship, stronger than anything this code
  infers.

  The byline was already being collected into `RawDocument.speaker_hints` and
  thrown away one step before it was needed, which is why `linked_speakers` was
  empty for 260 of 262 State statements: the evidence that decides each case
  existed and was discarded.
- **Status:** Settled and implemented. All 265 State statements now carry a
  byline. Evidence: 147 `speaker_is_document`, 101 `none`, 16 `name_in_body`,
  1 `name_in_title`. Preflight's `EVERY UNIT ATTRIBUTABLE` fell from 270 to
  163, and the 163 that remain are exactly the documents State bylined to the
  Secretary — the flag now reports something true. Selectable units rose from
  19,244 to 21,309, because real Rubio statements returned to the record as the
  institutional ones left it.
- **Context:** Scope-checked across the corpus before the change was accepted:
  270 documents in 3 agencies were affected, no `letter` documents were
  involved, and no other agency prints a per-document author. `speaker_hint`
  alone was deliberately NOT made sufficient — it says who held the office, not
  who wrote the page.

### H-87 — Fourteen documents are duplicates the agencies published themselves, and the manifest drops one of each

- **Location:** `[scripts/dedupe_corpus.py]`,
  `[harvest-code/us-harvest/duplicates.csv]`
- **Decision:** Where two manifest rows have byte-identical text, one is
  dropped from the ingest manifest by a stated ranking rule. Nothing is
  deleted: the documents stay on disk, stay in the screening log, and every
  drop is recorded against the row it duplicates.
- **Rationale:** Each of the fourteen pairs was checked against the live site,
  and the harvest is faithful in every one — the agencies really did publish
  the same words at two URLs:

      alias slug        EPA ran one op-ed under two headlines
      corrected URL     Justice reissued a release, "$160" -> "$135"
      "-0" reissue      SBA's CMS emits a numbered copy on re-publication
      fact sheet        State posts a release and its fact sheet as two

  One is not a republication but the agency's own error: SBA's Minnesota
  release of 2026-01-26 carries the body of its Florida release of 2026-01-16 —
  headline, date and media contact all Minnesota, prose entirely Florida. The
  page still reads that way. It was found by testing every SBA document for a
  state named in the title but absent from the body; only that one failed, and
  the two other candidates named a county rather than a state and were correct.

  Faithful is not the same as correct here. A dataset that counts statements
  would count each of these twice, and the extract stage would pay to read each
  twice.
- **Status:** Settled and implemented. 4,484 manifest rows became 4,470; the
  original is kept at `manifest_us_full.csv.bak`. (The count changed from 4,486
  when H-89 began dropping two bodyless rows upstream of this step.)
- **Context:** Which copy survives is decided in order: a typed document beats
  one typed `other`; then the URL slug that matches the title; then the earlier
  date; then the shorter URL; then the URL itself, so reruns agree. Rule two is
  skipped where any slug in the group is opaque — `press-releases/sb0394` can
  never agree with a title, and would otherwise lose to a wordy re-post of
  itself. That is the Treasury pair, and the official press-release number is
  the copy worth keeping.

### H-88 — The officeholder check tests whether two names overlap in time, not how many there are

- **Location:** `[scripts/preflight_corpus.py]`
- **Decision:** `MANY SPEAKERS` is replaced by `OVERLAPPING SPEAKERS`. Names
  are split on `;`, each name's date range is computed from the documents, and
  the corpus is flagged only when two ranges share more than one day. Clean
  handovers are printed, not flagged.
- **Rationale:** The old check flagged any agency with more than two distinct
  `speaker_hint` strings, and it fired on DHS and Justice, where nothing was
  wrong. Both had a documented mid-window handover (H-43), and the handover day
  itself is recorded as "Kristi Noem; Markwayne Mullin" on one row — a third
  string, not a third officeholder.

  Counting was the wrong test in both directions. A second handover inside one
  window is normal and would have been flagged; a genuinely bad join that
  credits two people with one office across the same months produces no extra
  names at all and would have passed. Overlap is what actually distinguishes
  them, and one day of tolerance covers the handover date appearing on both
  sides.
- **Status:** Settled and implemented. The three US transitions — Noem to
  Mullin, Bondi to Blanche, Chavez-DeRemer to Sonderling — now report as
  handovers and the check is silent.
- **Context:** A check that cries wolf is worse than no check: this one had
  been read past twice as "the known DHS/Justice thing" before it was fixed,
  which is precisely how a real join fault would have got through.

### H-89 — A document with no sentence in it is not a document

- **Location:** `[scripts/manifest_from_log.py]`
- **Decision:** A collected row whose text contains no sentence-ending
  punctuation anywhere is dropped from the ingest manifest and reported on its
  own line, beside the undated drop of H-84.
- **Rationale:** Two rows passed every check above them and carried no document:
  an Energy release whose entire body was its own subheadline, and an SBA
  testimony published only as a PDF, whose page body was a list of programme
  tags and the word "Download.PDF". Both would have been sent to the model,
  which would have found nothing and charged for looking.
- **Status:** Settled and implemented. It matches exactly those two across the
  4,496 collected documents, and nothing else.
- **Context:** Length cannot do this job, and trying it would have been costly.
  State's call readouts are 33 words and are real published statements; the two
  stubs are 10 and 12 words. Any word threshold high enough to catch the stubs
  throws away eleven genuine documents. The sentence test separates them
  exactly, because the distinction is prose versus not-prose, not long versus
  short. The full chain is now 4,496 collected -> 10 undated (H-84) -> 2
  bodyless -> 4,484 -> 14 duplicates (H-87) -> **4,470 ingested**.

### H-90 — "Privacy policy" is a department, not a cookie banner

- **Location:** `[scripts/preflight_corpus.py]` (`CHROME`)
- **Decision:** The `CHROME IN BODY` pattern no longer matches a bare "cookie"
  or "privacy policy". It matches consent-banner wording specifically: "accept
  cookies", "this site uses cookies", "cookie policy/preferences/settings".
- **Rationale:** The old pattern flagged eight Education releases that are
  entirely genuine prose, for the plain reason that Education's Student Privacy
  Policy Office is the SUBJECT of them — it investigates school districts under
  FERPA, and says so in its first sentence. The words that indicate navigation
  reached the corpus are narrower than the words that indicate privacy is being
  discussed.
- **Status:** Settled and implemented. `CHROME IN BODY` is now silent on the
  corpus; the one genuine hit it had found, an SBA PDF stub, is dropped by H-89
  instead.
- **Context:** Same lesson as H-88, in a different check, found the same way:
  by reading the documents a check had flagged instead of trusting the flag.
  Preflight now reports 2 classes rather than 5, and both that remain — 163
  State documents State itself bylined to the Secretary (H-86), and 11 genuine
  short call readouts — are reviewed and expected.

### H-91 — The UK corpus lost its quote structure, and nothing downstream noticed

- **Location:** `[harvest-code/uk-harvest/audit_text_fidelity.py]`,
  `[src/eps/normalise.py:mark_attribution()]`
- **Decision:** No UK extraction runs against `uk-harvest/documents/`. The text
  the pipeline reads must be the re-rendered `documents_v2/` output, which
  preserves `<blockquote>` as a `> ` prefix.
- **Rationale:** GOV.UK marks a ministerial quotation with `<blockquote>` and no
  quotation marks, and `mark_attribution()`'s colon-frame rule (I-09) needs
  exactly that structure: a frame paragraph ending in `:` immediately above a
  `> ` block. The original extraction flattened blockquotes into ordinary
  paragraphs. Of 2,455 collected UK documents, **one** carries a quote marker.

  The effect is total and silent. Measured over the same 719 press releases in
  both renderings:

      documents/      719 press releases,     0 attributable units,   0 documents
      documents_v2/   719 press releases, 2,250 attributable units, 556 documents

  A UK extract on the old text would have returned nothing from two thirds of
  the corpus, with clean logs, passing tests, a fidelity audit that compares
  words and finds them, and a corpus of exactly the expected size.
- **Status:** Settled and implemented. All 2,455 collected documents were
  re-rendered from the Content API into `documents_v2/`, 0 failed; 1,284 carry
  quote blocks. `queue_to_manifest.py --rewrite-log` now takes every path from
  the rewriter's own record and drops, by name, any URL it did not write, so the
  old folder cannot be reached by accident. The re-render also exposed a filename
  collision: FCDO's UK-France and UK-Spain joint statements on wildfires truncate
  to one filename, so the original harvest kept one and pointed both rows at it.
  The second claimant now gets a URL-derived suffix. One document, the military
  division of the King's Birthday Honours list, is a list of names with no
  sentence in it and is dropped under H-89's rule.
- **Context:** This is H-83's lesson somewhere H-83 cannot reach. Word-count
  variance is healthy in both renderings and the words themselves are nearly all
  present, so every check that counts or compares text passes. What was lost was
  structure. The only thing that surfaced it was asking how many units the
  attribution rule actually marks — which is worth doing to any corpus before
  paying to read it, and is now the reason the US corpus was checked the same
  way (21,307 selectable units across 4,470 documents).

### H-92 — A GOV.UK "letter" is a page about a letter, and none of the 317 contain one

- **Location:** `[harvest-code/uk-harvest/manifest_uk_full.csv]` (built with
  `--doc-type press_release --doc-type speech --doc-type statement --doc-type op_ed`)
- **Decision:** The 317 UK documents typed `letter` are excluded from the UK
  corpus, and their attachments are not collected.
- **Rationale:** GOV.UK publishes a ministerial letter as a publication page
  whose HTML body is a summary written by the department — "Please see the
  attached update", "The Minister of State for Housing and Planning has written
  to the Planning Inspectorate..." — with the letter itself as an attachment.
  Tested for a salutation or sign-off, **0 of 317** contain the letter. The
  median body is 48 words and 202 are under 60.

  Because `letter` was a whole-document type, every word of those summaries was
  marked as the minister's own: 1,865 units that are the department describing
  a document, credited to the person who signed it. The same stubs produced the
  corpus's only UK "duplicates" — five monthly Timms Review updates and six
  Home Office circulars share identical boilerplate — which is why deduplication
  was not applied to them: the documents differ, only the pages describing them
  do not.
- **Status:** Settled by the PI: letters stay out. Ministerial letters are
  mostly procedural — remit letters, appointment notices, circulars, replies to
  committees — and rarely carry the policy content the corpus is for, so
  recovering them is not worth the effort. For the record, recovery was
  feasible: a sample of 40 through the Content API found an attachment on every
  one (24 PDF, 16 HTML), and 22 of the 40 had two or more — letter and annex, or
  both halves of an exchange, which could not be whole-document attributed.
- **Context:** The old text did not contain the letters either; the original
  harvest's files were longer only by their five-line header.

### H-93 — A UK document is wholly the minister's only when GOV.UK says it is

- **Location:** `[src/eps/normalise.py]` (`COUNTRY_SPEAKER_ONLY_TYPES["UK"]`),
  `[harvest-code/uk-harvest/queue_to_manifest.py]` (`notes`)
- **Decision:** H-86's rule, applied to the UK. The UK type set is empty. The
  manifest's `notes` is `speaker_is_document` only when the harvester's
  `speaker_match` is `linked` — GOV.UK's own page names the expected
  officeholder as its speaker — AND the type is one that can be wholly one
  person's words. A press release linked to a minister is about their
  announcement, not their words, and is never whole-document.
- **Rationale:** H-86 stated "the UK is untouched", and it was — which is the
  problem this corrects. Measured against GOV.UK's speaker link, whole-document
  attribution by type credited the wrong person three times in four:

      speech      433   delivered by the officeholder  73   credited anyway  360
      statement    73                                   48                    25
      op_ed         1                                    0                     1

  The 360 speeches are junior ministers, ambassadors at the UN Security Council
  and the Human Rights Council, officials, and FCDO statements with no named
  speaker; the op-ed is the Chief Medical Officer's. Every word of each would
  have been attributed to a Secretary of State.
- **Status:** Settled and implemented. UK selectable units fell from 27,295 to
  15,115; what remains is 75 speeches and 48 statements GOV.UK tags to the
  officeholder, plus 2,493 framed quotations in 627 press releases.
- **Context:** The harvester already computed this verdict and wrote it to the
  screening log; it was simply not carried into the manifest. The provider
  tests built a UK speech with no verdict and started failing, correctly; their
  fixture now carries `speaker_is_document`, which is what it stands for.

### H-94 — US speeches are decided per document, and transcripts line by line

- **Location:** `[src/eps/normalise.py]` (`COUNTRY_SPEAKER_ONLY_TYPES["US"]`,
  `_mark_transcript()`), `[scripts/manifest_from_log.py:document_verdict()]`
- **Decision:** The US type set is empty too. For speeches, testimony and
  interview transcripts the manifest re-decides the collector's verdict:

      2+ distinct speaker labels            -> transcript     (line by line)
      "As Delivered By: <someone else>"     -> other_speaker
      officeholder named 2+ times in prose  -> name_in_body   (a release about them)
      title / byline names the officeholder -> speaker_is_document
      otherwise                             -> other_speaker

  A transcript is attributed by its labels: a paragraph belongs to whoever was
  last labelled, and is attributable only under a label naming the eligible
  officeholder. The label is trimmed from the unit, as the blockquote marker is.
- **Rationale:** The collector granted `speaker_is_document` to every speech and
  testimony by type. Of 110, 18 were delivered by someone else — Associate,
  Assistant and Deputy Assistant Attorneys General credited to the Attorney
  General, a Deputy Secretary of State credited to Rubio — and 49 were
  transcripts in which reporters, Secretary Hegseth, Prime Minister Fico and
  Senate chairs speak, all credited to the Secretary. Among them was a press
  release typed as testimony, and a speech written by Secretary Bessent but
  delivered by an Under Secretary.
- **Status:** Settled and implemented. Speeches: 29 whole, 49 transcripts, 15
  other speaker, 2 releases about the officeholder. Two transcripts correctly
  yield nothing — they are the Deputy Secretary's and the Counselor's. Spot-read
  on interviews: every question is excluded and every answer kept. US selectable
  units fell from 21,307 to 15,347.
- **Context:** Each rule was set by reading the documents it caught, not tuned
  to a count. The prose-mention rule was checked against every candidate: the
  one release it catches names its subject 13 times, and no genuine speech in
  the corpus names its own speaker more than once. The three pre-existing test
  failures are untouched by this and remain: they expect inline-quote
  attribution in a paragraph, which the colon-frame rule deliberately does not do.

### H-95 — A document with nothing selectable is not sent to the model

- **Location:** `[src/eps/cli.py:cmd_extract()]`
- **Decision:** `extract` skips any document with no attributable unit, and its
  closing line reports skipped and failed documents by count.
- **Rationale:** Every line of such a document is marked "not selectable", and
  validation rejects any observation built from a non-attributable unit, so no
  response could reach the dataset. That was 4,526 of 6,607 documents — about
  two thirds of the running time and half the selection cost, for identical
  results. The failed count exists because a per-document exception is recorded
  as "no candidates" so that one bad page cannot stop a long run; without the
  count, a bad key or a rate limit produces a run that looks finished.
- **Status:** Settled and implemented. Verified with a stand-in model on both
  pilots (4 and 3 skipped, 0 failed) and then in the real pilot run.

### H-96 — A retyped anchor is matched without regard to typography or case

- **Location:** `[src/eps/validate.py:reconstruct_quote()]`
- **Decision:** When the model's anchor phrase is not found exactly, the search
  is repeated on a length-preserving folded copy — curly quotes and dashes
  straightened, non-breaking spaces made plain, case ignored — and the quote is
  still sliced from the original text.
- **Rationale:** The model retypes anchors rather than copying them. In the
  pilot, 7 of 160 selections were rejected as "anchor phrase does not appear
  exactly": six were a curly apostrophe typed straight, one a capital letter
  added at the start. Each was the right passage. All seven are recovered and
  all seven quotes remain exact substrings of their documents.
- **Status:** Settled and implemented, with a regression test. A changed word
  still fails (`test_anchor_must_match_exactly`), so the rule forgives typing,
  not paraphrase.

### H-97 — The JEL code list is a cached system prefix, not a trailer on every quote

- **Location:** `[src/eps/extract.py:Extractor.classify()]`,
  `[src/eps/providers.py:AnthropicProvider]`, `[src/eps/cli.py:cmd_extract()]`
- **Decision:** The active JEL code list is part of the classification system
  prompt, built once per run, sent as a content block with
  `cache_control: ephemeral`. The user message carries only the quotation. The
  provider records the API's own token counts, and `extract` ends by printing
  cache writes, cache reads and the run's cost.
- **Rationale:** The pilot showed about 4,000 quotations to classify across the
  two corpora, and each call carried the 30KB list — about 8,300 tokens — at full
  price: roughly $100 of an estimated $125 extract. The list sat in the user
  message AFTER the quotation, and a cache is a prefix match, so it could never
  have been read back. An older direct-client path that claimed to cache it
  cached only the short instructions, was not reachable from the command line,
  and swallowed every exception from the API; it is removed.
- **Status:** Settled and implemented, with a regression test asserting an
  identical cached system block across calls and no list in the user message.
  Projected full-run cost falls to about $40. Verified on the real API by the
  check run: the closing `cache read` figure must dwarf `cache write`.
- **Context:** Caching fails silently — a broken prefix raises nothing and
  simply bills more — which is why the usage line exists and why the test pins
  the layout rather than the outcome.

### H-98 — Selection requires economic substance at the centre of the claim

- **Location:** `[src/eps/extract.py:EXTRACT_SYSTEM]` (`PROMPT_VERSION = "P7-units-blind"`)
- **Decision:** On the PI's instruction, a passage qualifies only if the
  speaker states their own policy position AND its economic substance is central:
  public money, prices, wages, employment, trade, sanctions on goods and finance,
  investment, regulation of firms and markets, housing or energy supply, the
  funding or provision of public services, migration rules governing work,
  settlement or public support, or measurable economic outcomes. Explicitly
  excluded, unless the claim is about money, markets or provision: criminal law,
  policing and counter-terrorism; security, conflict and diplomacy; online-safety
  and child-protection rules; clinical public-health measures; curriculum content;
  statements of fact; slogans. Selections must read as complete statements, not
  bare fragments. "When in doubt, leave it out."
- **Rationale:** Under P6, roughly 10–15% of pilot quotations were policy but not
  economics — Prevent training, bans on ninja swords, a new criminal offence, the
  Sudan arms embargo, a rule against strangers messaging children in games — and
  were forced into codes like K4 or D7. Each added classification cost and noise.
  A few selections were fragments without a subject ("maintain American
  leadership in low Earth orbit").
- **Status:** Superseded by H-99 before it was ever run. It defined economics
  by subject matter, and that is the wrong test for this project.
- **Context:** The exclusions carry their own exceptions on purpose, so that
  the pilot's clearly economic content survives: sanctions on Russian oil,
  foreign-aid budgets, settlement and asylum-support rules, NHS funding, school
  funding and structure.

### H-99 — A passage qualifies if economics research could produce evidence about it

- **Location:** `[src/eps/extract.py:EXTRACT_SYSTEM, JEL_SYSTEM]`
  (`PROMPT_VERSION = "P8-units-blind"`)
- **Decision:** Selection applies three tests. (1) A policy choice: the speaker
  states their own government's position, decision, proposal, commitment,
  target, design choice or causal belief, and there is a lever. (2) Researchable
  by economists: the passage can be turned into a one-line question an applied
  economist could answer with evidence — effects, costs and benefits, incentives,
  distribution, or design. (3) Substantive and self-contained. The model writes
  that research question as its `reason`, so every selected passage carries its
  justification into `observations_internal.csv`. Exclusions are defined by what
  is missing, not by subject: nothing chosen (ceremony, readouts, facts, process
  and timing announcements, appointments); no lever (slogans, condemnation,
  demands of others, criticism without an alternative); a matter economics would
  not inform (military operations, individual court outcomes, threat levels,
  commemorations, procedure); not the speaker; a fragment. The classifier is told
  the same thing: applied fields are economics, and a crime, health, schooling,
  migration, platform, defence, aid or conflict policy belongs in its applied
  code (K42, I18, I21, F22, L86, H56, F35, D74) rather than a catch-all.
- **Rationale:** The study this corpus serves compares what policymakers value
  with what economists produce, benchmarked against government Areas of Research
  Interest and learning agendas. There, economics is a discipline relevant to a
  question, not a subject heading: 96% of surveyed policymakers — spanning health
  and wellbeing to tax — report economics research as relevant to their work, and
  28% of UK ARI questions relate to economics under the OECD Fields of Science
  taxonomy. P7 (H-98) would have excluded a ban on social media for under-16s, a
  restriction on online knife sales, vaccine eligibility rules and a
  digital-literacy curriculum, all of which have active economics literatures and
  are exactly the kind of priority an ARI poses. The test that separates wheat
  from chaff is not "is this about money" but "is a policy being chosen that
  evidence could inform". Framing it as a research question also mirrors the ARI
  data the statements will be compared with. The classifier prompt previously said
  "a statement is not economic merely because an economist could study it",
  which contradicted this and has been removed.
- **Status:** Settled pending the P8 check run on the 54 pilot documents, to be
  compared against the P6 pilot.
- **Context:** The filter should match whatever rule decided which ARI and
  learning-agenda questions were economics-relevant for the website. If the two
  rules differ, any comparison between what governments ask for and what
  ministers say will partly measure the difference between the filters.

### H-100 — The detail is the policy, and the question must fit the quoted words

- **Location:** `[src/eps/extract.py:EXTRACT_SYSTEM]` (`PROMPT_VERSION = "P9-units-blind"`)
- **Decision:** Two additions to H-99. (1) Eligibility conditions, named
  instruments and mechanisms, scope and coverage, causal claims about what a
  specific policy has done or will do, and stated choices between alternatives
  each qualify in their own right, even when they elaborate a headline already
  selected; a list of conditions defining one policy is one observation, taken
  whole. (2) The one-line research question must be about what the selected
  words state; where they only praise a policy or name a goal, the model selects
  the words describing the policy, or nothing.
- **Rationale:** Comparing the P8 check with the P6 pilot passage by passage, P8
  removed the chaff it was meant to — rhetoric, self-praise, statistics, process
  announcements, fragments — and kept non-financial economics, but lost 8–10
  concrete policy details inside itemised passages: the Home Secretary's
  settlement conditions, asylum-accommodation eligibility, "an advanced market
  commitment to quantum", the Digital Sovereign Bond, and causal claims about a
  policy's effects. Those are what an Area of Research Interest asks about. It
  also kept a few praise quotes ("making defence an engine for jobs and growth")
  whose research question described a programme mentioned elsewhere in the press
  release rather than anything the quote said. JEL primary sub-category agreement
  between P6 and P8 on matched quotes was 79%, with most changes following H-99's
  applied-field instruction.
- **Status:** Settled; P9 is the prompt for the full run. The check recovered
  every P8 loss (settlement conditions, asylum-accommodation eligibility, the
  quantum commitment, the Digital Sovereign Bond, the pension-fund causal claim,
  the buy-to-let choice, the scope of the social media ban) and dropped the praise
  quotes. Because those passages are quoted in the prompt, that is not evidence of
  generalisation by itself. The evidence is elsewhere: on pilot documents P9 also
  added unquoted details of the same kind (the Decent Homes Standard, tightening
  domestic law on removals, a strengthened passenger watchdog), and on the 29
  holdout documents it kept 49 quotes, of which about 45 are clear policy choices
  (the HUD work requirements and time limits, the end of CDBG, the Pension Credit
  take-up campaign and the rejected flat-rate WASPI scheme, Workforce Pell, the
  SEND reforms). Chaff that survived: two praise quotes whose research question
  describes the press release's policy (hydrogen investment, the Scotch whisky
  tariff), one military deployment, and one piece of GCSE rationale — about 8%.
  Seven of the eight holdout documents with selectable text and no quotes were
  correct: their officeholder quotes are praise or a condolence. One is a likely
  loss (Interior's position that offshore wind is "subsidy-dependent"). JEL primary
  sub-category agreement with P8 on matched quotes was 92%. Validation rejected 7
  of 189 selections: three picks of non-attributable units, one anchor mismatch,
  and three the classifier found no economic object in (faster asylum appeals,
  chatbot functionality, Treasury guidance to child-welfare agencies), which the
  selection stage had judged researchable.
- **Context:** P8 and P9 both use examples drawn from the pilot documents, so a
  rerun on the pilot alone would partly measure the model finding passages the
  prompt quoted to it. The P9 check therefore adds a holdout of 29 documents never
  used in writing the prompt (14 US from 12 agencies, 15 UK from 12 departments),
  listed in `runs/check9-*/holdout_ids.pkl`; generalisation is judged on those,
  and on pilot passages the prompt does not quote.

### H-101 — Running out of credit stops the run, and the same command resumes it

- **Location:** `[src/eps/providers.py:stop_reason(), ProviderStopped]`,
  `[src/eps/cli.py:cmd_extract(), cmd_build()]`, `[tests/test_resume.py]`
- **Decision:** An API error that no further request on the key can succeed past
  — out of credit, a spend limit reached, a billing error, a rejected key or one
  lacking permission — raises `ProviderStopped`, and `extract` stops at once. The
  document being processed is left unrecorded so the next run does it again;
  everything else is saved. `extract` writes `extract_status.json` as incomplete
  before its first call and rewrites it at the end with whether the run is
  complete, why it stopped, and which documents remain or failed. `build` refuses
  to run on an incomplete extract unless given `--allow-incomplete`. The SDK's
  retries for transient errors (rate limits, 5xx, overloaded) are raised from 2
  to 8 for long runs. Exit codes: 0 complete, 2 finished with document failures,
  3 stopped.
- **Rationale:** The credit balance may not cover the full run. Before this, an
  exhausted balance would have made every remaining document fail in turn — each
  caught, recorded as "no quotes", and counted — so the run would have finished
  with thousands of failures and an `extractions.pkl` indistinguishable in shape
  from a complete one, and `build` would have written a dataset from it.
  Resumption needed no new mechanism: every response is already cached under a
  hash of its inputs, so a re-run replays paid work for free and calls the API
  only for what is missing. What was missing was stopping cleanly and refusing to
  treat the partial result as final.
- **Status:** Settled and implemented. Tested with a simulated credit failure
  partway through a document: the run stops after the failing call, `build`
  refuses, and the resumed run makes exactly the calls that were never answered
  (3 of 6), then builds. A run killed outright is never reported complete. Out of
  credit is recognised by error type and status and also by message, because it
  has been reported as a plain 400 `invalid_request_error` ("Your credit balance
  is too low"), as has a workspace spend limit; a rate limit, a server error or
  an ordinary bad request does not stop the run.
- **Context:** Ctrl+C is handled the same way as running out of credit. Closing
  the window kills the process before it can write anything, but responses
  already received are in the cache and the status file still says incomplete,
  so the same command resumes.

---

## 10. Quote fidelity and the Codex route

### H-102 — The blockquote marker is stripped on every attribution path

- **Location:** `[src/eps/normalise.py:mark_attribution(), strip_quote_markers()]`,
  `[tests/test_markers.py]`
- **Decision:** After attribution is decided, a final pass removes the
  renderer's `> ` from the opening unit of every paragraph that still starts
  with it. It changes text and `char_start` only, by the marker's two
  characters; `attributable`, unit IDs and `char_end` are untouched, and a unit
  an earlier path already trimmed is left alone so nothing is stripped twice.
  `SEGMENTER_VERSION` moves from `seg-1.0.0` to `seg-1.0.1`.
- **Rationale:** The quote-block path always trimmed the marker, but the
  speaker-only, `speaker_is_document` and transcript paths returned before it
  did. A released `direct_quote` could therefore open with two characters the
  agency never published, breaking the guide's verbatim requirement.
- **Status:** Settled and implemented (QUOTE_FIDELITY_BRIEF_v1, deliverables
  A–C). Re-ingesting all 6,607 documents of the full UK and US manifests before
  and after: exactly 123 units changed (42 UK, 81 US), every one on the
  pre-fix inventory and each differing only by the removed marker; document,
  unit and attributable counts (30,462) are identical; offsets still satisfy
  `doc.text[char_start:char_end] == unit.text` for every unit. Released damage
  was 4 quotes, all in `runs/trial-context-latest`; no other run's output
  carries the marker. Deliverables D–F of that brief are not done.
- **Context:** Existing runs hold `documents.pkl` files built before the fix.
  Re-ingesting them changes the select-call input for the affected documents
  (1 in jul2026-uk, 6 in jul2026-us, 8 in uk-full, 45 in us-full), so those
  calls would no longer replay from the cache. Only `trial-context-latest`
  needs re-running for correctness.

### H-103 — A `>` inside a GOV.UK paragraph is the publisher's, and stays

- **Location:** `[src/eps/normalise.py:strip_quote_markers()]`
- **Decision:** Only a `> ` opening a paragraph is treated as our marker. Ten
  UK units in five GOV.UK press releases carry `>` mid-paragraph (for example
  `Bridget Phillipson said: > > Nothing matters more…`); they are left as
  published.
- **Rationale:** Both renderers (`sources/blocks.py:render()` and the UK
  rewriter) write the marker at the start of a quote block and nowhere else,
  so a `>` elsewhere came from the source page, apparently malformed GOV.UK
  markup. Removing it would be editing the publisher's text on a guess.
- **Status:** Settled for now. None of the ten units is attributable, so none
  can reach the dataset under current rules.

### H-104 — A document's ID depends on its bytes as they sit on this machine

- **Location:** `[src/eps/normalise.py:make_doc_id()]`,
  `[src/eps/harvest/local.py:ingest_row()]`
- **Decision:** The bundle ships the harvested text files exactly as they are
  in this working tree (CRLF line endings), never re-exported from git.
- **Rationale:** `doc_id` hashes the URL with the raw file bytes. With
  `core.autocrlf=true` git stores the files with LF and checks them out with
  CRLF; every stored `doc_id` (6,607 of 6,607) matches the CRLF bytes and
  almost none match LF. A bundle built from LF bytes would give every document
  a new ID, and every unit ID with it. Ingest is otherwise deterministic:
  re-ingesting all four manifests reproduced every stored doc ID, unit ID,
  unit text and attribution flag.
- **Status:** Settled. The bundle's checksum file and reference ID list catch
  any change in transit.

### H-105 — Extraction can run through the Codex CLI on someone else's computer

- **Location:** `[src/eps/providers.py:CodexCLIProvider, run_command()]`,
  `[tests/test_codex_provider.py]`
- **Decision:** A provider that runs `codex exec` as a subprocess under the
  user's own ChatGPT sign-in, with no API key. Each call runs from an empty
  working folder (so no `AGENTS.md` is read), passes the extraction prompt as
  Codex's replacement instructions (`model_instructions_file`) and the document
  on stdin, and switches off shell, web search, multi-agent tools and app
  connectors, with a read-only sandbox and no saved session. Approval-bypass
  and write-enabled sandbox flags are never used. On timeout the whole process
  tree is killed. The Anthropic and Mistral providers are unchanged.
- **Rationale:** The PI can run the extraction on her own subscription. The
  prompt, parsing, validation and assembly are untouched, so the only thing
  that differs between routes is which model answered, and that is recorded.
- **Status:** Implemented and tested with the subprocess mocked; no real Codex
  call has been made. Flags were checked against OpenAI's documentation, not a
  local install. Codex's exit codes and usage-limit message are undocumented:
  a failure is classed `usage_limit` when its message contains "usage limit",
  which is unverified, and anything unrecognised is recorded as `cli_error`.

### H-106 — Two output schemas, one per kind of call

- **Location:** `[src/eps/cli_schemas.py]`
- **Decision:** Extraction makes two kinds of call with different answers, so
  there are two strict JSON Schemas: `select` (`observations` of `unit_ids`,
  `anchor`, `reason`) and `classify` (`mechanism`, `codes` of `code` and
  `strength` 1–3). Each mirrors exactly what `extract.py` parses, lists every
  property as required (`anchor` is nullable) and forbids extra properties.
  The provider picks the schema from the system prompt, which is fixed text;
  any other prompt is refused.
- **Rationale:** OpenAI's strict structured output needs a schema matching the
  answer exactly, and one schema cannot describe both shapes without making
  every answer ambiguous. A schema-enforced answer also removes the free-text
  failures seen in earlier runs (a JSON object followed by "Wait, …").
- **Status:** Settled. All 4,690 stored select and classify responses from
  earlier Anthropic runs conform. Answers are validated again on return.

### H-107 — A failed call is recorded by name, never as an empty document

- **Location:** `[src/eps/providers.py:CLI_FAILURES, CLICallFailed,
  CLIProviderStopped]`
- **Decision:** Seven failure classes: `auth_failure`, `usage_limit`,
  `timeout`, `cli_error`, `unparseable_output`, `schema_mismatch`,
  `empty_output`. Sign-in and usage-limit failures stop the run like running
  out of credit (H-101); a missing `codex` executable does too. The rest are
  per-call failures. Every call is logged with tool and version, model,
  effort, call kind, prompt version and fingerprint, schema hash, exit code,
  duration and failure class.
- **Rationale:** A document that failed and one in which nothing qualified
  both produce no observations; only the name tells them apart.
- **Status:** Settled and implemented.

### H-108 — The person running the bundle chooses the model and effort

- **Location:** `[src/eps/providers.py:CodexCLIProvider.__init__]`, the
  bundle's `run_extract.py` and README
- **Decision:** The Codex provider has no default model or reasoning effort.
  The README asks the recipient to choose both before running; the runner
  requires them and stops at once, before any call, if either is missing.
  Both are recorded on every call. Because the response cache is keyed on
  provider and model but not effort, the runner refuses to resume a run with
  different settings rather than mixing two configurations in one dataset.
- **Rationale:** The recipients know their own subscription and its limits;
  a default chosen here could exhaust their usage or under-use it.
- **Status:** Settled. `eps extract --provider codex` fails at construction
  for want of an effort, so the runner is the only way in.

### H-109 — The Codex bundle is a separate, Codex-native variant of the pipeline

- **Location:** branch `codex-native`, tags `codex-bundle-v1` to
  `codex-bundle-v4`; `[bundle/]`, `[tools/build_bundle.py]`,
  `[src/eps/providers.py:CodexCLIProvider]`, `[src/eps/cli_schemas.py]`
- **Decision:** The bundle runs both extract and build on the recipient's
  computer, with every model call (select, classify, context triage and
  resolve, intention) answered by the OpenAI model they choose through their
  own Codex sign-in. It is a variant for running the pipeline elsewhere, not
  the main pipeline. The main route (`eps extract`, `eps context`, `eps build`
  on Anthropic models) is unchanged and remains the reference.
- **Rationale:** The PIs can run the whole job on their own subscription by
  attaching one file to a Codex chat, with nothing to install but Python and
  Codex. Keeping it as a distinct, labelled variant stops a dataset built this
  way from being mistaken for one built on the reference route.
- **Status:** Settled. Every row records its provider and model, so the route
  that produced a dataset is visible in the data. A dataset built through the
  bundle is **not directly comparable** with one built on Claude: the context
  and intention stages, as well as extraction, ran on a different model.
  Comparing the two routes on the same documents would be a robustness check
  in its own right.

### H-110 — Three more output schemas, for the build-stage prompts

- **Location:** `[src/eps/cli_schemas.py:TRIAGE_SCHEMA, RESOLVE_SCHEMA,
  INTENTION_SCHEMA, LIST_KINDS]`
- **Decision:** The Codex provider serves all five of the pipeline's prompts.
  Context triage and resolve ask for a JSON list, but strict structured output
  must be an object at the top level, so their schemas wrap the list as
  `{"items": [...]}` and the provider hands `context.py` the bare list. The
  intention schema mirrors the prompt's eleven fields; nullable fields are
  required but may be null. Labels are plain strings, not enums, so the
  stages' own validators judge them exactly as they do for any provider.
  Prompt text and stage code are unchanged.
- **Rationale:** Same principle as H-106: each schema matches exactly what its
  caller parses, so the provider changes nothing downstream.
- **Status:** Settled. Stored responses from earlier Anthropic runs: all 741
  intention and 40 triage responses conform; 174 of 204 resolve responses do.
  The rest predate resolve prompt v2's `position` field, or carry a null
  `note`, which is now allowed because `context.py` already accepts it.

### H-111 — A usage limit inside the build is read from the call log

- **Location:** `[bundle/run_pipeline.py:build_one()]`
- **Decision:** After the context stage and after intention tagging, the
  runner checks its providers' call logs for a sign-in or usage-limit
  failure. If it finds one, it reports the build as stopped, writes no
  `build_status.json`, and asks for the same command to be run again.
- **Rationale:** Neither stage lets a stop escape. `context.py` catches every
  error around its calls and records the batch as a parse failure;
  `intention.py` records the remaining quotes as `provider_error`. Left alone,
  a usage limit mid-build would produce a finished-looking dataset with
  thousands of failed rows. Every successful answer is cached, so the re-run
  replays them and calls only for what failed.
- **Status:** Settled and tested. The same swallowing affects `eps context`
  on the main route when credit runs out; it is not fixed there.

### H-112 — Settings lock only once a document has succeeded

- **Location:** `[bundle/run_pipeline.py:check_settings()]`
- **Decision:** Amends H-108. The model and effort are recorded at the first
  run, but a later run with different settings is refused only once at least
  one document has completed. Until then, the new settings replace the old.
- **Rationale:** A first attempt with a model the account cannot use fails
  every call and stops after five documents. Locking at that point would trap
  the run on a model that cannot work. With nothing completed there is nothing
  to mix, so changing is safe.
- **Status:** Settled and tested.

### H-113 — A Codex chat sets the bundle up from an instructions file

- **Location:** `[bundle/INSTRUCTIONS_FOR_CODEX.md]` (also shipped as
  `AGENTS.md`), `[bundle/README.md]`
- **Decision:** The recipient attaches `eps-bundle.zip` to a Codex chat and
  sends one fixed message. Codex follows the instructions file: it unpacks the
  bundle, checks Python, creates the environment, runs `--check`, asks for the
  model and effort, opens the run in its own terminal window, and handles
  restarts and the final zip. The instructions forbid changing the bundle,
  running the real run inside Codex's own sandbox, or using any option other
  than `--workers`. The by-hand copy-and-paste steps remain in the README.
- **Rationale:** The run makes thousands of Codex calls over many hours and
  needs the network and the user's sign-in, which a chat's sandbox blocks and
  its command timeouts would cut short. So the chat does the set-up and
  launches the run outside itself. The calls inside the run use an empty
  folder with project documents switched off, so they never read `AGENTS.md`.
- **Status:** Untested with a real Codex. OpenAI's documentation does not say
  what happens to a file attached to a chat, so the message also tells Codex
  to look in Downloads.

### H-114 — Several Codex calls run at once (`--workers`, default 4)

- **Location:** `[bundle/run_pipeline.py:WorkerPool, extract_all(),
  tag_intentions_in_parallel()]`, `[src/eps/providers.py:kill_running()]`
- **Decision:** Extraction runs documents on a pool of workers, each with its
  own Codex provider and empty working folder. Only the main thread writes
  result files. Before the build, the kept quotes' intentions are requested on
  the pool through the same `IntentionTagger.tag_one()`, so the sequential
  build finds every answer in the response cache. The context stage stays
  sequential (a few hundred calls). Ctrl+C kills every running Codex process.
- **Rationale:** About 5,000 to 6,000 sequential calls would take days. Four
  at a time cuts the extraction and intention time roughly fourfold, with the
  same total usage; it only reaches a plan's limits sooner, which
  `--workers 2` or `--workers 1` eases.
- **Status:** Settled and tested. On the full bundle with the fake provider,
  four workers produced the same UK (750 quotes) and US (1,331 quotes)
  datasets, row for row, as one worker.
