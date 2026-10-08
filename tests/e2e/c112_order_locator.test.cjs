'use strict';
// Source/mock regression only: no browser, private input, network or database.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, 'c112_analytics.spec.cjs'), 'utf8');
const stageStart = "await stage(c.REQUIRED_STEPS[4], async () => {";
const reportStart = 'const pathname = `/api/v1/reports/orders/${selected.order.id}`;';
const start = source.indexOf(stageStart), end = source.indexOf(reportStart, start);
assert.ok(start >= 0 && end > start, 'the real order-selection stage must exist');
const selectionSource = source.slice(start + stageStart.length, end);
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const selectObservedOrder = new AsyncFunction('master', 'selected', 'expect', selectionSource);

async function exercise({ count = 1, returned, value } = {}) {
  // Each execution supplies an independent observed ID; the real stage cannot
  // succeed by choosing a guessed fixture ID, index, option text or first match.
  const observedId = randomUUID(), calls = [];
  const orderSelect = {
    async selectOption(options) {
      calls.push('select');
      assert.deepEqual(options, { value: observedId });
      return returned === undefined ? [observedId] : returned;
    },
  };
  const scope = {
    getByRole(role, options) {
      assert.equal(role, 'combobox');
      assert.deepEqual(options, { name: 'Наряд для отчёта', exact: true });
      return orderSelect;
    },
  };
  const master = { page: {
    getByRole(role, options) {
      assert.equal(role, 'region');
      assert.deepEqual(options, { name: 'Аналитика и отчёты', exact: true });
      return scope;
    },
  } };
  const expect = actual => ({
    async toHaveCount(expected) {
      calls.push('count');
      assert.equal(actual, orderSelect);
      assert.equal(expected, 1);
      assert.equal(count, expected);
    },
    toEqual(expected) {
      calls.push('returned');
      assert.deepEqual(expected, [observedId]);
      assert.deepEqual(actual, expected);
    },
    async toHaveValue(expected) {
      calls.push('value');
      assert.equal(actual, orderSelect);
      assert.equal(expected, observedId);
      assert.equal(value === undefined ? observedId : value, expected);
    },
  });
  await selectObservedOrder(master, { order: { id: observedId } }, expect);
  assert.deepEqual(calls, ['count', 'select', 'returned', 'value']);
}

test('real order stage selects the exact scoped semantic combobox and verifies both ID results', async () => {
  await exercise();
  await exercise();
  assert.doesNotMatch(selectionSource, /getByLabel|\.first\(|\.nth\(|\.locator\(|timeout\s*:/);
  assert.match(source, /selected = facts\.orders\.find\(f => f\.attempts\.some\(a => a\.submission\.payload\.after_photo_ids\.length > 0\)\);/);
  assert.match(source, /c\.stable\(result\.body\.order\) === c\.stable\(selected\)/);
});
for (const count of [0, 2]) test(`order selection rejects ${count} matching comboboxes`, async () => {
  await assert.rejects(exercise({ count }));
});
test('order selection rejects an empty selected-ID result', async () => {
  await assert.rejects(exercise({ returned: [] }));
});
test('order selection rejects a different returned ID', async () => {
  await assert.rejects(exercise({ returned: [randomUUID()] }));
});
test('order selection rejects a different actual field value', async () => {
  await assert.rejects(exercise({ value: randomUUID() }));
});
