"""Tests for the filtering and relevance logic."""

from __future__ import annotations

import pandas as pd
import pytest

from gosha.filters import (
    city_only,
    expand_keyword,
    filter_dataframe,
    keyword_wants_entry_level,
    keyword_wants_tech,
    location_matches,
    matches_company_blacklist,
    matches_excluded_keywords,
    matches_experience_level,
    matches_salary_minimum,
    normalize_location,
    title_is_relevant,
)


# ── normalize_location ────────────────────────────────────────────────


class TestNormalizeLocation:
    def test_known_alias(self):
        search, subs = normalize_location("Cluj")
        assert search == "Cluj-Napoca, Romania"
        assert "cluj" in subs

    def test_case_insensitive(self):
        search, subs = normalize_location("BUCHAREST")
        assert search == "Bucharest, Romania"
        assert "bucharest" in subs

    def test_unknown_location_passthrough(self):
        search, subs = normalize_location("New York")
        assert search == "New York"
        assert subs == ["new york"]

    def test_romania_expands_to_multiple_cities(self):
        search, subs = normalize_location("romania")
        assert search == "Romania"
        assert "bucharest" in subs
        assert "cluj" in subs


# ── expand_keyword ────────────────────────────────────────────────────


class TestExpandKeyword:
    def test_known_keyword_expands(self):
        terms = expand_keyword("computer science internship")
        assert len(terms) > 10
        assert "software engineer intern" in terms

    def test_unknown_keyword_passthrough(self):
        terms = expand_keyword("underwater basket weaving")
        assert terms == ["underwater basket weaving"]

    def test_case_insensitive(self):
        terms = expand_keyword("Data Science")
        assert "data scientist" in terms


# ── location_matches ──────────────────────────────────────────────────


class TestLocationMatches:
    def test_match(self):
        assert location_matches("Cluj-Napoca, Romania", ["cluj"]) is True

    def test_no_match(self):
        assert location_matches("Berlin, Germany", ["cluj"]) is False

    def test_empty_location_includes(self):
        assert location_matches("", ["cluj"]) is True

    def test_nan_location_includes(self):
        assert location_matches("nan", ["cluj"]) is True

    def test_none_location_includes(self):
        assert location_matches(None, ["cluj"]) is True  # type: ignore[arg-type]

    def test_multiple_substrings(self):
        assert location_matches("București, Romania", ["bucuresti", "bucurești"]) is True


# ── keyword_wants_entry_level ─────────────────────────────────────────


class TestKeywordWantsEntryLevel:
    def test_internship(self):
        assert keyword_wants_entry_level("computer science internship") is True

    def test_junior(self):
        assert keyword_wants_entry_level("junior developer") is True

    def test_generic(self):
        assert keyword_wants_entry_level("software engineer") is False


# ── keyword_wants_tech ────────────────────────────────────────────────


class TestKeywordWantsTech:
    def test_known_expansion(self):
        assert keyword_wants_tech("computer science") is True

    def test_tech_keyword(self):
        assert keyword_wants_tech("cloud engineer") is True

    def test_non_tech(self):
        assert keyword_wants_tech("marketing manager") is False


# ── title_is_relevant ─────────────────────────────────────────────────


class TestTitleIsRelevant:
    def test_intern_title_for_intern_keyword(self):
        assert title_is_relevant("Software Engineer Intern", "computer science internship") is True

    def test_senior_title_rejected_for_intern_keyword(self):
        assert title_is_relevant("Senior Software Engineer", "computer science internship") is False

    def test_non_entry_rejected_for_intern_keyword(self):
        assert title_is_relevant("Software Engineer", "computer science internship") is False

    def test_tech_title_for_tech_keyword(self):
        assert title_is_relevant("Backend Developer", "software engineering") is True

    def test_non_tech_rejected(self):
        assert title_is_relevant("Marketing Manager", "software engineering") is False

    def test_generic_keyword_passes_all(self):
        assert title_is_relevant("Anything Goes", "random keyword") is True

    def test_empty_title_rejected(self):
        assert title_is_relevant("", "software engineering") is False


# ── matches_excluded_keywords ─────────────────────────────────────────


class TestMatchesExcludedKeywords:
    def test_match(self):
        assert matches_excluded_keywords("Sales Engineer at TechCo", ["sales"]) is True

    def test_no_match(self):
        assert matches_excluded_keywords("Backend Developer", ["sales"]) is False

    def test_empty_exclusions(self):
        assert matches_excluded_keywords("Anything", []) is False

    def test_case_insensitive(self):
        assert matches_excluded_keywords("SALES rep", ["sales"]) is True


# ── matches_company_blacklist ─────────────────────────────────────────


class TestMatchesCompanyBlacklist:
    def test_match(self):
        assert matches_company_blacklist("Accenture", ["Accenture", "Deloitte"]) is True

    def test_no_match(self):
        assert matches_company_blacklist("Google", ["Accenture"]) is False

    def test_case_insensitive(self):
        assert matches_company_blacklist("accenture", ["Accenture"]) is True

    def test_empty_blacklist(self):
        assert matches_company_blacklist("Anyone", []) is False


# ── matches_salary_minimum ────────────────────────────────────────────


class TestMatchesSalaryMinimum:
    def test_no_filter(self):
        assert matches_salary_minimum(None, 30000, 50000) is True

    def test_meets_minimum(self):
        assert matches_salary_minimum(40000, 30000, 50000) is True

    def test_below_minimum(self):
        assert matches_salary_minimum(60000, 30000, 50000) is False

    def test_no_salary_data_includes(self):
        assert matches_salary_minimum(40000, None, None) is True

    def test_only_min_salary(self):
        assert matches_salary_minimum(30000, 35000, None) is True

    def test_only_min_salary_below(self):
        assert matches_salary_minimum(50000, 35000, None) is False


# ── matches_experience_level ──────────────────────────────────────────


class TestMatchesExperienceLevel:
    def test_any_matches_everything(self):
        assert matches_experience_level("CEO", ["any"]) is True

    def test_empty_matches_everything(self):
        assert matches_experience_level("CEO", []) is True

    def test_intern(self):
        assert matches_experience_level("Software Engineer Intern", ["intern"]) is True

    def test_junior(self):
        assert matches_experience_level("Junior Developer", ["junior"]) is True

    def test_mid_level(self):
        assert matches_experience_level("Software Engineer", ["mid"]) is True

    def test_mid_rejects_senior(self):
        assert matches_experience_level("Senior Engineer", ["mid"]) is False

    def test_mid_rejects_intern(self):
        assert matches_experience_level("Intern", ["mid"]) is False

    def test_senior(self):
        assert matches_experience_level("Senior Backend Developer", ["senior"]) is True

    def test_multiple_levels(self):
        assert matches_experience_level("Junior Dev", ["intern", "junior"]) is True
        assert matches_experience_level("Senior Dev", ["intern", "junior"]) is False


# ── city_only ─────────────────────────────────────────────────────────


class TestCityOnly:
    def test_city_country(self):
        assert city_only("Cluj-Napoca, Romania") == "Cluj-Napoca"

    def test_city_only_input(self):
        assert city_only("Dublin") == "Dublin"


# ── filter_dataframe ──────────────────────────────────────────────────


class TestFilterDataframe:
    def test_filters_irrelevant_titles(self):
        df = pd.DataFrame({
            "title": [
                "Software Engineer Intern",
                "Marketing Manager",
                "Data Analyst Intern",
                "Senior VP of Sales",
            ]
        })
        result = filter_dataframe(df, "computer science internship")
        assert len(result) == 2
        assert "Software Engineer Intern" in result["title"].values
        assert "Data Analyst Intern" in result["title"].values

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = filter_dataframe(df, "anything")
        assert result.empty

    def test_no_title_column(self):
        df = pd.DataFrame({"company": ["Acme"]})
        result = filter_dataframe(df, "anything")
        assert len(result) == 1  # returned as-is
