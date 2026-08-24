const DB_NAME = "nevo_affective_session";
const DB_VERSION = 1;
const STORE_NAME = "session_signals";
const BUSY_STORE_NAME = "system_busy_markers";
const ADAPTATION_RATE_LIMIT_MS = 90_000;

export const AFFECTIVE_STATES = Object.freeze({
  NEUTRAL: "neutral",
  ANXIETY: "anxiety",
  BOREDOM: "boredom",
  FRUSTRATION: "frustration",
  CONFUSION: "confusion",
});

export const FORM_FACTORS = Object.freeze([
  "tablet_touch",
  "desktop_cursor",
  "mobile_touch",
]);

export const SIGNAL_TYPES = Object.freeze([
  "tap_latency",
  "tap_duration",
  "aborted_gesture",
  "inter_touch_idle",
  "scroll_pattern",
  "gesture_completion_rate",
  "typing_rhythm_variability",
  "deletion_rate",
  "error_rate",
  "rapid_repeated_taps",
  "rapid_repeated_clicks",
  "sudden_acceleration",
  "rapid_backspace",
  "rapid_backscroll",
  "question_reference_transition",
  "hesitation_idle",
  "noninteractive_tap",
  "hover_without_action",
  "off_content_scroll",
  "attempt_made",
  "reread",
  "step_error",
  "skip_or_exit",
  "resolved_confusion",
]);

export const RAW_TOUCH_SIGNAL_TYPES = Object.freeze([
  "tap_latency",
  "tap_duration",
  "aborted_gesture",
  "inter_touch_idle",
  "scroll_pattern",
  "gesture_completion_rate",
]);

export const TOUCH_SIGNAL_SURFACING_POLICY = Object.freeze({
  storage: "indexeddb_session_only",
  deleteAt: "session_end",
  backendTransport: false,
  opsFeed: false,
  downstreamApi: false,
  visibleLabels: false,
});

export const SYSTEM_BUSY_REASONS = Object.freeze([
  "route_transition",
  "content_loading",
  "asset_loading",
  "modal_opening",
  "feedback_animating",
  "scaffold_generating",
  "audio_buffering",
  "background_sync",
]);

let lastAdaptationAt = 0;

function hasIndexedDb() {
  return typeof indexedDB !== "undefined";
}

function openAffectiveDb() {
  if (!hasIndexedDb()) {
    return Promise.reject(new Error("IndexedDB is not available."));
  }

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, {
          keyPath: "id",
          autoIncrement: true,
        });
        store.createIndex("sessionId", "sessionId");
        store.createIndex("timestamp", "timestamp");
        store.createIndex("formFactor", "formFactor");
      }
      if (!db.objectStoreNames.contains(BUSY_STORE_NAME)) {
        const store = db.createObjectStore(BUSY_STORE_NAME, {
          keyPath: "id",
          autoIncrement: true,
        });
        store.createIndex("sessionId", "sessionId");
        store.createIndex("startedAt", "startedAt");
      }
    };
  });
}

function transactionDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

function putLocalRecord(storeName, record) {
  return openAffectiveDb().then((db) => {
    const tx = db.transaction(storeName, "readwrite");
    tx.objectStore(storeName).add(record);
    return transactionDone(tx).finally(() => db.close());
  });
}

function readAll(storeName) {
  return openAffectiveDb().then((db) => {
    const tx = db.transaction(storeName, "readonly");
    const request = tx.objectStore(storeName).getAll();
    return new Promise((resolve, reject) => {
      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve(request.result);
    }).finally(() => db.close());
  });
}

function normalizeTimestamp(value, fallback = Date.now()) {
  return Number.isFinite(value) ? value : fallback;
}

function normalizedAttentionDPrime(value) {
  if (!Number.isFinite(value)) {
    return 0.5;
  }
  return clamp(value / 3, 0, 1);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function sameFormFactor(event, formFactor) {
  return !event.formFactor || event.formFactor === formFactor;
}

function notDuringBusy(event, markers) {
  return !markers.some((marker) => {
    const startedAt = normalizeTimestamp(marker.startedAt, marker.timestamp);
    const endedAt = normalizeTimestamp(marker.endedAt, Date.now());
    return event.timestamp >= startedAt && event.timestamp <= endedAt;
  });
}

function recentEvents(events, now, durationMs) {
  const start = now - durationMs;
  return events.filter((event) => event.timestamp >= start && event.timestamp <= now);
}

function signalPresent(events, types, predicate = () => true) {
  const typeSet = new Set(Array.isArray(types) ? types : [types]);
  return events.some((event) => typeSet.has(event.type) && predicate(event));
}

function countEvents(events, types, predicate = () => true) {
  const typeSet = new Set(Array.isArray(types) ? types : [types]);
  return events.filter((event) => typeSet.has(event.type) && predicate(event)).length;
}

function valueAtLeast(minimum) {
  return (event) => Number(event.value ?? event.count ?? 0) >= minimum;
}

function sustainedWindow(events, durationMs, now) {
  if (events.length === 0) {
    return false;
  }
  const earliest = Math.min(...events.map((event) => event.timestamp));
  return earliest <= now - durationMs;
}

function motorScale(baseline = {}) {
  const motorBaselineMs = Number(baseline.motor_baseline_ms ?? baseline.motorBaselineMs);
  if (!Number.isFinite(motorBaselineMs) || motorBaselineMs <= 0) {
    return 1;
  }
  return clamp(motorBaselineMs / 500, 0.75, 1.6);
}

function anxietySignals(events, baseline) {
  const scale = motorScale(baseline);
  return [
    signalPresent(events, ["typing_rhythm_variability", "tap_latency"], valueAtLeast(0.7 * scale)),
    signalPresent(events, ["deletion_rate", "aborted_gesture"], valueAtLeast(3)),
    signalPresent(events, "scroll_pattern", (event) => event.pattern === "rapid" || Number(event.value ?? 0) >= 0.75),
    signalPresent(events, "error_rate", valueAtLeast(0.35)),
  ].filter(Boolean).length;
}

function boredomSignals(events) {
  return [
    signalPresent(events, "scroll_pattern", (event) => event.pattern === "slow" || Number(event.value ?? 0) <= 0.2),
    signalPresent(events, ["inter_touch_idle", "hesitation_idle"], valueAtLeast(10_000)),
    signalPresent(events, "off_content_scroll"),
  ].filter(Boolean).length;
}

function frustrationSignals(events) {
  return [
    signalPresent(events, ["rapid_repeated_taps", "rapid_repeated_clicks"], valueAtLeast(3)),
    signalPresent(events, "sudden_acceleration", valueAtLeast(0.7)),
    signalPresent(events, ["rapid_backspace", "rapid_backscroll"], valueAtLeast(2)),
  ].filter(Boolean).length;
}

function confusionSignals(events) {
  return [
    signalPresent(events, "question_reference_transition"),
    signalPresent(events, ["hesitation_idle", "inter_touch_idle"], valueAtLeast(5_000)),
    signalPresent(events, ["hover_without_action", "noninteractive_tap"]),
  ].filter(Boolean).length;
}

export function calibratedConfusionGraceMs({ schoolBand = "jss", attentionDPrime = null } = {}) {
  const baseSecondsByBand = {
    primary: 45,
    jss: 60,
    ss: 90,
  };
  const baseSeconds = baseSecondsByBand[String(schoolBand).toLowerCase()] ?? 60;
  const attentionScale = 0.5 + 0.5 * normalizedAttentionDPrime(attentionDPrime);
  return Math.round(baseSeconds * 1000 * attentionScale);
}

export function evaluateProductiveConfusion(
  events,
  {
    now = Date.now(),
    confusionStartedAt = now,
    schoolBand = "jss",
    baseline = {},
  } = {},
) {
  const graceMs = calibratedConfusionGraceMs({
    schoolBand,
    attentionDPrime: baseline.attention_d_prime ?? baseline.attentionDPrime,
  });
  const elapsedMs = now - confusionStartedAt;
  const withinGrace = elapsedMs < graceMs;
  const recent = recentEvents(events, now, Math.max(elapsedMs, 1));
  const productive = signalPresent(recent, ["attempt_made", "reread", "question_reference_transition"]);
  const stalled = signalPresent(recent, ["inter_touch_idle", "hesitation_idle"], valueAtLeast(15_000));
  const repeatedErrors = countEvents(recent, "step_error") >= 3;
  const leaving = signalPresent(recent, "skip_or_exit");
  const resolved = signalPresent(recent, "resolved_confusion");

  if (resolved || (withinGrace && productive && !stalled && !repeatedErrors && !leaving)) {
    return { graceMs, elapsedMs, interventionReady: false, trajectory: "productive" };
  }
  if (withinGrace) {
    return { graceMs, elapsedMs, interventionReady: false, trajectory: "observing" };
  }
  if (stalled || repeatedErrors || leaving) {
    return { graceMs, elapsedMs, interventionReady: true, trajectory: "unproductive" };
  }
  return { graceMs, elapsedMs, interventionReady: false, trajectory: "productive" };
}

export function evaluateAffectiveWindow(
  events,
  {
    now = Date.now(),
    formFactor = "tablet_touch",
    baseline = {},
    busyMarkers = [],
    schoolBand = "jss",
    confusionStartedAt = null,
  } = {},
) {
  const usableEvents = events
    .map((event) => ({ ...event, timestamp: normalizeTimestamp(event.timestamp) }))
    .filter((event) => sameFormFactor(event, formFactor))
    .filter((event) => notDuringBusy(event, busyMarkers))
    .sort((left, right) => left.timestamp - right.timestamp);

  const anxietyWindow = recentEvents(usableEvents, now, 30_000);
  if (sustainedWindow(anxietyWindow, 30_000, now) && anxietySignals(anxietyWindow, baseline) >= 3) {
    return { state: AFFECTIVE_STATES.ANXIETY, interventionReady: true, signals: anxietySignals(anxietyWindow, baseline) };
  }

  const frustrationWindow = recentEvents(usableEvents, now, 20_000);
  if (sustainedWindow(frustrationWindow, 20_000, now) && frustrationSignals(frustrationWindow) >= 2) {
    return { state: AFFECTIVE_STATES.FRUSTRATION, interventionReady: true, signals: frustrationSignals(frustrationWindow) };
  }

  const confusionWindow = recentEvents(usableEvents, now, 30_000);
  if (sustainedWindow(confusionWindow, 30_000, now) && confusionSignals(confusionWindow) >= 2) {
    const productiveConfusion = evaluateProductiveConfusion(confusionWindow, {
      now,
      confusionStartedAt: confusionStartedAt ?? Math.min(...confusionWindow.map((event) => event.timestamp)),
      schoolBand,
      baseline,
    });
    return {
      state: AFFECTIVE_STATES.CONFUSION,
      interventionReady: productiveConfusion.interventionReady,
      signals: confusionSignals(confusionWindow),
      productiveConfusion,
    };
  }

  const boredomWindow = recentEvents(usableEvents, now, 60_000);
  if (sustainedWindow(boredomWindow, 60_000, now) && boredomSignals(boredomWindow) >= 2) {
    return { state: AFFECTIVE_STATES.BOREDOM, interventionReady: true, signals: boredomSignals(boredomWindow) };
  }

  return { state: AFFECTIVE_STATES.NEUTRAL, interventionReady: false, signals: 0 };
}

export function inferAffectiveStateFromWindow(events, options = {}) {
  return evaluateAffectiveWindow(events, options).state;
}

export function shouldTriggerAffectiveAdaptation(state, { now = Date.now() } = {}) {
  if (!state || state === AFFECTIVE_STATES.NEUTRAL) {
    return false;
  }
  if (now - lastAdaptationAt < ADAPTATION_RATE_LIMIT_MS) {
    return false;
  }
  lastAdaptationAt = now;
  return true;
}

export function resetAffectiveAdaptationRateLimit() {
  lastAdaptationAt = 0;
}

export async function recordAffectiveSignal(signal) {
  if (!SIGNAL_TYPES.includes(signal.type)) {
    throw new Error(`Unsupported affective signal type: ${signal.type}`);
  }
  const record = {
    ...signal,
    timestamp: normalizeTimestamp(signal.timestamp),
    formFactor: signal.formFactor ?? "tablet_touch",
  };
  await putLocalRecord(STORE_NAME, record);
}

export async function recordSystemBusyMarker(marker) {
  if (!SYSTEM_BUSY_REASONS.includes(marker.reason)) {
    throw new Error(`Unsupported system busy reason: ${marker.reason}`);
  }
  const record = {
    ...marker,
    startedAt: normalizeTimestamp(marker.startedAt, marker.timestamp),
    endedAt: marker.endedAt == null ? null : normalizeTimestamp(marker.endedAt),
    formFactor: marker.formFactor ?? "tablet_touch",
  };
  await putLocalRecord(BUSY_STORE_NAME, record);
}

export async function getCurrentAffectiveState(options = {}) {
  const events = await readAll(STORE_NAME);
  const busyMarkers = await readAll(BUSY_STORE_NAME);
  return inferAffectiveStateFromWindow(events, { ...options, busyMarkers });
}

export async function cleanupAffectiveSession() {
  if (!hasIndexedDb()) {
    return;
  }
  const db = await openAffectiveDb();
  db.close();
  await new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DB_NAME);
    request.onerror = () => reject(request.error);
    request.onsuccess = resolve;
    request.onblocked = resolve;
  });
  resetAffectiveAdaptationRateLimit();
}

export function attachAffectiveCaptureListeners(root = document, options = {}) {
  const sessionId = options.sessionId;
  const formFactor = options.formFactor ?? "tablet_touch";
  let lastPointerDownAt = null;
  let lastTouchAt = null;
  let lastScrollAt = null;
  let lastScrollY = typeof window === "undefined" ? 0 : window.scrollY;
  let keyDownAt = null;

  const write = (type, value, extra = {}) =>
    recordAffectiveSignal({ type, value, sessionId, formFactor, ...extra }).catch(() => {});

  const onPointerDown = () => {
    const now = Date.now();
    if (lastTouchAt != null) {
      write("inter_touch_idle", now - lastTouchAt);
    }
    lastPointerDownAt = now;
    lastTouchAt = now;
  };

  const onPointerUp = () => {
    if (lastPointerDownAt != null) {
      write("tap_duration", Date.now() - lastPointerDownAt);
    }
    lastPointerDownAt = null;
  };

  const onPointerCancel = () => write("aborted_gesture", 1);

  const onClick = () => write(formFactor === "desktop_cursor" ? "rapid_repeated_clicks" : "rapid_repeated_taps", 1);

  const onScroll = () => {
    const now = Date.now();
    const y = window.scrollY;
    const deltaY = Math.abs(y - lastScrollY);
    const deltaMs = Math.max(now - (lastScrollAt ?? now), 1);
    const speed = deltaY / deltaMs;
    write("scroll_pattern", speed, { pattern: speed > 1.2 ? "rapid" : speed < 0.1 ? "slow" : "steady" });
    lastScrollY = y;
    lastScrollAt = now;
  };

  const onKeyDown = (event) => {
    keyDownAt = Date.now();
    if (event.key === "Backspace" || event.key === "Delete") {
      write("deletion_rate", 1);
      write("rapid_backspace", 1);
    }
  };

  const onKeyUp = () => {
    if (keyDownAt != null) {
      write("typing_rhythm_variability", Date.now() - keyDownAt);
    }
    keyDownAt = null;
  };

  root.addEventListener("pointerdown", onPointerDown, { passive: true });
  root.addEventListener("pointerup", onPointerUp, { passive: true });
  root.addEventListener("pointercancel", onPointerCancel, { passive: true });
  root.addEventListener("click", onClick, { passive: true });
  root.addEventListener("keydown", onKeyDown, { passive: true });
  root.addEventListener("keyup", onKeyUp, { passive: true });
  window.addEventListener("scroll", onScroll, { passive: true });

  return () => {
    root.removeEventListener("pointerdown", onPointerDown);
    root.removeEventListener("pointerup", onPointerUp);
    root.removeEventListener("pointercancel", onPointerCancel);
    root.removeEventListener("click", onClick);
    root.removeEventListener("keydown", onKeyDown);
    root.removeEventListener("keyup", onKeyUp);
    window.removeEventListener("scroll", onScroll);
  };
}
