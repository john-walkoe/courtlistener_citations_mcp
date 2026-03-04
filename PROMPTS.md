# CourtListener Citation Validation MCP — Prompt Templates

Reusable prompt templates for Claude to validate legal citations, detect AI hallucinations, and analyze case law using the CourtListener Citation Validation MCP.

---

## Table of Contents

- [About Prompt Templates](#about-prompt-templates)
- [Template 1: validate_legal_brief](#template-1-validate_legal_brief)
- [Template 2: Quick Citation Check](#template-2-quick-citation-check)
- [Template 3: Hallucination Triage](#template-3-hallucination-triage)
- [Template 4: Citation Inventory Only](#template-4-citation-inventory-only)
- [Template 5: Federal Circuit Patent Brief](#template-5-federal-circuit-patent-brief)
- [Template 6: Supreme Court Brief](#template-6-supreme-court-brief)
- [Template 7: Case Name Lookup](#template-7-case-name-lookup)
- [Template 8: Pre-Filing Checklist](#template-8-pre-filing-checklist)
- [Template 9: Mismatch Analysis](#template-9-mismatch-analysis)
- [Template 10: Bulk Citation Report](#template-10-bulk-citation-report)
- [Template 11: Guidance and Workflow Help](#template-11-guidance-and-workflow-help)

---

## About Prompt Templates

These templates are designed to be pasted directly into Claude. Each template activates specific CourtListener MCP tools and produces structured output useful for legal review workflows.

**How to use:**
1. Copy a template
2. Replace `[PASTE DOCUMENT TEXT HERE]` or other bracketed placeholders with your content
3. Paste into Claude

Some templates call the built-in `validate_legal_brief` MCP prompt, which contains a full step-by-step execution plan for comprehensive citation auditing.

---

## Template 1: validate_legal_brief

**Purpose:** Full citation hallucination audit using the built-in MCP prompt template.

**Features:**
- Calls `courtlistener_extract_citations` first (local, no API, instant)
- Runs full 3-tool fallback chain
- Comprehensive mismatch detection
- Structured ✅/⚠️/❌ report
- Risk assessment with filing recommendations

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `document_text` | Yes | — | Full text of the legal document |
| `court_focus` | No | (inferred) | Primary court identifier (e.g., `scotus`, `cafc`) |
| `analysis_depth` | No | `comprehensive` | `standard` or `comprehensive` |

**Template:**
```
Use the validate_legal_brief prompt with the following parameters:
- document_text: [PASTE DOCUMENT TEXT HERE]
- court_focus: [COURT ID e.g. cafc, scotus, ca9 — or omit to infer]
- analysis_depth: comprehensive
```

**Screenshot — Full Brief Audit Output:**
> 📷 `documentation_photos/template1_full_audit_output.png`

**Screenshot — Risk Assessment Section:**
> 📷 `documentation_photos/template1_risk_assessment.png`

**Use cases:**
- Pre-filing citation audit for AI-drafted briefs
- Hallucination detection in motions and memos
- Quality control before attorney review
- Identifying mismatched party names

**Integration with other tools:**

| Tool Used | Purpose |
|-----------|---------|
| `courtlistener_extract_citations` | Step 0 — local citation inventory |
| `courtlistener_validate_citations` | Step 1 — primary API validation |
| `courtlistener_search_cases` | Step 2 — fallback for 404s |
| `courtlistener_lookup_citation` | Step 3 — last resort |
| `courtlistener_get_cluster` | URL and case details for all found |

---

## Template 2: Quick Citation Check

**Purpose:** Validate one or a few specific citations without running a full document audit.

**Features:**
- Fast single-call validation
- Immediate ✅/❌ status
- CourtListener links for verified citations
- No document required

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `citations` | Yes | One or more citations as plain text |

**Template:**
```
Validate these citations and provide CourtListener links for any that are found:

[PASTE CITATIONS HERE — one per line or as a comma-separated list]

For each citation:
1. Run courtlistener_validate_citations
2. If found, call courtlistener_get_cluster for the URL
3. If 404, try courtlistener_search_cases
4. Report ✅/⚠️/❌ status for each
```

**Screenshot — Quick Check Output:**
> 📷 `documentation_photos/template2_quick_check.png`

**Use cases:**
- Spot-checking a single suspicious citation
- Verifying a citation found in secondary source
- Quick sanity check before including a case in a brief

---

## Template 3: Hallucination Triage

**Purpose:** Focused triage of citations suspected to be AI hallucinations.

**Features:**
- Comprehensive mismatch detection enabled
- Party name confusion detection
- Reporter transposition checks
- Identifies fabricated volume/page combinations

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `citations` | Yes | Suspect citations to investigate |
| `claimed_propositions` | No | What the document says each case stands for |

**Template:**
```
I suspect these citations may be AI hallucinations. Please investigate each one:

[PASTE SUSPECT CITATIONS HERE]

For each citation:
1. Use courtlistener_validate_citations — report the status code
2. If 404: try courtlistener_search_cases with the case name
3. If found but name differs from what's claimed: flag as MISMATCH
4. Check for common AI patterns:
   - Wrong party name (e.g., AI system name instead of human inventor)
   - Transposed reporter (U.S. vs S. Ct. for same case)
   - Citation from a different but thematically related case
   - Wrong year (off by 1-2 years)
5. For each MISMATCH: find the CORRECT citation for the claimed proposition
```

**Screenshot — Hallucination Detection:**
> 📷 `documentation_photos/template3_hallucination_triage.png`

**Use cases:**
- Investigating citations that "feel wrong"
- Reviewing AI-drafted sections of a brief
- Checking citations for cases that are commonly confused
- Post-filing discovery of potential citation errors

---

## Template 4: Citation Inventory Only

**Purpose:** Extract and count all citation types without running API validation. Useful for scoping a document or understanding its citation composition.

**Features:**
- Local only — no API calls, instant
- Full breakdown by citation type
- Identifies statutory and journal citations that cannot be validated
- Resolves id. and supra references to antecedents

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `text` | Yes | Document text |

**Template:**
```
Use courtlistener_extract_citations to get a full citation inventory for this document.
Report counts by type and list all case citations extracted.

[PASTE DOCUMENT TEXT HERE]
```

**Screenshot — Citation Inventory Output:**
> 📷 `documentation_photos/template4_citation_inventory.png`

**Use cases:**
- Understanding citation composition before committing to a full audit
- Identifying documents with mostly statutory citations (which can't be validated)
- Counting citations to estimate validation cost/time
- Generating a citation list for manual review

---

## Template 5: Federal Circuit Patent Brief

**Purpose:** Specialized audit for Federal Circuit patent litigation briefs.

**Features:**
- Sets `court_focus: cafc` for faster fallbacks
- Recognizes common patent law landmarks (Alice, KSR, Mayo, eBay, Bilski)
- Notes non-validatable patent statute citations (35 U.S.C. §§)
- Mismatch detection tuned for patent case name confusions

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `document_text` | Yes | Patent brief text |
| `analysis_depth` | No | Default: `comprehensive` |

**Template:**
```
Use the validate_legal_brief prompt with:
- document_text: [PASTE PATENT BRIEF TEXT HERE]
- court_focus: cafc
- analysis_depth: comprehensive

Note: 35 U.S.C. statutory citations will appear as "not validatable" — this is expected.
Flag any 35 U.S.C. § 101 case (Alice, Mayo, Bilski, Myriad) that cannot be verified.
```

**Screenshot — Patent Brief Audit:**
> 📷 `documentation_photos/template5_patent_brief_audit.png`

**Use cases:**
- IPR petition citation validation
- § 101 eligibility brief review
- Obviousness (KSR) citation checks
- Federal Circuit appeal brief pre-filing audit

---

## Template 6: Supreme Court Brief

**Purpose:** Validation for Supreme Court briefs, cert petitions, and amicus briefs.

**Features:**
- Handles U.S. vs S. Ct. reporter discrepancies
- Recognizes recent landmark cases with low citation counts
- Sets `court_focus: scotus` for precise fallbacks
- Notes when U.S. Reports is not yet indexed for recent terms

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `document_text` | Yes | SCOTUS brief text |

**Template:**
```
Use the validate_legal_brief prompt with:
- document_text: [PASTE SCOTUS BRIEF TEXT HERE]
- court_focus: scotus
- analysis_depth: comprehensive

Important notes for SCOTUS briefs:
- If a U.S. Reports cite (e.g., 573 U.S. 208) returns 404, also try the S. Ct. parallel
- Recent decisions (last 1-2 terms) may not yet be indexed in U.S. Reports
- Low citation_count on recent SCOTUS cases is normal
```

**Screenshot — SCOTUS Brief Audit:**
> 📷 `documentation_photos/template6_scotus_brief.png`

**Use cases:**
- Cert petition citation review
- SCOTUS merits brief pre-filing check
- Amicus brief citation validation
- Response to cert petition citation verification

---

## Template 7: Case Name Lookup

**Purpose:** Find a case in CourtListener by name when you don't have the citation, or verify the correct citation for a case you know by name.

**Features:**
- Multiple search strategies (full name → simplified → first party only → no court filter)
- Returns correct citation and CourtListener URL
- Useful for checking citation accuracy in secondary sources

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `case_name` | Yes | Case name (both parties, or just one) |
| `court` | No | Court identifier to narrow search |

**Template:**
```
Find the case "[CASE NAME HERE]" in CourtListener.

Use courtlistener_search_cases with:
1. Full case name + court (if known)
2. If no results: simplified name (remove Inc., LLC, Corp., Int'l)
3. If no results: first party name only
4. If no results: no court filter

Return the correct citation, date decided, and CourtListener URL.
```

**Screenshot — Case Name Search:**
> 📷 `documentation_photos/template7_case_lookup.png`

**Use cases:**
- Finding the correct citation for a case known only by name
- Confirming which reporter volume/page is correct
- Checking if a case was overruled (use Shepard's/KeyCite after finding)
- Verifying party names before including in a brief

---

## Template 8: Pre-Filing Checklist

**Purpose:** Comprehensive pre-filing validation combining citation audit with a structured checklist.

**Features:**
- Full citation audit
- Generates filing checklist at the end
- Flags any citation_count=0 for cases over 1 year old
- Reminds about coverage limitations (statutes, good law status)

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `document_text` | Yes | Final brief text |
| `filing_date` | No | Planned filing date for urgency context |

**Template:**
```
Pre-filing citation audit for a brief I'm filing [FILING DATE or "soon"].

[PASTE BRIEF TEXT HERE]

Please:
1. Run a full citation audit (validate_legal_brief, comprehensive)
2. Generate CourtListener links for every verified case
3. Flag any case with citation_count=0 that was decided more than 12 months ago
4. Generate a pre-filing checklist at the end
5. Note any limitations (statutes not covered, recently decided cases, etc.)
```

**Screenshot — Pre-Filing Report:**
> 📷 `documentation_photos/template8_prefiling_checklist.png`

**Use cases:**
- Day-before-filing citation sanity check
- Partner/supervising attorney review support
- Quality control handoff checklist
- Documenting citation verification for the file

---

## Template 9: Mismatch Analysis

**Purpose:** In-depth analysis when you suspect a citation number is real but points to the wrong case — a common AI hallucination pattern.

**Features:**
- Validates citation to find actual case
- Searches for the "intended" case by name
- Shows both the actual case and the correct citation for what was intended
- Explains the likely AI confusion pattern

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `citation` | Yes | The suspect citation |
| `claimed_case_name` | Yes | What the document says the case is |
| `claimed_proposition` | No | What the document says the case stands for |

**Template:**
```
Investigate this potential citation mismatch:

Citation in document: [CITATION]
Document claims this is: [CASE NAME]
Document says it stands for: [PROPOSITION — optional]

Steps:
1. Use courtlistener_validate_citations on the citation
2. If found: call courtlistener_get_cluster and compare actual case_name to claimed name
3. If names differ: this is a MISMATCH — report both:
   - Actual case at that citation + CourtListener URL
   - Correct citation for the claimed case name (use courtlistener_search_cases)
4. Explain the likely AI confusion pattern
```

**Screenshot — Mismatch Analysis:**
> 📷 `documentation_photos/template9_mismatch_analysis.png`

**Use cases:**
- Deep-dive on a single suspicious citation
- Explaining hallucination pattern to a supervising attorney
- Finding the correct replacement citation
- Documenting the error for a privilege log or correction

---

## Template 10: Bulk Citation Report

**Purpose:** Generate a structured spreadsheet-ready citation report for large documents.

**Features:**
- Tabular output format (CSV-compatible)
- One row per citation with status, URL, and notes
- Suitable for exporting to Excel or review tools

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `document_text` | Yes | Document text |

**Template:**
```
Validate all case citations in this document and generate a CSV-format report.

[PASTE DOCUMENT TEXT HERE]

Output format (one row per citation):
Citation | Status | Case Name | Date Filed | Court | Citation Count | CourtListener URL | Notes

Status codes:
- VERIFIED: found via validate_citations
- PARTIAL: found via search_cases fallback
- MISMATCH: citation exists but points to different case
- NOT_FOUND: all tools returned 404
- INVALID_FORMAT: status 400 from validate_citations
```

**Screenshot — Bulk Report Output:**
> 📷 `documentation_photos/template10_bulk_report.png`

**Use cases:**
- Large-scale citation audit (20+ citations)
- Creating a citation verification record for the file
- Exporting to a review management system
- Tracking citation cleanup progress across revisions

---

## Template 11: Guidance and Workflow Help

**Purpose:** Learn how the CourtListener MCP works, understand the fallback chain, or get help interpreting risk levels.

**Features:**
- No API calls — instant response
- Section-based help (get only what you need)
- Available at any time — no citations required

**Parameters:**

| Parameter | Required | Values | Description |
|-----------|----------|--------|-------------|
| `section` | Yes | See below | Which guidance section to retrieve |

**Available sections:**

| Section | Content |
|---------|---------|
| `overview` | What this MCP does, when to use it |
| `citation_workflow` | The 3-tool fallback chain explained |
| `tools` | Reference for all 7 tools |
| `fallback_chain` | Detailed fallback logic with search optimization |
| `risk_assessment` | How to interpret ✅/⚠️/❌ and risk levels |
| `limitations` | CourtListener coverage gaps and false negatives |

**Templates:**
```
Use courtlistener_get_guidance with section="overview"
```
```
Use courtlistener_get_guidance with section="risk_assessment"
```
```
Use courtlistener_get_guidance with section="limitations"
```

**Use cases:**
- Onboarding a new user to the tool
- Understanding why a citation returned 404
- Explaining risk levels to a non-technical attorney
- Understanding what CourtListener doesn't cover

---

## Common Court Identifiers

| Identifier | Court |
|------------|-------|
| `scotus` | U.S. Supreme Court |
| `cafc` | Federal Circuit |
| `ca1` – `ca11` | First through Eleventh Circuits |
| `cadc` | D.C. Circuit |
| `dcd` | District of D.C. |

---

## Rate Limits

| Limit | Value |
|-------|-------|
| General | 5,000 requests/hour |
| Citation-lookup | 60 valid citations/minute |
| Max citations per call | 250 |
| Max characters per call | 64,000 (auto-chunked) |

`extract_citations` has no rate limit — it runs locally.
