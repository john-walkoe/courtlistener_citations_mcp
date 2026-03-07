# CourtListener Citation Validation MCP — Usage Examples

Practical examples for validating legal citations using the CourtListener Citation Validation MCP. The primary use case is detecting AI-generated hallucinated citations in legal briefs, motions, and memos before filing.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Core Workflows](#core-workflows)
  - [1. Full Legal Brief Audit](#1-full-legal-brief-audit)
  - [2. Quick Citation Spot-Check](#2-quick-citation-spot-check)
  - [3. Known Hallucination Patterns](#3-known-hallucination-patterns)
  - [4. Extract All Citation Types from a Document](#4-extract-all-citation-types-from-a-document)
  - [5. Case Name Lookup (Fallback Chain)](#5-case-name-lookup-fallback-chain)
  - [6. Find a Case by Name](#6-find-a-case-by-name)
  - [7. Get Full Case Details and CourtListener URL](#7-get-full-case-details-and-courtlistener-url)
- [Advanced Workflows](#advanced-workflows)
  - [8. Federal Circuit Patent Brief Audit](#8-federal-circuit-patent-brief-audit)
  - [9. Supreme Court Brief Validation](#9-supreme-court-brief-validation)
  - [10. Validate Before Filing — Complete Checklist Flow](#10-validate-before-filing--complete-checklist-flow)
- [Cross-MCP Workflows](#cross-mcp-workflows)
  - [11. Patent Brief with USPTO + CourtListener Validation](#11-patent-brief-with-uspto--courtlistener-validation)
- [Tool Reference Summary](#tool-reference-summary)
- [Testing with Known Citations](#testing-with-known-citations)

---

## Quick Start

The fastest way to start is to ask Claude to validate specific citations:

```
Validate these citations from my brief:
- Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014)
- KSR Int'l Co. v. Teleflex Inc., 550 U.S. 398 (2007)
- Mayo Collaborative Services v. Prometheus Laboratories, Inc., 566 U.S. 66 (2012)
```

Or paste an entire document:

```
Please validate all citations in the attached brief and generate a hallucination report.

[paste document text here]
```

---

## Core Workflows

### 1. Full Legal Brief Audit

**Use case:** You have an AI-drafted brief and want to verify every citation before filing.

**Prompt:**
```
Use the validate_legal_brief prompt to run a full citation audit on the following brief.
Report all citations with ✅/⚠️/❌ status and include CourtListener links.

[paste full brief text here]
```

**What happens:**
1. `courtlistener_extract_citations` inventories all citation types (case, statutory, journal, id., supra)
2. `courtlistener_validate_citations` validates all case citations in one API call
3. For any 404s: `courtlistener_search_cases` attempts 4 search strategies
4. For remaining misses: `courtlistener_lookup_citation` tries direct reporter lookup
5. `courtlistener_get_cluster` fetches CourtListener URLs for all found cases
6. Full report generated with risk assessment

**Sample output:**
```
📊 VALIDATION SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All Citations Identified:   14
  Case citations:            9  (validated against CourtListener)
  Statutory citations:       4  (not validatable)
  Id. / supra references:    1  (resolved)

Case Citation Results:
✅ Verified:                 7
⚠️  Partial Matches:         1
❌ Not Found:                1

🚨 RISK ASSESSMENT
Overall Risk Level: HIGH
1 citation not found — likely AI fabrication. Review immediately.
```

---

### 2. Quick Citation Spot-Check

**Use case:** You have one or a few specific citations to verify quickly.

**Prompt:**
```
Validate this citation: Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014)
```

**Tool call:**
```json
{
  "tool": "courtlistener_validate_citations",
  "text": "Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014)"
}
```

**Note:** Alice Corp. `573 U.S. 208` returns 404 from `validate_citations` because the U.S. Reports indexing is incomplete. The fallback chain resolves it via `search_cases(case_name="Alice Corp v CLS Bank", court="scotus")`. The correct parallel cite `134 S. Ct. 2347` validates directly. This is expected behavior — not a hallucination.

---

### 3. Known Hallucination Patterns

**Use case:** Check citations that have common AI hallucination patterns — wrong parties, transposed reporters, or fabricated volume/page numbers.

**Prompt:**
```
Validate these citations from an AI-generated patent brief and check for hallucinations.
Use comprehensive analysis depth.

1. DABUS v. Vidal, 985 F.3d 1234 (Fed. Cir. 2021)
2. eBay Inc. v. MercExchange, 646 F.3d 869 (Fed. Cir. 2011)
3. Thaler v. Vidal, 43 F.4th 1207 (Fed. Cir. 2022)
```

**Expected findings:**
- Citation 1 (`DABUS v. Vidal, 985 F.3d 1234`) — ❌ NOT FOUND. AI used the AI system's name instead of the inventor's. Real case: Thaler v. Vidal.
- Citation 2 (`eBay v. MercExchange, 646 F.3d 869`) — ⚠️ MISMATCH. 646 F.3d 869 is TiVo v. EchoStar. Real eBay cite: 547 U.S. 388 (2006).
- Citation 3 (`Thaler v. Vidal, 43 F.4th 1207`) — ✅ VERIFIED.

---

### 4. Extract All Citation Types from a Document

**Use case:** Get a full inventory of all citation types before validation — useful for scoping work or documents with many statutory references.

**Prompt:**
```
Use courtlistener_extract_citations to extract all citations from this text and
give me counts by type.

[paste text here]
```

**Tool call:**
```json
{
  "tool": "courtlistener_extract_citations",
  "text": "See 35 U.S.C. § 101; Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014);\nKSR, 550 U.S. at 418; id. at 420."
}
```

**Sample response:**
```json
{
  "summary": {
    "total": 4,
    "case_citations": 1,
    "statutory_citations": 1,
    "id_citations": 2,
    "supra_citations": 0,
    "law_journal_citations": 0
  },
  "case_citations": [
    {
      "token": "573 U.S. 208",
      "reporter": "U.S.",
      "volume": "573",
      "page": "208"
    }
  ],
  ...
}
```

**Key point:** `extract_citations` runs locally using eyecite — no API key, no rate limit, instant. Always run this first.

---

### 5. Case Name Lookup (Fallback Chain)

**Use case:** A citation returned 404 from `validate_citations`. Walk through the manual fallback chain.

**Prompt:**
```
The citation "KSR Int'l Co. v. Teleflex Inc., 550 U.S. 398 (2007)" returned 404.
Use courtlistener_search_cases to find it, then get the CourtListener URL.
```

**Tool calls (in order):**

```json
// Attempt 1: Full name + court
{
  "tool": "courtlistener_search_cases",
  "case_name": "KSR Int'l Co. v. Teleflex Inc.",
  "court": "scotus"
}

// Attempt 2: Simplified
{
  "tool": "courtlistener_search_cases",
  "case_name": "KSR v Teleflex",
  "court": "scotus"
}

// If found, get the URL
{
  "tool": "courtlistener_get_cluster",
  "cluster_id": 145658
}
```

---

### 6. Find a Case by Name

**Use case:** You know the case name but not the citation, or want to verify the correct citation for a well-known case.

**Prompts:**
```
What is the correct citation for eBay v. MercExchange?
```
```
Find the Alice Corp case in CourtListener.
```
```
Search for Mayo v. Prometheus in the Supreme Court.
```

**Tool call:**
```json
{
  "tool": "courtlistener_search_cases",
  "case_name": "Alice Corp v CLS Bank",
  "court": "scotus"
}
```

**Tips for better search results:**
- Strip corporate suffixes: `Inc.`, `LLC`, `Corp.`, `Ltd.`, `Int'l`
- Use short names: `"KSR v Teleflex"` not `"KSR International Co. v. Teleflex Inc."`
- For Federal Circuit: `court="cafc"`
- For numbered circuits: `court="ca1"` through `court="ca11"`
- For DC Circuit: `court="cadc"`

---

### 7. Get Full Case Details and CourtListener URL

**Use case:** You have a cluster ID from search results and want the full case details.

**Prompt:**
```
Get the full details for CourtListener cluster 2679558 (Alice Corp).
```

**Tool call:**
```json
{
  "tool": "courtlistener_get_cluster",
  "cluster_id": 2679558
}
```

**Sample response:**
```json
{
  "cluster_id": 2679558,
  "case_name": "Alice Corp. v. CLS Bank Int'l",
  "date_filed": "2014-06-19",
  "court": "scotus",
  "citations": [
    {"volume": "573", "reporter": "U.S.", "page": "208"},
    {"volume": "134", "reporter": "S. Ct.", "page": "2347"}
  ],
  "citation_count": 847,
  "courtlistener_url": "https://www.courtlistener.com/opinion/2679558/alice-corp-v-cls-bank/"
}
```

---

## Advanced Workflows

### 8. Federal Circuit Patent Brief Audit

**Use case:** Patent litigation brief focused on Federal Circuit and SCOTUS patent law cases.

**Prompt:**
```
Run a full citation audit on this Federal Circuit patent brief.
Focus court: cafc. Use comprehensive analysis to catch party name confusions.

[paste brief text here]
```

**What to expect:**
- Common 35 U.S.C. § 101/102/103/112 statutory citations flagged as non-validatable
- `search_cases` fallbacks use `court="cafc"` for 404s, then broaden
- Mismatch detection active for patent landmark cases (eBay, Alice, KSR, Mayo, Bilski)
- Risk assessment flags if foundational §101 cases can't be verified

---

### 9. Supreme Court Brief Validation

**Use case:** Validate citations in a cert petition or merits brief for the Supreme Court.

**Prompt:**
```
Validate all case citations in this Supreme Court brief.
Flag any citation where the U.S. Reports cite returns 404 but a S. Ct. parallel exists.

[paste brief text here]
```

**Notes:**
- SCOTUS opinions are often indexed under `S. Ct.` before `U.S.` reporters are finalized
- If `573 U.S. 208` → 404, try `134 S. Ct. 2347` — same case, different reporter
- The fallback chain handles this automatically via `search_cases(court="scotus")`

---

### 10. Validate Before Filing — Complete Checklist Flow

**Use case:** Final pre-filing check combining citation validation with a manual review checklist.

**Prompt:**
```
I'm filing this brief tomorrow. Please:
1. Run a full citation validation audit
2. Generate CourtListener links for every case
3. Flag any citation with citation_count=0 that is more than 1 year old
4. Provide a filing checklist at the end

[paste brief text here]
```

**Filing checklist output format requested:**
```
📋 PRE-FILING CHECKLIST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
□ All ❌ citations replaced with verified alternatives
□ All ⚠️ MISMATCH citations corrected
□ All ⚠️ PARTIAL MATCH citations verified independently
□ All 🔗 CourtListener links clicked and visually confirmed
□ Shepard's / KeyCite run on all verified citations (check good law status)
□ Statutory citations verified against current code (CourtListener does not cover statutes)
□ Id. and supra references point to the correct antecedent cases
```

---

## Cross-MCP Workflows

### 11. Patent Brief with USPTO + CourtListener Validation

**Use case:** Validate both patent references (USPTO PFW MCP) and case law citations (CourtListener MCP) in a combined patent litigation brief.

**Prompt:**
```
This brief cites both patents and court cases. Please:
1. Use USPTO PFW MCP to verify patent numbers (e.g., US10,123,456)
2. Use CourtListener MCP to validate case citations
3. Generate a combined report

[paste brief text here]
```

**Tool execution order:**
1. `courtlistener_extract_citations` — inventory case citations
2. `uspto_pfw_get_patent` — verify each patent number
3. `courtlistener_validate_citations` — validate case citations
4. Fallback chain as needed
5. Combined report with both patent and case validation results

---

## Tool Reference Summary

| Tool | When to Use | API Required | Rate Limited |
|------|-------------|--------------|--------------|
| `courtlistener_extract_citations` | Always run first — full citation inventory | No (local) | No |
| `courtlistener_validate_citations` | Primary case citation validation | Yes | 60 valid citations/min |
| `courtlistener_search_cases` | Fallback when validate returns 404 | Yes | 5,000 req/hr |
| `courtlistener_lookup_citation` | Last resort only | Yes | 5,000 req/hr |
| `courtlistener_get_cluster` | Get CourtListener URL + case details | Yes | 5,000 req/hr |
| `courtlistener_search_clusters` | Advanced filtered search | Yes | 5,000 req/hr |
| `courtlistener_get_guidance` | Workflow help and risk explanation | No | No |

**3-Tool Fallback Chain:**
```
validate_citations (primary)
    └─ 404 → search_cases (fallback, 4 attempts)
                └─ 0 results → lookup_citation (last resort)
                                   └─ 404 → ❌ LIKELY HALLUCINATION
```

---

## Testing with Known Citations

Use these citations to verify your setup is working:

| Citation | Expected Result | Notes |
|----------|----------------|-------|
| `134 S. Ct. 2347` | ✅ VERIFIED | Alice Corp. — use S.Ct. reporter |
| `573 U.S. 208` | ⚠️ PARTIAL (via search_cases) | Alice Corp. in U.S. Reports — 404 is expected |
| `550 U.S. 398` | ✅ VERIFIED | KSR v. Teleflex |
| `566 U.S. 66` | ✅ VERIFIED | Mayo v. Prometheus |
| `547 U.S. 388` | ✅ VERIFIED | eBay v. MercExchange |
| `43 F.4th 1207` | ✅ VERIFIED | Thaler v. Vidal (Fed. Cir.) |
| `985 F.3d 1234` | ❌ NOT FOUND | DABUS hallucination — does not exist |

**Quick test prompt:**
```
Use courtlistener_validate_citations on: 134 S. Ct. 2347 and 985 F.3d 1234
```

Expected: first verified ✅, second not found ❌.

---

## Getting Help

```
Use courtlistener_get_guidance with section="overview" to learn what this MCP does.
Use courtlistener_get_guidance with section="workflow" to understand the fallback chain.
Use courtlistener_get_guidance with section="risk_assessment" to understand risk levels.
Use courtlistener_get_guidance with section="limitations" to understand coverage gaps.
```
