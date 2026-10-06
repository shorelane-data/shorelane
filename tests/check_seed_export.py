"""The bank exports cleanly as ACF eval seeds, and never into an analytics-context checkout."""
import pathlib
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "bank"))
import export_seeds  # noqa: E402

failures = []
with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    out = tmp / "seeds"
    if export_seeds.main(["--out", str(out), "--tiers", ",".join(export_seeds.TIERS)]) != 0:
        failures.append("export reported errors")
    bank = yaml.safe_load((ROOT / "evals" / "bank" / "dev.yaml").read_text())["questions"]
    expected = {q["id"] for q in bank if export_seeds.context_domain(q)}
    got = {p.name.removesuffix(".seed.yaml") for p in out.glob("*.seed.yaml")}
    if got != expected:
        failures.append(f"exported {sorted(got ^ expected)} unexpectedly")
    unmapped = {q["id"] for q in bank if not export_seeds.context_domain(q)}
    if any(not qid.startswith("ops_") for qid in unmapped):
        failures.append(f"questions without a context domain: {sorted(unmapped)}")
    for p in out.glob("*.seed.yaml"):
        seed = yaml.safe_load(p.read_text())
        if seed["domain"] not in set(export_seeds.DOMAINS.values()):
            failures.append(f"{p.name}: domain {seed['domain']!r} is not a context domain")

    fake = tmp / "context"
    fake.mkdir()
    (fake / "context.config.yaml").write_text("version: 0.1\n")
    if export_seeds.main(["--out", str(fake / "evals" / "seeds")]) != 2:
        failures.append("export did not refuse an analytics-context checkout")
    if (fake / "evals").exists():
        failures.append("export wrote into an analytics-context checkout")

for f in failures:
    print(f"FAIL {f}")
print("OK" if not failures else f"{len(failures)} failures")
sys.exit(1 if failures else 0)
