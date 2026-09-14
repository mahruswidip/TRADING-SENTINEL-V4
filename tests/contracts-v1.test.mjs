import test from "node:test";
import assert from "node:assert/strict";
import {
  CONTRACT_V1,
  CONTRACT_VERSION_V1,
  MANUAL_APPROVAL_STAGES_V1,
  PROMOTION_STAGES_V1,
  PROMOTION_TRANSITIONS_V1,
  isPromotionTransitionV1,
} from "../src/domain/contracts-v1.ts";

test("D5 freezes a unique, versioned contract vocabulary", () => {
  assert.equal(CONTRACT_VERSION_V1, "1.0.0");
  for (const values of Object.values(CONTRACT_V1.enums)) {
    assert.equal(new Set(values).size, values.length);
  }
});

test("D5 promotion workflow allows only the next stage", () => {
  for (let index = 0; index < PROMOTION_STAGES_V1.length - 1; index += 1) {
    const from = PROMOTION_STAGES_V1[index];
    const to = PROMOTION_STAGES_V1[index + 1];
    assert.equal(PROMOTION_TRANSITIONS_V1[from], to);
    assert.equal(isPromotionTransitionV1(from, to), true);
    if (index + 2 < PROMOTION_STAGES_V1.length) assert.equal(isPromotionTransitionV1(from, PROMOTION_STAGES_V1[index + 2]), false);
  }
  assert.equal(PROMOTION_TRANSITIONS_V1.REAL, null);
  assert.deepEqual(MANUAL_APPROVAL_STAGES_V1, ["SHADOW", "CANARY_REAL", "REAL"]);
  assert.equal(CONTRACT_V1.promotion.automatic_real_promotion_forbidden, true);
});

test("D5 publishes the frozen contract manifest without enabling execution", async () => {
  const { GET } = await import("../src/app/api/contracts/v1/route.ts");
  const response = GET();
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "public, max-age=86400, immutable");
  assert.deepEqual(await response.json(), CONTRACT_V1);
});

