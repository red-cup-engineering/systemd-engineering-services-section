// Pure derivation: two ObserveUnitResourceAccounting rows for the same
// host+unit in -> zero or more resource-consumed receipts out. No I/O here;
// this die stays host-agnostic and writes nowhere (see house data-custody
// law). Receipt shape mirrors the inference-purchased receipt's price
// object exactly (denomination {kind, asset, unit}, amount {numerator,
// denominator} as decimal-string exact fractions, never floats) so
// derive-inference-pnl.mjs's accumulate() can ingest a receipt's `record`
// unchanged: it only reads price.denomination, price.amount, provider, actor.

function requireSameUnit(before, after) {
  if (before.host !== after.host || before.unit !== after.unit) {
    throw new Error(
      `derive-unit-resource-receipts: host/unit mismatch (${before.host}/${before.unit} vs ${after.host}/${after.unit})`,
    );
  }
}

// Cumulative counters (CPUUsageNSec, IPIngressBytes, IPEgressBytes) reset to
// zero when a unit restarts. Differencing across a restart would undercount
// or throw on a spurious "negative delta", so a delta receipt is only
// derived when both observations agree on ActiveEnterTimestamp -- the same
// unit incarnation throughout the interval.
function sameIncarnation(before, after) {
  const b = before.properties.ActiveEnterTimestamp;
  const a = after.properties.ActiveEnterTimestamp;
  return b.known && a.known && b.value === a.value;
}

function observationReference(observation) {
  return Object.freeze({ host: observation.host, unit: observation.unit, observedAt: observation.observedAt });
}

function makeRecord({ host, unit, before, after, asset, denominatorUnit, numerator, denominator }) {
  return Object.freeze({
    type: "bare-cedar-fog.resource-metering/unit-resource-consumed",
    version: 1,
    host,
    unit,
    provider: host,
    actor: unit,
    intervalStart: before.observedAt,
    intervalEnd: after.observedAt,
    derivedFrom: Object.freeze({ before: observationReference(before), after: observationReference(after) }),
    price: Object.freeze({
      denomination: Object.freeze({ kind: "resource", asset, unit: denominatorUnit }),
      amount: Object.freeze({ numerator: numerator.toString(), denominator: denominator.toString() }),
    }),
  });
}

// A monotonic counter within one incarnation: the receipt amount is the
// exact-fraction increment (numerator over denominator) consumed in the
// interval. Skipped (returns null) when either side is unknown, the
// incarnation changed, or the counter appears to have gone backwards within
// one incarnation (a contract violation this die refuses to paper over).
function counterDeltaRecord({ host, unit, before, after, propertyName, asset, denominatorUnit, denominator }) {
  if (!sameIncarnation(before, after)) return null;
  const beforeProperty = before.properties[propertyName];
  const afterProperty = after.properties[propertyName];
  if (beforeProperty?.known !== true || afterProperty?.known !== true) return null;
  if (!/^(?:0|[1-9][0-9]*)$/u.test(beforeProperty.value) ||
      !/^(?:0|[1-9][0-9]*)$/u.test(afterProperty.value)) {
    throw new TypeError(`derive-unit-resource-receipts: ${propertyName} requires exact unsigned decimal cumulative counters`);
  }
  const beforeValue = BigInt(beforeProperty.value);
  const afterValue = BigInt(afterProperty.value);
  if (afterValue < beforeValue) {
    throw new Error(
      `derive-unit-resource-receipts: ${propertyName} went backwards for ${host}/${unit} within one incarnation (${beforeProperty.value} -> ${afterProperty.value})`,
    );
  }
  return makeRecord({ host, unit, before, after, asset, denominatorUnit, numerator: afterValue - beforeValue, denominator });
}

// MemoryPeak is a high-water mark, not a flow: differencing two peaks is not
// "memory consumed in the interval". The receipt instead states the peak
// known as of the later observation -- a snapshot, honestly labeled by its
// intervalEnd rather than implying a rate.
function memoryPeakRecord({ host, unit, before, after }) {
  const afterProperty = after.properties.MemoryPeak;
  if (!afterProperty.known) return null;
  return makeRecord({
    host,
    unit,
    before,
    after,
    asset: "memory-peak-bytes",
    denominatorUnit: "byte",
    numerator: BigInt(afterProperty.value),
    denominator: 1n,
  });
}

/**
 * Derives zero-to-six resource-consumed receipts (cpu-seconds,
 * memory-peak-bytes, network-ingress-bytes, network-egress-bytes,
 * disk-read-bytes, disk-write-bytes) from two
 * ObserveUnitResourceAccounting rows for the same host+unit.
 * @param {object} before - an ObserveUnitResourceAccounting row (observe-unit-resource-accounting.mjs's observeUnitResourceAccounting return shape), the earlier observation.
 * @param {object} after - an ObserveUnitResourceAccounting row, the later observation.
 * @returns {object[]} receipts shaped {type, version, host, unit, provider, actor, intervalStart, intervalEnd, derivedFrom, price: {denomination: {kind, asset, unit}, amount: {numerator, denominator}}}.
 * @throws {Error} when host/unit disagree between before and after, or a cumulative counter runs backwards within one incarnation.
 */
export function deriveUnitResourceRecords(before, after) {
  requireSameUnit(before, after);
  const { host, unit } = before;
  const records = [];
  const cpu = counterDeltaRecord({
    host, unit, before, after,
    propertyName: "CPUUsageNSec", asset: "cpu-seconds", denominatorUnit: "second", denominator: 1_000_000_000n,
  });
  if (cpu) records.push(cpu);
  const memoryPeak = memoryPeakRecord({ host, unit, before, after });
  if (memoryPeak) records.push(memoryPeak);
  // The Linux/systemd property vocabulary belongs here; all four measures
  // use one exact cumulative-byte delta law rather than four bespoke folds.
  const byteCounters = [
    ["IPIngressBytes", "network-ingress-bytes"],
    ["IPEgressBytes", "network-egress-bytes"],
    ["IOReadBytes", "disk-read-bytes"],
    ["IOWriteBytes", "disk-write-bytes"],
  ];
  for (const [propertyName, asset] of byteCounters) {
    const record = counterDeltaRecord({ host, unit, before, after,
      propertyName, asset, denominatorUnit: "byte", denominator: 1n });
    if (record) records.push(record);
  }
  return records;
}

/**
 * Pairs two observation sets by host+unit and derives receipts for every
 * matched pair. Unmatched observations (a unit present only before or only
 * after) contribute no receipt.
 * @param {object[]} observationsBefore - ObserveUnitResourceAccounting rows, the earlier observation set.
 * @param {object[]} observationsAfter - ObserveUnitResourceAccounting rows, the later observation set.
 * @returns {object[]} receipts, per deriveUnitResourceReceipts, concatenated across every matched pair.
 */
// A service is sampled at most once per observation set. The observer is
// allowed to preserve a caller's duplicate requested unit names; the
// receiving resource fold must not bill the same underlying counter twice.
function uniqueUnitObservations(observations) {
  const keyed = new Map();
  for (const row of observations) {
    const key = JSON.stringify([row.host, row.unit]);
    const prior = keyed.get(key);
    if (prior !== undefined && JSON.stringify(prior) !== JSON.stringify(row)) {
      throw new Error(`derive-unit-resource-receipts: contradictory observations for ${row.host}/${row.unit} in one source set`);
    }
    keyed.set(key, row);
  }
  return keyed;
}

export function deriveSetOfUnitResourceRecords(observationsBefore, observationsAfter) {
  const beforeByKey = uniqueUnitObservations(observationsBefore);
  const afterByKey = uniqueUnitObservations(observationsAfter);
  const records = [];
  for (const [key, before] of beforeByKey) {
    const after = afterByKey.get(key);
    if (after === undefined) continue;
    records.push(...deriveUnitResourceRecords(before, after));
  }
  return records;
}
