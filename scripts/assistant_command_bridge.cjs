'use strict';

const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const crypto = require('node:crypto');
const { isDeepStrictEqual } = require('node:util');

try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const filename = path.resolve(process.argv[2]);
  const originalLoad = Module._load;
  const allowed = new Set([filename, 'node:crypto', 'node:util']);
  Module._load = function (request, ...args) {
    if (!allowed.has(request)) {
      throw new Error('Forbidden dependency in isolated verification');
    }
    return originalLoad.call(this, request, ...args);
  };
  const { createAssistantCommandVerifier } = require(filename);
  const verify = createAssistantCommandVerifier({
    publicKeys: input.public_keys,
    clock: () => input.now,
  });
  const results = input.cases.map((testCase) => {
    try {
      const command = verify(testCase.envelope, testCase.professional_id);
      const result = { accepted: true };
      if (testCase.expected_signed_bytes !== undefined) {
        const expected = Buffer.from(testCase.expected_signed_bytes, 'base64url');
        const original = Buffer.from(testCase.envelope.command, 'base64url');
        const signed = Buffer.concat([
          Buffer.from('PhysioPlus/assistant-command/v1\0', 'ascii'),
          Buffer.from(testCase.envelope.key_id, 'ascii'),
          Buffer.from([0]),
          original,
        ]);
        result.bytes_match = signed.equals(expected);
        result.raw_signature_valid = crypto.verify(
          null,
          expected,
          crypto.createPublicKey(input.public_keys[testCase.envelope.key_id]),
          Buffer.from(testCase.envelope.signature, 'base64url'),
        );
      }
      if (testCase.expected_parameters !== undefined) {
        result.utf8_preserved = isDeepStrictEqual(command.parameters, testCase.expected_parameters);
      }
      return result;
    } catch (error) {
      if (error.name !== 'AssistantCommandVerificationError') {
        throw error;
      }
      return { accepted: false, code: error.code };
    }
  });
  process.stdout.write(JSON.stringify(results));
} catch {
  process.stderr.write('Isolated Node verification failed.\n');
  process.exitCode = 1;
}
