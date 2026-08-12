from vyom.retrieve.router import route


def test_bse_query():
    d = route("What is HDFC Bank NPA in latest annual report?")
    assert "bse" in d.sources


def test_sebi_query():
    d = route("Latest SEBI circular on NBFC co-lending norms")
    assert "sebi" in d.sources


def test_rbi_query():
    d = route("What is the current repo rate and CPI inflation?")
    assert "rbi" in d.sources


def test_cross_source_query():
    d = route(
        "Given HDFC Bank NPA risk, what does RBI repo rate say "
        "and any SEBI circular on lending norms?"
    )
    assert len(d.sources) >= 2


def test_general_query_defaults():
    d = route("tell me about this company")
    assert len(d.sources) >= 1


def test_enabled_sources_filter():
    d = route("What is the repo rate?", enabled_sources=["bse"])
    assert "rbi" not in d.sources


def test_rationale_is_string():
    d = route("HDFC Bank results")
    assert isinstance(d.rationale, str)
    assert len(d.rationale) > 0


def test_sebi_brsr_query():
    d = route("What are SEBI BRSR disclosure requirements?")
    assert "sebi" in d.sources
    