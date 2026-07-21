// Pure source-policy comparison used by the report and regression tests.
export function sourcesDiffer(advisory, canonical) {
  const fields = (source) => [
    source.provider,
    source.timeframe,
    source.start ?? source.window ?? null,
    source.end ?? null,
    source.fingerprint,
  ];
  const left = fields(advisory);
  const right = fields(canonical);
  return left.some((value, index) => value !== right[index]) ? "YES" : "NO";
}
