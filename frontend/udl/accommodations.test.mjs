import assert from "node:assert/strict";
import test from "node:test";
import {
  applyAccommodationSignal,
  clearActiveAccommodations,
  getActiveAccommodations,
} from "./accommodations.js";

test("stores only current-session accommodation names", () => {
  clearActiveAccommodations();
  applyAccommodationSignal({
    activeAccommodations: ["reading", "attention", "diagnostic_label"],
  });

  assert.deepEqual(getActiveAccommodations(), ["reading", "attention"]);
});

test("clears active accommodation state at session boundary", () => {
  applyAccommodationSignal(["numerical"]);
  clearActiveAccommodations();

  assert.deepEqual(getActiveAccommodations(), []);
});
