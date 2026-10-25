# Validação da primeira versão

Validado em 24/10/2026, numa máquina Linux de desenvolvimento. O computador Windows AMD A4-6300, com 8 GB de RAM e GT 420, não estava conectado a este ambiente.

## Resultados executados

- **52 testes Python aprovados**: servidor HTTP/WebSocket, contexto e cancelamento, memória SQLite, configurações, autorização de ferramentas, adaptadores neurais e integridade do downloader.
- A suíte também passou numa instalação Python limpa, sem aproveitar os pacotes globais da máquina.
- O comando de inicialização instalado foi executado nessa instalação limpa; a página respondeu e o comando `/ajuda` funcionou por uma conexão WebSocket real.
- **10 cenários de navegador aprovados**: desktop/mobile, mensagens, erros de modelo ausente, memória, configurações persistentes, confirmação de ações e ausência de erros JavaScript/CSP/recursos locais.
- **6 cenários de áudio sintético aprovados**: ativação explícita do microfone, AudioWorklet, VAD, WAV PCM16 mono a 16 kHz, encerramento da captura, reação da onda sonora e interrupção da reprodução.
- `llama-cpp-python 0.3.36` foi compilado e importado em CPU no Linux. `faster-whisper 1.2.1`, `piper-tts 1.8.0` e suas APIs foram importados/verificados. A fonemização pt-br do espeak incluído no Piper foi exercitada.

Os testes dos adaptadores e do fluxo de resposta usam substitutos explícitos de modelos. O áudio sintético é um sinal de teste. Esses resultados validam a infraestrutura; não medem inteligência, qualidade de voz nem entendimento de fala real.

## Validações pendentes

O proxy recusou o acesso ao Hugging Face com `CONNECT 403`. Nenhum modelo GGUF, Whisper ou voz ONNX foi baixado ou executado. A interface mostra a indisponibilidade; não há resposta neural simulada nem serviço de nuvem alternativo.

Ainda precisam ser testados no PC de destino: instalação das bibliotecas nativas, compatibilidade de instruções da CPU, inferência real, uso de memória e latência, microfone físico, reprodução, eco, palavra de ativação transcrita e abertura dos aplicativos Windows. Os modelos e a voz sugeridos também devem ter suas fontes e licenças conferidas no download.

A síntese está organizada por frases; não inclui treinamento de uma identidade vocal própria nem controle emocional de prosódia. O Spotify abre uma busca e depende do usuário para iniciar uma faixa. O nome de ativação é reconhecido pela transcrição, sem um detector dedicado de palavra de ativação.

Os arquivos do projeto BateuQuero não foram modificados. Esta implementação fica separada, na pasta `IVI`.
