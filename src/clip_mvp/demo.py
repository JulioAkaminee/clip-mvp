"""Modo demo: pipeline completo sem chamar OpenRouter.

Serve para (a) rodar a UI de ponta a ponta sem chave/custo e (b) testar render,
legendas e fronteiras de forma determinística. Nada aqui substitui a IA em
produção — quando `OPENROUTER_API_KEY` existe e `--demo` não é passado, os
módulos reais assumem.
"""

from __future__ import annotations

import hashlib
import random

from .transcript import Segment, Transcript, Word

SCRIPT: list[str] = [
    "Cara, deixa eu te perguntar uma coisa que eu queria saber desde o começo dessa conversa.",
    "Você largou um emprego estável pra abrir a empresa sozinho, sem nenhum investidor.",
    "Como é que você explicou isso pra sua família na época?",
    "Olha, foi o pior almoço de domingo da minha vida, sinceramente.",
    "Minha mãe achou que eu tinha sido demitido e estava com vergonha de contar.",
    "Meu pai só perguntou se eu ia conseguir pagar o aluguel no mês seguinte.",
    "E a resposta honesta era não, eu não ia conseguir.",
    "Eu tinha três meses de reserva e um cliente que ainda não tinha assinado nada.",
    "Aí eu fiz a coisa mais burra e mais certa que eu já fiz na vida.",
    "Eu liguei pra esse cliente e falei que já tinha pedido demissão por causa dele.",
    "E ele riu, mandou o contrato no mesmo dia e virou meu sócio dois anos depois.",
    "Espera, o cara que quase te deixou na rua virou seu sócio?",
    "Virou. E hoje ele conta essa história em palestra como se a ideia fosse dele.",
    "Isso é muito engraçado e muito injusto ao mesmo tempo.",
    "Mas eu quero voltar num ponto que você falou rápido e passou batido.",
    "Você disse que foi a coisa mais burra e mais certa. Por quê as duas?",
    "Porque burra é apostar a sua sobrevivência num contrato que não existe.",
    "E certa é porque eu criei uma urgência real, do tipo que ninguém consegue fingir.",
    "Quando você não tem plano B, você para de mandar mensagem bonitinha e vai atrás.",
    "Eu não recomendo pra ninguém, mas eu faria de novo do mesmo jeito.",
    "Tem uma frase que eu ouvi no começo e que eu odiei por uns três anos.",
    "Me falaram assim: você não tem um problema de dinheiro, você tem um problema de coragem.",
    "Na hora eu achei aquilo a coisa mais arrogante do mundo.",
    "Hoje eu acho que estava certo, mas dito da pior forma possível.",
    "E o que mudou pra você entender isso?",
    "Eu comecei a perceber que eu ficava dois meses arrumando um site pra não ligar pro cliente.",
    "O site era desculpa, o medo era o telefone.",
    "Isso é a coisa mais real que você falou hoje, e a mais dolorida pra quem tá ouvindo.",
    "Todo mundo tem um site que é desculpa pra não fazer a ligação.",
    "Exatamente. E o teu site vai ficar lindo enquanto a tua empresa morre.",
    "Vamos falar de dinheiro de verdade, porque essa parte todo mundo esconde.",
    "Quanto você tirava por mês no primeiro ano, sem romantizar?",
    "Nada nos primeiros cinco meses, e depois uns dois mil e quinhentos.",
    "Eu morava com um colega, dividia internet e comia arroz com ovo umas quatro vezes por semana.",
    "E eu postava foto de café em coworking como se estivesse vencendo.",
    "O marketing pessoal era melhor que o fluxo de caixa.",
    "Isso é praticamente um resumo do empreendedorismo brasileiro em uma frase.",
    "E o que você faria diferente se voltasse pro primeiro dia hoje?",
    "Eu cobraria mais caro no primeiro contrato e não pediria desculpa pelo preço.",
    "Desconto no começo não compra cliente, compra cliente ruim.",
    "Essa eu vou levar tatuada, porque eu errei isso por seis anos seguidos.",
]

MONOLOGUE = [
    "Deixa eu explicar isso com calma porque é o ponto mais importante da conversa.",
    "Quando a gente fala de operação, todo mundo pensa em planilha e em processo bonito.",
    "Mas operação de verdade é decidir o que você não vai fazer naquela semana.",
    "Eu levei quatro anos e uma equipe inteira pedindo demissão pra entender isso.",
    "Na prática a gente tinha onze prioridades, o que significa que a gente não tinha nenhuma.",
    "Todo mundo trabalhava muito e nada terminava, e eu chamava isso de time comprometido.",
    "O que eu fiz foi cortar sete frentes num sábado e avisar os clientes na segunda.",
    "Perdi trinta por cento do faturamento em dois meses e dormi pela primeira vez em um ano.",
    "Seis meses depois a gente tinha faturado mais do que no ano anterior inteiro.",
    "Então quando eu falo que foco dói, eu não falo por frase de efeito, eu falo por boleto.",
    "E tem uma parte dessa história que eu nunca contei em entrevista nenhuma até hoje.",
    "Duas das pessoas que saíram naquele mês eram as duas melhores que eu já contratei.",
    "Elas não saíram por dinheiro, saíram porque não aguentavam mais a bagunça de prioridade.",
    "Uma delas me mandou um documento de nove páginas explicando tudo o que estava errado.",
    "Eu li aquilo três vezes e chorei na terceira, porque estava tudo certo, ponto por ponto.",
    "Aí eu chamei o time que ficou e leu o documento inteiro em voz alta na reunião.",
    "Foi a coisa mais desconfortável que eu já fiz como gestor, e a mais útil também.",
    "Desde aquele dia a gente escreve no quadro uma prioridade só, e ela fica lá o mês inteiro.",
    "Quando alguém pede uma coisa nova, a resposta é: qual dessas você quer tirar do lugar?",
    "Noventa por cento das vezes a pessoa desiste na hora, porque não era prioridade nenhuma.",
]

WORDS_PER_SECOND = 2.6
GAP_S = 0.28


def _sentence_pool(duration_s: float) -> list[tuple[str, bool]]:
    """Falas cobrindo a duração; o bool marca o monólogo longo (contexto único)."""
    pool: list[tuple[str, bool]] = []
    inserted_monologue = False
    while _estimated_duration(pool) < duration_s:
        remaining = duration_s - _estimated_duration(pool)
        if not inserted_monologue and remaining > 200:
            pool.extend((line, True) for line in MONOLOGUE)
            inserted_monologue = True
            continue
        pool.extend((line, False) for line in SCRIPT)
    return pool


def _estimated_duration(sentences: list[tuple[str, bool]]) -> float:
    total = 0.0
    for sentence, _ in sentences:
        total += len(sentence.split()) / WORDS_PER_SECOND + GAP_S
    return total


def build_transcript(duration_s: float, seed: str = "demo") -> Transcript:
    """Transcrição sintética PT-BR com word timestamps e pontuação real."""
    rng = random.Random(int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16))
    segments: list[Segment] = []
    t = 0.6
    speaker_index = 0
    for sentence, monologue in _sentence_pool(duration_s):
        tokens = sentence.split()
        words: list[Word] = []
        for token in tokens:
            length = len(token)
            dur = max(0.16, min(0.62, length / 9.0 + rng.uniform(0.06, 0.16)))
            if t + dur > duration_s:
                break
            words.append(Word(start=round(t, 3), end=round(t + dur, 3), text=token))
            t = t + dur + rng.uniform(0.01, 0.05)
        if not words:
            break
        # No monólogo o mesmo falante segura o turno: o contexto só fecha no fim.
        speaker_index = 1 if monologue else (speaker_index + 1) % 2
        segments.append(
            Segment(
                start=words[0].start,
                end=words[-1].end,
                text=" ".join(w.text for w in words),
                speaker=f"SPEAKER_{speaker_index:02d}",
                words=words,
            )
        )
        t += GAP_S + rng.uniform(0.0, 0.25)
        if t >= duration_s:
            break
    return Transcript(
        duration=duration_s,
        segments=segments,
        language="pt",
        stt_model="demo/local-synthetic",
        diarization=True,
    )
