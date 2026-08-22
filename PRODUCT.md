# Product

## Register

product

## Users

Um usuário só: o Julio, no MacBook dele, com o Terminal aberto ao lado. Ele
conhece a ferramenta por dentro — escreveu boa parte dela — então a tela não
precisa ensinar o que já está óbvio para quem opera. O que ele precisa é
**decidir rápido**: este corte presta? qual publico primeiro? o que copio para
o TikTok?

O contexto de uso tem duas metades bem diferentes:

- **Esperando** (20 a 30 min por vídeo): ele dispara um job e vai fazer outra
  coisa. Volta à aba de vez em quando para ver se ainda anda. A tela precisa
  responder "está vivo e falta quanto" de relance, de longe, sem ler.
- **Escolhendo** (5 a 10 min): o job terminou e ele revisa 5 a 15 cortes,
  decide quais valem, copia os textos e baixa. Aqui a tela é uma bancada de
  triagem: assistir, julgar, descartar, levar.

## Product Purpose

Transformar um podcast de três horas em cortes prontos para publicar, sem
cortar ninguém no meio da frase. Sucesso é ele abrir a tela depois do
processamento e, em poucos minutos, sair com os arquivos e os textos na mão —
sem abrir o Finder, sem reescrever título, sem conferir se o vídeo ficou torto.

O produto acerta quando ele confia na nota o bastante para publicar o primeiro
corte sem assistir aos outros quatro.

## Brand Personality

**Bancada de criador.** O vídeo é o herói: miniatura grande, imagem antes de
texto, a tela existe para emoldurar o conteúdo. Energia vem do material e do
trabalho acontecendo — não de enfeite.

Voz: direta, sem cerimônia, sem jargão. Diz o que aconteceu e o que fazer.
Nunca festeja o óbvio ("Tudo pronto! 🎉") nem se desculpa em excesso.

## Anti-references

- **SaaS genérico**: gradiente roxo, grade de cards idênticos com ícone +
  título + parágrafo, ilustração de bonequinho, tudo com a mesma sombra.
- **Enfeitada demais**: animação em cada elemento, brilho, vidro fosco como
  decoração, movimento que compete com o vídeo em vez de guiar o olho.
- **Painel de controle**: tudo à mostra ao mesmo tempo, gráficos e métricas que
  ninguém pediu, densidade como sinal de seriedade.
- **Infantil**: cor saturada por diversão, emoji como linguagem, tom de
  brincadeira.

## Design Principles

1. **O conteúdo é a interface.** A maior coisa na tela é sempre o vídeo. Chrome
   encolhe; miniatura cresce. Se um elemento não ajuda a julgar ou a levar o
   corte, ele não está na tela principal.
2. **Movimento só quando algo muda de verdade.** Toda animação corresponde a um
   fato: um corte ficou pronto, uma etapa virou, uma nota chegou. Nada anima
   por entrar na tela.
3. **Duas velocidades, dois layouts.** Esperando, a tela é legível de longe e
   quase estática. Escolhendo, ela é densa, rápida e responde ao teclado.
4. **Ser honesto vale mais que parecer competente.** Quando a IA falhou, quando
   a fonte é ruim, quando o corte não fecha a ideia — a tela diz. Fallback
   silencioso é bug.
5. **Um usuário conhecido merece atalhos.** Teclado antes de mouse na triagem.
   Nada de confirmar o que dá para desfazer.

## Accessibility & Inclusion

- Contraste AA em texto de corpo (≥4.5:1). O tema é escuro por escolha: a
  ferramenta roda ao lado de um editor de vídeo, à noite, e branco puro
  cansaria.
- `prefers-reduced-motion` respeitado em toda animação — a alternativa é
  transição instantânea ou crossfade curto, nunca a ausência do estado.
- Foco visível em tudo que é navegável por teclado.
- Nenhuma informação transmitida só por cor: a nota tem número, o estado tem
  palavra.
