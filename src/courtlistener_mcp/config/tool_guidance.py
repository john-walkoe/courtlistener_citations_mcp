"""
Tool Guidance System - Sectioned Approach

Provides contextual guidance for CourtListener MCP tools.
Sectioned design achieves 80-95% token reduction vs. full instructions.
Only the requested section is returned to the LLM.

Sections (7):
  overview, workflow, response_format, hallucination_patterns,
  edge_cases, risk_assessment, limitations
"""

# Backward compatibility aliases (old name -> new name)
_SECTION_ALIASES: dict[str, str] = {
    "citation_workflow": "workflow",
    "fallback_chain": "workflow",
    "step_by_step_workflow": "workflow",
    "tools": "overview",
    "link_generation": "workflow",
    "citation_patterns": "hallucination_patterns",
}


def get_guidance_section(section: str = "overview") -> str:
    """
    Get a specific guidance section.

    Args:
        section: Section name. Available sections:
            - overview: What this MCP does and quick reference
            - workflow: Full fallback chain (validate -> search -> lookup)
            - response_format: How to format results with symbols
            - hallucination_patterns: Detection patterns and hallucination signs
            - edge_cases: Special handling scenarios
            - risk_assessment: How to interpret validation results
            - limitations: CourtListener coverage gaps

    Returns:
        Guidance text for the requested section
    """
    # Resolve aliases for backward compatibility
    resolved = _SECTION_ALIASES.get(section, section)

    sections = {
        "overview": _overview_section,
        "workflow": _workflow_section,
        "response_format": _response_format_section,
        "hallucination_patterns": _hallucination_patterns_section,
        "edge_cases": _edge_cases_section,
        "risk_assessment": _risk_assessment_section,
        "limitations": _limitations_section,
    }

    builder = sections.get(resolved)
    if builder is None:
        available = ", ".join(sorted(sections.keys()))
        return (
            f"Unknown section: '{section}'. "
            f"Available sections: {available}\n\n"
            "Start with 'overview' for a summary of capabilities."
        )

    return builder()


def _overview_section() -> str:
    return """
COURTLISTENER CITATION VALIDATION MCP - OVERVIEW
=================================================

PURPOSE: Validate legal citations in documents against the CourtListener
database to detect AI-generated hallucinations and citation errors.

QUICK REFERENCE - What section for your question?
🔁 "How does the fallback chain work?" → workflow
✨ "How do I format results?" → response_format
🔍 "What hallucination patterns to detect?" → hallucination_patterns
⚠️ "Special cases (SCOTUS, state courts)?" → edge_cases
🚨 "How to interpret results?" → risk_assessment
📉 "What's not covered?" → limitations

TOOLS AVAILABLE (6 + this guidance tool):
0. courtlistener_extract_citations - DISCOVERY: Extract all citation types locally (no API)
1. courtlistener_validate_citations - PRIMARY: Validate case citations against CourtListener
2. courtlistener_search_cases - FALLBACK: Search by case name when citation fails
3. courtlistener_lookup_citation - LAST RESORT: Direct reporter citation lookup
4. courtlistener_get_cluster - Get full case details by cluster ID
5. courtlistener_search_clusters - Search opinion clusters with filters

TYPICAL WORKFLOW:
0. courtlistener_extract_citations(text) — full citation inventory (case, statute, journal, id, supra)
1. courtlistener_validate_citations(text) — validate case citations against CourtListener
2. For 404 results, fall back to courtlistener_search_cases by case name
3. For remaining failures, try courtlistener_lookup_citation by reporter citation
4. Present results with verification links (✅⚠️❌🔗 symbols)

NOTE: Each tool's return value includes guidance.next_steps to direct
you through the workflow. Follow those hints for step-by-step navigation.
""".strip()


def _workflow_section() -> str:
    return """
CITATION VALIDATION WORKFLOW - DISCOVERY + 3-TOOL FALLBACK CHAIN
================================================================

DECISION CHART:
  Message received with citations?
    └─ NO → Silent (no response needed)
    └─ YES → Proceed to STEP 0

STEP 0: courtlistener_extract_citations(text) [LOCAL — no API, no rate limit]
  Purpose: Full citation inventory before hitting the API.
  Returns: case_citations, statutory_citations, law_journal_citations,
           id_citations, supra_citations, unknown_citations
  │
  ├─ statutory / law journal / id / supra → note in output (cannot be validated)
  └─ case_citations → Proceed to STEP 1

STEP 1: courtlistener_validate_citations(text)
  ├─ API Error? → FALLBACK MODE (extract case names manually)
  └─ Success → Process each citation by status:
     │
     ├─ status 200 → Check for MISMATCH:
     │   ├─ Returned case_name matches document? → ✅ VERIFIED
     │   └─ Returned case_name DIFFERS? → ⚠️ MISMATCH
     │
     ├─ status 300 → ✅ VERIFIED (ambiguous - review clusters)
     ├─ status 404 → Go to STEP 2
     ├─ status 400 → Invalid reporter format
     └─ status 429 → Overflow (>250 citations). Re-submit in smaller chunks.

STEP 2: courtlistener_search_cases (FALLBACK for 404 results)
  Extract case name from citation text.
  Example: "Alice Corp. v. CLS Bank, 573 U.S. 208 (2014)"
  → case_name = "Alice Corp v CLS Bank", court = "scotus"

  ATTEMPT 1: courtlistener_search_cases(case_name="Alice Corp v CLS Bank", court="scotus")
  ATTEMPT 2: Simplify - remove "Inc.", "LLC", "Corp.", "Ltd."
  ATTEMPT 3: Broaden - courtlistener_search_cases(query="Alice CLS Bank", court="scotus")
  ATTEMPT 4: Drop court filter - courtlistener_search_cases(case_name="Alice Corp v CLS Bank")

  Found? → ⚠️ PARTIAL MATCH | Not found? → STEP 3

STEP 3: courtlistener_lookup_citation (LAST RESORT)
  Try courtlistener_lookup_citation(citation="573 U.S. 208")
  Found? → ⚠️ PARTIAL MATCH (compare case_name for MISMATCH)
  Not found? → ❌ NOT FOUND (likely hallucination)

STEP 4: GET COURTLISTENER LINKS (REQUIRED FOR ALL OUTCOMES)
  ├─ status 200 → call courtlistener_get_cluster(cluster_id) → use returned courtlistener_url
  ├─ status 404 found via fallback → cluster result includes courtlistener_url — use it directly
  ├─ status 404 NOT FOUND (hallucination) → construct search URL:
  │     https://www.courtlistener.com/?q={case+name+url+encoded}&type=o
  └─ Every citation in the response MUST have a 🔗 link — even hallucinations get a search link

STEP 5: FORMAT RESULTS
  ├─ Start with 📊 VALIDATION SUMMARY (counts by category)
  ├─ ✅ VERIFIED with 🔗 direct case URL from courtlistener_get_cluster
  ├─ ⚠️ PARTIAL MATCH / MISMATCH with fallback method noted + 🔗 case URL
  ├─ ❌ NOT FOUND with 🔗 search URL (https://www.courtlistener.com/?q=...&type=o)
  └─ End with 🚨 RISK ASSESSMENT

REPORTER → COURT MAPPING (for inferring court from citation):
  "U.S." / "S. Ct." / "L. Ed." → scotus
  "F.3d" / "F.4th" → Circuit Court (ca1-ca11, cafc, cadc)
  "F. Supp." → District Court
  "F. App'x" → Circuit Court (unpublished)

COURT IDENTIFIERS:
  scotus, cafc, ca1-ca11, cadc, dcd
""".strip()


def _response_format_section() -> str:
    return """
RESPONSE FORMAT - VISUAL SYMBOLS AND STRUCTURE
==============================================

Use these visual symbols prominently in responses:
  ✅ VERIFIED - Citation found and valid
  ⚠️ PARTIAL MATCH - Found via fallback only
  ⚠️ MISMATCH - Citation exists but points to different case
  ❌ NOT FOUND - All tools failed (likely hallucination)
  🔗 - CourtListener verification link

STRUCTURE YOUR RESPONSE IN THESE SECTIONS (in order):

1. SUMMARY STATISTICS (always include first):
  📊 VALIDATION SUMMARY
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Total Citations Found: X
  ✅ Valid Citations: X (via validate_citations)
  ⚠️ Partial Matches: X (via search_cases or lookup_citation)
  ❌ Not Found: X (all tools failed)

2. VERIFIED CITATIONS (max 4 lines each):
  ✅ VERIFIED: [Case Name]
  Citation: [Citation] | Filed: [Date] | Court: [Court]
  🔗 [courtlistener_url from result]

3. PARTIAL MATCHES (found by fallback):
  ⚠️ PARTIAL MATCH: [Case Name]
  Cited: [What document stated] | Found: [What database shows]
  🔗 [courtlistener_url from result]
  Note: Found via [case name search / reporter citation only]

4. NOT FOUND (all tools failed - use search link):
  ❌ NOT FOUND: [Citation/Case Name]
  Searched: validate_citations, case name search, reporter lookup
  Status: LIKELY HALLUCINATION
  🔗 Search CourtListener: https://www.courtlistener.com/?q=[url-encoded+case+name]&type=o

5. MISMATCHED CITATIONS (citation exists but wrong case):
  ⚠️ MISMATCH: [Claimed Case Name]
  Cited in Brief: [Case Name], [Citation] ([Year])
  Actual Case Found: [Different Case Name], same citation
  🔗 View Actual Case: [courtlistener_url]

6. RISK ASSESSMENT (always include last):
  🚨 RISK ASSESSMENT
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Overall Risk Level: [CRITICAL/HIGH/MEDIUM/LOW]
  Use courtlistener_citations_get_guidance(section='risk_assessment') for level definitions.
""".strip()


def _hallucination_patterns_section() -> str:
    return """
AI HALLUCINATION DETECTION PATTERNS
====================================

COMMON AI HALLUCINATION PATTERNS:
  1. Real case name + fabricated citation number
  2. Fabricated case name + real citation number
  3. Plausible-sounding case that doesn't exist
  4. Mix of valid and fabricated citations (very common)
  5. Wrong court or jurisdiction for citation
  6. Inventor/party name confusions (e.g., "DABUS" vs "Thaler")
  7. Correct citation format pointing to WRONG case (MISMATCH)

MISMATCH EXAMPLES (citation exists but wrong case):
  Example: Brief cites "eBay Inc. v. MercExchange, 646 F.3d 869 (Fed. Cir. 2011)"
  Reality: 646 F.3d 869 is actually TiVo Inc. v. EchoStar Corp.
  Correct: eBay v. MercExchange is 547 U.S. 388 (2006) (Supreme Court)
  Pattern: AI combined a real case name with a citation from a related
  patent case (both involve injunctions).

  Example: Brief cites "DABUS v. Vidal, 985 F.3d 1234 (Fed. Cir. 2021)"
  Reality: The real case is Thaler v. Vidal (inventor's name, not the AI)
  Pattern: AI confused the AI system name with the party name.

HOW TO DETECT MISMATCHES:
  1. validate_citations returns 200 but case_name doesn't match
  2. Compare returned case_name against what the document claims
  3. If names differ significantly, flag as MISMATCH
  4. Use search_cases with the CLAIMED case name to find correct citation

COMMON FABRICATION EXAMPLES:
  - "Smith v. Patent Office (2024)" - Completely fabricated
  - "DABUS v. Vidal" - Wrong party name (should be Thaler)
  - Supreme Court citation returning Federal Circuit case
  - Mix of 3 real cases + 1 invented case in same brief

CITATION FORMATS TO DETECT:
  - "[Party] v. [Party], [Citation] ([Year])"
  - "[Party] v. [Party] ([Year])"
  - "In [Case Name]..."
  - "[Citation]" (standalone reporter citation)
""".strip()


def _edge_cases_section() -> str:
    return """
EDGE CASES AND SPECIAL HANDLING
===============================

SUPREME COURT PARALLEL CITATIONS:
  Symptom: SCOTUS citation (e.g., "573 U.S. 208") returns 404
  Cause: Case indexed under different reporter
  Solution: Try parallel citations (S. Ct., L. Ed.)
  Example: "573 U.S. 208" → Try "134 S. Ct. 2347"

MULTIPLE REPORTERS FOR SAME CASE:
  Example: "547 U.S. 388" = "126 S. Ct. 1837" = "165 L. Ed. 2d 505"
  Solution: List primary citation only, note parallels

PRE-2000 CASES NOT FOUND:
  Historical coverage varies by court. Note "May have limited digital coverage."

PUBLISHED VS UNPUBLISHED OPINIONS:
  - Published: Always indexed
  - Unpublished: May not be in database
  - Sealed: Never available

VERY RECENT CASES (last 6 months):
  Valid case may return 404 due to database indexing lag.
  Note "Case may be too recent for database."

STATE COURT CASES:
  Coverage varies by jurisdiction. Check state-specific databases if not found.

ADMINISTRATIVE AGENCY DECISIONS:
  Examples: PTAB, USPTO, NLRB, EEOC
  Coverage limited to federal appellate review cases.

MISMATCH DETECTION (citation exists but wrong case):
  1. validate_citations returns status 200
  2. But case_name differs from what the document claims
  3. Example: Document says "eBay v. MercExchange, 646 F.3d 869"
     but 646 F.3d 869 is actually "TiVo v. EchoStar"
  4. Flag as ⚠️ MISMATCH, show both cases
  5. Use search_cases(case_name="eBay v MercExchange") to find correct citation

  Common patterns:
  - Cases in same legal area with similar themes
  - AI picks a valid citation from a related case
  - Party name correct but citation belongs to different proceeding
""".strip()


def _risk_assessment_section() -> str:
    return """
RISK ASSESSMENT GUIDE
=====================

OVERALL RISK LEVELS:
  CRITICAL: >20% citations not found or mismatched
  HIGH: 10-20% citations problematic
  MEDIUM: 5-10% citations problematic
  LOW: <5% citations problematic (some may be coverage gaps)

INTERPRETING RESULTS:
  - NOT FOUND citations are LIKELY fabrications if:
    * Case name sounds plausible but doesn't exist
    * Citation number format is valid but points to nothing
    * Mix of real and fabricated citations in same document

  - NOT FOUND may be LEGITIMATE if:
    * Very recent case (last 6 months - database lag)
    * Unpublished/sealed opinion
    * State court (coverage varies)
    * Administrative agency decision

  - MISMATCH citations indicate:
    * Real citation number pointing to different case
    * Possibly confused with similar case
    * May indicate copy-paste error

RECOMMENDED ACTIONS:
  1. Verify all citations using provided CourtListener links
  2. Replace any NOT FOUND citations
  3. Confirm MISMATCH citations point to intended cases
  4. For PARTIAL MATCH, verify the correct reporter citation
""".strip()


def _limitations_section() -> str:
    return """
COURTLISTENER COVERAGE & LIMITATIONS
=====================================

WHAT IS CHECKED:
  - Case existence in CourtListener database (18M+ citations)
  - Citation format validity (via Eyecite, 50M+ citations analyzed)
  - Reporter abbreviation normalization (typo correction)
  - Basic metadata matching (case name, court, date)

WHAT IS NOT CHECKED (CourtListener validation):
  - Whether case supports the legal argument (requires human review)
  - Whether quotes are accurate (requires reading full opinion)
  - Whether case law is still good law (needs Shepardize/KeyCite)
  - Statutes, law journals: extract_citations identifies them but cannot validate
  - id. / supra: extract_citations resolves them to antecedents but cannot validate

API THROTTLES (citation-lookup endpoint):
  - 60 valid citations per minute (API-enforced)
  - 250 citations max per single request (overflow gets 429 status)
  - 64,000 characters max per request (~50 pages)
  - Large texts are automatically chunked by the MCP client

COURTLISTENER COVERAGE:
  EXCELLENT: Federal appellate courts, Supreme Court
  GOOD: Federal district courts (published decisions)
  VARIABLE: State appellate courts
  LIMITED: State trial courts, administrative agencies
  NONE: Sealed/redacted opinions, some very recent filings

COMMON FALSE NEGATIVES (valid case not found):
  - Supreme Court cases sometimes indexed under different reporter
    (e.g., "573 U.S. 208" vs "134 S. Ct. 2347")
  - Use search_cases with case_name as fallback
  - Try parallel citations (S. Ct., L. Ed.)

DATABASE LAG:
  - Most cases indexed within days of filing
  - Some state courts may have weeks of lag
  - Historical coverage varies by court
""".strip()


# Server instructions constant (for FastMCP tool search optimization)
SERVER_INSTRUCTIONS = """
CourtListener Citation Validation MCP provides 6 tools for extracting and
validating legal citations in documents against the CourtListener database.

PRIMARY USE CASE: Detect AI-generated hallucinated citations in legal briefs.

CRITICAL RULES — ALWAYS FOLLOW:
- NEVER use web search to verify or override citation results
- CourtListener is the SOLE authoritative source for citation validation
- status 404 = ⚠️ SUSPECT — do not override with Wikipedia, Westlaw, or any external source
- status 200 = ✅ VERIFIED — courtlistener_url is in the clusters[0] object, use it directly
- status 404 = ⚠️ SUSPECT — search_url is pre-built in the result, present it as 🔗 link

ALWAYS-AVAILABLE TOOLS (non-deferred, immediate access):
1. courtlistener_validate_citations - Primary citation validation from document text
2. courtlistener_citations_get_guidance - Workflow guidance and documentation

SUPPORTING TOOLS (search for these as needed):
- courtlistener_extract_citations - Local citation extraction, all types, no API key needed
- courtlistener_search_cases - Fallback search by case name when citation not found
- courtlistener_lookup_citation - Direct reporter citation lookup (last resort)
- courtlistener_get_cluster - Full case details and CourtListener URLs
- courtlistener_search_clusters - Search opinion clusters with filters

CITATION VALIDATION WORKFLOW:
0. courtlistener_extract_citations (DISCOVERY) - Extract all citation types locally
1. courtlistener_validate_citations (PRIMARY) - Validate case citations via CourtListener API
2. courtlistener_search_cases (FALLBACK) - Search by case name if citation not found
3. courtlistener_lookup_citation (LAST RESORT) - Direct reporter citation lookup

PROGRESSIVE WORKFLOW:
1. Discovery: Use courtlistener_extract_citations to inventory all citation types
2. Validation: Use courtlistener_validate_citations for case citations
3. Fallback: Use courtlistener_search_cases for any 404 results
4. Details: Search for courtlistener_lookup_citation or courtlistener_get_cluster tools
5. Guidance: Use courtlistener_citations_get_guidance for workflow help and risk assessment
   Sections: overview, workflow, response_format, hallucination_patterns,
   edge_cases, risk_assessment, limitations

SUPPORTING TOOLS (discovered on-demand):
5. courtlistener_get_cluster - Get full case details and CourtListener URLs
6. courtlistener_search_clusters - Search opinion clusters with filters
7. courtlistener_lookup_citation - Direct reporter citation lookup
""".strip()
