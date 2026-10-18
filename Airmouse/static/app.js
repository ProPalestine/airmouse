const $ = (id) => document.getElementById(id);
const els = {
  video: $('video'), canvas: $('overlay'), frame: $('videoFrame'), placeholder: $('placeholder'),
  start: $('startButton'), pause: $('pauseButton'), stop: $('stopButton'), emergency: $('emergencyButton'), float: $('floatButton'),
  cameraSelect: $('cameraSelect'), cameraInfo: $('cameraInfo'), trackingPill: $('trackingPill'),
  gestureText: $('gestureText'), gestureHint: $('gestureHint'), gestureSymbol: $('gestureSymbol'),
  handStatus: $('handStatus'), handDot: $('handDot'), desktopStatus: $('desktopStatus'), desktopDot: $('desktopDot'),
  resolution: $('resolution'), connection: $('connection'), fps: $('fpsBadge'), notice: $('systemNotice'), error: $('errorNotice'),
};
const ctx = els.canvas.getContext('2d');
let visionModule = null;
let landmarker = null;
let stream = null;
let rafId = null;
let active = false;
let paused = false;
let stopped = true;
let lastVideoTime = -1;
let lastApiAt = 0;
let lastScrollAt = 0;
let lastClickAt = 0;
let clickArmed = true;
let nonClickSince = null;
let smoothed = null;
let lastPoint = null;
let pointerFilter = null;
let fpsFrames = 0;
let fpsAt = performance.now();
let cameraDevices = [];
let gestureName = 'Waiting for camera';
let pinchState = 'idle';
let desktopScreen = null;
let moveInFlight = false;
let pendingMove = null;
let pausePoseSince = null;
let scrollReference = null;
let rightClickPoseSince = null;

const modelUrl = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
// 0.10.14 is pinned because this package version has a published ESM bundle;
// the earlier 0.10.22 URL returned 404 and prevented all hand tracking.
const visionBundleUrl = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs';
const wasmRoot = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm';

function setNotice(text, kind = 'info') {
  const kindMap = { info: 'info', warning: 'warning', error: 'error' };
  els.notice.className = `notice${kindMap[kind] || 'info'}`;
  els.notice.textContent = text;
  els.notice.hidden = !text;
}
function setError(text) { els.error.textContent = text; els.error.hidden = !text; }
function setConnection(kind, text) {
  const kindMap = { connected: 'connected', failed: 'failed', disconnected: 'disconnected' };
  els.connection.className = `connection ${kindMap[kind] || 'failed'}`;
  els.connection.lastElementChild.textContent = text;
}
function setGesture(name, hint, symbol = '—') {
  gestureName = name; els.gestureText.textContent = name; els.gestureHint.textContent = hint; els.gestureSymbol.textContent = symbol;
}
function setPill(text, state = '') { els.trackingPill.className = `feed-state ${state}`; els.trackingPill.lastElementChild.textContent = text; }
function statusDot(element, kind) { element.className = `tiny-dot ${kind}`; }
function reportMouseFailure(message) {
  setError(`Desktop mouse action failed: ${message}. Tracking remains active; Pause or Stop camera while you check desktop input support.`);
  els.desktopStatus.textContent = 'Action blocked'; statusDot(els.desktopDot, 'bad');
}

async function api(path, body) {
  const response = await fetch(path, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined, cache: 'no-store' });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || result.error || `Backend returned HTTP ${response.status}`);
  return result;
}

async function checkBackend() {
  try {
    const status = await api('/api/health');
    setConnection('connected', 'Backend connected');
    const desktop = status.desktop;
    desktopScreen = desktop.screen || null;
    els.resolution.textContent = desktop.screen ? `${desktop.screen.width} × ${desktop.screen.height}` : 'Unavailable';
    if (desktop.mouseControl === 'available') {
      els.desktopStatus.textContent = desktop.inputMethod === 'ydotool'
        ? `Ready · ydotool (${desktop.eventPacketsSent ?? 0} events)` : 'Ready';
      statusDot(els.desktopDot, 'good');
      setNotice('Desktop display detected. Start with a brief pointer movement in a safe area.', 'info');
    } else if (desktop.mouseControl === 'limited') {
      els.desktopStatus.textContent = 'Wayland limited'; statusDot(els.desktopDot, 'warn');
      setNotice(`${desktop.detail} Tracking preview is available; desktop cursor injection is not confirmed.`, 'warning');
    } else {
      els.desktopStatus.textContent = 'Unavailable'; statusDot(els.desktopDot, 'bad');
      setNotice(`Desktop control unavailable: ${desktop.mouseError || desktop.detail}`, 'warning');
    }
    if (desktop.mouseControl === 'unavailable' && desktop.mouseError) {
      const recovery = desktop.mouseError.includes('ydotoold')
        ? 'Start it with: systemctl --user start ydotoold'
        : 'Check the desktop input backend and permissions.';
      setError(`Desktop control is unavailable: ${desktop.mouseError}. ${recovery}`);
    } else if (els.error.textContent.startsWith('Desktop control is unavailable:')) setError('');
  } catch (err) {
    setConnection('failed', 'Backend disconnected'); els.desktopStatus.textContent = 'Disconnected'; statusDot(els.desktopDot, 'bad');
    setError(`Backend connection problem: ${err.message}. Keep this app open with ./run.sh.`);
  }
}

async function loadVision() {
  if (landmarker) return landmarker;
  try {
    visionModule ||= await import(visionBundleUrl);
    const vision = await visionModule.FilesetResolver.forVisionTasks(wasmRoot);
    landmarker = await visionModule.HandLandmarker.createFromOptions(vision, {
      baseOptions: { modelAssetPath: modelUrl, delegate: 'GPU' },
      runningMode: 'VIDEO', numHands: 1,
      minHandDetectionConfidence: 0.58, minHandPresenceConfidence: 0.55, minTrackingConfidence: 0.55,
    });
    return landmarker;
  } catch (gpuError) {
    try {
      const vision = await visionModule.FilesetResolver.forVisionTasks(wasmRoot);
      landmarker = await visionModule.HandLandmarker.createFromOptions(vision, {
        baseOptions: { modelAssetPath: modelUrl, delegate: 'CPU' }, runningMode: 'VIDEO', numHands: 1,
        minHandDetectionConfidence: 0.58, minHandPresenceConfidence: 0.55, minTrackingConfidence: 0.55,
      });
      setNotice('GPU tracking was unavailable; using browser CPU processing.', 'warning');
      return landmarker;
    } catch (cpuError) {
      throw new Error(`Could not load MediaPipe. Check your internet connection / CDN access, then retry. ${cpuError.message || gpuError.message}`);
    }
  }
}

function classify(points) {
  const distance = (a, b) => Math.hypot(points[a].x - points[b].x, points[a].y - points[b].y);
  // Compare fingertip-to-wrist length with PIP-to-wrist length instead of
  // relying on image y direction. This works when the hand is rotated/tilted.
  const fingerExtended = (tip, pip) => distance(0, tip) > distance(0, pip) * 1.12;
  const indexUp = fingerExtended(8, 6);
  const middleUp = fingerExtended(12, 10);
  const ringUp = fingerExtended(16, 14);
  const pinkyUp = fingerExtended(20, 18);
  const thumbUp = distance(0, 4) > distance(0, 2) * 1.12 && distance(4, 5) > distance(2, 5) * 1.08;
  // Apply the requested pose priorities directly: pause, two-finger move,
  // one-finger right click, then closed-fist scroll. No pinch overrides these.
  if (thumbUp && indexUp && middleUp && !ringUp && !pinkyUp) return { name: 'Pause gesture', symbol: 'Ⅱ', action: 'pause', points };
  if (indexUp && middleUp && !ringUp && !pinkyUp) return { name: 'Move pointer', symbol: '☝☝', action: 'move', points };
  if (indexUp && !middleUp && !ringUp && !pinkyUp) return { name: 'Right click', symbol: 'R', action: 'right', points };
  if (!indexUp && !middleUp && !ringUp && !pinkyUp) return { name: 'Scroll', symbol: '↕', action: 'scroll', points };
  return { name: 'Hand ready', symbol: '✳', action: 'idle', points };
}

function drawLandmarks(points) {
  const w = els.canvas.width, h = els.canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!points) return;
  const edges = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];
  ctx.lineWidth = Math.max(2, w / 300); ctx.strokeStyle = 'rgba(138,216,177,.85)';
  for (const [a,b] of edges) { ctx.beginPath(); ctx.moveTo(points[a].x*w, points[a].y*h); ctx.lineTo(points[b].x*w, points[b].y*h); ctx.stroke(); }
  points.forEach((p, i) => { ctx.beginPath(); ctx.fillStyle = [4,8,12].includes(i) ? '#e6bd75' : '#abebcb'; ctx.arc(p.x*w,p.y*h,[4,8,12].includes(i)?4:2.5,0,Math.PI*2); ctx.fill(); });
}

function resetGestureState() { clickArmed = true; nonClickSince = null; pinchState = 'idle'; lastPoint = null; smoothed = null; pointerFilter = null; scrollReference = null; pausePoseSince = null; rightClickPoseSince = null; }
function smoothPointer(point, now, smoothingPercent) {
  const dt = pointerFilter ? Math.max(1 / 120, Math.min(0.12, (now - pointerFilter.time) / 1000)) : 1 / 30;
  const alpha = (cutoff) => {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
  };
  const minimumCutoff = Math.max(1.5, 8 - Number(smoothingPercent) * 0.05);
  const beta = 2.0;
  if (!pointerFilter) {
    pointerFilter = {raw: point, filtered: point, derivative: {x: 0, y: 0}, time: now};
    return point;
  }
  const next = {x: 0, y: 0};
  const derivative = {x: 0, y: 0};
  for (const axis of ['x', 'y']) {
    const rawVelocity = (point[axis] - pointerFilter.raw[axis]) / dt;
    const dAlpha = alpha(1.0);
    derivative[axis] = dAlpha * rawVelocity + (1 - dAlpha) * pointerFilter.derivative[axis];
    const cutoff = minimumCutoff + beta * Math.abs(derivative[axis]);
    const valueAlpha = alpha(cutoff);
    next[axis] = valueAlpha * point[axis] + (1 - valueAlpha) * pointerFilter.filtered[axis];
  }
  pointerFilter = {raw: point, filtered: next, derivative, time: now};
  return next;
}
function cursorCoordinates(nx, ny, width, height, sensitivity) {
  const xNorm = Math.max(0, Math.min(1, (1 - nx - .5) * sensitivity + .5));
  const yNorm = Math.max(0, Math.min(1, (ny - .5) * sensitivity + .5));
  return {x: Math.round(xNorm * (width - 1)), y: Math.round(yNorm * (height - 1))};
}
function stopActions(reason = 'Tracking paused') {
  active = false; paused = true; resetGestureState();
  els.handStatus.textContent = reason; statusDot(els.handDot, 'warn');
  const emergency = reason === 'Emergency stop' || reason === 'Emergency stop active';
  setGesture(emergency ? 'Emergency stop' : 'Paused', emergency ? 'Control is locked until you press Resume.' : reason, emergency ? '!' : 'Ⅱ');
  setPill(reason, 'paused');
  els.pause.disabled = !stream || stopped;
  els.pause.innerHTML = '<span class="button-icon">▶</span> Resume';
}
function pauseTracking() {
  if (!stream || stopped || paused) return;
  stopActions('Paused by you');
  els.pause.disabled = false; els.pause.innerHTML = '<span class="button-icon">▶</span> Resume';
  setNotice('Gesture control is paused. Resume explicitly to move the desktop pointer.', 'warning');
}
function resumeTracking() {
  if (!stream || stopped) return;
  paused = false; active = true; resetGestureState();
  els.pause.disabled = false; els.pause.innerHTML = '<span class="button-icon">Ⅱ</span> Pause';
  els.handStatus.textContent = 'Searching…'; statusDot(els.handDot, 'warn');
  setPill('Searching for hand', 'live'); setError('');
  setGesture('Looking for a hand', 'Show one hand clearly in the preview.', '…');
  if (rafId === null) rafId = requestAnimationFrame(trackFrame);
}
function stopCamera() {
  stopActions('Camera stopped'); stopped = true;
  if (rafId !== null) cancelAnimationFrame(rafId);
  rafId = null; stream?.getTracks().forEach(track => track.stop()); stream = null;
  els.video.srcObject = null; els.frame.classList.remove('active');
  if (document.pictureInPictureElement) void document.exitPictureInPicture().catch(() => {});
  ctx.clearRect(0,0,els.canvas.width,els.canvas.height);
  els.start.disabled = false; els.pause.disabled = true; els.stop.disabled = true; els.cameraSelect.disabled = true; els.float.disabled = true;
  els.cameraInfo.textContent = 'Camera not started'; setPill('Camera off');
  els.handStatus.textContent = 'Not active'; statusDot(els.handDot, '');
  els.pause.innerHTML = '<span class="button-icon">Ⅱ</span> Pause';
  setGesture('Camera stopped', 'No control commands are sent when the camera is stopped.', '—');
  setNotice('Camera stopped. The browser webcam stream has been released.', 'info');
}

async function sendMove(nx, ny) {
  if (!active || paused || stopped || !stream) return;
  const now = performance.now(); if (now - lastApiAt < 24) return;
  lastApiAt = now;
  const dead = Number($('deadzone').value) / 100;
  const dx = lastPoint ? nx - lastPoint.x : 0, dy = lastPoint ? ny - lastPoint.y : 0;
  if (lastPoint && Math.hypot(dx,dy) < dead) return;
  lastPoint = {x:nx,y:ny};
  if (!desktopScreen) {
    const status = await api('/api/screen');
    desktopScreen = status.screen || null;
  }
  if (!active || paused || stopped || !stream) return;
  if (!desktopScreen) throw new Error('Screen dimensions are unavailable from the desktop backend.');
  // Preview is mirrored; reverse the visual x coordinate before mapping to desktop space.
  const coords = cursorCoordinates(nx, ny, desktopScreen.width, desktopScreen.height, Number($('sensitivity').value));
  if (moveInFlight) {
    // Drop stale positions and retain only the newest sample.
    pendingMove = coords;
    return;
  }
  moveInFlight = true;
  try {
    let next = coords;
    while (next && active && !paused && !stopped && stream) {
      pendingMove = null;
      await api('/api/move', next);
      next = pendingMove;
    }
  } finally {
    moveInFlight = false;
  }
}

async function handleGesture(result) {
  if (!active || paused || stopped || !stream) return;
  const action = result.action, points = result.points;
  if (action !== 'scroll') scrollReference = null;
  if (action !== 'move') { pointerFilter = null; smoothed = null; lastPoint = null; }
  if (action === 'pause') {
    rightClickPoseSince = null;
    if (pausePoseSince === null) pausePoseSince = performance.now();
    if (performance.now() - pausePoseSince >= 700) {
      stopActions('Paused by gesture');
      setNotice('Gesture control paused. Release the three-finger pose, then press Resume to continue.', 'warning');
    }
    return;
  }
  pausePoseSince = null;
  if (action === 'right') {
    nonClickSince = null;
    if (rightClickPoseSince === null) rightClickPoseSince = performance.now();
    const now = performance.now();
    if (clickArmed && now - rightClickPoseSince >= 120 && now - lastClickAt > 550) {
      clickArmed = false; lastClickAt = now; pinchState = action;
      try { await api('/api/click', {button: action}); }
      catch (err) { reportMouseFailure(err.message); throw err; }
    }
  } else {
    rightClickPoseSince = null;
    // Require a stable release pose before another right-click. This suppresses
    // brief classifier flicker while the index finger is still held up.
    if (!clickArmed) {
      if (nonClickSince === null) nonClickSince = performance.now();
      if (performance.now() - nonClickSince >= 180) clickArmed = true;
    }
    pinchState = 'idle';
    if (action === 'move') {
      // With the new pose, midpoint of index/middle tips is the pointer target.
      const index = {x:(points[8].x + points[12].x) / 2, y:(points[8].y + points[12].y) / 2};
      smoothed = smoothPointer(index, performance.now(), $('smoothing').value);
      try { await sendMove(smoothed.x, smoothed.y); }
      catch (err) { reportMouseFailure(err.message); throw err; }
    }
    if (action === 'scroll') {
      const now = performance.now();
      // Fist-scroll tracks palm-center movement while all four fingers are curled.
      const scrollPoint = {x: points[9].x, y: points[9].y};
      // Establish a fresh baseline on entering fist mode; never compare against
      // stale pointer coordinates, which used to trigger a jump scroll.
      if (scrollReference && now-lastScrollAt > 180 && Math.abs(scrollPoint.y-scrollReference.y) > .012) {
        const direction = scrollPoint.y < scrollReference.y ? 1 : -1;
        lastScrollAt = now;
        try { await api('/api/scroll', {amount: direction * Number($('scrollSpeed').value)}); }
        catch (err) { reportMouseFailure(err.message); throw err; }
      }
      scrollReference = scrollPoint;
    } else if (action === 'move') {
      lastPoint = {x: smoothed.x, y: smoothed.y};
    } else {
      lastPoint = null;
    }
  }
}

function trackFrame() {
  rafId = null;
  if (!active || paused || stopped || !stream) return;
  if (els.video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && els.video.currentTime !== lastVideoTime) {
    lastVideoTime = els.video.currentTime;
    try {
      const result = landmarker.detectForVideo(els.video, performance.now());
      const points = result.landmarks?.[0];
      els.canvas.width = els.video.videoWidth; els.canvas.height = els.video.videoHeight;
      if (points) {
        drawLandmarks(points); els.handStatus.textContent = 'Hand detected'; statusDot(els.handDot, 'good');
        const gesture = classify(points);
        const instructions = gesture.action === 'move' ? 'Raise index + middle together. Move the midpoint between their tips.' :
          gesture.action === 'scroll' ? 'Close all four fingers into a fist. Move your fist up/down to scroll.' :
          gesture.action === 'right' ? 'Hold index only steady briefly for one right-click; lower it to re-arm.' :
          gesture.action === 'pause' ? 'Hold thumb + index + middle up for a moment to pause; Resume button restarts.' :
          'Two fingers = move · one index = right-click · fist = scroll · thumb+two = pause.';
        setGesture(gesture.name, instructions, gesture.symbol);
        setPill('Hand detected', 'live');
        void handleGesture(gesture).then(() => {
          if (active && !paused && !stopped && gesture.action !== 'idle' && gesture.action !== 'pause') {
            els.handStatus.textContent = gesture.action === 'move' ? 'Pointer command sent' : `${gesture.name} command sent`;
          }
        }).catch(() => {});
      } else {
        drawLandmarks(null); lastPoint = null; smoothed = null; pausePoseSince = null; els.handStatus.textContent = 'No hand detected'; statusDot(els.handDot, 'warn');
        setGesture('No hand detected', 'Move your hand into the frame. Control pauses until a hand returns.', '…'); setPill('Searching for hand', 'live');
      }
      fpsFrames++;
      const now = performance.now();
      if (now-fpsAt >= 1000) { els.fps.textContent = `${Math.round(fpsFrames*1000/(now-fpsAt))} FPS`; fpsAt=now; fpsFrames=0; }
    } catch (err) {
      setError(`Hand tracking failed: ${err.message}`); stopActions('Tracking error');
      return;
    }
  }
  if (active && !paused && !stopped) rafId = requestAnimationFrame(trackFrame);
}

async function refreshCameras() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  try {
    cameraDevices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
    els.cameraSelect.replaceChildren();
    cameraDevices.forEach((device, index) => { const option = document.createElement('option'); option.value = device.deviceId; option.textContent = device.label || `Camera ${index+1}`; els.cameraSelect.append(option); });
    els.cameraSelect.disabled = !stream || cameraDevices.length < 2;
  } catch { /* device selection is optional */ }
}

async function startCamera(deviceId) {
  setError(''); setNotice('');
  if (!navigator.mediaDevices?.getUserMedia) {
    setError('Camera unavailable: this browser does not support getUserMedia. Open AirMouse at http://127.0.0.1:5000 in a supported browser.'); return;
  }
  els.start.disabled = true;
  try {
    // Ask for camera access on the explicit button action first so a model CDN
    // or download failure cannot be confused with a permission/camera failure.
    stream = await navigator.mediaDevices.getUserMedia({audio:false, video:{...(deviceId ? {deviceId:{exact:deviceId}} : {}), width:{ideal:960}, height:{ideal:540}, frameRate:{ideal:30,max:30}}});
    let handLandmarker;
    try {
      handLandmarker = await loadVision();
    } catch (modelError) {
      stream.getTracks().forEach(track => track.stop()); stream = null;
      throw modelError;
    }
    els.video.srcObject = stream; await els.video.play();
    active = true; paused = false; stopped = false; lastVideoTime=-1; resetGestureState();
    els.frame.classList.add('active'); els.pause.disabled=false; els.stop.disabled=false;
    els.float.disabled = !(document.pictureInPictureEnabled && els.video.requestPictureInPicture);
    els.cameraInfo.textContent = `${els.video.videoWidth} × ${els.video.videoHeight} · Local processing`;
    setPill('Searching for hand','live'); setGesture('Looking for a hand','Show one hand clearly in the preview.','…');
    await refreshCameras(); els.cameraSelect.disabled = cameraDevices.length < 2;
    setNotice('Camera is active. Tracking runs locally in your browser; no frames are uploaded.','info');
    void handLandmarker;
    rafId=requestAnimationFrame(trackFrame);
  } catch (err) {
    stream?.getTracks().forEach(t=>t.stop()); stream=null; stopped=true; active=false; paused=true;
    els.start.disabled=false; els.pause.disabled=true; els.stop.disabled=true;
    if (err.name === 'NotAllowedError' || err.name === 'SecurityError') setError('Camera permission denied. Allow camera access for 127.0.0.1 in your browser site settings, then try again.');
    else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') setError('No available camera was found. Connect or enable a webcam and retry.');
    else if (err.message?.includes('MediaPipe')) setError(`Hand-tracking setup problem: ${err.message}`);
    else setError(`Camera startup failed: ${err.message || err.name}. Check that another app is not using the webcam.`);
    setPill('Camera unavailable'); setGesture('Camera unavailable','Resolve the message above and try again.','!');
  }
}

els.start.addEventListener('click',()=>startCamera());
els.stop.addEventListener('click',stopCamera);
els.pause.addEventListener('click',()=>paused?resumeTracking():pauseTracking());
els.float.addEventListener('click',async()=>{
  try {
    if (document.pictureInPictureElement) await document.exitPictureInPicture();
    else if (document.pictureInPictureEnabled && els.video.requestPictureInPicture) await els.video.requestPictureInPicture();
  } catch (err) {
    setError(`Could not float camera preview: ${err.message}`);
  }
});
els.video.addEventListener('enterpictureinpicture',()=>{els.float.textContent='Close floating preview';});
els.video.addEventListener('leavepictureinpicture',()=>{els.float.textContent='Float preview';});
els.emergency.addEventListener('click',()=>{ if (stream && !stopped) { stopActions('Emergency stop'); setError('Emergency stop engaged. Resume explicitly to re-enable gestures.'); } else stopCamera(); });
els.cameraSelect.addEventListener('change',async()=>{const id=els.cameraSelect.value; stopCamera(); await startCamera(id);});
document.addEventListener('keydown',(event)=>{if(event.key==='Escape'){event.preventDefault(); if(stream&&!stopped){stopActions('Emergency stop');setError('Emergency stop engaged. Resume explicitly to re-enable gestures.');}}});
window.addEventListener('beforeunload',()=>{active=false;stream?.getTracks().forEach(t=>t.stop());if(rafId!==null)cancelAnimationFrame(rafId);landmarker?.close();});
document.addEventListener('visibilitychange',()=>{
  if (document.hidden && stream && active) {
    setNotice('AirMouse is in a background tab. Browsers may throttle camera tracking here; keep this dashboard visible for responsive desktop control.', 'warning');
  } else if (!document.hidden && stream && active) {
    setNotice('Dashboard visible. Hand tracking and desktop control are active.', 'info');
  }
});

for (const [id, outputId, suffix] of [['sensitivity','sensitivityOutput','×'],['smoothing','smoothingOutput','%'],['scrollSpeed','scrollOutput',''],['deadzone','deadzoneOutput','%']]) {
  $(id).addEventListener('input',()=>$(outputId).value=`${$(id).value}${suffix}`);
}

void checkBackend();
setInterval(async()=>{
  if (els.connection.classList.contains('failed')) { void checkBackend(); return; }
  try {
    const {desktop} = await api('/api/health');
    if (desktop.mouseControl === 'available' && desktop.inputMethod === 'ydotool') {
      els.desktopStatus.textContent = `Ready · ydotool (${desktop.eventPacketsSent ?? 0} events)`;
      statusDot(els.desktopDot, 'good');
    }
  } catch { /* the normal connection poll reports backend errors */ }
}, 3000);
