# Validação da I.V.I. 0.3.0

## Resultados executados

- **124 testes Python aprovados**: diálogo, memória, ferramentas, launcher, atualizador, instalação guiada, cancelamento e protocolo do motor local.
- **20 verificações reais no navegador aprovadas**, em nove viewports, incluindo tela cheia, histórico longo, configurações, preparação guiada, cancelamento e avisos de falha.
- A página não apresenta rolagem horizontal ou vertical em 1366×640, 1366×768, 1280×720, 1920×1080, 1024×600, 1093×510, 390×844, 360×640 e 844×390. A conversa longa tem apenas rolagem interna.
- Nenhum erro JavaScript, CSP ou recurso ausente foi observado na execução final. O progresso de instalação no teste de navegador foi uma simulação explícita, sem baixar ou executar modelos.
- O modo econômico usa timer, cache de arte e menor resolução de desenho. Na comparação instrumental, passou de 181 callbacks rAF/90 desenhos para 15 callbacks/15 desenhos em 3 segundos. A amostra CDP da thread principal caiu de cerca de 954 ms para 21 ms nesse intervalo. Com animação desligada não houve callbacks recorrentes; o áudio continuou reagindo. Isso mede o navegador da nuvem, não garante a porcentagem de CPU no AMD A4.
- O prisma, reflexos e anéis complexos são desenhados no cache quando o tamanho muda. O sinal de voz e as órbitas dinâmicas continuam ligados aos estados reais do programa.
- A atualização de um ZIP real da versão 0.2.0 para 0.3.0 foi exercitada em uma pasta temporária: código novo foi copiado, o backup manteve a versão antiga e configuração, runtime.json, ambiente Python, modelos e memória de teste permaneceram idênticos.

No encerramento normal pelo iniciador Windows, o servidor recebe um sinal de parada para encerrar seu próprio motor antes de sair. Esse caminho foi validado com processos substitutos; não encerra aplicativos abertos pelo usuário.

## Instalação guiada e motor local

A origem oficial llama.cpp b11869 foi conferida. O ZIP Windows CPU possui SHA256 `68bbb8f833d6b623386d50f958af8cf5d9f4b39897ba8ab79b9b294093304891`; o download independente bateu com o digest publicado no GitHub. A extração real manteve os 52 arquivos, incluindo os backends x64/SSE4.2/Sandy Bridge/Piledriver e as DLLs necessárias ao pacote.

Os testes de instalação usam arquivos substitutos para verificar SHA256, hashes Git, limites, cancelamento, recusa de ZIPs inseguros, preservação de caminhos personalizados e configuração atômica. Redirecionamentos para HTTP são bloqueados antes de serem seguidos. A preparação exige clique explícito e não começa durante inicialização ou consultas GET.

Os testes do protocolo nativo exercitaram HTTP/SSE real em loopback com servidor substituto: autenticação local temporária, tokenização, streaming UTF-8, cancelamento, recusa de redirecionamento e encerramento somente do processo próprio. Eles não validam inteligência nem executam um modelo neural real.

## Pendências de validação no equipamento

O acesso ao Hugging Face continua bloqueado por CONNECT 403 neste ambiente. Nenhum modelo GGUF, Whisper ou voz ONNX foi baixado ou inferido aqui. Os binários Windows não foram executados no Linux. Instalação real no Windows, microfone, áudio físico, compatibilidade dos pacotes de voz e latência no AMD A4 ainda precisam de teste no PC de destino.

A preparação guiada no Windows baixa os modelos quando solicitada pelo usuário. O motor é compilado oficialmente com seleção dinâmica de variantes de CPU; não exige instalar compiladores. Se faltar o runtime Microsoft Visual C++ x64, a interface mostra a falha e o link oficial, sem executar esse instalador automaticamente.

O modelo sugerido é pequeno e possui limitações de raciocínio e linguagem. A atualização não implementa treinamento de uma voz própria nem controle autenticado de reprodução do Spotify: pedidos de música podem abrir o aplicativo, com confirmação, e a faixa é escolhida pelo usuário.

## Histórico

A versão 0.1.0 passou 52 testes Python, 10 verificações de interface e 6 de áudio sintético. A versão 0.2.0 passou 71 testes Python e 17 verificações de interface. Os resultados atuais substituem as capturas anteriores desta pasta.

A branch main da vitrine BateuQuero permanece separada da entrega da I.V.I.
