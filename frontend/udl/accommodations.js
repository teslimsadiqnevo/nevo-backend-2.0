const ACTIVE_ACCOMMODATIONS = new Set();
const SUPPORTED_ACCOMMODATIONS = Object.freeze(["reading", "attention", "numerical"]);

export function applyAccommodationSignal(payload) {
  ACTIVE_ACCOMMODATIONS.clear();
  const values = Array.isArray(payload)
    ? payload
    : payload?.activeAccommodations ?? [];
  for (const value of values) {
    if (SUPPORTED_ACCOMMODATIONS.includes(value)) {
      ACTIVE_ACCOMMODATIONS.add(value);
    }
  }
}

export function getActiveAccommodations() {
  return Array.from(ACTIVE_ACCOMMODATIONS);
}

export function clearActiveAccommodations() {
  ACTIVE_ACCOMMODATIONS.clear();
}

export { SUPPORTED_ACCOMMODATIONS };

