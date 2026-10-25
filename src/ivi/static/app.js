'use strict';

(() => {
  const $ = selector => document.querySelector(selector);
  const els = {
    messages: $('#messages'), input: $('#chatInput'), form: $('#chatForm'),
    mic: $('#micButton'), voice: $('#voiceButton'), interrupt: $('#interruptButton'),
    state: $('#stateLabel'), description: $('#stateDescription'),
  };
  const stateCopy = {
    idle: ['Em espera', 'Um espaço para conversar, criar e fazer acontecer.'],
    listening: ['Escutando', 'Pode falar. Estou acompanhando sua voz.'],
    transcribing: ['Reconhecendo sua fala', 'Transformando sua voz em palavras.'],
    thinking: ['Construindo uma resposta', 'O modelo local está processando a conversa.'],
    speaking: ['Conversando', 'Você pode me interromper para continuar.'],
    interrupted: ['Resposta interrompida', 'Vamos continuar do seu jeito.'],
  };
  let settings = { require_wake_word: false, speech_rate: 1, voice_enabled: true, performance_mode: 'eco', animation_enabled: true };
  let socket = null;
  let reconnectAttempt = 0;
  let reconnectTimer = null;
  let serverState = 'idle';
  let pendingMessage = null;
  let pendingText = '';
  let appStatus = null;
  let pendingTool = null;
  let suppressAudio = false;
  let destroyed = false;
  let mic = null;
  let micStarting = false;
  let microphoneLevel = 0;
  let playbackLevel = 0;
  const micHistory = new Array(64).fill(0);
  let audioContext = null;
  let analyser = null;
  let audioQueue = [];
  let audioPlaying = false;
  let audioSource = null;
  let audioEpoch = 0;
  let toastTimer = null;
  let settingsQueue = Promise.resolve();
  let settingsPending = 0;
  let setupState = null;
  let setupTimer = null;
  let setupBusy = false;
  let setupLoading = false;
  const narrowLayout = matchMedia('(max-width: 980px)');

  function selectView(view) {
    if (!['core', 'conversation', 'system'].includes(view)) return;
    document.body.dataset.view = view;
    document.querySelectorAll('button[data-view]').forEach(button => {
      const selected = button.dataset.view === view;
      if (button.getAttribute('role') === 'tab') button.setAttribute('aria-selected', String(selected));
      button.setAttribute('aria-pressed', String(selected));
      button.classList.toggle('active', selected);
    });
    if (view === 'conversation') scrollConversation();
  }

  function revealConversation() {
    if (narrowLayout.matches) selectView('conversation');
  }

  function toast(message) {
    $('#toast').textContent = message;
    $('#toast').classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 5000);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) {
      let message = 'Não foi possível concluir a solicitação (' + response.status + ').';
      try {
        const body = await response.json();
        if (typeof body.detail === 'string') message = body.detail;
      } catch { /* Keep the HTTP error if response is not JSON. */ }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function showNotice(message) {
    $('#connectionNotice').textContent = message;
    $('#connectionNotice').hidden = !message;
  }

  function scrollConversation() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function appendMessage(role, text, { streaming = false, timestamp } = {}) {
    $('#emptyConversation')?.remove();
    const item = document.createElement('article');
    item.className = 'message ' + role + (streaming ? ' streaming' : '');
    const head = document.createElement('div');
    head.className = 'message-label';
    const label = document.createElement('span');
    label.textContent = { user: 'VOCÊ', assistant: 'I.V.I.', error: 'ATENÇÃO', tool: 'AÇÃO' }[role] || 'I.V.I.';
    const time = document.createElement('time');
    time.className = 'message-time';
    const date = timestamp ? new Date(timestamp) : new Date();
    if (!Number.isNaN(date.getTime())) {
      time.dateTime = date.toISOString();
      time.textContent = date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    }
    head.append(label, time);
    const body = document.createElement('div');
    body.className = 'message-body';
    body.textContent = text;
    item.append(head, body);
    els.messages.append(item);
    scrollConversation();
    return item;
  }

  function finishPending(text, interrupted = false) {
    if (!pendingMessage) return;
    if (typeof text === 'string') pendingMessage.querySelector('.message-body').textContent = text;
    pendingMessage.classList.remove('streaming');
    if (interrupted) {
      pendingMessage.classList.add('interrupted');
      const status = document.createElement('span');
      status.className = 'message-interrupted';
      status.textContent = 'Resposta interrompida';
      pendingMessage.append(status);
    }
    pendingMessage = null;
    pendingText = '';
  }

  function refreshState() {
    let state = audioPlaying ? 'speaking' : serverState;
    if ((state === 'idle' || state === 'interrupted') && mic) state = 'listening';
    const copy = stateCopy[state] || stateCopy.idle;
    document.body.dataset.state = state;
    els.state.textContent = copy[0];
    els.description.textContent = state === 'listening' && settings.require_wake_word
      ? 'Diga “Ivi” antes do seu pedido.' : copy[1];
    $('#coreMode').textContent = copy[0].toLocaleUpperCase('pt-BR');
    els.interrupt.disabled = !audioPlaying && !['thinking', 'speaking', 'transcribing'].includes(serverState);
    scheduleAnimation();
  }

  function updateTelemetry(system) {
    if (!system) return;
    const percentage = value => Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : null;
    const cpu = percentage(system.cpu_percent);
    const ram = percentage(system.ram_percent);
    $('#cpuValue').textContent = cpu === null ? '—' : Math.round(cpu) + '%';
    $('#ramValue').textContent = ram === null ? '—' : Math.round(ram) + '%';
    for (const [id, value] of [['cpuMeter', cpu], ['ramMeter', ram]]) {
      const meter = $('#' + id);
      if (!meter) continue;
      meter.max = 100;
      meter.value = value ?? 0;
      meter.setAttribute('aria-valuetext', value === null ? 'Medição indisponível' : Math.round(value) + '% em uso');
      meter.classList.toggle('unavailable', value === null);
    }
    if (Number.isFinite(system.ram_total_gb) && system.ram_total_gb > 0) {
      const format = value => value.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
      $('#ramValue').title = format(system.ram_total_gb) + ' GB de memória no computador que executa a I.V.I.';
      const used = Number.isFinite(system.ram_used_gb) ? system.ram_used_gb : ram === null ? null : system.ram_total_gb * ram / 100;
      if ($('#ramDetail')) $('#ramDetail').textContent = (used === null ? '—' : format(used) + ' GB') + ' / ' + format(system.ram_total_gb) + ' GB';
    } else if ($('#ramDetail')) $('#ramDetail').textContent = 'Medição indisponível';
    if ($('#cpuThreads')) $('#cpuThreads').textContent = Number.isInteger(system.cpu_threads) && system.cpu_threads > 0
      ? system.cpu_threads + (system.cpu_threads === 1 ? ' thread' : ' threads') : 'CPU LOCAL';
  }

  function applySettings(values) {
    if (!values) return;
    const previousPerformance = settings.performance_mode;
    const previousAnimation = settings.animation_enabled;
    settings = { ...settings, ...values };
    settings.performance_mode = settings.performance_mode === 'balanced' ? 'balanced' : 'eco';
    settings.animation_enabled = settings.animation_enabled !== false;
    document.body.dataset.performance = settings.performance_mode;
    document.body.dataset.animation = settings.animation_enabled ? 'on' : 'off';
    if ($('#performanceSetting')) $('#performanceSetting').checked = settings.performance_mode === 'eco';
    if ($('#animationSetting')) $('#animationSetting').checked = settings.animation_enabled;
    if ($('#performanceBadge')) $('#performanceBadge').textContent = settings.performance_mode === 'eco' ? 'MODO ECONÔMICO' : 'MODO EQUILIBRADO';
    $('#wakeWordSetting').checked = Boolean(settings.require_wake_word);
    $('#voiceSetting').checked = settings.voice_enabled !== false;
    $('#rateSetting').value = settings.speech_rate;
    $('#rateOutput').textContent = Number(settings.speech_rate).toLocaleString('pt-BR', { minimumFractionDigits: 1 }) + '×';
    els.voice.setAttribute('aria-pressed', String(settings.voice_enabled !== false));
    $('#voiceLabel').textContent = settings.voice_enabled !== false ? 'Voz ativada' : 'Voz silenciada';
    els.voice.classList.toggle('muted', settings.voice_enabled === false);
    if (previousPerformance !== settings.performance_mode) resizeCanvases();
    if (previousAnimation !== settings.animation_enabled) coreDirty = true;
    refreshMicCaption();
    refreshState();
  }

  function updateStatus(status) {
    if (!status) return;
    appStatus = status;
    if (settingsPending === 0 && document.activeElement !== $('#rateSetting')) applySettings(status.settings);
    updateTelemetry(status.system);
    $('#platformLabel').textContent = status.platform ? String(status.platform).toLocaleUpperCase('pt-BR') : 'AMBIENTE LOCAL';
    const details = $('#modelDetails');
    details.replaceChildren();
    for (const [name, title] of [['llm', 'Inteligência'], ['stt', 'Reconhecimento de fala'], ['tts', 'Voz neural']]) {
      const model = status.models?.[name] || { ready: false, detail: 'Status indisponível.' };
      const chip = $('[data-model="' + name + '"]');
      chip.classList.toggle('ready', Boolean(model.ready));
      chip.classList.toggle('unavailable', !model.ready);
      chip.title = model.detail || (model.ready ? 'Disponível' : 'Modelo não configurado');
      const row = document.createElement('div');
      row.className = 'model-detail ' + (model.ready ? 'ready' : 'unavailable');
      const dot = document.createElement('i');
      dot.className = 'model-dot';
      const text = document.createElement('div');
      text.className = 'model-text';
      const heading = document.createElement('strong');
      heading.textContent = title;
      const detail = document.createElement('p');
      detail.textContent = model.detail || (model.ready ? 'Disponível no computador.' : 'Modelo local não configurado.');
      text.append(heading, detail);
      row.append(dot, text);
      details.append(row);
    }
    if (socket?.readyState === WebSocket.OPEN) {
      showNotice(status.models?.llm?.ready ? '' : 'Para conversar livremente, use “Ativar conversa local” e prepare a I.V.I. neste computador. Os comandos de aplicativos e a memória já podem ser usados.');
    }
    if ($('#setupStrip')) $('#setupStrip').hidden = Boolean(status.models?.llm?.ready);
    const quickSetup = $('#setupQuickOpen');
    if (quickSetup) {
      const title = status.models?.llm?.ready ? 'Gerenciar modelos locais' : 'Ativar conversa local';
      quickSetup.title = title;
      quickSetup.setAttribute('aria-label', title);
      if (quickSetup.querySelector('span')) quickSetup.querySelector('span').textContent = status.models?.llm?.ready ? 'Modelos locais' : 'Ativar conversa';
    }
  }

  function stopSetupPolling() {
    clearTimeout(setupTimer);
    setupTimer = null;
  }

  function updateRuntimeHelp(message, failed) {
    const help = $('#setupRuntimeHelp');
    if (help) help.hidden = !(failed && /Microsoft\s+Visual\s+C\+\+|VC\+\+|VCRUNTIME|MSVCP\d+/i.test(String(message || '')));
  }

  function renderSetup(job) {
    if (!job || !$('#setupStatus')) return;
    setupState = job;
    const running = job.state === 'running';
    const blocked = running || setupBusy;
    const canVoice = job.can_install_voice === true || job.components?.voice?.can_install === true;
    const installReason = job.components?.conversation?.reason || job.reason;
    const unavailable = job.state === 'idle' && job.can_install !== true;
    $('#setupJob').hidden = job.state === 'idle' && !unavailable && !(job.log?.length);
    $('#setupStatus').textContent = unavailable
      ? installReason || 'A preparação automática não está disponível neste computador. Consulte os detalhes da configuração.'
      : job.message || ({ idle: 'Escolha o que deseja preparar neste computador.', running: 'Preparação em andamento.', completed: 'Preparação encerrada. Verificando os modelos locais.', failed: 'A preparação não foi concluída. Consulte os detalhes abaixo.', cancelled: 'A preparação foi cancelada.' }[job.state] || 'Estado da preparação indisponível.');
    $('#setupStatus').dataset.state = job.state || 'idle';
    updateRuntimeHelp(job.message, job.state === 'failed');
    $('#setupConversationButton').disabled = blocked || job.can_install !== true;
    $('#setupVoiceButton').disabled = blocked || !canVoice;
    if ($('#setupVoiceNote')) $('#setupVoiceNote').textContent = canVoice
      ? 'O reconhecimento de fala e a voz são preparados neste computador; o download inicial usa a internet.'
      : job.components?.voice?.reason || 'A preparação automática de voz ainda não está disponível neste instalador. Você pode continuar por texto.';
    $('#setupCancelButton').hidden = !running;
    $('#setupCancelButton').disabled = setupBusy;
    const progress = Number.isFinite(job.progress) ? Math.max(0, Math.min(100, job.progress)) : null;
    $('#setupProgress').hidden = progress === null;
    $('#setupProgress').value = progress ?? 0;
    if ($('#setupProgressLabel')) {
      $('#setupProgressLabel').hidden = progress === null;
      $('#setupProgressLabel').textContent = progress === null ? '' : Math.round(progress) + '%';
    }
    $('#setupDetails').textContent = (Array.isArray(job.log) ? job.log : []).slice(-100).map(line => typeof line === 'string' ? line : JSON.stringify(line)).join('\n');
    $('#setupDetails').scrollTop = $('#setupDetails').scrollHeight;
  }

  function showSetupError(error) {
    if (!$('#setupStatus')) return;
    stopSetupPolling();
    $('#setupJob').hidden = false;
    const message = error.status === 404
      ? 'Os arquivos novos estão prontos, mas o servidor antigo ainda está aberto. Feche-o com Ctrl+C e abra INICIAR-IVI.cmd novamente.'
      : error.message || 'Não foi possível consultar a preparação local.';
    $('#setupStatus').textContent = message;
    $('#setupStatus').dataset.state = 'failed';
    updateRuntimeHelp(message, true);
    $('#setupProgress').hidden = true;
    if ($('#setupProgressLabel')) $('#setupProgressLabel').hidden = true;
    $('#setupCancelButton').hidden = setupState?.state !== 'running';
    $('#setupCancelButton').disabled = false;
    $('#setupConversationButton').disabled = setupState?.state === 'running' || setupState?.can_install !== true;
    $('#setupVoiceButton').disabled = setupState?.state === 'running' || !(setupState?.can_install_voice === true || setupState?.components?.voice?.can_install === true);
  }

  function scheduleSetupPoll() {
    stopSetupPolling();
    if (!destroyed && !document.hidden && setupState?.state === 'running') setupTimer = setTimeout(() => void loadSetup(), 2000);
  }

  async function loadSetup() {
    if (setupLoading || destroyed) return;
    setupLoading = true;
    if (!setupState && $('#setupConversationButton')) {
      $('#setupConversationButton').disabled = true;
      $('#setupVoiceButton').disabled = true;
    }
    const previousState = setupState?.state;
    try {
      const job = await api('/api/setup');
      renderSetup(job);
      if (previousState === 'running' && job.state !== 'running') {
        updateStatus(await api('/api/status'));
      }
      scheduleSetupPoll();
    } catch (error) { showSetupError(error); }
    finally { setupLoading = false; }
  }

  async function openSetup() {
    const dialog = $('#setupDialog');
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    await loadSetup();
  }

  async function startSetup(component) {
    if (setupBusy || setupState?.state === 'running') return;
    const allowed = component === 'voice'
      ? setupState?.can_install_voice === true || setupState?.components?.voice?.can_install === true
      : setupState?.can_install === true;
    if (!allowed) return toast('Aguarde a verificação da preparação disponível neste computador.');
    setupBusy = true;
    let operationError = null;
    if (setupState) renderSetup(setupState);
    try {
      const job = await api('/api/setup', { method: 'POST', body: JSON.stringify({ component }) });
      renderSetup(job);
      if (job.state === 'completed') updateStatus(await api('/api/status'));
    } catch (error) { operationError = error; }
    finally {
      setupBusy = false;
      if (operationError) showSetupError(operationError);
      else { if (setupState) renderSetup(setupState); scheduleSetupPoll(); }
    }
  }

  async function cancelSetup() {
    if (setupBusy || setupState?.state !== 'running') return;
    setupBusy = true;
    let operationError = null;
    stopSetupPolling();
    renderSetup(setupState);
    try {
      renderSetup(await api('/api/setup', { method: 'DELETE' }));
      updateStatus(await api('/api/status'));
    } catch (error) { operationError = error; }
    finally {
      setupBusy = false;
      if (operationError) showSetupError(operationError);
      else { if (setupState) renderSetup(setupState); scheduleSetupPoll(); }
    }
  }

  async function saveSettings(changes) {
    // Keep controls responsive without allowing an earlier save response to
    // overwrite a later edit. Serialize writes to preserve their order.
    settingsPending++;
    applySettings(changes);
    if (changes.voice_enabled === false) stopPlayback();
    settingsQueue = settingsQueue.catch(() => {}).then(() => api('/api/settings', {
      method: 'PATCH', body: JSON.stringify(changes),
    }));
    let saved = null;
    try {
      saved = await settingsQueue;
    } catch (error) {
      toast(error.message);
      if (settingsPending === 1) {
        try { saved = (await api('/api/status')).settings; } catch { /* Reconnect handles an unavailable server. */ }
      }
    } finally {
      settingsPending--;
      if (settingsPending === 0 && saved) applySettings(saved);
    }
  }

  function send(payload) {
    if (socket?.readyState !== WebSocket.OPEN) {
      toast('A conexão local está sendo restabelecida. Sua mensagem continua aqui.');
      return false;
    }
    socket.send(JSON.stringify(payload));
    return true;
  }

  function interrupt() {
    suppressAudio = true;
    stopPlayback();
    finishPending(undefined, true);
    send({ type: 'interrupt' });
    serverState = 'interrupted';
    refreshState();
  }

  function sendText(text) {
    text = text.trim();
    if (!text) return false;
    revealConversation();
    if (socket?.readyState !== WebSocket.OPEN) return send({ type: 'text', text });
    stopPlayback();
    finishPending(undefined, true);
    suppressAudio = false;
    void unlockAudio();
    return send({ type: 'text', text });
  }

  function handleEvent(event) {
    switch (event.type) {
      case 'ready':
        updateStatus(event.status);
        break;
      case 'status':
        serverState = event.state || 'idle';
        if (['transcribing', 'thinking'].includes(serverState)) suppressAudio = false;
        if (serverState === 'interrupted') {
          stopPlayback();
          finishPending(undefined, true);
        }
        refreshState();
        break;
      case 'user':
        suppressAudio = false;
        finishPending(undefined, true);
        appendMessage('user', event.text || '');
        $('#transcriptPreview').hidden = true;
        break;
      case 'token':
        if (!pendingMessage) {
          revealConversation();
          pendingText = '';
          pendingMessage = appendMessage('assistant', '', { streaming: true });
        }
        pendingText += event.text || '';
        pendingMessage.querySelector('.message-body').textContent = pendingText;
        scrollConversation();
        break;
      case 'assistant':
        if (pendingMessage) finishPending(event.text || pendingText);
        else { revealConversation(); appendMessage('assistant', event.text || ''); }
        break;
      case 'transcript':
        $('#transcriptPreview').hidden = !event.text;
        $('#transcriptPreview p').textContent = event.activated === false
          ? 'Ouvi “' + (event.text || '') + '”. Diga “Ivi” para iniciar.' : event.text || '';
        break;
      case 'audio':
        if (!suppressAudio && settings.voice_enabled !== false) enqueueAudio(event.audio);
        break;
      case 'error':
        revealConversation();
        finishPending();
        appendMessage('error', event.message || 'Não foi possível concluir esta etapa.');
        serverState = 'idle';
        refreshState();
        break;
      case 'tool_confirmation':
        if (pendingTool) send({ type: 'confirm_tool', id: pendingTool.id, approved: false });
        pendingTool = event;
        $('#toolTitle').textContent = event.title || 'Autorizar ação';
        $('#toolDescription').textContent = event.description || 'A I.V.I. pediu autorização para executar uma ação no computador.';
        if (!$('#toolDialog').open) $('#toolDialog').showModal();
        break;
      case 'tool_result':
        appendMessage('tool', event.text || event.message || 'Ação concluída.');
        break;
      case 'telemetry':
        updateTelemetry(event.system);
        break;
      case 'memory_updated':
        if ($('#memoryDialog').open) void loadMemory();
        break;
    }
  }

  function connect() {
    if (destroyed) return;
    socket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
    socket.addEventListener('open', () => {
      reconnectAttempt = 0;
      $('#connectionPill').classList.add('connected');
      $('#connectionPill').classList.remove('offline');
      $('#connectionLabel').textContent = 'Conectada · local';
      $('#sendButton').disabled = false;
      if (appStatus) updateStatus(appStatus);
    });
    socket.addEventListener('message', event => {
      try { handleEvent(JSON.parse(event.data)); }
      catch (error) { console.error('I.V.I.: mensagem não processada', error); }
    });
    socket.addEventListener('close', () => {
      stopMicrophone();
      stopPlayback();
      finishPending(undefined, true);
      $('#toolDialog').close();
      pendingTool = null;
      $('#connectionPill').classList.remove('connected');
      $('#connectionPill').classList.add('offline');
      $('#connectionLabel').textContent = 'Reconectando';
      $('#sendButton').disabled = true;
      showNotice('Conexão com a I.V.I. interrompida. Tentando reconectar…');
      serverState = 'idle';
      refreshState();
      if (!destroyed) {
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connect, Math.min(1000 * 2 ** reconnectAttempt++, 15000));
      }
    });
    socket.addEventListener('error', () => {
      $('#connectionLabel').textContent = 'Sem conexão';
    });
  }

  async function unlockAudio() {
    if (!audioContext) {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) return null;
      audioContext = new Context();
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.4;
      analyser.connect(audioContext.destination);
    }
    if (audioContext.state === 'suspended') {
      try { await audioContext.resume(); }
      catch { return null; }
    }
    return audioContext;
  }

  function decodeBase64(base64) {
    const raw = atob(base64);
    const result = new Uint8Array(raw.length);
    for (let index = 0; index < raw.length; index++) result[index] = raw.charCodeAt(index);
    return result.buffer;
  }

  function enqueueAudio(base64) {
    if (typeof base64 !== 'string' || !base64) return;
    audioQueue.push(base64);
    if (!audioPlaying) void playQueue();
  }

  async function playQueue() {
    const epoch = audioEpoch;
    audioPlaying = true;
    refreshState();
    try {
      const context = await unlockAudio();
      if (!context) throw new Error('O navegador não liberou a reprodução de áudio.');
      while (audioQueue.length && epoch === audioEpoch) {
        const bytes = decodeBase64(audioQueue.shift());
        const buffer = await context.decodeAudioData(bytes);
        if (epoch !== audioEpoch) break;
        const source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(analyser);
        audioSource = source;
        await new Promise(resolve => {
          source.onended = resolve;
          source.start();
        });
        source.disconnect();
        if (audioSource === source) audioSource = null;
      }
    } catch (error) {
      if (epoch === audioEpoch) {
        audioQueue = [];
        toast('Não foi possível reproduzir a voz. ' + error.message);
      }
    } finally {
      if (epoch === audioEpoch) {
        audioPlaying = false;
        playbackLevel = 0;
        waveDirty = true;
        refreshState();
      }
    }
  }

  function stopPlayback() {
    audioEpoch++;
    audioQueue = [];
    if (audioSource) {
      try { audioSource.stop(); } catch { /* It may already have ended. */ }
      audioSource = null;
    }
    audioPlaying = false;
    playbackLevel = 0;
    waveDirty = true;
    refreshState();
  }

  function refreshMicCaption() {
    if (micStarting) {
      $('#micLabel').textContent = 'Aguardando permissão do microfone…';
      if ($('#micActionLabel')) $('#micActionLabel').textContent = 'Aguardando microfone';
      return;
    }
    $('#micLabel').replaceChildren();
    $('#micLabel').append(document.createTextNode(mic ? 'Microfone ligado' : 'Microfone desligado'));
    const hint = document.createElement('span');
    hint.textContent = mic ? (settings.require_wake_word ? ' · diga “Ivi” para começar' : ' · pode falar naturalmente') : ' · toque para conversar';
    $('#micLabel').append(hint);
    els.mic.setAttribute('aria-pressed', String(Boolean(mic)));
    els.mic.setAttribute('aria-label', mic ? 'Desligar microfone' : 'Ativar microfone');
    if ($('#micActionLabel')) $('#micActionLabel').textContent = mic ? 'Desligar microfone' : 'Ativar microfone';
    els.mic.classList.toggle('active', Boolean(mic));
    $('#micIcon use').setAttribute('href', mic ? '#i-mic' : '#i-mic-off');
  }

  function encodeWav(samples, sampleRate) {
    const targetRate = 16000;
    const ratio = sampleRate / targetRate;
    const length = Math.floor(samples.length / ratio);
    const pcm = new Int16Array(length);
    for (let index = 0; index < length; index++) {
      const start = Math.floor(index * ratio);
      const end = Math.max(start + 1, Math.floor((index + 1) * ratio));
      let sum = 0;
      for (let cursor = start; cursor < Math.min(end, samples.length); cursor++) sum += samples[cursor];
      const value = Math.max(-1, Math.min(1, sum / (end - start)));
      pcm[index] = value < 0 ? value * 32768 : value * 32767;
    }
    const bytes = new ArrayBuffer(44 + pcm.byteLength);
    const view = new DataView(bytes);
    const ascii = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
    ascii(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true);
    ascii(8, 'WAVE'); ascii(12, 'fmt '); view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, targetRate, true); view.setUint32(28, targetRate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    ascii(36, 'data'); view.setUint32(40, pcm.byteLength, true);
    for (let index = 0; index < pcm.length; index++) view.setInt16(44 + index * 2, pcm[index], true);
    const data = new Uint8Array(bytes);
    let binary = '';
    for (let offset = 0; offset < data.length; offset += 8192) {
      binary += String.fromCharCode(...data.subarray(offset, offset + 8192));
    }
    return btoa(binary);
  }

  function completeUtterance(session) {
    if (!session.frames.length) return;
    const frames = session.frames;
    const voicedTime = session.voicedTime;
    session.frames = [];
    session.speech = false;
    session.silence = 0;
    session.voicedTime = 0;
    session.consecutive = 0;
    session.preRoll = [];
    if (voicedTime < 0.24 || mic !== session) return;
    const length = frames.reduce((total, frame) => total + frame.length, 0);
    const samples = new Float32Array(length);
    let position = 0;
    for (const frame of frames) { samples.set(frame, position); position += frame.length; }
    suppressAudio = false;
    if (send({ type: 'audio', audio: encodeWav(samples, session.context.sampleRate) })) {
      serverState = 'transcribing';
      refreshState();
    }
  }

  function receiveMicrophone(session, event) {
    if (mic !== session) return;
    const frame = new Float32Array(event.samples);
    const rms = Math.min(1, event.rms || 0);
    microphoneLevel = rms;
    waveDirty = true;
    micHistory.push(rms);
    micHistory.shift();
    scheduleAnimation();
    const duration = frame.length / session.context.sampleRate;
    if (!session.speech && !audioPlaying) session.noise = session.noise * 0.985 + Math.min(rms, 0.025) * 0.015;
    const threshold = Math.max(audioPlaying ? 0.045 : 0.012, Math.min(0.065, session.noise * (audioPlaying ? 4.5 : 3.2)));
    const voiced = rms > threshold;
    if (!session.speech) {
      session.preRoll.push(frame);
      while (session.preRoll.reduce((sum, item) => sum + item.length, 0) > session.context.sampleRate * 0.25) session.preRoll.shift();
      session.consecutive = voiced ? session.consecutive + 1 : 0;
      if (session.consecutive >= (audioPlaying ? 3 : 2)) {
        session.speech = true;
        session.frames = [...session.preRoll];
        session.voicedTime = session.consecutive * duration;
        session.silence = 0;
        if (audioPlaying || ['thinking', 'speaking'].includes(serverState)) interrupt();
      }
      return;
    }
    session.frames.push(frame);
    session.voicedTime += voiced ? duration : 0;
    session.silence = voiced ? 0 : session.silence + duration;
    const total = session.frames.reduce((sum, item) => sum + item.length, 0) / session.context.sampleRate;
    if (session.silence >= 0.7 || total >= 19.5) completeUtterance(session);
  }

  async function startMicrophone() {
    if (mic || micStarting) return;
    if (socket?.readyState !== WebSocket.OPEN) return toast('Aguarde a conexão com o servidor local antes de ativar o microfone.');
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) return toast('O microfone exige localhost ou HTTPS e um navegador compatível.');
    if (appStatus?.models?.stt?.ready === false) return toast('A escuta ainda não está pronta. Abra a configuração da I.V.I. para conferir a preparação de voz; você pode continuar por texto.');
    micStarting = true;
    els.mic.disabled = true;
    refreshMicCaption();
    let stream = null;
    let context = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 }, video: false });
      if (destroyed || socket?.readyState !== WebSocket.OPEN) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      const Context = window.AudioContext || window.webkitAudioContext;
      context = new Context();
      await context.audioWorklet.addModule('/static/audio-worklet.js');
      const input = context.createMediaStreamSource(stream);
      const processor = new AudioWorkletNode(context, 'ivi-capture');
      const silent = context.createGain();
      silent.gain.value = 0;
      input.connect(processor);
      processor.connect(silent);
      silent.connect(context.destination);
      const session = { context, stream, input, processor, silent, speech: false, frames: [], preRoll: [], consecutive: 0, silence: 0, voicedTime: 0, noise: 0.004 };
      mic = session;
      processor.port.onmessage = event => receiveMicrophone(session, event.data);
      stream.getAudioTracks().forEach(track => track.addEventListener('ended', () => { if (mic === session) stopMicrophone(); }));
      await context.resume();
      void unlockAudio();
    } catch (error) {
      if (stream) stream.getTracks().forEach(track => track.stop());
      if (context) await context.close().catch(() => {});
      mic = null;
      const message = error.name === 'NotAllowedError' ? 'Permissão de microfone negada. Você pode continuar por texto.' : 'Não consegui iniciar o microfone: ' + error.message;
      toast(message);
    } finally {
      micStarting = false;
      els.mic.disabled = false;
      refreshMicCaption();
      refreshState();
    }
  }

  function stopMicrophone() {
    const session = mic;
    mic = null;
    microphoneLevel = 0;
    micHistory.fill(0);
    waveDirty = true;
    if (session) {
      session.processor.port.onmessage = null;
      session.input.disconnect();
      session.processor.disconnect();
      session.silent.disconnect();
      session.stream.getTracks().forEach(track => track.stop());
      void session.context.close().catch(() => {});
    }
    refreshMicCaption();
    refreshState();
  }

  async function loadMemory() {
    const list = $('#memoryList');
    try {
      const data = await api('/api/memory');
      list.replaceChildren();
      if (!data.items?.length) {
        const empty = document.createElement('p');
        empty.className = 'memory-empty';
        empty.textContent = 'Nenhuma memória guardada por enquanto.';
        list.append(empty);
      }
      for (const item of data.items || []) {
        const row = document.createElement('article');
        row.className = 'memory-item';
        const text = document.createElement('p');
        text.className = 'memory-text';
        text.textContent = item.content;
        const remove = document.createElement('button');
        remove.className = 'memory-delete';
        remove.textContent = 'Apagar';
        remove.setAttribute('aria-label', 'Apagar memória: ' + item.content.slice(0, 50));
        remove.addEventListener('click', async () => {
          try { await api('/api/memory/' + encodeURIComponent(item.id), { method: 'DELETE' }); await loadMemory(); }
          catch (error) { toast(error.message); }
        });
        row.append(text, remove);
        list.append(row);
      }
    } catch (error) {
      list.textContent = error.message;
    }
  }

  function confirmTool(approved) {
    if (!pendingTool) return;
    send({ type: 'confirm_tool', id: pendingTool.id, approved });
    pendingTool = null;
    $('#toolDialog').close();
  }

  els.form.addEventListener('submit', event => {
    event.preventDefault();
    if (sendText(els.input.value)) { els.input.value = ''; els.input.style.height = ''; }
  });
  els.input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); els.form.requestSubmit(); }
  });
  els.input.addEventListener('input', () => {
    els.input.style.height = 'auto';
    els.input.style.height = Math.min(els.input.scrollHeight, 150) + 'px';
  });
  document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => sendText(button.dataset.prompt)));
  document.querySelectorAll('[data-command]').forEach(button => button.addEventListener('click', () => sendText(button.dataset.command)));
  document.querySelectorAll('button[data-view]').forEach(button => button.addEventListener('click', event => {
    selectView(button.dataset.view);
    if (event.detail === 0 && button.dataset.view === 'conversation') els.input.focus({ preventScroll: true });
  }));
  selectView(document.body.dataset.view || 'core');

  function syncFullscreen() {
    const button = $('#fullscreenButton');
    if (!button) return;
    const active = Boolean(document.fullscreenElement);
    const label = active ? 'Sair da tela cheia' : 'Entrar em tela cheia';
    button.setAttribute('aria-pressed', String(active));
    button.setAttribute('aria-label', label);
    button.title = label;
    button.classList.toggle('active', active);
    document.body.classList.toggle('fullscreen-active', active);
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement) {
        if (typeof document.exitFullscreen !== 'function') throw new Error('API indisponível');
        await document.exitFullscreen();
      } else {
        if (typeof document.documentElement.requestFullscreen !== 'function') throw new Error('API indisponível');
        await document.documentElement.requestFullscreen();
      }
    } catch {
      toast('O navegador não permitiu a tela cheia. Você pode usar o controle de tela cheia do próprio navegador.');
    } finally {
      syncFullscreen();
    }
  }

  $('#fullscreenButton')?.addEventListener('click', () => void toggleFullscreen());
  document.addEventListener('fullscreenchange', () => { syncFullscreen(); resizeCanvases(); });
  document.addEventListener('keydown', event => {
    if (event.ctrlKey && event.shiftKey && !event.altKey && !event.metaKey && event.key.toLowerCase() === 'f') {
      event.preventDefault();
      void toggleFullscreen();
    }
  });
  syncFullscreen();
  els.mic.addEventListener('click', () => { if (mic) stopMicrophone(); else void startMicrophone(); });
  els.voice.addEventListener('click', () => void saveSettings({ voice_enabled: settings.voice_enabled === false }));
  els.interrupt.addEventListener('click', interrupt);
  $('#settingsOpen').addEventListener('click', () => $('#settingsDialog').showModal());
  $('#setupOpen')?.addEventListener('click', () => void openSetup());
  document.querySelectorAll('[data-setup-open]').forEach(button => button.addEventListener('click', () => void openSetup()));
  $('#setupConversationButton')?.addEventListener('click', () => void startSetup('conversation'));
  $('#setupVoiceButton')?.addEventListener('click', () => void startSetup('voice'));
  $('#setupCancelButton')?.addEventListener('click', () => void cancelSetup());
  $('#memoryOpen').addEventListener('click', () => { $('#memoryDialog').showModal(); void loadMemory(); });
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $('#' + button.dataset.close).close()));
  document.querySelectorAll('.panel-dialog:not(#toolDialog)').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); }));
  $('#toolDialog').addEventListener('cancel', event => { event.preventDefault(); confirmTool(false); });
  $('#toolApprove').addEventListener('click', () => confirmTool(true));
  $('#toolReject').addEventListener('click', () => confirmTool(false));
  $('#wakeWordSetting').addEventListener('change', event => void saveSettings({ require_wake_word: event.target.checked }));
  $('#voiceSetting').addEventListener('change', event => void saveSettings({ voice_enabled: event.target.checked }));
  $('#performanceSetting')?.addEventListener('change', event => void saveSettings({ performance_mode: event.target.checked ? 'eco' : 'balanced' }));
  $('#animationSetting')?.addEventListener('change', event => void saveSettings({ animation_enabled: event.target.checked }));
  $('#rateSetting').addEventListener('input', event => { $('#rateOutput').textContent = Number(event.target.value).toLocaleString('pt-BR', { minimumFractionDigits: 1 }) + '×'; });
  $('#rateSetting').addEventListener('change', event => void saveSettings({ speech_rate: Number(event.target.value) }));
  $('#memoryForm').addEventListener('submit', async event => {
    event.preventDefault();
    const content = $('#memoryInput').value.trim();
    if (!content) return;
    try { await api('/api/memory', { method: 'POST', body: JSON.stringify({ content }) }); $('#memoryInput').value = ''; await loadMemory(); }
    catch (error) { toast(error.message); }
  });
  $('#newConversation').addEventListener('click', async () => {
    try {
      interrupt();
      await api('/api/history', { method: 'DELETE' });
      els.messages.replaceChildren();
      pendingMessage = null;
      pendingText = '';
      const welcome = document.createElement('div');
      welcome.className = 'conversation-reset';
      welcome.textContent = 'Uma nova conversa começa aqui.';
      els.messages.append(welcome);
      toast('Histórico da conversa apagado.');
    } catch (error) { toast(error.message); }
  });

  function updateClock() {
    $('#clock').textContent = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    $('#clock').dateTime = new Date().toISOString();
  }
  updateClock();
  const clockTimer = setInterval(updateClock, 15000);

  // Detailed neon artwork is rasterized only when its dimensions change.
  // Runtime frames composite those local Canvas layers without shadows/filters.
  const core = $('#coreCanvas');
  const wave = $('#waveCanvas');
  const coreContext = core.getContext('2d');
  const waveContext = wave.getContext('2d');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const particles = Array.from({ length: 32 }, (_, index) => {
    const y = 1 - index / 31 * 2;
    const r = Math.sqrt(1 - y * y);
    const angle = index * Math.PI * (3 - Math.sqrt(5));
    return [Math.cos(angle) * r, y, Math.sin(angle) * r];
  });
  let dimensions = { width: 0, height: 0, waveWidth: 0, waveHeight: 0, ratio: 1 };
  let coreLayers = null;
  let coreDirty = true;
  let waveDirty = true;
  let animationTimer = null;
  let animationDue = 0;
  let lastFrame = 0;
  let lastCoreLevel = -1;
  let phase = 0;
  const analyserValues = new Float32Array(128);
  const tau = Math.PI * 2;

  function cachedLayer(size, ratio, paint) {
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.ceil(size * ratio));
    canvas.height = Math.max(1, Math.ceil(size * ratio));
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.translate(size / 2, size / 2);
    paint(ctx, size * 0.435);
    return canvas;
  }

  function buildCoreLayers(size, ratio) {
    const key = size.toFixed(2) + '/' + ratio;
    if (coreLayers?.key === key) return;
    const arc = (ctx, r, start, end, color, width = 1, blur = 0) => {
      ctx.beginPath(); ctx.arc(0, 0, r, start, end);
      ctx.strokeStyle = color; ctx.lineWidth = width;
      ctx.shadowBlur = blur; ctx.shadowColor = color;
      ctx.stroke(); ctx.shadowBlur = 0;
    };
    const base = cachedLayer(size, ratio, (ctx, r) => {
      const glow = ctx.createRadialGradient(0, 0, r * 0.08, 0, 0, r * 1.1);
      glow.addColorStop(0, 'rgba(29,178,255,.24)');
      glow.addColorStop(.48, 'rgba(0,109,196,.19)');
      glow.addColorStop(.77, 'rgba(0,108,190,.08)');
      glow.addColorStop(1, 'rgba(0,40,80,0)');
      ctx.fillStyle = glow; ctx.fillRect(-size / 2, -size / 2, size, size);
      // Fine registration lines, etched rings, dotted tracks and ticks.
      ctx.strokeStyle = 'rgba(66,178,218,.2)'; ctx.lineWidth = .6;
      ctx.setLineDash([2, 7]); ctx.beginPath();
      ctx.moveTo(-r * 1.06, 0); ctx.lineTo(r * 1.06, 0);
      ctx.moveTo(0, -r * 1.06); ctx.lineTo(0, r * 1.06); ctx.stroke(); ctx.setLineDash([]);
      arc(ctx, r * 1.025, 0, tau, 'rgba(55,147,189,.45)', .7);
      arc(ctx, r * .992, 0, tau, 'rgba(77,217,255,.23)', .7);
      for (let group = 0; group < 2; group++) {
        ctx.beginPath();
        for (let i = group ? 0 : 1; i < 144; i += group ? 12 : 1) {
          if (!group && i % 12 === 0) continue;
          const a = i / 144 * tau;
          const inner = r * (group ? 1.018 : 1.028);
          const outer = r * (group ? 1.066 : 1.047);
          ctx.moveTo(Math.cos(a) * inner, Math.sin(a) * inner);
          ctx.lineTo(Math.cos(a) * outer, Math.sin(a) * outer);
        }
        ctx.strokeStyle = group ? 'rgba(119,232,255,.73)' : 'rgba(72,167,211,.36)';
        ctx.lineWidth = group ? 1.3 : .65; ctx.stroke();
      }
      // Beveled blue iris bands: glow is paid once, never once per frame.
      for (let i = 0; i < 12; i++) {
        const a = i / 12 * tau + .035;
        const b = a + tau / 12 - .09;
        arc(ctx, r * .944, a, b, 'rgba(5,40,76,.96)', r * .052);
        arc(ctx, r * .944, a + .008, b - .008, i % 3 ? 'rgba(13,139,228,.78)' : 'rgba(27,193,255,.93)', r * .022, 8);
        arc(ctx, r * .967, a + .008, b - .008, 'rgba(111,237,255,.66)', .8);
        arc(ctx, r * .916, a + .008, b - .008, 'rgba(5,66,121,.8)', 1.3);
        arc(ctx, r * .853, a + .05, b - .015, 'rgba(22,111,179,.45)', r * .018);
      }
      for (const [scale, opacity] of [[.887,.48],[.796,.66],[.762,.42],[.705,.55],[.654,.35],[.6,.3],[.3,.4]]) {
        arc(ctx, r * scale, 0, tau, 'rgba(54,187,241,' + opacity + ')', scale === .705 ? 1.2 : .65);
      }
      ctx.setLineDash([1, 5]);
      arc(ctx, r * .817, 0, tau, 'rgba(108,229,255,.54)', 1.1);
      arc(ctx, r * .575, 0, tau, 'rgba(52,166,218,.38)', .8); ctx.setLineDash([]);
      // Static depth planes under the moving orbit highlights.
      for (let i = 0; i < 3; i++) {
        ctx.beginPath(); ctx.ellipse(0, 0, r * .665, r * (.24 + i * .04), i * 1.02, 0, tau);
        ctx.strokeStyle = 'rgba(43,185,237,.24)'; ctx.lineWidth = .8; ctx.stroke();
      }
      // Circuit junctions and warm reference marks remain fixed.
      for (let i = 0; i < 4; i++) {
        const a = i / 4 * tau;
        const x = Math.cos(a) * r * .725, y = Math.sin(a) * r * .725;
        ctx.beginPath(); ctx.arc(x, y, 2, 0, tau);
        ctx.fillStyle = '#b8fbff'; ctx.shadowColor = '#00bdff'; ctx.shadowBlur = 11; ctx.fill(); ctx.shadowBlur = 0;
        ctx.beginPath(); ctx.moveTo(x - Math.cos(a) * 8, y - Math.sin(a) * 8); ctx.lineTo(x + Math.cos(a) * 8, y + Math.sin(a) * 8);
        ctx.strokeStyle = 'rgba(117,239,255,.8)'; ctx.lineWidth = 1; ctx.stroke();
      }
      for (const side of [-1, 1]) {
        ctx.beginPath();
        for (let i = 0; i < 7; i++) {
          const a = (side === 1 ? 0 : Math.PI) + (i - 3) * .027;
          ctx.moveTo(Math.cos(a) * r * .978, Math.sin(a) * r * .978);
          ctx.lineTo(Math.cos(a) * r * 1.011, Math.sin(a) * r * 1.011);
        }
        ctx.strokeStyle = 'rgba(243,192,78,.8)'; ctx.lineWidth = 1.5; ctx.stroke();
      }
    });
    const sweep = cachedLayer(size, ratio, (ctx, r) => {
      for (const [scale, start, length, opacity] of [[.889,-1.15,1.7,.95],[.889,2.2,.95,.72],[.784,.3,.85,.9],[.784,3.4,1,.75],[.652,1.8,.55,.8]]) {
        arc(ctx, r * scale, start, start + length, 'rgba(76,217,255,' + opacity + ')', 1.4, 7);
        arc(ctx, r * scale, start + .1, start + length - .1, 'rgba(178,251,255,.83)', .6);
      }
    });
    const crystal = cachedLayer(size, ratio, (ctx, r) => {
      const halo = ctx.createRadialGradient(0, 0, r*.1, 0, 0, r*.5);
      halo.addColorStop(0, 'rgba(42,207,255,.38)');
      halo.addColorStop(.45, 'rgba(0,132,239,.2)');
      halo.addColorStop(.78, 'rgba(0,93,181,.08)'); halo.addColorStop(1, 'rgba(0,40,100,0)');
      ctx.fillStyle = halo; ctx.fillRect(-r*.52,-r*.52,r*1.04,r*1.04);
      // An inset blue optical chamber adds depth behind the suspended prism.
      const chamber = ctx.createRadialGradient(-r*.1,-r*.14,r*.03,0,0,r*.355);
      chamber.addColorStop(0,'rgba(40,146,231,.3)');
      chamber.addColorStop(.46,'rgba(3,41,94,.5)');
      chamber.addColorStop(.82,'rgba(0,13,40,.69)');
      chamber.addColorStop(1,'rgba(4,117,196,.1)');
      ctx.beginPath();ctx.arc(0,0,r*.355,0,tau);ctx.fillStyle=chamber;ctx.fill();
      arc(ctx,r*.355,0,tau,'rgba(37,169,230,.38)',.7);
      arc(ctx,r*.335,3.6,5.3,'rgba(132,236,255,.56)',.8,5);
      // The energy spine, glow and speculars below are also cached artwork.
      const beam=ctx.createLinearGradient(-r*.025,0,r*.025,0);
      beam.addColorStop(0,'rgba(0,135,255,0)');beam.addColorStop(.4,'rgba(28,197,255,.2)');
      beam.addColorStop(.5,'rgba(208,255,255,.68)');beam.addColorStop(.6,'rgba(28,197,255,.2)');beam.addColorStop(1,'rgba(0,135,255,0)');
      ctx.fillStyle=beam;ctx.fillRect(-r*.025,-r*.785,r*.05,r*1.57);
      const h=r*.295,w=r*.155;
      const top=[-w*.08,-h],upperLeft=[-w*.63,-h*.3],left=[-w,0],lowerLeft=[-w*.57,h*.39];
      const bottom=[w*.12,h],lowerRight=[w*.65,h*.33],right=[w,0],upperRight=[w*.59,-h*.34];
      const ridge=[w*.12,-h*.055],innerTop=[w*.04,-h*.66],innerLeft=[-w*.42,h*.035],innerRight=[w*.49,-h*.025],innerBottom=[w*.025,h*.63];
      const polygon=points=>{ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();};
      const facet=(points,light,dark,from=[-w,-h],to=[w,h])=>{
        const gradient=ctx.createLinearGradient(...from,...to);gradient.addColorStop(0,light);gradient.addColorStop(1,dark);
        polygon(points);ctx.fillStyle=gradient;ctx.fill();ctx.strokeStyle='rgba(130,239,255,.3)';ctx.lineWidth=.55;ctx.stroke();
      };
      const hull=[top,upperRight,right,lowerRight,bottom,lowerLeft,left,upperLeft];
      facet(hull,'rgba(33,164,231,.85)','rgba(0,34,107,.96)');
      // Wide lit face, narrow bevels and dark reverse faces make a solid volume.
      facet([top,upperRight,ridge,upperLeft],'rgba(232,255,255,.96)','rgba(20,137,215,.65)',top,ridge);
      facet([upperLeft,left,ridge],'rgba(51,211,255,.82)','rgba(0,61,141,.88)',upperLeft,left);
      facet([upperRight,right,ridge],'rgba(246,255,255,.98)','rgba(64,206,250,.7)',upperRight,ridge);
      facet([left,lowerLeft,bottom,ridge],'rgba(0,120,208,.93)','rgba(0,26,91,.92)',ridge,bottom);
      facet([right,lowerRight,bottom,ridge],'rgba(187,253,255,.92)','rgba(0,136,230,.76)',right,bottom);
      facet([top,upperLeft,innerTop],'rgba(255,255,255,.96)','rgba(95,232,255,.2)',top,innerTop);
      facet([top,upperRight,innerTop],'rgba(220,253,255,.8)','rgba(3,99,185,.58)',top,upperRight);
      facet([lowerRight,bottom,innerBottom],'rgba(91,234,255,.82)','rgba(0,62,168,.56)',lowerRight,bottom);
      facet([left,lowerLeft,innerBottom,innerLeft],'rgba(10,184,250,.42)','rgba(2,65,156,.66)',left,innerBottom);
      // Internal refraction planes remain translucent instead of flat fills.
      facet([innerTop,innerRight,innerBottom,innerLeft],'rgba(222,255,255,.33)','rgba(0,111,216,.18)',innerTop,innerBottom);
      facet([upperLeft,right,innerBottom],'rgba(228,255,255,.19)','rgba(29,141,241,.04)',upperLeft,innerBottom);
      facet([top,ridge,bottom,innerLeft],'rgba(117,244,255,.12)','rgba(0,50,157,.25)',top,bottom);
      polygon(hull);ctx.strokeStyle='rgba(181,254,255,.92)';ctx.lineWidth=.9;ctx.shadowBlur=13;ctx.shadowColor='#0dcaff';ctx.stroke();ctx.shadowBlur=0;
      ctx.beginPath();ctx.moveTo(...top);ctx.lineTo(...ridge);ctx.lineTo(...bottom);
      ctx.moveTo(...left);ctx.lineTo(...ridge);ctx.lineTo(...right);
      ctx.strokeStyle='rgba(222,255,255,.72)';ctx.lineWidth=.6;ctx.stroke();
      // A white-cyan optical glare sits on a bevel, not at the flat center.
      const flareX=-w*.2,flareY=-h*.41;
      const flare=ctx.createRadialGradient(flareX,flareY,0,flareX,flareY,r*.115);
      flare.addColorStop(0,'rgba(255,255,255,.98)');flare.addColorStop(.12,'rgba(224,255,255,.82)');flare.addColorStop(.35,'rgba(64,215,255,.18)');flare.addColorStop(1,'rgba(15,155,255,0)');
      ctx.fillStyle=flare;ctx.fillRect(flareX-r*.12,flareY-r*.12,r*.24,r*.24);
      const streak=ctx.createLinearGradient(-r*.28,flareY,r*.28,flareY);
      streak.addColorStop(0,'rgba(88,224,255,0)');streak.addColorStop(.46,'rgba(147,245,255,.26)');streak.addColorStop(.5,'rgba(255,255,255,.94)');streak.addColorStop(.54,'rgba(147,245,255,.26)');streak.addColorStop(1,'rgba(88,224,255,0)');
      ctx.fillStyle=streak;ctx.fillRect(-r*.28,flareY-.45,r*.56,.9);
      ctx.beginPath();ctx.moveTo(flareX,flareY-r*.047);ctx.lineTo(flareX,flareY+r*.047);
      ctx.strokeStyle='rgba(229,255,255,.88)';ctx.lineWidth=.7;ctx.stroke();
      ctx.beginPath();ctx.arc(right[0]*.72,-h*.075,.85,0,tau);ctx.fillStyle='#eeffff';ctx.fill();
    });
    coreLayers = { key, size, base, sweep, crystal };
    coreDirty = true;
  }

  function resizeCanvases() {
    const ratio = Math.min(window.devicePixelRatio || 1, settings.performance_mode === 'balanced' ? 1.25 : 1);
    const bounds = core.getBoundingClientRect(), waveBounds = wave.getBoundingClientRect();
    const changed = dimensions.width !== bounds.width || dimensions.height !== bounds.height || dimensions.ratio !== ratio;
    dimensions = { width: bounds.width, height: bounds.height, waveWidth: waveBounds.width, waveHeight: waveBounds.height, ratio };
    for (const [canvas, ctx, width, height] of [[core,coreContext,bounds.width,bounds.height],[wave,waveContext,waveBounds.width,waveBounds.height]]) {
      const nextWidth = Math.max(1, Math.round(width * ratio)), nextHeight = Math.max(1, Math.round(height * ratio));
      if (canvas.width !== nextWidth || canvas.height !== nextHeight) { canvas.width = nextWidth; canvas.height = nextHeight; }
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }
    if (bounds.width > 0 && bounds.height > 0 && changed) buildCoreLayers(Math.min(bounds.width, bounds.height), ratio);
    coreDirty = true; waveDirty = true;
    renderFrame(performance.now(), false);
    scheduleAnimation();
  }
  const resizeObserver = new ResizeObserver(resizeCanvases);
  resizeObserver.observe(core); resizeObserver.observe(wave);

  function drawCore(level) {
    const { width, height } = dimensions;
    if (width < 1 || height < 1 || !coreLayers) return;
    const ctx = coreContext, size = coreLayers.size, r = size * .435;
    ctx.clearRect(0, 0, width, height);
    ctx.save(); ctx.translate(width / 2, height / 2);
    ctx.drawImage(coreLayers.base, -size/2, -size/2, size, size);
    ctx.save(); ctx.rotate(phase * .35); ctx.globalAlpha = .88 + level * .12;
    ctx.drawImage(coreLayers.sweep, -size/2, -size/2, size, size); ctx.restore();
    // Two inexpensive moving planes; all soft halo work is already cached.
    for (let i = 0; i < 2; i++) {
      ctx.beginPath(); ctx.ellipse(0, 0, r * (.66 + level * .012), r * .245, phase * (i ? -.15 : .18) + i * 1.25, .15, Math.PI + .9);
      ctx.strokeStyle = i ? 'rgba(42,177,248,.7)' : 'rgba(129,239,255,.82)'; ctx.lineWidth = 1; ctx.stroke();
    }
    const rotation = phase * .16, cos = Math.cos(rotation), sin = Math.sin(rotation);
    for (const [x,y,z] of particles) {
      const px = x * cos + z * sin, depth = -x * sin + z * cos;
      ctx.fillStyle = 'rgba(131,228,255,' + (.18 + (1-depth)*.24) + ')';
      ctx.fillRect(px * r * .55, y * r * .55, 1 + level * .3, 1 + level * .3);
    }
    const pulse = 1 + level * .075;
    ctx.globalAlpha = .87 + level * .13;
    ctx.drawImage(coreLayers.crystal, -size*pulse/2, -size*pulse/2, size*pulse, size*pulse);
    ctx.restore();
    lastCoreLevel = level; coreDirty = false;
  }

  function drawWave() {
    const { waveWidth: width, waveHeight: height } = dimensions;
    if (width < 1 || height < 1) return;
    const ctx = waveContext;
    ctx.clearRect(0, 0, width, height);
    const count = 48, gap = Math.min(7, width / count), start = (width - gap * count) / 2;
    ctx.lineCap = 'round'; ctx.lineWidth = 1.6;
    for (let i = 0; i < count; i++) {
      const value = audioPlaying ? Math.abs(analyserValues[Math.floor(i/count*analyserValues.length)] || 0) : micHistory[Math.floor(i/count*micHistory.length)] || 0;
      const heightUsed = Math.min(height * .8, Math.max(1, value * height * (audioPlaying ? 3.5 : 8)));
      const x = start + i * gap;
      ctx.beginPath(); ctx.moveTo(x, (height-heightUsed)/2); ctx.lineTo(x, (height+heightUsed)/2);
      ctx.strokeStyle = value > .01 ? 'rgba(115,237,255,.9)' : 'rgba(83,163,188,.32)'; ctx.stroke();
    }
    waveDirty = false;
  }

  function renderPolicy() {
    const visible = dimensions.width > 0 && dimensions.height > 0 || dimensions.waveWidth > 0 && dimensions.waveHeight > 0;
    const signal = audioPlaying || Boolean(mic && microphoneLevel > .008);
    const ornamental = settings.animation_enabled !== false && !reducedMotion.matches;
    return { run: visible && (ornamental || signal || Boolean(mic && waveDirty)), interval: 1000 / (signal ? (settings.performance_mode === 'balanced' ? 20 : 12) : (settings.performance_mode === 'balanced' ? 8 : 5)), ornamental };
  }

  function renderFrame(time, advance = true) {
    if (document.hidden || destroyed) return;
    if (analyser && audioPlaying) {
      analyser.getFloatTimeDomainData(analyserValues);
      let sum = 0; for (const value of analyserValues) sum += value * value;
      playbackLevel = Math.sqrt(sum / analyserValues.length);
    } else { analyserValues.fill(0); playbackLevel = 0; }
    const policy = renderPolicy();
    const elapsed = lastFrame ? Math.min(time-lastFrame, 300) : 0;
    if (advance && policy.ornamental) phase += elapsed * (serverState === 'thinking' ? .00024 : .0002);
    const level = settings.animation_enabled === false ? 0 : Math.min(1, Math.max(microphoneLevel, playbackLevel) * 7);
    if (coreDirty || (advance && policy.ornamental) || Math.abs(level-lastCoreLevel) > .002) drawCore(level);
    if (waveDirty || mic || audioPlaying) drawWave();
    lastFrame = time;
  }

  function pauseAnimation() {
    clearTimeout(animationTimer); animationTimer = null; animationDue = 0;
  }

  function scheduleAnimation() {
    if (destroyed || document.hidden) { pauseAnimation(); return; }
    const policy = renderPolicy();
    if (!policy.run) { pauseAnimation(); renderFrame(performance.now(), false); return; }
    const now = performance.now(), delay = Math.max(0, policy.interval - (now-lastFrame));
    const due = now + delay;
    if (animationTimer !== null && animationDue <= due + 1) return;
    pauseAnimation(); animationDue = due;
    animationTimer = setTimeout(() => {
      animationTimer = null; animationDue = 0;
      renderFrame(performance.now()); scheduleAnimation();
    }, delay);
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { pauseAnimation(); stopSetupPolling(); }
    else { lastFrame = 0; coreDirty = true; waveDirty = true; renderFrame(performance.now(), false); scheduleAnimation(); scheduleSetupPoll(); }
  });
  reducedMotion.addEventListener('change', () => { coreDirty = true; pauseAnimation(); renderFrame(performance.now(), false); scheduleAnimation(); });
  resizeCanvases();

  async function initialize() {
    const results = await Promise.allSettled([api('/api/status'), api('/api/history')]);
    if (results[0].status === 'fulfilled') updateStatus(results[0].value);
    else showNotice('Não foi possível consultar o servidor local. Tentando conectar…');
    if (results[1].status === 'fulfilled') {
      for (const message of results[1].value.messages || []) appendMessage(message.role, message.content, { timestamp: message.created_at });
    }
    connect();
    refreshMicCaption();
    setTimeout(() => $('#bootScreen').classList.add('finished'), reducedMotion.matches ? 0 : 900);
  }
  const statusTimer = setInterval(async () => {
    if (document.hidden || socket?.readyState !== WebSocket.OPEN) return;
    try { updateStatus(await api('/api/status')); } catch { /* WebSocket reconnect owns connection messaging. */ }
  }, 15000);
  window.addEventListener('pagehide', () => {
    destroyed = true;
    clearTimeout(reconnectTimer);
    clearInterval(clockTimer);
    clearInterval(statusTimer);
    pauseAnimation();
    stopSetupPolling();
    resizeObserver.disconnect();
    stopMicrophone();
    stopPlayback();
    socket?.close();
    if (audioContext) void audioContext.close().catch(() => {});
  }, { once: true });
  void initialize();
})();
