/* Independent animation controller. Qt receives events through its console.
   Do not connect this page to the network or to Codex's document/runtime. */
(() => {
  'use strict';
  const query = new URLSearchParams(location.search);
  const mode = query.get('mode') === 'full' ? 'full' : 'simple';
  const audioEnabled = query.get('sound') !== 'off';
  const requestedScheme = query.get('color') || query.get('scheme') || 'amber';
  const scheme = ['amber','green','cyan','white'].includes(requestedScheme) ? requestedScheme : 'amber';
  document.documentElement.dataset.scheme = scheme;
  const status = document.getElementById('launcher-status');
  const message = document.getElementById('launcher-message');
  const close = document.getElementById('launcher-close');
  const startTime = performance.now();
  const state = {mode, scheme, loaded: false, ready: false, logoVisible: false, systemReady: false, animationDone: false, skipped: false, exiting: false, error: null, phases: []};
  let show, finishedTimer = null;
  const emit = (event, details = {}) => console.info('LAUNCHER:' + JSON.stringify({event, ...details}));
  // Play the latest user MP3 once at the start of the animation. Starting it
  // before the logo drawing reduces the final audio barrier by about 2.45 s.
  const audio = audioEnabled ? new Audio('audio/boot.mp3') : new Audio();
  if (audioEnabled) {
    audio.preload = 'auto';
  }
  audio.loop = false;
  const audioState = {enabled: audioEnabled, status: audioEnabled ? 'idle' : 'disabled', error: null, loops: 0};
  let audioFadeFrame = null, audioDeadline = null;
  let audioEndPromise = Promise.resolve(), resolveAudioEnd = null;
  const settleAudioEnd = () => {
    if (audioDeadline !== null) clearTimeout(audioDeadline);
    audioDeadline = null;
    resolveAudioEnd?.(); resolveAudioEnd = null;
  };
  const cancelAudioFade = () => {
    if (audioFadeFrame !== null) cancelAnimationFrame(audioFadeFrame);
    audioFadeFrame = null;
  };
  const stopAudio = (reason = 'native') => {
    // Native stop and JS skip may arrive as separate browser tasks. Cancel the
    // show before releasing its audio barrier so a final plate cannot revive.
    if (reason === 'native') show?.cancel();
    if (!audioEnabled) return;
    cancelAudioFade();
    const wasStopped = audioState.status === 'stopped';
    audioState.status = 'stopped';
    audio.pause();
    try { audio.currentTime = 0; } catch (_) { /* metadata might not be loaded */ }
    settleAudioEnd();
    if (!wasStopped) emit('audio_stopped', {reason, elapsed_ms: Math.round(performance.now()-startTime)});
  };
  const audioError = error => {
    if (!audioEnabled || audioState.status === 'stopped') return;
    audioState.error = String(error?.message || error);
    stopAudio('audio_error');
    // Sound failure must never prevent animation or the official-app handoff.
    emit('audio_error', {message: audioState.error});
  };
  audio.addEventListener('error', () => audioError('本地 MP3 无法播放（' + (audio.error?.code || 'unknown') + '）'));
  audio.addEventListener('playing', () => {
    if (!audioEnabled) return;
    if (audioState.status === 'stopped') { audio.pause(); return; }
    if (audioState.status === 'starting') {
      audioState.status = 'playing';
      emit('audio_started', {source: 'audio/boot.mp3', loop: false, elapsed_ms: Math.round(performance.now()-startTime)});
    }
  });
  audio.addEventListener('ended', () => {
    if (!audioEnabled || audioState.status === 'stopped') return;
    audioState.status = 'ended';
    settleAudioEnd();
    emit('audio_ended', {elapsed_ms: Math.round(performance.now()-startTime)});
  });
  const startAudio = () => {
    if (!audioEnabled || state.skipped || state.exiting || state.error || audioState.status !== 'idle') return;
    audioState.status = 'starting';
    audioEndPromise = new Promise(resolve => { resolveAudioEnd = resolve; });
    // Absolute deadline starts here, not when the visual phases later reach
    // beforeReady. A media stall therefore fits within Qt's 22-second watchdog.
    const seconds = Number.isFinite(audio.duration) && audio.duration > 0 ? Math.min(audio.duration + 2, 16) : 16;
    audioDeadline = setTimeout(() => { emit('audio_timeout'); stopAudio('timeout'); }, seconds * 1000);
    audio.volume = 1;
    try { Promise.resolve(audio.play()).catch(audioError); } catch (error) { audioError(error); }
  };
  const fadeAudio = () => {
    if (!audioEnabled) return;
    if (audio.paused || audioState.status === 'stopped') { stopAudio('exit'); return; }
    cancelAudioFade();
    audioState.status = 'fading';
    const began = performance.now(), initialVolume = audio.volume;
    const step = now => {
      const progress = Math.min(1, Math.max(0, (now - began) / 600));
      audio.volume = initialVolume * (1 - progress);
      if (progress >= 1) stopAudio('exit');
      else audioFadeFrame = requestAnimationFrame(step);
    };
    audioFadeFrame = requestAnimationFrame(step);
  };
  const setWaiting = text => {
    if (state.exiting || state.error) return;
    message.textContent = text || '等待 OpenAI Codex 主窗口就绪…';
    status.hidden = false;
  };
  const complete = () => {
    if (state.animationDone || state.exiting || state.error) return;
    state.animationDone = true;
    if (!state.ready) setWaiting();
    emit('animation_done', {skipped: state.skipped, elapsed_ms: Math.round(performance.now()-startTime)});
  };
  const skip = () => {
    if (state.exiting || state.error) return;
    stopAudio('skip');
    if (state.animationDone) return;
    state.skipped = true; show?.cancel(); emit('skip'); complete();
  };
  const finish = () => {
    if (state.exiting) return;
    state.exiting = true; show?.cancel(); status.hidden = true;
    fadeAudio();
    document.body.classList.add('launcher-out');
    finishedTimer = setTimeout(() => { emit('exit_done'); finishedTimer = null; }, 660);
  };
  const showError = text => {
    if (state.exiting) return;
    state.error = String(text || 'Codex 启动失败'); show?.cancel();
    stopAudio('error');
    message.textContent = state.error; status.hidden = false; close.hidden = false;
    document.body.classList.add('launcher-error');
  };
  window.launcher = {
    setReady() { state.ready = true; if (!state.error) status.hidden = true; },
    finish, setWaiting, showError, skip, stopAudio,
    getState() { return {...state, phases: [...state.phases], timers: show?.timers(),
      audio: {...audioState, paused: audio.paused, currentTime: audio.currentTime,
        duration: Number.isFinite(audio.duration) ? audio.duration : null,
        volume: audio.volume, fadePending: audioFadeFrame !== null, deadlinePending: audioDeadline !== null}}; },
    dispose() { stopAudio('dispose'); show?.cancel(); if (finishedTimer !== null) clearTimeout(finishedTimer); },
  };
  document.addEventListener('click', event => { if (event.target === close) { emit('close_requested'); finish(); } else skip(); });
  window.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); if (state.error) { emit('close_requested'); finish(); } else skip(); } }, true);
  window.addEventListener('pagehide', () => window.launcher.dispose(), {once:true});
  const fail = error => { const text = String(error?.message || error); showError('动画无法继续播放：' + text); emit('animation_error', {message:text}); };
  window.addEventListener('error', event => fail(event.error || event.message));
  try {
    show = window.create550CShow({mode,
      onLogoVisible() { state.logoVisible = true; emit('logo_visible', {elapsed_ms: Math.round(performance.now()-startTime)}); },
      async beforeReady() {
        if (!audioEnabled) return;
        const began = performance.now();
        const waiting = audioState.status === 'starting' || audioState.status === 'playing';
        emit('ready_audio_wait', {waiting, elapsed_ms: Math.round(began-startTime)});
        await audioEndPromise;
        emit('ready_audio_wait_done', {elapsed_ms: Math.round(performance.now()-startTime), duration_ms: Math.round(performance.now()-began)});
      },
      onSystemReady() { state.systemReady = true; stopAudio('system_ready'); emit('system_ready', {elapsed_ms: Math.round(performance.now()-startTime)}); },
      onPhase: phase => state.phases.push({phase, elapsed_ms: Math.round(performance.now()-startTime)}), onError: fail});
    state.loaded = true; emit('loaded', {mode, scheme, audio_enabled: audioEnabled});
    startAudio();
    show.start().then(complete, error => { if (!show.isCancelled(error)) fail(error); });
  } catch (error) { fail(error); }
})();
