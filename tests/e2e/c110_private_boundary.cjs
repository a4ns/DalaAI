'use strict';
// Shared by the real login and the mandatory dummy-failure preflight.
const PRIVATE_ACTION_TIMEOUT_MS = 5000;
async function privateLoginBoundary(role, operation) {
  try { return await operation(); }
  catch { throw new Error(`C110 BLOCKED: synthetic ${role} login failed; credential-bearing details suppressed`); }
}
module.exports = { PRIVATE_ACTION_TIMEOUT_MS, privateLoginBoundary };
