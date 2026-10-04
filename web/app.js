const state = {
  mediaRecorder: null,
  stream: null,
  chunks: [],
  busy: false,
  health: null,
};

const elements = {
  schoolName: document.querySelector('#school-name'),
  statusButton: document.querySelector('#status-button'),
  statusDot: document.querySelector('#status-dot'),
  statusLabel: document.querySelector('#status-label'),
  servicePanel: document.querySelector('#service-panel'),
  closeServices: document.querySelector('#close-services'),
  services: document.querySelector('#services'),
  talkButton: document.querySelector('#talk-button'),
  talkLabel: document.querySelector('#talk-label'),
  queryForm: document.querySelector('#query-form'),
  queryInput: document.querySelector('#query-input'),
  accessible: document.querySelector('#accessible-toggle'),
  answerCard: document.querySelector('#answer-card'),
  answerKicker: document.querySelector('#answer-kicker'),
  answerText: document.querySelector('#answer-text'),
  locationMeta: document.querySelector('#location-meta'),
  clarificationOptions: document.querySelector('#clarification-options'),
  locationList: document.querySelector('#location-list'),
  locationCount: document.querySelector('#location-count'),
};

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Servizio non disponibile');
  return data;
}

function setBusy(busy, label = '') {
  state.busy = busy;
  elements.talkButton.disabled = busy;
  elements.queryInput.disabled = busy;
  elements.talkButton.classList.toggle('processing', busy);
  if (label) elements.talkLabel.textContent = label;
  else if (!elements.talkButton.classList.contains('recording')) elements.talkLabel.textContent = 'Premi per parlare';
}

function showAnswer(message, { error = false, kicker = 'Indicazioni', location = null } = {}) {
  elements.answerCard.classList.toggle('error', error);
  elements.answerKicker.textContent = kicker;
  elements.answerText.textContent = message;
  if (location) {
    const parts = [location.building, location.floor, location.room].filter(Boolean);
    elements.locationMeta.textContent = parts.join(' · ');
    elements.locationMeta.hidden = false;
  } else {
    elements.locationMeta.hidden = true;
  }
  elements.clarificationOptions.replaceChildren();
  elements.clarificationOptions.hidden = true;
}

function showClarificationOptions(options = []) {
  if (!options.length) return;
  const buttons = options.map(option => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'clarification-button';
    const title = document.createElement('strong');
    title.textContent = option.name;
    const detail = document.createElement('small');
    detail.textContent = [option.building, option.floor, option.room].filter(Boolean).join(' · ');
    button.append(title, detail);
    button.addEventListener('click', () => ask(`Intendo ${option.name}`));
    return button;
  });
  elements.clarificationOptions.replaceChildren(...buttons);
  elements.clarificationOptions.hidden = false;
}

async function ask(text) {
  const cleanText = text.trim();
  if (!cleanText || state.busy) return;
  setBusy(true, 'Cerco la risposta…');
  showAnswer(`Hai chiesto: “${cleanText}”`, { kicker: 'Domanda ricevuta' });
  try {
    const result = await jsonFetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: cleanText, accessible: elements.accessible.checked }),
    });
    const ok = result.status === 'ok';
    showAnswer(result.answer, {
      error: !ok && result.status !== 'clarification_required',
      kicker: ok ? 'Percorso trovato' : result.status === 'clarification_required' ? 'Scegli una destinazione' : 'Serve un dettaglio',
      location: result.matched_location,
    });
    if (result.status === 'clarification_required') showClarificationOptions(result.options);
    if (ok || result.status === 'clarification_required') await speak(result.answer);
  } catch (error) {
    showAnswer(error.message, { error: true, kicker: 'Non riesco a rispondere' });
  } finally {
    setBusy(false);
  }
}

async function speak(text) {
  try {
    const response = await fetch('/api/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) throw new Error('Piper non disponibile');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true });
    await audio.play();
  } catch {
    if (state.health?.browser_tts_fallback && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'it-IT';
      utterance.rate = 0.96;
      window.speechSynthesis.speak(utterance);
    }
  }
}

async function beginRecording(event) {
  event.preventDefault();
  if (state.busy || state.mediaRecorder?.state === 'recording') return;
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const preferredType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '';
    state.mediaRecorder = new MediaRecorder(state.stream, preferredType ? { mimeType: preferredType } : undefined);
    state.chunks = [];
    state.mediaRecorder.addEventListener('dataavailable', event => {
      if (event.data.size) state.chunks.push(event.data);
    });
    state.mediaRecorder.addEventListener('stop', finishRecording, { once: true });
    state.mediaRecorder.start();
    elements.talkButton.classList.add('recording');
    elements.talkLabel.textContent = 'Sto ascoltando…';
  } catch {
    showAnswer('Non riesco ad accedere al microfono. Controlla il permesso del browser oppure usa la domanda scritta.', {
      error: true,
      kicker: 'Microfono non disponibile',
    });
  }
}

function endRecording(event) {
  event.preventDefault();
  if (state.mediaRecorder?.state === 'recording') state.mediaRecorder.stop();
}

async function finishRecording() {
  elements.talkButton.classList.remove('recording');
  setBusy(true, 'Trascrivo la domanda…');
  const mimeType = state.mediaRecorder?.mimeType || 'audio/webm';
  const blob = new Blob(state.chunks, { type: mimeType });
  state.stream?.getTracks().forEach(track => track.stop());
  try {
    const result = await jsonFetch('/api/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': mimeType },
      body: blob,
    });
    elements.queryInput.value = result.text;
    setBusy(false);
    await ask(result.text);
  } catch (error) {
    showAnswer(error.message, { error: true, kicker: 'Trascrizione non disponibile' });
    setBusy(false);
    elements.queryInput.focus();
  }
}

function renderServices(services) {
  const labels = {
    database: 'Archivio scolastico',
    llama: 'Modello Llama',
    embeddings: 'Ricerca semantica',
    whisper: 'Riconoscimento vocale',
    piper: 'Sintesi vocale',
  };
  elements.services.replaceChildren(...Object.entries(services).map(([name, online]) => {
    const row = document.createElement('div');
    row.className = 'service-row';
    const label = document.createElement('strong');
    label.textContent = labels[name] || name;
    const badge = document.createElement('span');
    badge.className = `service-badge ${online ? 'online' : ''}`;
    badge.textContent = online ? 'Attivo' : 'Da collegare';
    row.append(label, badge);
    return row;
  }));
}

async function loadHealth() {
  try {
    state.health = await jsonFetch('/api/health');
    elements.schoolName.textContent = state.health.school_name;
    renderServices(state.health.services);
    const voiceReady = state.health.services.whisper && (state.health.services.piper || state.health.browser_tts_fallback);
    elements.statusDot.classList.toggle('ready', voiceReady);
    elements.statusLabel.textContent = voiceReady ? 'Sistema pronto' : 'Demo testuale pronta';
  } catch {
    elements.statusLabel.textContent = 'Verifica necessaria';
  }
}

async function loadLocations() {
  try {
    const locations = await jsonFetch('/api/locations');
    elements.locationCount.textContent = locations.length;
    elements.locationList.replaceChildren(...locations.map((location, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'location-card';
      button.innerHTML = `<span class="location-number">${String(index + 1).padStart(2, '0')}</span><span><strong></strong><small></small></span>`;
      button.querySelector('strong').textContent = location.name;
      button.querySelector('small').textContent = [location.building, location.floor, location.room].filter(Boolean).join(' · ');
      button.addEventListener('click', () => ask(`Dove si trova ${location.name}?`));
      return button;
    }));
  } catch {
    elements.locationList.textContent = 'Archivio momentaneamente non disponibile.';
  }
}

elements.queryForm.addEventListener('submit', event => {
  event.preventDefault();
  ask(elements.queryInput.value);
});

elements.talkButton.addEventListener('pointerdown', beginRecording);
elements.talkButton.addEventListener('pointerup', endRecording);
elements.talkButton.addEventListener('pointercancel', endRecording);
elements.talkButton.addEventListener('keydown', event => {
  if ((event.code === 'Space' || event.code === 'Enter') && !event.repeat) beginRecording(event);
});
elements.talkButton.addEventListener('keyup', event => {
  if (event.code === 'Space' || event.code === 'Enter') endRecording(event);
});

elements.statusButton.addEventListener('click', () => {
  const opening = elements.servicePanel.hidden;
  elements.servicePanel.hidden = !opening;
  elements.statusButton.setAttribute('aria-expanded', String(opening));
});
elements.closeServices.addEventListener('click', () => {
  elements.servicePanel.hidden = true;
  elements.statusButton.setAttribute('aria-expanded', 'false');
});

loadHealth();
loadLocations();
