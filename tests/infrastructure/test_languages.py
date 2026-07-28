from keystrike.infrastructure.languages import BundledLanguageProvider


def test_loads_bundled_english_transitions():
    provider = BundledLanguageProvider()
    table = provider.transitions("en")
    assert table.order == 2
    assert len(table.transitions) > 0


def test_caches_loaded_table():
    provider = BundledLanguageProvider()
    first = provider.transitions("en")
    second = provider.transitions("en")
    assert first is second
