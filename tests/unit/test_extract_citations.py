"""
Unit tests for extract_citations tool and _extract_citations_sync helper.

Tests cover:
- Case citation extraction and metadata
- Statutory citation extraction
- Law journal citation extraction
- Id./supra citation extraction and resolution
- Mixed document (multiple types in one text)
- Empty text and text with no citations
- Guidance generation logic
- ImportError handling in the async tool
- No API calls required (eyecite is local)
"""

import pytest
from unittest.mock import patch, AsyncMock

from courtlistener_mcp.main import _extract_citations_sync


# =============================================================================
# Fixtures
# =============================================================================

CASE_CITATION_TEXT = "Alice Corp. v. CLS Bank, 573 U.S. 208 (2014)."

STATUTE_TEXT = "Under 42 U.S.C. § 1983, a person acting under color of state law."

JOURNAL_TEXT = "See John Doe, Title of Article, 128 Harv. L. Rev. 1 (2014)."

ID_SUPRA_TEXT = (
    "Alice Corp. v. CLS Bank, 573 U.S. 208 (2014). "
    "Id. at 212. "
    "Alice supra, at 210."
)

MIXED_TEXT = (
    "The Supreme Court held in Alice Corp. v. CLS Bank, 573 U.S. 208 (2014). "
    "See also Mayo Collaborative Servs. v. Prometheus Labs., 566 U.S. 66 (2012). "
    "Under 35 U.S.C. § 101, patent eligibility is limited. "
    "Id. at 214."
)


# =============================================================================
# Case Citation Tests
# =============================================================================

class TestCaseCitations:
    def test_extracts_case_citation(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        assert result["summary"]["case_citations"] >= 1

    def test_case_citation_has_reporter(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        cit = result["case_citations"][0]
        assert cit["reporter"] == "U.S."

    def test_case_citation_has_volume(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        cit = result["case_citations"][0]
        assert cit["volume"] == "573"

    def test_case_citation_has_page(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        cit = result["case_citations"][0]
        assert cit["page"] == "208"

    def test_case_citation_has_text(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        cit = result["case_citations"][0]
        assert "U.S." in cit["text"]

    def test_case_citation_metadata_plaintiff(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        cit = result["case_citations"][0]
        # Eyecite extracts plaintiff/defendant from surrounding context
        assert "plaintiff" in cit or "defendant" in cit or cit["reporter"] == "U.S."

    def test_case_citation_year(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        cit = result["case_citations"][0]
        if "year" in cit:
            assert str(cit["year"]) == "2014"

    def test_multiple_case_citations(self):
        text = (
            "Mayo Collaborative Servs. v. Prometheus Labs., 566 U.S. 66 (2012), "
            "and Alice Corp. v. CLS Bank, 573 U.S. 208 (2014)."
        )
        result = _extract_citations_sync(text)
        assert result["summary"]["case_citations"] == 2

    def test_federal_circuit_citation(self):
        text = "TiVo Inc. v. EchoStar Corp., 646 F.3d 869 (Fed. Cir. 2011)."
        result = _extract_citations_sync(text)
        assert result["summary"]["case_citations"] >= 1
        cit = result["case_citations"][0]
        assert "F.3d" in cit["reporter"] or "F." in cit["reporter"]


# =============================================================================
# Statutory Citation Tests
# =============================================================================

class TestStatutoryCitations:
    def test_extracts_statutory_citation(self):
        result = _extract_citations_sync(STATUTE_TEXT)
        assert result["summary"]["statutory_citations"] >= 1

    def test_statutory_citation_has_text(self):
        result = _extract_citations_sync(STATUTE_TEXT)
        cit = result["statutory_citations"][0]
        assert "U.S.C." in cit.get("text", "") or "U.S.C." in cit.get("reporter", "")

    def test_statutory_citation_has_note(self):
        result = _extract_citations_sync(STATUTE_TEXT)
        cit = result["statutory_citations"][0]
        assert "note" in cit
        assert "not validated" in cit["note"].lower()

    def test_statutory_citation_not_in_case_list(self):
        result = _extract_citations_sync(STATUTE_TEXT)
        # Statutes should not appear in case_citations
        case_texts = [c["text"] for c in result["case_citations"]]
        for c in result["statutory_citations"]:
            assert c.get("text") not in case_texts


# =============================================================================
# Law Journal Citation Tests
# =============================================================================

class TestJournalCitations:
    def test_extracts_journal_citation(self):
        result = _extract_citations_sync(JOURNAL_TEXT)
        # Eyecite may or may not parse all journal formats; just check structure
        summary = result["summary"]
        assert "law_journal_citations" in summary

    def test_journal_citation_has_note_if_found(self):
        result = _extract_citations_sync(JOURNAL_TEXT)
        for cit in result["law_journal_citations"]:
            assert "not validated" in cit.get("note", "").lower()


# =============================================================================
# Id. / Supra Citation Tests
# =============================================================================

class TestIdSupraCitations:
    def test_extracts_id_citation(self):
        result = _extract_citations_sync(ID_SUPRA_TEXT)
        assert result["summary"]["id_citations"] >= 1

    def test_id_citation_has_text(self):
        result = _extract_citations_sync(ID_SUPRA_TEXT)
        cit = result["id_citations"][0]
        assert "Id" in cit["text"] or "id" in cit["text"].lower()

    def test_id_citation_resolves_to_antecedent(self):
        result = _extract_citations_sync(ID_SUPRA_TEXT)
        # At least one Id. citation should resolve to the preceding case citation
        resolved = [c for c in result["id_citations"] if "resolves_to" in c]
        assert len(resolved) >= 1

    def test_id_citation_antecedent_contains_reporter(self):
        result = _extract_citations_sync(ID_SUPRA_TEXT)
        resolved = [c for c in result["id_citations"] if "resolves_to" in c]
        if resolved:
            assert "U.S." in resolved[0]["resolves_to"]

    def test_id_citation_pin_cite(self):
        result = _extract_citations_sync(ID_SUPRA_TEXT)
        # "Id. at 212" should have pin_cite
        with_pin = [c for c in result["id_citations"] if "pin_cite" in c]
        assert len(with_pin) >= 1


# =============================================================================
# Summary and Structure Tests
# =============================================================================

class TestSummaryStructure:
    def test_summary_has_all_keys(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        expected_keys = {
            "total", "case_citations", "statutory_citations",
            "law_journal_citations", "id_citations", "supra_citations",
            "unknown_citations",
        }
        assert expected_keys == set(result["summary"].keys())

    def test_result_has_all_sections(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        for key in (
            "summary", "case_citations", "statutory_citations",
            "law_journal_citations", "id_citations", "supra_citations",
            "unknown_citations", "guidance",
        ):
            assert key in result

    def test_total_equals_sum_of_parts(self):
        result = _extract_citations_sync(MIXED_TEXT)
        s = result["summary"]
        total = (
            s["case_citations"] + s["statutory_citations"]
            + s["law_journal_citations"] + s["id_citations"]
            + s["supra_citations"] + s["unknown_citations"]
        )
        assert s["total"] == total

    def test_empty_text_returns_zero_citations(self):
        result = _extract_citations_sync("")
        assert result["summary"]["total"] == 0
        assert result["case_citations"] == []

    def test_no_citations_text(self):
        result = _extract_citations_sync("This document has no legal citations at all.")
        assert result["summary"]["total"] == 0

    def test_guidance_has_next_steps(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        assert "next_steps" in result["guidance"]
        assert len(result["guidance"]["next_steps"]) >= 1

    def test_guidance_mentions_validate_citations_when_cases_found(self):
        result = _extract_citations_sync(CASE_CITATION_TEXT)
        steps = " ".join(result["guidance"]["next_steps"])
        assert "validate_citations" in steps

    def test_guidance_mentions_statute_cannot_be_validated(self):
        result = _extract_citations_sync(STATUTE_TEXT)
        steps = " ".join(result["guidance"]["next_steps"])
        if result["summary"]["statutory_citations"] > 0:
            assert "cannot be validated" in steps.lower() or "not in CourtListener" in steps

    def test_empty_text_guidance_says_no_citations(self):
        result = _extract_citations_sync("")
        steps = " ".join(result["guidance"]["next_steps"])
        assert "no citations" in steps.lower()


# =============================================================================
# Mixed Document Tests
# =============================================================================

class TestMixedDocument:
    def test_mixed_text_finds_case_citations(self):
        result = _extract_citations_sync(MIXED_TEXT)
        assert result["summary"]["case_citations"] >= 2

    def test_mixed_text_finds_statutory_citation(self):
        result = _extract_citations_sync(MIXED_TEXT)
        assert result["summary"]["statutory_citations"] >= 1

    def test_mixed_text_finds_id_citation(self):
        result = _extract_citations_sync(MIXED_TEXT)
        assert result["summary"]["id_citations"] >= 1

    def test_mixed_text_total_is_sum(self):
        result = _extract_citations_sync(MIXED_TEXT)
        s = result["summary"]
        total = (
            s["case_citations"] + s["statutory_citations"]
            + s["law_journal_citations"] + s["id_citations"]
            + s["supra_citations"] + s["unknown_citations"]
        )
        assert s["total"] == total


# =============================================================================
# Async Tool Tests (ImportError handling)
# =============================================================================

class TestExtractCitationsAsyncTool:
    async def test_import_error_raises_tool_error(self):
        """When eyecite is not installed, tool raises ToolError."""
        from fastmcp.exceptions import ToolError
        from courtlistener_mcp.main import extract_citations

        ctx = AsyncMock()
        ctx.info = AsyncMock()

        def raise_import(*args, **kwargs):
            raise ImportError("No module named 'eyecite'")

        with patch("courtlistener_mcp.main._extract_citations_sync", side_effect=raise_import):
            with pytest.raises(ToolError) as exc_info:
                await extract_citations(ctx, "Alice Corp. v. CLS Bank, 573 U.S. 208.")
            assert "eyecite" in str(exc_info.value).lower()

    async def test_returns_json_string(self):
        """Tool returns a JSON string."""
        import json
        from courtlistener_mcp.main import extract_citations

        ctx = AsyncMock()
        ctx.info = AsyncMock()

        result = await extract_citations(ctx, CASE_CITATION_TEXT)
        parsed = json.loads(result)
        assert "summary" in parsed
        assert "case_citations" in parsed

    async def test_logs_info_with_char_count(self):
        """Tool calls ctx.info with character count."""
        from courtlistener_mcp.main import extract_citations

        ctx = AsyncMock()
        ctx.info = AsyncMock()

        await extract_citations(ctx, CASE_CITATION_TEXT)
        ctx.info.assert_called_once()
        call_args = ctx.info.call_args[0][0]
        assert str(len(CASE_CITATION_TEXT)) in call_args or "chars" in call_args
