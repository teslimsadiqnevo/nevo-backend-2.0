import assert from "node:assert/strict";
import test from "node:test";
import {
  AFFECTIVE_STATES,
  FORM_FACTORS,
  RAW_TOUCH_SIGNAL_TYPES,
  SIGNAL_TYPES,
  SYSTEM_BUSY_REASONS,
  TOUCH_SIGNAL_SURFACING_POLICY,
  calibratedConfusionGraceMs,
  evaluateAffectiveWindow,
  evaluateProductiveConfusion,
  inferAffectiveStateFromWindow,
  resetAffectiveAdaptationRateLimit,
  shouldTriggerAffectiveAdaptation,
} from "./affective_inference.js";

const now = 1_000_000;

function event(type, ageMs, value = 1, extra = {}) {
  return {
    type,
    timestamp: now - ageMs,
    value,
    formFactor: "tablet_touch",
    ...extra,
  };
}

test("exports the contract states and tablet-first signals", () => {
  assert.deepEqual(Object.values(AFFECTIVE_STATES), [
    "neutral",
    "anxiety",
    "boredom",
    "frustration",
    "confusion",
  ]);
  assert.ok(FORM_FACTORS.includes("tablet_touch"));
  assert.ok(FORM_FACTORS.includes("desktop_cursor"));
  assert.ok(FORM_FACTORS.includes("mobile_touch"));
  assert.ok(SIGNAL_TYPES.includes("tap_duration"));
  assert.ok(SIGNAL_TYPES.includes("inter_touch_idle"));
  assert.ok(RAW_TOUCH_SIGNAL_TYPES.includes("tap_latency"));
  assert.ok(RAW_TOUCH_SIGNAL_TYPES.includes("gesture_completion_rate"));
  assert.equal(TOUCH_SIGNAL_SURFACING_POLICY.storage, "indexeddb_session_only");
  assert.equal(TOUCH_SIGNAL_SURFACING_POLICY.backendTransport, false);
  assert.equal(TOUCH_SIGNAL_SURFACING_POLICY.opsFeed, false);
  assert.equal(TOUCH_SIGNAL_SURFACING_POLICY.downstreamApi, false);
  assert.equal(TOUCH_SIGNAL_SURFACING_POLICY.visibleLabels, false);
  assert.ok(!SIGNAL_TYPES.includes("cursor_dwell_time"));
  assert.equal(SYSTEM_BUSY_REASONS.length, 8);
});

test("detects anxiety only when at least three signals sustain for thirty seconds", () => {
  const state = inferAffectiveStateFromWindow(
    [
      event("tap_latency", 30_000, 0.9),
      event("deletion_rate", 20_000, 4),
      event("scroll_pattern", 10_000, 0.9, { pattern: "rapid" }),
      event("error_rate", 2_000, 0.4),
    ],
    { now, formFactor: "tablet_touch" },
  );

  assert.equal(state, "anxiety");
});

test("keeps slow accurate work neutral when it does not match affective patterns", () => {
  const state = inferAffectiveStateFromWindow(
    [
      event("tap_duration", 50_000, 1_900),
      event("inter_touch_idle", 20_000, 8_000),
      event("attempt_made", 3_000, 1),
    ],
    {
      now,
      formFactor: "tablet_touch",
      baseline: { motor_baseline_ms: 1_200, attention_d_prime: 2.8 },
    },
  );

  assert.equal(state, "neutral");
});

test("does not compare affective baselines across form factors", () => {
  const state = inferAffectiveStateFromWindow(
    [
      { ...event("tap_latency", 30_500, 0.9), formFactor: "desktop_cursor" },
      { ...event("deletion_rate", 20_000, 4), formFactor: "desktop_cursor" },
      { ...event("scroll_pattern", 10_000, 0.9, { pattern: "rapid" }), formFactor: "desktop_cursor" },
    ],
    { now, formFactor: "tablet_touch" },
  );

  assert.equal(state, "neutral");
});

test("excludes system busy intervals from idle-based boredom", () => {
  const state = inferAffectiveStateFromWindow(
    [
      event("inter_touch_idle", 50_000, 14_000),
      event("scroll_pattern", 45_000, 0.05, { pattern: "slow" }),
      event("off_content_scroll", 10_000, 1),
    ],
    {
      now,
      formFactor: "tablet_touch",
      busyMarkers: [{ startedAt: now - 55_000, endedAt: now - 40_000 }],
    },
  );

  assert.equal(state, "neutral");
});

test("detects frustration from repeated taps and backtracking", () => {
  const result = evaluateAffectiveWindow(
    [
      event("rapid_repeated_taps", 20_000, 4),
      event("sudden_acceleration", 10_000, 0.8),
      event("rapid_backscroll", 2_000, 2),
    ],
    { now, formFactor: "tablet_touch" },
  );

  assert.equal(result.state, "frustration");
  assert.equal(result.interventionReady, true);
});

test("confusion waits through productive grace before intervention", () => {
  const result = evaluateAffectiveWindow(
    [
      event("question_reference_transition", 30_000),
      event("hesitation_idle", 20_000, 6_000),
      event("reread", 1_000),
    ],
    {
      now,
      formFactor: "tablet_touch",
      schoolBand: "jss",
      baseline: { attention_d_prime: 3 },
      confusionStartedAt: now - 30_000,
    },
  );

  assert.equal(result.state, "confusion");
  assert.equal(result.interventionReady, false);
  assert.equal(result.productiveConfusion.trajectory, "productive");
});

test("confusion intervention becomes ready after grace with stalled or repeated errors", () => {
  const decision = evaluateProductiveConfusion(
    [
      event("question_reference_transition", 90_000),
      event("hesitation_idle", 2_000, 16_000),
      event("step_error", 1_800),
      event("step_error", 1_000),
      event("step_error", 500),
    ],
    {
      now,
      schoolBand: "primary",
      baseline: { attention_d_prime: 0 },
      confusionStartedAt: now - 90_000,
    },
  );

  assert.equal(decision.interventionReady, true);
  assert.equal(decision.trajectory, "unproductive");
});

test("school band and attention d prime calibrate productive confusion grace", () => {
  assert.equal(calibratedConfusionGraceMs({ schoolBand: "primary", attentionDPrime: 0 }), 22_500);
  assert.equal(calibratedConfusionGraceMs({ schoolBand: "jss", attentionDPrime: 3 }), 60_000);
  assert.equal(calibratedConfusionGraceMs({ schoolBand: "ss", attentionDPrime: 3 }), 90_000);
});

test("adaptation triggers are rate limited for ninety seconds", () => {
  resetAffectiveAdaptationRateLimit();

  assert.equal(shouldTriggerAffectiveAdaptation("anxiety", { now }), true);
  assert.equal(shouldTriggerAffectiveAdaptation("frustration", { now: now + 89_999 }), false);
  assert.equal(shouldTriggerAffectiveAdaptation("frustration", { now: now + 90_000 }), true);
  assert.equal(shouldTriggerAffectiveAdaptation("neutral", { now: now + 180_000 }), false);
});
