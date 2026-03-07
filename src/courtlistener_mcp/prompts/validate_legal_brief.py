"""Validate Legal Brief - Citation hallucination detection workflow."""

from . import mcp


@mcp.prompt(
    name="validate_legal_brief",
    description=(
        "Full citation validation audit for a legal document. "
        "Runs the 3-tool fallback chain (courtlistener_validate_citations → courtlistener_search_cases → courtlistener_lookup_citation) "
        "on every citation in the document, generates CourtListener citations verification links, "
        "and produces a structured report with ✅/⚠️/❌ status and risk assessment. "
        "Requires CourtListener citations MCP. "
        "Parameters: document_text (paste text OR leave blank and attach a file), "
        "court_focus (e.g. 'cafc', 'scotus'), "
        "analysis_depth ('standard' or 'comprehensive')."
    ),
)
async def validate_legal_brief_prompt(
    document_text: str = "",
    court_focus: str = "",
    analysis_depth: str = "comprehensive",
) -> str:
    """
    Citation hallucination audit for a legal document.

    Optional (provide one of):
    - document_text: Paste the full text of the brief/motion/memo here, OR
      leave blank and attach the document file (PDF, Word, txt) to the conversation —
      Claude will read the attachment automatically.

    Optional:
    - court_focus: Primary court identifier for fallback searches (e.g. 'scotus', 'cafc',
      'ca1'-'ca11', 'cadc', 'dcd'). Speeds up courtlistener_search_cases fallbacks when known.
    - analysis_depth: 'standard' (validate and link only) or 'comprehensive' (also check
      for mismatches, party name confusions, and produce detailed risk commentary).
      [DEFAULT: comprehensive]

    Returns a complete step-by-step execution plan with tool calls, output format,
    and risk assessment instructions.
    """
    doc_source = (
        f"**Document source:** Pasted text ({len(document_text):,} chars)"
        if document_text.strip()
        else (
            "**Document source:** No text pasted — read the attached file(s) in this conversation "
            "(PDF, Word, or text). Extract the full text and use it as `document_text` for all tool calls below. "
            "If no attachment is present, ask the user to either paste the document text or attach the file."
        )
    )

    court_hint = (
        f"\nPrimary court focus: {court_focus} — use as default `court` param in courtlistener_search_cases fallbacks."
        if court_focus
        else "\nInfer court from reporter abbreviation (U.S./S.Ct. → scotus, F.3d/F.4th → circuit, F.Supp. → district)."
    )

    mismatch_instructions = ""
    if analysis_depth == "comprehensive":
        mismatch_instructions = """
## MISMATCH DETECTION (comprehensive mode)

After each 200-status citation, compare the returned `case_name` against what the
document states. A significant name difference is a MISMATCH — the citation number
is real, but it points to a different case than the document claims.

Common mismatch pattern: AI combines a well-known case name (e.g., "eBay v. MercExchange")
with a citation from a thematically related case (e.g., "TiVo v. EchoStar, 646 F.3d 869").

For each MISMATCH:
1. Note the claimed case name and what the document says the case stands for
2. Note the actual case at that citation (from courtlistener_get_cluster result)
3. Use courtlistener_search_cases to find the CORRECT citation for the claimed case name
4. Present both: the actual case at the cited number AND the correct citation for the intended case

Hallucination patterns to watch for in comprehensive mode:
- Party name confusions: "DABUS v. Vidal" → real case is "Thaler v. Vidal"
- Reporter transposition: same case, wrong reporter (U.S. vs S. Ct.)
- Wrong court: federal circuit case cited as SCOTUS
- Year off by 1-2: real case exists but year is wrong
- citation_count=0 on a case the document treats as foundational — but only flag this if date_filed is more than ~12 months ago; recent decisions naturally accumulate citations slowly
"""

    return f"""# Citation Validation Audit — Legal Brief

{doc_source}
**Court focus:** {court_focus or "infer from reporter"}
**Analysis depth:** {analysis_depth}
{court_hint}

---

## STEP 0: Full Citation Inventory (Local — no API, run first)

{"Read the attached file first and extract its full text. Use that text as `document_text` for all steps below." if not document_text.strip() else ""}

Call courtlistener_extract_citations to discover ALL citation types before hitting the API:

```python
inventory = courtlistener_extract_citations(text=document_text)
```

This runs locally (no API key, no rate limit, instant). Record the counts from
`inventory["summary"]`:
- `case_citations` → these need CourtListener validation (proceed to STEP 1)
- `statutory_citations` → cannot be validated; note in report as "not validatable"
- `law_journal_citations` → cannot be validated; note in report as "not validatable"
- `id_citations` → resolved to antecedents; no validation needed
- `supra_citations` → resolved where possible; no validation needed

If extract_citations finds 0 case citations, skip STEP 1–3 entirely and report that
no case citations were found.

---

## STEP 1: Primary Validation

Call courtlistener_validate_citations with the full document text:

```python
result = courtlistener_validate_citations(text=document_text)
# document_text is the {len(document_text):,}-char brief provided by the user
```

This returns a list of citations with status codes. Track counts:
- `valid_count` = citations with status 200 or 300
- `not_found_count` = citations with status 404
- `invalid_count` = citations with status 400 (bad reporter format)
- `overflow_count` = citations with status 429

If courtlistener_validate_citations fails entirely (API error), extract case names manually
from the text and jump directly to STEP 2 for each one.

---

## STEP 2: Process Each Citation by Status

For each citation returned by courtlistener_validate_citations:

### Status 200 (found) or 300 (ambiguous)

1. Call courtlistener_get_cluster to retrieve the CourtListener URL:
   ```python
   cluster_data = courtlistener_get_cluster(cluster_id=<from result>)
   courtlistener_url = cluster_data["courtlistener_url"]
   citation_count   = cluster_data["citation_count"]
   ```

2. Check case_name for MISMATCH:
   - Compare `cluster_data["case_name"]` against what the document states
   - If names match → ✅ VERIFIED
   - If names differ significantly → ⚠️ MISMATCH (see mismatch instructions below)

3. Check citation_count as a hallucination signal (use date_filed as context):
   - If `citation_count=0` AND `date_filed` is more than ~12 months ago AND the document treats this as a landmark case → ⚠️ flag it
   - Do NOT flag low citation_count for recent decisions (< 12 months old) — new cases always have low counts regardless of importance
   - Example: Thaler v. Perlmutter (130 F.4th 1039, decided March 2025) had citation_count=2 shortly after publication — normal for a brand-new landmark ruling

### Status 404 (not found) — fallback to courtlistener_search_cases

Extract case name from the citation string (strip reporter/year/parentheses).
Example: `"KSR Int'l Co. v. Teleflex Inc., 550 U.S. 398 (2007)"` → `"KSR v Teleflex"`

```python
# Attempt 1: full name + inferred court
results = courtlistener_search_cases(case_name="KSR Int'l v Teleflex", court="scotus")

# Attempt 2: simplified — remove Inc./LLC/Corp./Ltd./Int'l
results = courtlistener_search_cases(case_name="KSR v Teleflex", court="scotus")

# Attempt 3: first party only
results = courtlistener_search_cases(case_name="KSR", court="scotus")

# Attempt 4: no court filter
results = courtlistener_search_cases(case_name="KSR Int'l v Teleflex")
```

If any attempt finds results:
- Call courtlistener_get_cluster for the first match to get courtlistener_url
- Mark as ⚠️ PARTIAL MATCH
- Note which attempt succeeded (e.g., "found via simplified case name search")

If all four attempts fail → proceed to Step 3.

### Status 400 (invalid reporter)

The citation format is not a recognized legal reporter. It may be a statute, rule number,
or a footnote reference misidentified as a citation. Note it but do not run fallback tools.

### Status 429 (overflow)

More than 250 citations in one call. Re-submit the document in smaller chunks:
```python
# Split roughly in half and validate each chunk
chunk1 = courtlistener_validate_citations(text=document_text[:len(document_text)//2])
chunk2 = courtlistener_validate_citations(text=document_text[len(document_text)//2:])
```

---

## STEP 3: Last Resort — courtlistener_lookup_citation

For any citation where courtlistener_search_cases found nothing:

```python
result = courtlistener_lookup_citation(citation="550 U.S. 398")
```

Found → ⚠️ PARTIAL MATCH. Compare returned case_name against what the document claims.
Not found → ❌ NOT FOUND — all three tools failed. Mark as LIKELY HALLUCINATION.
{mismatch_instructions}
---

## STEP 4: Generate the Report

Structure your response in exactly this order:

### 📊 VALIDATION SUMMARY
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All Citations Identified:    X  (courtlistener_extract_citations)
  Case citations:            X  (validated against CourtListener)
  Statutory citations:       X  (not validatable — CourtListener only covers cases)
  Law journal citations:     X  (not validatable)
  Id. / supra references:    X  (resolved to antecedents where possible)

Case Citation Results:
✅ Verified:                 X  (via courtlistener_validate_citations)
⚠️  Partial Matches:         X  (found via fallback search)
⚠️  Mismatches:              X  (citation real, wrong case)
❌ Not Found:                X  (likely hallucinations)
400 Invalid Format:          X  (not a recognizable citation format)
```

### ✅ VERIFIED CITATIONS

For each 200/300 result (include ALL, not just a sample):

```
✅ VERIFIED: Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014)
Court: Supreme Court | Filed: 2014-06-19 | Cited by: 847 later opinions
🔗 https://www.courtlistener.com/opinion/2679558/alice-corp-v-cls-bank/
```

### ⚠️ PARTIAL MATCHES

```
⚠️ PARTIAL MATCH: KSR Int'l Co. v. Teleflex Inc., 550 U.S. 398 (2007)
Found via: case name search (courtlistener_validate_citations returned 404)
🔗 https://www.courtlistener.com/opinion/145658/ksr-v-teleflex/
Note: Citation number not directly validated — verify independently.
```

### ⚠️ MISMATCHES (comprehensive mode only)

```
⚠️ MISMATCH: eBay Inc. v. MercExchange, 646 F.3d 869 (Fed. Cir. 2011)
As cited: eBay v. MercExchange — cited for "injunction test"
Actual case at 646 F.3d 869: TiVo Inc. v. EchoStar Corp.
🔗 Actual case: https://www.courtlistener.com/opinion/215085/tivo-v-echostar/
Correct eBay citation: 547 U.S. 388 (2006) → scotus
🔗 Correct case: https://www.courtlistener.com/opinion/145655/ebay-v-mercexchange/
```

### ❌ NOT FOUND (NO LINK — case does not exist in database)

```
❌ NOT FOUND: DABUS v. Vidal, 985 F.3d 1234 (Fed. Cir. 2021)
Tried: courtlistener_validate_citations → 404 | courtlistener_search_cases (4 attempts) → 0 results | courtlistener_lookup_citation → 404
Status: LIKELY HALLUCINATION
Note: Real case is Thaler v. Vidal — AI used the AI system's name instead of the inventor's.
```

---

## STEP 5: Risk Assessment

Always end with this section:

```
🚨 RISK ASSESSMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Overall Risk Level: [see levels below]

[CRITICAL] 3+ citations not found OR any citation points to a completely different case
[HIGH]     1-2 citations not found, or mismatches present
[MEDIUM]   All citations found, but some only via fallback (not directly validated)
[LOW]      All citations verified directly via courtlistener_validate_citations

Findings:
- X citations not found in any database (likely fabrications)
- X citations verified but pointing to wrong cases (mismatches)
- X citations found only via case name search (not direct validation)
- X citations fully verified with CourtListener links

Recommended Actions:
1. Replace every ❌ citation — these are likely AI inventions
2. Confirm every ⚠️ MISMATCH — the wrong case is being cited
3. Verify citation numbers for ⚠️ PARTIAL MATCH entries independently
4. Click all 🔗 links to visually confirm cases before filing
5. Run Shepard's or KeyCite on verified citations — these tools check existence only, not good law status
```

---

## SAFETY RAILS

- Always run courtlistener_extract_citations first — it's free (local, no API), gives the full census
- Do not call courtlistener_get_cluster more than once per citation (it is only needed for the URL)
- If the document is larger than 64,000 characters, chunk it before calling courtlistener_validate_citations
- courtlistener_search_cases fallback: stop after 4 attempts per citation to avoid rate limiting
- courtlistener_lookup_citation is the last resort only — never start with it
- Do not omit any citation from the report, even 400-status and non-validatable ones
- Never fabricate a CourtListener URL — only use URLs returned by courtlistener_get_cluster or search results
"""
