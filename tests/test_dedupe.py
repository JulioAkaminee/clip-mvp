"""Testes de deduplicação por overlap temporal / punchline repetida (SPEC §3, §14.3)."""

from __future__ import annotations

from clip_mvp.dedupe import (
    DedupeItem,
    content_tokens,
    dedupe_items,
    temporal_overlap_ratio,
    text_similarity,
    token_overlap_ratio,
)


def test_temporal_overlap_ratio_full_containment_is_1():
    # B (10-20) está totalmente contido em A (0-30): overlap relativo a B = 1.0
    assert temporal_overlap_ratio(0, 30, 10, 20) == 1.0


def test_temporal_overlap_ratio_no_overlap_is_0():
    assert temporal_overlap_ratio(0, 10, 20, 30) == 0.0


def test_temporal_overlap_ratio_partial():
    # A: 0-10, B: 5-15 -> intersecao 5-10 (5s), menor janela = 10s -> 0.5
    assert temporal_overlap_ratio(0, 10, 5, 15) == 0.5


def test_text_similarity_identical_is_1():
    assert text_similarity("mesma piada aqui", "mesma piada aqui") == 1.0


def test_text_similarity_different_is_low():
    assert text_similarity("um assunto totalmente diferente", "outra coisa qualquer sem relacao") < 0.5


def test_dedupe_removes_overlapping_keeps_higher_score():
    items = [
        DedupeItem(item="A", start=0, end=20, text="piada do carro", score=70),
        DedupeItem(item="B", start=5, end=15, text="piada completamente diferente sobre outra coisa", score=90),
    ]
    result = dedupe_items(items)
    assert result.kept == ["B"]
    assert result.removed_count == 1


def test_dedupe_removes_similar_text_keeps_higher_score():
    items = [
        DedupeItem(item="low", start=0, end=10, text="ele contou a piada do carro quebrado", score=55),
        DedupeItem(item="high", start=200, end=210, text="ele contou a piada do carro quebrado", score=88),
    ]
    result = dedupe_items(items)
    assert result.kept == ["high"]
    assert result.removed_count == 1


def test_dedupe_keeps_distinct_candidates():
    items = [
        DedupeItem(item="A", start=0, end=10, text="assunto A totalmente distinto", score=60),
        DedupeItem(item="B", start=100, end=110, text="assunto B nada a ver com o outro", score=65),
        DedupeItem(item="C", start=300, end=310, text="assunto C tambem diferente de tudo", score=70),
    ]
    result = dedupe_items(items)
    assert set(result.kept) == {"A", "B", "C"}
    assert result.removed_count == 0


def test_short_texts_are_not_treated_as_the_same_moment():
    """Dois trechos curtos batem quase 100% por acaso — não são duplicata."""
    items = [
        DedupeItem(item="a", start=0.0, end=30.0, text="Isso mudou tudo.", score=90.0),
        DedupeItem(item="b", start=600.0, end=630.0, text="Isso mudou tudo.", score=80.0),
    ]
    result = dedupe_items(items)
    assert result.kept == ["a", "b"]
    assert result.removed_count == 0


def test_long_near_identical_texts_are_still_deduped():
    text = (
        "eu perdi oitenta mil reais no primeiro ano por vergonha de cobrar o preço "
        "certo, porque eu olhava pro cliente e falava um número trinta por cento "
        "menor do que tinha calculado em casa antes da reunião"
    )
    items = [
        DedupeItem(item="a", start=0.0, end=60.0, text=text, score=90.0),
        DedupeItem(item="b", start=600.0, end=660.0, text=text, score=70.0),
    ]
    result = dedupe_items(items)
    assert result.kept == ["a"]
    assert result.removed_count == 1


def test_text_similarity_respects_min_words():
    assert text_similarity("mudou tudo", "mudou tudo", min_words=6) == 0.0
    assert text_similarity("mudou tudo", "mudou tudo") > 0.9


class TestContentTokens:
    def test_stopwords_and_accents_are_normalized_away(self):
        tokens = content_tokens("Eu não acredito que a Márcia falou isso do preço")
        assert "marcia" in tokens
        assert "preco" in tokens
        # funcionais somem: não dizem nada sobre o assunto
        assert "que" not in tokens
        assert "nao" not in tokens

    def test_overlap_uses_the_shorter_vocabulary_as_denominator(self):
        short = content_tokens("vergonha de cobrar o preço certo do orçamento")
        long = content_tokens(
            "eu tinha vergonha de cobrar o preço certo do orçamento e por isso perdi "
            "oitenta mil reais no primeiro ano inteiro da empresa"
        )
        assert token_overlap_ratio(short, long) == 1.0

    def test_unrelated_topics_do_not_overlap(self):
        a = content_tokens("a receita do bolo de cenoura da minha avó ficou perfeita")
        b = content_tokens("o mercado de criptomoedas quebrou de novo nesta semana")
        assert token_overlap_ratio(a, b) < 0.2

    def test_tiny_vocabularies_are_ignored(self):
        assert token_overlap_ratio(content_tokens("mudou tudo"), content_tokens("mudou tudo")) == 0.0


class TestSameIdeaDifferentWords:
    def test_the_same_punchline_rephrased_is_deduped(self):
        """Mesma ideia, janelas diferentes: o texto literal não bate, o assunto sim.

        A comparação caractere-a-caractere passava batido nesse caso e o job
        entregava dois cortes da mesma história (SPEC §14.3).
        """
        items = [
            DedupeItem(
                item="curto",
                start=0.0,
                end=40.0,
                text=(
                    "eu tinha vergonha de cobrar o preço certo, então dava desconto "
                    "antes mesmo de o cliente pedir"
                ),
                score=70.0,
            ),
            DedupeItem(
                item="longo",
                start=400.0,
                end=470.0,
                text=(
                    "olha, no primeiro ano eu dava desconto antes de o cliente pedir "
                    "qualquer coisa, porque eu tinha vergonha de cobrar o preço certo, "
                    "e isso custou caro"
                ),
                score=88.0,
            ),
        ]
        result = dedupe_items(items)
        assert result.kept == ["longo"]
        assert result.removed_reasons[0].startswith("token_overlap=")
        # o texto literal jamais teria disparado a regra antiga
        assert text_similarity(items[0].text, items[1].text, min_words=6) < 0.82


class TestVerticalWindowOverlap:
    def test_two_candidates_with_nearly_the_same_short_are_deduped(self):
        """O 16:9 mal se sobrepõe, mas os dois 9:16 são praticamente o mesmo Short.

        É o 9:16 que vai para o TikTok, então olhar só o 16:9 deixava passar
        duas publicações quase idênticas.
        """
        items = [
            DedupeItem(
                item="a",
                start=0.0,
                end=200.0,
                text="uma discussao longa sobre precificacao de servicos criativos",
                score=90.0,
                alt_start=180.0,
                alt_end=230.0,
            ),
            DedupeItem(
                item="b",
                start=170.0,
                end=400.0,
                text="outra conversa completamente distinta sobre contratacao de equipe",
                score=80.0,
                alt_start=182.0,
                alt_end=232.0,
            ),
        ]
        result = dedupe_items(items)
        assert result.kept == ["a"]
        assert result.removed_reasons[0].startswith("overlap_9x16=")

    def test_distinct_verticals_inside_overlapping_context_survive(self):
        items = [
            DedupeItem(
                item="a",
                start=0.0,
                end=200.0,
                text="uma discussao longa sobre precificacao de servicos criativos",
                score=90.0,
                alt_start=10.0,
                alt_end=60.0,
            ),
            DedupeItem(
                item="b",
                start=120.0,
                end=400.0,
                text="outra conversa completamente distinta sobre contratacao de equipe",
                score=80.0,
                alt_start=300.0,
                alt_end=350.0,
            ),
        ]
        result = dedupe_items(items)
        assert set(result.kept) == {"a", "b"}


def test_long_text_similarity_is_bounded_in_cost():
    """Excerpt gigante não pode custar O(n²) de CPU no dedupe."""
    a = "palavra " * 5000
    b = "palavra " * 5000 + "diferente"
    # Se o custo não fosse limitado, isso levaria segundos; aqui é imediato.
    assert text_similarity(a, b) > 0.9
