import assert from "node:assert/strict";
import test from "node:test";
import * as verbs from "../scripts/observe-unit-inventory-verb.mjs";

test("the observation verb declares that a call needs an admitted machine:observe control command", () => {
  const verb = verbs["observe-unit-inventory"];
  assert.deepEqual(verb.admission, { effect: "machine:observe" });
  assert.deepEqual(verb.effects, ["process:execute"]);
});
