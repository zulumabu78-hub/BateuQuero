# I.V.I. — Inteligência Virtual Independente

[Especificação original](docs/REQUISITOS.md) · [Validação executada e pendências](docs/VALIDACAO.md) · [Interface desktop](docs/interface-desktop.png)

Assistente pessoal em Python com interface própria, conversa por texto, memória persistente, voz local opcional e ferramentas autorizadas para Windows. O projeto usa llama.cpp, faster-whisper e Piper diretamente; não depende de OpenAI, Ollama ou uma API paga.

Esta é uma primeira implementação funcional da arquitetura. Os modelos neurais não acompanham o código. Sem eles, a interface, a memória e os comandos locais continuam disponíveis, mas a I.V.I. informa que ainda não pode gerar conversas, transcrever ou sintetizar voz. Ela não simula uma inteligência com respostas prontas.

## Abrir a interface em tela cheia

Com a instalação concluída, dê dois cliques em **`INICIAR-IVI.cmd`** na pasta do projeto. O inicializador usa o Python de `.venv`, inicia ou reutiliza o servidor local da I.V.I. e procura Microsoft Edge ou Google Chrome para abrir uma janela de aplicativo em tela cheia, sem barra de endereços. O navegador usa um perfil próprio na pasta de dados da I.V.I.

Se Edge e Chrome não forem encontrados, o inicializador abre o navegador padrão. Use o controle de tela cheia da interface ou `F11` para alternar a visualização. O endereço local continua sendo `http://127.0.0.1:8765`, salvo se você configurou outra porta em `.env`.

O atalho não pede administrador, não ativa scripts PowerShell e não instala pacotes. O comportamento da janela Edge/Chrome no Windows ainda precisa ser confirmado no computador de destino; a implementação e os testes feitos no Linux não substituem essa verificação.

### Atualizar uma instalação que já funciona

1. Encerre o servidor antigo com `Ctrl+C` no terminal e feche a janela antiga da interface.
2. Extraia a versão nova em **outra pasta**, sem apagar a instalação atual.
3. Na pasta **nova**, dê dois cliques em **`ATUALIZAR-IVI.cmd`**. Selecione a sua pasta **antiga**, que contém `.venv`, `.env` e os dados já instalados. Se a janela de seleção não estiver disponível, informe esse caminho no terminal.
4. Ao terminar, abra **`INICIAR-IVI.cmd` na pasta antiga**. A pasta nova serve como fonte da atualização e não precisa ter uma `.venv` própria.

O atualizador usa o Python 3.11 já instalado e copia somente arquivos do programa, scripts, documentação e o exemplo de configuração. Ele preserva `.env`, `.ivi`, `.venv`, modelos, dados personalizados e `.git`. Os arquivos anteriores substituídos ficam em `.ivi-backups`, dentro da instalação antiga; uma falha de cópia tenta restaurá-los e informa o caminho do backup. Nenhum arquivo antigo é apagado para fazer a atualização. Se você extraiu diretamente sobre a instalação atual e selecionou a mesma pasta, o atualizador informa que nenhuma cópia é necessária.

Essa atualização da interface não baixa modelos, não recompila mecanismos neurais e não abre a assistente automaticamente. Ela também não encerra processos: feche o servidor antes de começar. A seleção de pasta e os atalhos Windows ainda precisam de validação no computador de destino.

## Perfil do seu computador

O perfil inicial considera **AMD A4-6300, 8 GB de RAM, GeForce GT 420 e 1 TB de armazenamento**. RAM e armazenamento são recursos diferentes: o espaço de 1 TB comporta os modelos, mas não aumenta a memória disponível para inferência.

O processamento é por CPU, com contexto de 1.024 tokens. O perfil Python usa até duas threads; o motor nativo preparado pela interface reserva apenas uma para geração, deixando recursos para a interface nesse processador de dois núcleos. A GT 420 não é usada para inferência. O modelo sugerido, Qwen2.5 0.5B Instruct quantizado em Q4, é uma escolha pequena para começar; sua capacidade de conversar em português e raciocinar é limitada. O Whisper tiny prioriza recursos baixos e pode errar com ruído e fala informal. O Piper fornece voz neural em português brasileiro, mas não garante entonação emocional ou naturalidade de serviços maiores. Nenhuma estimativa de latência foi medida nesse computador.

## Iniciar no Windows

Instale Python 3.11 de [python.org](https://www.python.org/downloads/windows/) com o Python Launcher. Na pasta do projeto, use o PowerShell:

```powershell
.\scripts\setup-windows.ps1
.\INICIAR-IVI.cmd
```

O inicializador abre a janela no próprio computador. O microfone começa desligado e só é solicitado ao pressionar o controle de microfone. Para executar apenas o servidor no terminal, use `.\.venv\Scripts\python.exe -m ivi`; nesse modo, encerre com `Ctrl+C`.

O script cria `.venv` e copia `.env.example` para `.env` somente se o arquivo ainda não existir. Ele não altera a política de execução do PowerShell e não requer privilégios de administrador. Se sua política bloquear scripts, use a instalação manual abaixo ou uma política aprovada por você; não há instrução de contorno no instalador.

### Instalação manual

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env   # apenas se ainda nao houver .env
.\INICIAR-IVI.cmd
```

Instalar somente o pacote básico não instala os mecanismos neurais nem baixa modelos.

## Ativar conversa e voz pela interface

No Windows x64, abra a I.V.I. e clique em **Ativar conversa local**. A preparação baixa o motor CPU oficial do llama.cpp e o modelo pequeno Qwen2.5 0.5B Instruct em GGUF. Ela confere o SHA256 dos arquivos, mantém todas as DLLs do motor juntas e executa somente um teste de versão do motor antes de baixar o modelo. Não é necessário instalar C++ Build Tools ou compilar o mecanismo por esse caminho.

O motor fixado é o [llama.cpp b11869 para Windows x64 CPU](https://github.com/ggml-org/llama.cpp/releases/tag/b11869). Seu ZIP oficial contém variantes x64, SSE4.2, Sandy Bridge e Piledriver, selecionadas conforme os recursos da CPU. Isso não substitui um teste real no AMD A4. Se faltarem DLLs do Windows, a preparação informa o erro e aponta para o [Microsoft Visual C++ x64 Redistributable](https://aka.ms/vc14/vc_redist.x64.exe); esse componente é um runtime, não um compilador. A I.V.I. não executa esse instalador automaticamente.

Depois, use **Preparar voz e microfone** para instalar os pacotes binários de faster-whisper e Piper e baixar os arquivos de escuta e fala. A instalação exige wheels compatíveis: se não houver uma para seu Python ou se o teste de importação falhar na CPU, a preparação termina com um erro em vez de iniciar uma compilação. Preparar os arquivos não valida, por si só, a qualidade de transcrição, a reprodução de áudio ou a latência no seu computador.

Esses downloads só começam depois do clique, exigem internet e podem somar centenas de megabytes. Você pode acompanhar e cancelar a preparação. Uma falha de verificação não ativa o componente nem substitui um arquivo anterior por um download incompleto. Os caminhos são salvos em `runtime.json`, dentro de `IVI_DATA_DIR`, preservando configurações existentes e sem editar seu `.env`. O microfone continua desligado até você ativá-lo. A conversa carrega o modelo local na primeira mensagem.

Os pesos grandes são conferidos pelos SHA256 LFS publicados pelo Hugging Face. Arquivos pequenos de configuração e licença são conferidos pelo hash de objeto Git do commit fixado quando essa é a verificação publicada pelo provedor; o SHA256 calculado é registrado separadamente no resultado, sem ser apresentado como hash esperado do provedor. A preparação usa HTTPS com verificação de certificados e recusa redirecionamento para HTTP.

O assistente guiado está limitado a Windows x64. Neste ambiente Linux, os contratos foram testados com arquivos substitutos, e o ZIP oficial do motor teve seu digest conferido; a execução do motor no Windows, o download real do GGUF e a inferência continuam sem validação aqui, pois o Hugging Face está bloqueado pelo proxy.

### Instalação manual alternativa dos mecanismos neurais

O caminho abaixo é opcional e usa `llama-cpp-python`, em vez do executável nativo preparado pela interface. Ele exige compilador e não é necessário para o botão **Ativar conversa local**.

Para instalar os mecanismos e baixar os modelos pequenos sugeridos:

```powershell
.\scripts\setup-windows.ps1 -WithNeural -WithModels
```

O script solicita uma compilação conservadora do `llama-cpp-python`, sem AVX/AVX2, BMI2, FMA e F16C, limitada a duas tarefas. Essa configuração ainda não foi validada no A4 físico. A compilação exige [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) com desenvolvimento C++ e CMake, e pode demorar e ocupar memória. Executar com `-WithNeural` força a recompilação do mecanismo a partir do código-fonte, ignorando wheels em cache; depois resolve as dependências, sem forçar a reinstalação de todas elas. Executar sem esse parâmetro preserva o mecanismo já instalado. Apenas alterar `CMAKE_ARGS` e executar um `pip install` comum não recompila um pacote que o pip considera satisfeito. Wheels das outras bibliotecas também precisam ser compatíveis com a CPU: um erro `Illegal instruction` ou uma DLL incompatível deve ser diagnosticado no Windows, sem presumir que uma GPU antiga o resolverá.

Você pode separar as etapas:

```powershell
.\scripts\setup-windows.ps1 -WithNeural
.\.venv\Scripts\python.exe -m pip install -e ".[models]"
.\.venv\Scripts\python.exe -m ivi.download_models --list
.\.venv\Scripts\python.exe -m ivi.download_models
```

O downloader consulta a revisão real dos repositórios e fixa cada download no commit retornado. Baixa apenas GGUF, arquivos CTranslate2 e a voz ONNX selecionada, além de metadados e licenças disponíveis. Quando o provedor informa SHA256 de um arquivo LFS, o conteúdo é comparado antes de ser registrado como concluído. O manifesto registra também o hash SHA256 calculado, a origem e o commit de cada componente; isso não substitui a verificação de procedência e das licenças.

As fontes selecionadas, validadas novamente pelo downloader na execução, são:

| Componente | Fonte | Uso |
| --- | --- | --- |
| LLM | [Qwen/Qwen2.5-0.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) | `qwen2.5-0.5b-instruct-q4_k_m.gguf` |
| STT | [Systran/faster-whisper-tiny](https://huggingface.co/Systran/faster-whisper-tiny) | Transcrição local com CPU/int8 |
| TTS | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR/faber/medium) | `pt_BR-faber-medium.onnx` e JSON da voz |

Consulte a licença do modelo e o `MODEL_CARD` da voz: a licença de um repositório, de uma voz e de seu dataset pode diferir. As bibliotecas também possuem suas próprias licenças; o [Piper atual](https://github.com/OHF-Voice/piper1-gpl) é distribuído sob GPL.

Para repetir uma versão específica, use `--component llm --revision COMMIT`, trocando o componente e o SHA conforme o manifesto. Downloads não ocorrem ao iniciar o servidor. Depois do download, confira os caminhos `IVI_*` impressos e reinicie a I.V.I.; o downloader nunca sobrescreve `.env`.

### Configuração

O arquivo `.env` na pasta em que você inicia o programa define os caminhos. Variáveis do processo têm prioridade. `IVI_ENV_FILE` permite selecionar outro arquivo.

| Variável | Descrição |
| --- | --- |
| `IVI_DATA_DIR` | Banco SQLite e pasta de modelos; `.ivi` no exemplo portátil |
| `IVI_LLM_MODEL` | Caminho de um GGUF Instruct compatível com llama.cpp |
| `IVI_LLM_SERVER_EXE` | Opcional: executável llama-server próprio; a preparação guiada dispensa editar este valor |
| `IVI_STT_MODEL` | Diretório local do modelo faster-whisper |
| `IVI_TTS_MODEL` | Caminho do arquivo ONNX da voz Piper |
| `IVI_TTS_CONFIG` | JSON correspondente à mesma voz |
| `IVI_CPU_THREADS` | `2` para o perfil A4 |
| `IVI_CONTEXT_TOKENS` | `1024` para reduzir memória e latência |
| `IVI_PORT` | `8765` por padrão; o servidor escuta somente em loopback |

Sem `IVI_DATA_DIR`, os dados ficam em `%LOCALAPPDATA%/IVI` no Windows e `~/.local/share/ivi` no Linux. Os dados persistem entre reinicializações. Memórias são adicionadas explicitamente; revise e apague pela interface o que não quiser conservar.

## O que a experiência faz

- Conversa por texto com histórico e geração de tokens em streaming quando um GGUF compatível está configurado.
- Transcrição local de trechos de fala, detectados por atividade de áudio no navegador. A escuta contínua exige uma sessão de microfone autorizada.
- Síntese neural local por frases com Piper e reprodução em sequência. Não é síntese neural incremental de cada token nem controle emocional de prosódia.
- Interrupção de geração/reprodução ao começar uma nova entrada; o núcleo visual acompanha níveis reais de áudio.
- Opção de ativação pelo nome transcrito. Não é um detector dedicado de palavra de ativação em baixíssimo consumo.
- Pedidos de ferramentas passam por confirmação e por uma lista limitada de ações. Não há execução livre de código de um modelo.
- Spotify abre uma busca; escolher e reproduzir uma faixa requer interação no aplicativo. Controle de reprodução autenticado não está implementado.

O navegador pede redução de ruído e cancelamento de eco, mas a eficácia depende do microfone, do driver e do navegador. Use fones no primeiro teste: a captura da própria voz e interrupções indevidas não podem ser descartadas sem teste no equipamento. O indicador e o botão de microfone mostram e encerram a captura.

## Desenvolvimento e validação

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes de infraestrutura com modelos substitutos verificam contratos, cancelamento, persistência e controles de ferramentas. Eles não validam qualidade de voz, entendimento de português, latência ou inferência real. Esses pontos exigem os modelos e o equipamento de destino. Teste o microfone, a reprodução, as interrupções e a abertura de aplicativos no Windows antes de considerar o conjunto pronto para uso diário.

Neste ambiente de criação Linux, o acesso ao Hugging Face foi recusado pelo proxy (`CONNECT 403`). Nenhum modelo neural foi baixado ou executado aqui. A interface e o servidor podem ser validados sem esses arquivos; inferência, microfone físico e automação no Windows permanecem pendentes de validação no computador de destino.

O código está organizado em `src/ivi`: configuração, provedores locais, memória, ferramentas, servidor assíncrono e interface estática. Não há dependências de CDN na interface. Evite expor a porta à rede: as ferramentas operam no computador do servidor, não em um computador remoto que apenas abriu a página.
