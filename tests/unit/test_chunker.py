from vyom.ingest.chunker import chunk_text, add_context_prefix


def test_basic_chunking():
    text = " ".join(["word"] * 600)
    chunks = chunk_text(text, chunk_size=100, overlap=10)
    assert len(chunks) > 1
    assert chunks[0].index == 0
    assert chunks[1].index == 1


def test_section_label():
    chunks = chunk_text("some text here", section="mda")
    assert all(c.section == "mda" for c in chunks)


def test_empty_text_returns_empty():
    assert chunk_text("") == []


def test_context_prefix():
    chunks = chunk_text("HDFC Bank reported strong results", section="mda")
    result = add_context_prefix(chunks, "HDFC Bank FY2025 Annual Report")
    assert "HDFC Bank FY2025" in result[0].context_prefix


def test_overlap_creates_shared_words():
    text = " ".join([str(i) for i in range(200)])
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    # Last words of chunk 0 should appear in start of chunk 1
    end_of_first = chunks[0].content.split()[-5:]
    start_of_second = chunks[1].content.split()[:25]
    overlap_found = any(w in start_of_second for w in end_of_first)
    assert overlap_found
    