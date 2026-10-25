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
  let settings = { require_wake_word: false, speech_rate: 1, voice_enabled: true };
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
      throw new Error(message);
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
  }

  function updateTelemetry(system) {
    if (!system) return;
    $('#cpuValue').textContent = Number.isFinite(system.cpu_percent) ? Math.round(system.cpu_percent) + '%' : '—';
    $('#ramValue').textContent = Number.isFinite(system.ram_percent) ? Math.round(system.ram_percent) + '%' : '—';
    if (Number.isFinite(system.ram_total_gb)) $('#ramValue').title = system.ram_total_gb.toFixed(1) + ' GB disponíveis no servidor';
  }

  function applySettings(values) {
    if (!values) return;
    settings = { ...settings, ...values };
    $('#wakeWordSetting').checked = Boolean(settings.require_wake_word);
    $('#voiceSetting').checked = settings.voice_enabled !== false;
    $('#rateSetting').value = settings.speech_rate;
    $('#rateOutput').textContent = Number(settings.speech_rate).toLocaleString('pt-BR', { minimumFractionDigits: 1 }) + '×';
    els.voice.setAttribute('aria-pressed', String(settings.voice_enabled !== false));
    $('#voiceLabel').textContent = settings.voice_enabled !== false ? 'Voz ativada' : 'Voz silenciada';
    els.voice.classList.toggle('muted', settings.voice_enabled === false);
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
      showNotice(status.models?.llm?.ready ? '' : 'O modelo de conversa ainda não está disponível. Os comandos locais e a memória podem ser usados agora.');
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
          pendingText = '';
          pendingMessage = appendMessage('assistant', '', { streaming: true });
        }
        pendingText += event.text || '';
        pendingMessage.querySelector('.message-body').textContent = pendingText;
        scrollConversation();
        break;
      case 'assistant':
        if (pendingMessage) finishPending(event.text || pendingText);
        else appendMessage('assistant', event.text || '');
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
    refreshState();
  }

  function refreshMicCaption() {
    if (micStarting) {
      $('#micLabel').textContent = 'Aguardando permissão do microfone…';
      return;
    }
    $('#micLabel').replaceChildren();
    $('#micLabel').append(document.createTextNode(mic ? 'Microfone ligado' : 'Microfone desligado'));
    const hint = document.createElement('span');
    hint.textContent = mic ? (settings.require_wake_word ? ' · diga “Ivi” para começar' : ' · pode falar naturalmente') : ' · toque para conversar';
    $('#micLabel').append(hint);
    els.mic.setAttribute('aria-pressed', String(Boolean(mic)));
    els.mic.setAttribute('aria-label', mic ? 'Desligar microfone' : 'Ativar microfone');
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
    micHistory.push(rms);
    micHistory.shift();
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
    if (appStatus?.models?.stt?.ready === false) return toast('Configure o modelo local de reconhecimento de fala antes de ativar o microfone. Veja as configurações.');
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
  els.mic.addEventListener('click', () => { if (mic) stopMicrophone(); else void startMicrophone(); });
  els.voice.addEventListener('click', () => void saveSettings({ voice_enabled: settings.voice_enabled === false }));
  els.interrupt.addEventListener('click', interrupt);
  $('#settingsOpen').addEventListener('click', () => $('#settingsDialog').showModal());
  $('#memoryOpen').addEventListener('click', () => { $('#memoryDialog').showModal(); void loadMemory(); });
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $('#' + button.dataset.close).close()));
  document.querySelectorAll('.panel-dialog:not(#toolDialog)').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); }));
  $('#toolDialog').addEventListener('cancel', event => { event.preventDefault(); confirmTool(false); });
  $('#toolApprove').addEventListener('click', () => confirmTool(true));
  $('#toolReject').addEventListener('click', () => confirmTool(false));
  $('#wakeWordSetting').addEventListener('change', event => void saveSettings({ require_wake_word: event.target.checked }));
  $('#voiceSetting').addEventListener('change', event => void saveSettings({ voice_enabled: event.target.checked }));
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

  // A lightweight projected sphere: 220 particles, no WebGL or remote assets.
  const core = $('#coreCanvas');
  const wave = $('#waveCanvas');
  const coreContext = core.getContext('2d');
  const waveContext = wave.getContext('2d');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const particles = Array.from({ length: 220 }, (_, index) => {
    const y = 1 - (index / 219) * 2;
    const radius = Math.sqrt(1 - y * y);
    const angle = index * Math.PI * (3 - Math.sqrt(5));
    return [Math.cos(angle) * radius, y, Math.sin(angle) * radius];
  });
  let dimensions = { width: 600, height: 430, waveWidth: 500, waveHeight: 32 };
  let frameId = null;
  let lastFrame = 0;
  let phase = 0;
  const analyserValues = new Float32Array(128);

  function resizeCanvases() {
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
    const bounds = core.getBoundingClientRect();
    const waveBounds = wave.getBoundingClientRect();
    dimensions = { width: bounds.width, height: bounds.height, waveWidth: waveBounds.width, waveHeight: waveBounds.height };
    for (const [canvas, context, width, height] of [[core, coreContext, bounds.width, bounds.height], [wave, waveContext, waveBounds.width, waveBounds.height]]) {
      const nextWidth = Math.max(1, Math.round(width * ratio));
      const nextHeight = Math.max(1, Math.round(height * ratio));
      if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
        canvas.width = nextWidth;
        canvas.height = nextHeight;
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
      }
    }
    // Resizing clears a Canvas; paint synchronously instead of leaving a blank
    // frame while a dialog or full-page capture changes viewport dimensions.
    drawCore(Math.min(1, Math.max(microphoneLevel, playbackLevel) * 7));
    drawWave();
  }
  const resizeObserver = new ResizeObserver(resizeCanvases);
  resizeObserver.observe(core);
  resizeObserver.observe(wave);

  function projected(point, radius, rotation) {
    const [x, y, z] = point;
    const rx = x * Math.cos(rotation) + z * Math.sin(rotation);
    const rz = -x * Math.sin(rotation) + z * Math.cos(rotation);
    const ry = y * Math.cos(0.4) - rz * Math.sin(0.4);
    const depth = y * Math.sin(0.4) + rz * Math.cos(0.4);
    const scale = 2.8 / (2.8 + depth * 0.36);
    return [rx * radius * scale, ry * radius * scale, depth];
  }

  function drawCore(level) {
    const { width, height } = dimensions;
    const ctx = coreContext;
    ctx.clearRect(0, 0, width, height);
    if (width < 1 || height < 1) return;
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width * 0.27, height * 0.34) * (1 + level * 0.1);
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * 1.8);
    glow.addColorStop(0, 'rgba(31,157,207,' + (0.13 + level * 0.15) + ')');
    glow.addColorStop(0.45, 'rgba(22,121,180,0.05)');
    glow.addColorStop(1, 'rgba(10,80,140,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);
    ctx.save();
    ctx.translate(cx, cy);
    for (let ring = 0; ring < 3; ring++) {
      ctx.beginPath();
      for (let step = 0; step <= 96; step++) {
        const angle = step / 96 * Math.PI * 2;
        const tilt = 0.25 + ring * 0.66 + Math.sin(phase * 0.5) * 0.07;
        const point = [Math.cos(angle), Math.sin(angle) * Math.cos(tilt), Math.sin(angle) * Math.sin(tilt)];
        const [x, y] = projected(point, radius * (1.28 + ring * 0.08), phase * (ring % 2 ? -0.25 : 0.3) + ring);
        if (step === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = ['rgba(69,198,243,0.25)', 'rgba(46,112,171,0.18)', 'rgba(80,221,238,0.2)'][ring];
      ctx.lineWidth = ring === 0 ? 1 : 0.65;
      ctx.stroke();
    }
    const points = particles.map((point, index) => {
      const motion = 1 + Math.sin(phase * 1.4 + index * 0.16) * (0.018 + level * 0.07);
      return projected(point, radius * motion, phase * 0.35);
    }).sort((a, b) => b[2] - a[2]);
    for (const [x, y, depth] of points) {
      const front = (1 - depth) / 2;
      ctx.beginPath();
      ctx.arc(x, y, 0.7 + front * 1.15 + level * 0.3, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + Math.round(55 + front * 55) + ',' + Math.round(155 + front * 85) + ',245,' + (0.16 + front * 0.68) + ')';
      ctx.fill();
    }
    ctx.beginPath();
    ctx.arc(0, 0, radius * 0.48, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(80,212,249,0.08)';
    ctx.stroke();
    ctx.restore();
  }

  function drawWave() {
    const ctx = waveContext;
    const { waveWidth: width, waveHeight: height } = dimensions;
    ctx.clearRect(0, 0, width, height);
    const count = 56;
    const gap = Math.min(7, width / count);
    const start = (width - gap * count) / 2;
    ctx.lineCap = 'round';
    ctx.lineWidth = 2;
    for (let index = 0; index < count; index++) {
      const value = audioPlaying ? Math.abs(analyserValues[Math.floor(index / count * analyserValues.length)] || 0) : micHistory[Math.floor(index / count * micHistory.length)] || 0;
      const size = Math.min(height * 0.8, Math.max(1, value * height * (audioPlaying ? 3.5 : 8)));
      const x = start + index * gap;
      ctx.beginPath();
      ctx.moveTo(x, (height - size) / 2);
      ctx.lineTo(x, (height + size) / 2);
      ctx.strokeStyle = value > 0.01 ? 'rgba(99,215,238,0.78)' : 'rgba(100,143,165,0.25)';
      ctx.stroke();
    }
  }

  function animate(time) {
    frameId = requestAnimationFrame(animate);
    const interval = reducedMotion.matches ? 120 : 1000 / 30;
    if (time - lastFrame < interval) return;
    const elapsed = Math.min(time - lastFrame, 100);
    lastFrame = time;
    if (analyser && audioPlaying) {
      analyser.getFloatTimeDomainData(analyserValues);
      let sum = 0;
      for (const value of analyserValues) sum += value * value;
      playbackLevel = Math.sqrt(sum / analyserValues.length);
    } else analyserValues.fill(0);
    const level = Math.min(1, Math.max(microphoneLevel, playbackLevel) * 7);
    phase += elapsed * (reducedMotion.matches ? 0.00005 : 0.00034);
    drawCore(level);
    drawWave();
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelAnimationFrame(frameId); frameId = null; }
    else if (!frameId) { lastFrame = 0; frameId = requestAnimationFrame(animate); }
  });
  resizeCanvases();
  frameId = requestAnimationFrame(animate);

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
    cancelAnimationFrame(frameId);
    resizeObserver.disconnect();
    stopMicrophone();
    stopPlayback();
    socket?.close();
    if (audioContext) void audioContext.close().catch(() => {});
  }, { once: true });
  void initialize();
})();
