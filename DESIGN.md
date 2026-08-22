# Design

## Theme

Escuro, por cenário e não por gosto: a ferramenta roda de madrugada ao lado de
um editor de vídeo, e uma tela branca ao lado de uma timeline escura cansa. O
fundo é quase preto com um azul mínimo dentro — o suficiente para o vídeo, que
é colorido e brilhante, ser a coisa mais viva da tela.

Estratégia de cor: **restrained**. Um acento só, usado para ação primária,
seleção e estado. A cor da interface nunca compete com a cor do conteúdo.

## Color

Tokens em `web/src/index.css`, camada `@theme` do Tailwind 4.

| Papel | Token | Uso |
|---|---|---|
| Fundo da aplicação | `ink-950` | Corpo. Onde o vídeo descansa. |
| Superfície | `ink-900` / `ink-850` | Painéis, cards, barra lateral. |
| Linha | `white/8` a `white/12` | Divisão. Nunca sombra larga para separar. |
| Texto de corpo | `mist-200` | ≥ 7:1 no fundo. |
| Texto secundário | `mist-300` | ≥ 4.5:1. |
| Texto de apoio | `mist-400` | Só rótulo e metadado, nunca frase longa. |
| Acento | `brand-500` / `brand-400` | Ação primária, seleção, foco. |

**Escala de nota** (a única cor semântica além do acento). A nota é o
julgamento que o produto entrega, então ela tem cor própria — e sempre vem
acompanhada do número e de uma frase, nunca só da cor:

- ≥ 85 `lime-300` — melhor do vídeo
- ≥ 70 `brand-400` — forte
- ≥ 60 `amber-300` — publicável
- < 60 `mist-400` — não fecha a ideia

## Typography

Uma família só (Inter, com `system-ui` atrás). Escala fixa em rem — nada de
`clamp` em UI de produto: o usuário está sempre no mesmo monitor, e um título
que encolhe dentro de um painel fica pior, não melhor.

| Passo | Tamanho | Uso |
|---|---|---|
| `text-2xl` | 1.5rem | Título de tela |
| `text-lg` | 1.125rem | Título de corte |
| `text-sm` | 0.875rem | Corpo, botões |
| `0.8rem` | | Metadado, rótulo |
| `0.7rem` | | Etiqueta, contador |

Números que mudam ao vivo (percentual, nota, tempo) usam `tabular-nums` — sem
isso o número dança quando o dígito troca.

## Layout

Duas velocidades, dois layouts — é o princípio 3 do PRODUCT.md:

- **Esperando**: pouca coisa, grande, legível de longe. O percentual é o maior
  elemento da tela depois dos cortes que já saíram.
- **Escolhendo**: grade densa de miniaturas **9:16**, navegável pelo teclado.

A grade usa `repeat(auto-fit, minmax(...))` — sem breakpoint, o número de
colunas segue a largura disponível.

**A miniatura é vertical.** O que se publica é o 9:16; julgar o corte por um
quadro 16:9 é olhar para um enquadramento que não vai ao ar.

Raio: 12px em card e painel, 8-10px em controle, pill só em etiqueta. Nada de
24px+ em card.

## Motion

Movimento corresponde a fato. Nada anima por entrar na tela.

| Token | Curva | Duração | Quando |
|---|---|---|---|
| `--ease-out-quart` | `cubic-bezier(.25,1,.5,1)` | 180ms | Estado de controle |
| `--ease-out-expo` | `cubic-bezier(.16,1,.3,1)` | 260ms | Entrada de conteúdo |

- **Corte que fica pronto** entra com deslocamento + fade (260ms). Só o corte
  novo anima; os que já estavam na tela ficam parados.
- **Barra de progresso** interpola a largura (300ms) para não pular.
- **Nota** conta de 0 até o valor quando chega (600ms) — é a única animação
  puramente expressiva do produto, e existe porque a nota é o veredito.
- **Hover na miniatura** avança o vídeo (scrub) em vez de aplicar zoom: o
  movimento mostra o conteúdo, não o card.

`prefers-reduced-motion: reduce` troca tudo isso por transição instantânea ou
crossfade curto. O estado final nunca depende da animação ter rodado.

## Components

Vocabulário em `web/src/components/ui.tsx`. Todo controle interativo tem
default, hover, focus visível, active, disabled e — quando faz I/O — loading.

- **Skeleton** enquanto carrega conteúdo, nunca spinner no meio da tela.
- **Empty state** ensina o próximo passo; nunca "nada aqui".
- Um botão primário por tela.
