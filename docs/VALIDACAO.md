# Validação da I.V.I. 0.2.0

## Interface em tela cheia

- **71 testes Python aprovados**: servidor, contexto e cancelamento, memória, ferramentas, adaptadores, downloader, launcher e atualizador.
- **17 verificações reais no navegador aprovadas** em nove viewports: 1366×640, 1366×768, 1280×720, 1920×1080, 1024×600, 1093×510, 390×844, 360×640 e 844×390.
- A página e o corpo mantiveram exatamente as dimensões do viewport, sem rolagem horizontal ou vertical. O teste incluiu 100 mensagens longas e avisos extensos: apenas o histórico interno da conversa rola.
- Entrada e saída pela Fullscreen API foram exercitadas com o botão real, assim como conversa via WebSocket, configurações, memória e confirmação de aplicativos. Nenhum erro JavaScript, CSP ou recurso ausente foi observado.
- Animação padrão, pausa em movimento reduzido e reação do núcleo/onda ao áudio reproduzido foram verificadas. O sinal de áudio usado era sintético, sem inferência de modelos. No navegador de desenvolvimento, o desenho manteve aproximadamente 30 FPS inclusive com throttle de CPU 4×; isso não mede o desempenho do AMD A4 físico.
- A atualização de uma extração real do pacote 0.1.0 para 0.2.0 foi exercitada numa pasta temporária. Código, HUD e launcher foram atualizados; configuração, ambiente Python, dados e modelos de teste permaneceram idênticos. O backup manteve o código anterior.
- Os testes de atualizador também verificam recusa de destino incorreto, escapes de diretório e restauração após falha parcial de cópia. O launcher valida a identidade/versão do servidor, recusa redirecionamentos HTTP e encerra somente o servidor que iniciou.

As capturas nesta pasta mostram a interface realmente executada no Linux de desenvolvimento. Os percentuais e a capacidade de RAM correspondem à máquina de teste, não ao computador Windows do usuário.

## Limites da validação

A janela Edge/Chrome no Windows, os arquivos CMD e o seletor gráfico de pastas não foram executados no PC de destino; as rotinas Python foram testadas com substitutos dos processos Windows. A Fullscreen API do navegador foi testada de fato. O botão da interface e F11 continuam disponíveis como alternativas de tela cheia.

O acesso ao Hugging Face permaneceu bloqueado por CONNECT 403 neste ambiente. Nenhum modelo GGUF, Whisper ou voz ONNX foi baixado ou inferido. Os testes de resposta dos modelos usam substitutos explícitos. Microfone físico, acústica, latência neural, compatibilidade das bibliotecas no AMD A4 e abertura real dos aplicativos Windows ainda exigem teste no equipamento do usuário.

Esta atualização muda a interface e o fluxo de abertura/atualização. Ela não baixa modelos, não cria uma voz treinada própria nem implementa controle autenticado de reprodução do Spotify. O botão Spotify solicita a abertura do aplicativo, com confirmação.

## Histórico

Na versão 0.1.0, passaram 52 testes Python, 10 verificações de interface e 6 cenários de áudio sintético. O pacote também foi instalado em um ambiente Python limpo, com HTTP e WebSocket reais. As bibliotecas llama-cpp-python 0.3.36, faster-whisper 1.2.1 e piper-tts 1.8.0 foram importadas no Linux; isso não equivale a executar os modelos.

A vitrine BateuQuero na branch main permanece separada desta entrega da I.V.I.
