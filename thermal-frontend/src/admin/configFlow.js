export function buildConfigPatchPayload({ key, value, expectedVersion, reason, dryRun }) {
  if (typeof value !== 'boolean') throw new TypeError('Config value must be boolean.');
  const normalizedReason = String(reason || '').trim();
  if (!normalizedReason) throw new TypeError('Config reason is required.');
  return {
    changes: { [key]: value },
    expected_version: expectedVersion,
    reason: normalizedReason,
    dry_run: Boolean(dryRun),
  };
}

export function buildConfigRollbackPayload({ targetVersion, expectedVersion, reason, dryRun }) {
  const normalizedReason = String(reason || '').trim();
  if (!normalizedReason) throw new TypeError('Rollback reason is required.');
  return {
    target_version: targetVersion,
    expected_version: expectedVersion,
    reason: normalizedReason,
    dry_run: Boolean(dryRun),
  };
}

export function mutationFingerprint(value) {
  return JSON.stringify(value);
}

export function canApplyPreview(preview, expectedFingerprint) {
  return Boolean(preview?.dry_run && preview?.side_effects?.length === 0 && preview.fingerprint === expectedFingerprint);
}
