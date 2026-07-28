from keystrike.infrastructure.code_generators.python import PythonCodeGenerator


def test_snippets_are_nonempty_and_single_line():
    generator = PythonCodeGenerator()
    snippets = generator.snippets()
    assert len(snippets) > 0
    for snippet in snippets:
        assert snippet
        assert "\n" not in snippet


def test_snippets_look_like_python():
    generator = PythonCodeGenerator()
    joined = " ".join(generator.snippets())
    assert "def " in joined
    assert "return" in joined
