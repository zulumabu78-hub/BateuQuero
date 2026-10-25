# I.V.I. — Inteligência Virtual Independente

## Comunicação humana, voz e interface interativa

A I.V.I. será uma inteligência artificial pessoal desenvolvida em Python, inspirada no conceito de J.A.R.V.I.S., com capacidade de controlar o computador, executar tarefas e, principalmente, **manter conversas naturais, fluidas e contextualizadas com o usuário sobre praticamente qualquer assunto.**

A comunicação por voz será uma das funcionalidades centrais do projeto, não apenas um recurso secundário.

### 1. Voz extremamente natural e humana

A I.V.I. deverá possuir um sistema avançado de síntese de voz neural, priorizando:

- Voz natural, expressiva e agradável, sem a sonoridade metálica de sintetizadores tradicionais.
- Entonação variável conforme o contexto da conversa.
- Pausas naturais, ritmo humano e pronúncia fluida.
- Capacidade de expressar diferentes tons, como curiosidade, entusiasmo, seriedade e tranquilidade.
- Velocidade de fala ajustável.
- Voz personalizada, com identidade própria.
- Reprodução de respostas em tempo real, preferencialmente por streaming, sem precisar esperar a geração completa do texto.
- Transições suaves entre frases, evitando interrupções artificiais.

A voz deverá ser gerada por um mecanismo de síntese neural executado localmente sempre que tecnicamente possível, sem depender obrigatoriamente de serviços externos.

### 2. Microfone e conversação em tempo real

A I.V.I. deverá utilizar o microfone do computador para escutar e compreender o usuário.

O sistema deverá incluir:

- Reconhecimento contínuo de fala durante sessões de conversa.
- Detecção automática de quando o usuário começa e termina de falar.
- Ativação por voz, utilizando expressões como "I.V.I.".
- Capacidade de interromper a própria resposta quando o usuário começar a falar.
- Redução de ruído e filtragem de sons ambientes.
- Prevenção de que a IA interprete sua própria voz reproduzida nos alto-falantes como um novo comando.
- Reconhecimento de português brasileiro, incluindo expressões informais e diferentes formas de falar.
- Indicador visual de quando o microfone estiver ativo.
- Possibilidade de silenciar completamente o microfone.

O objetivo é permitir conversas sem precisar pressionar botões constantemente.

### 3. Conversas fluidas sobre qualquer assunto

A I.V.I. não deverá se limitar a comandos predefinidos.

Ela deverá conseguir conversar sobre tecnologia, ciência, filosofia, história, jogos, programação, sentimentos, ideias, projetos, assuntos cotidianos e outros temas.

Durante essas conversas, deverá ser capaz de:

- Compreender o contexto de perguntas anteriores.
- Manter o assunto sem exigir que o usuário repita informações.
- Fazer perguntas pertinentes espontaneamente.
- Desenvolver explicações aprofundadas.
- Participar de debates e discussões.
- Compreender humor, ironia e expressões informais quando houver contexto suficiente.
- Adaptar a extensão das respostas ao estilo da conversa.
- Alternar naturalmente entre conversar e executar comandos.
- Reconhecer incertezas e evitar inventar informações.
- Retomar assuntos anteriores utilizando sua memória.

A I.V.I. deverá demonstrar uma personalidade consistente, expressiva e adaptável, sem depender de respostas fixas ou diálogos previamente programados.

### 4. Interface futurista sincronizada com a voz

A interface gráfica deverá representar visualmente os diferentes estados de funcionamento da I.V.I.

Ela deverá possuir um núcleo digital tridimensional ou uma representação visual animada, desenvolvida especificamente para o projeto.

A interface deverá incluir:

- Animação cinematográfica de inicialização.
- Núcleo central com movimentos orgânicos e fluidos.
- Efeitos luminosos em azul e ciano.
- Animações sincronizadas com a intensidade e o ritmo da voz.
- Visualização das ondas sonoras captadas pelo microfone.
- Indicadores de escuta, interpretação, raciocínio e resposta.
- Painéis holográficos e informações do computador.
- Transições suaves entre diferentes estados.
- Animações em tempo real, evitando imagens estáticas ou elementos visuais improvisados.
- Interface responsiva, com uma identidade visual original.

Quando a I.V.I. estiver ouvindo, seu núcleo deverá reagir aos sons captados. Quando estiver falando, as animações deverão acompanhar sua voz.

### 5. Integração entre conversa e controle do computador

A I.V.I. deverá conversar e executar tarefas dentro de uma mesma experiência.

**Exemplo de interação:**

**Usuário:** "I.V.I., tá me ouvindo?"

**I.V.I.:** "Estou sim. O que vamos fazer hoje?"

**Usuário:** "Sei lá, tô meio entediado. O que você sugere?"

**I.V.I.:** "Podemos continuar algum dos seus projetos, jogar alguma coisa ou simplesmente conversar. O que você prefere?"

**Usuário:** "Abre o Spotify e coloca uma música da Laufey."

**I.V.I.:** "Claro. Vou procurar uma música dela."

**Usuário:** "Enquanto isso, me explica uma coisa. Você acha possível criar uma inteligência artificial do zero?"

**I.V.I.:** "É possível, sim. Mas depende do tipo de inteligência que queremos construir. Você está pensando em treinar um modelo de linguagem próprio ou desenvolver uma arquitetura diferente?"

A conversa deverá continuar naturalmente, preservando o contexto e permitindo novos comandos a qualquer momento.

### 6. Arquitetura técnica necessária

Para alcançar esse resultado, a I.V.I. deverá integrar os seguintes sistemas:

1. **LLM local:** modelo de linguagem para interpretação, raciocínio e geração de respostas.
2. **STT (Speech-to-Text):** reconhecimento de fala e transcrição do microfone.
3. **TTS neural (Text-to-Speech):** geração de voz expressiva e natural.
4. **VAD (Voice Activity Detection):** identificação de momentos de fala e silêncio.
5. **Gerenciador de diálogo:** manutenção de contexto, interrupções e alternância de turnos.
6. **Memória persistente:** armazenamento e recuperação de informações relevantes.
7. **Sistema de ferramentas:** execução autorizada de comandos no Windows, abertura de aplicativos, navegação e integração com Spotify.
8. **Motor gráfico:** interface futurista com animações sincronizadas à atividade da IA.

Os componentes deverão funcionar de forma integrada, utilizando processamento assíncrono para evitar que a interface congele durante as respostas.

### 7. Prioridade de desenvolvimento

A I.V.I. deverá priorizar três aspectos fundamentais:

**Inteligência:** conversar livremente, compreender assuntos complexos e interpretar comandos.

**Naturalidade:** escutar e responder com voz humana, baixa latência e continuidade de diálogo.

**Presença visual:** possuir uma interface cinematográfica que reaja às conversas e transmita a sensação de um sistema inteligente ativo.

## Objetivo final

Criar uma assistente virtual pessoal que funcione como uma presença digital interativa no computador, capaz de conversar naturalmente por voz sobre inúmeros assuntos, recordar informações, executar tarefas, controlar aplicativos e apresentar uma identidade visual e vocal própria.

A I.V.I. não deverá ser apenas um chatbot com microfone, mas um sistema integrado de inteligência artificial, comunicação em tempo real, memória, automação e interface gráfica.

O projeto deverá buscar a maior naturalidade possível sem depender obrigatoriamente da OpenAI, do Ollama ou de APIs pagas, utilizando tecnologias locais e componentes independentes.