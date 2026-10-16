"""Reconstruct the exact inherited engine, then apply this versioned FT layer.

The two source repositories are read-only. Nothing is pushed by this tool.
Use the original recovery attachments; private retrieval IDs are not needed here.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = "fdede6f16721f06422d0798a79d84170969b83f8"
HELD = "c8bef62d623b55054594d1328dfd649c52811641"
ARCHIVES = {
    "held": "30ee3b393fa0b619cc7f2f8e6191a8769dc9f2b4382627eda1f00d759d801df0",
    "repairs": "1b7ca5507e7a82e9c1fc09d7485f6b47cfc91fa3302268006e9180c5ed5616d7",
}
BUNDLE_SHA = "83af5f74bd162337b3c1b0eb135066aab99f0bd69b7e294d7d8c885c38656e2f"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def safe_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name or not p.parts:
        raise ValueError("unsafe archive or layer path: " + name)
    return p


def checked_archive(path, kind):
    if digest(path) != ARCHIVES[kind]:
        raise ValueError("wrong " + kind + " archive digest")
    z = zipfile.ZipFile(path)
    names = z.namelist()
    if len(names) != len(set(names)):
        raise ValueError("duplicate archive member")
    for info in z.infolist():
        safe_path(info.filename)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError("archive symlink is not a regular source member")
    if kind == "held":
        manifest = json.loads(z.read("SHA256.json"))
    else:
        rows = json.loads(z.read("Repair_Evidence_Manifest.json"))
        manifest = {r["path"]: r["sha256"] for r in rows}
        if len(manifest) != len(rows):
            raise ValueError("duplicate evidence manifest path")
    for name, expected in manifest.items():
        if hashlib.sha256(z.read(name)).hexdigest() != expected:
            raise ValueError("archive member mismatch: " + name)
    return z, manifest


def prepare(held_archive, repair_archive, output, source_checkout=None, repair_checkout=None):
    if output.exists():
        raise ValueError("output must be a new directory; existing work is preserved")
    manifest_path = ROOT / "docs/Source_Dependencies.json"
    dependencies = json.loads(manifest_path.read_text())
    if dependencies["base_commit"] != BASE or dependencies["held_commit"] != HELD:
        raise ValueError("dependency base differs from registered recovery")
    held, held_members = checked_archive(held_archive, "held")
    repairs, repair_members = checked_archive(repair_archive, "repairs")
    try:
        with tempfile.TemporaryDirectory(prefix="soc-g-verified-bundle-") as tmp:
            bundle = Path(tmp) / "held.bundle"
            bundle.write_bytes(held.read("Engine_Socionics_FT_checkpoint.bundle"))
            if digest(bundle) != BUNDLE_SHA:
                raise ValueError("bundle identity mismatch")
            source = str(source_checkout.resolve()) if source_checkout else "https://github.com/GregoritHub/Socionics_Engine.git"
            run("git", "clone", "--no-hardlinks", source, str(output))
            run("git", "remote", "set-url", "--push", "origin", "DISABLED_READ_ONLY_SOURCE", cwd=output)
            run("git", "checkout", "--detach", BASE, cwd=output)
            run("git", "bundle", "verify", str(bundle), cwd=output)
            run("git", "fetch", str(bundle), "refs/heads/main:refs/heads/held-ft3", cwd=output)
            run("git", "checkout", "--detach", HELD, cwd=output)
            repaired = Path(tmp) / "repaired"
            repair_source = str(repair_checkout.resolve()) if repair_checkout else "https://github.com/GregoritHub/Engine_Socionics.git"
            run("git", "clone", "--no-hardlinks", repair_source, str(repaired))
            run("git", "remote", "set-url", "--push", "origin", "DISABLED_READ_ONLY_SOURCE", cwd=repaired)
            run("git", "checkout", "--detach", dependencies["repair_commit"], cwd=repaired)
            for name, expected in dependencies["repair_files"].items():
                safe_path(name)
                if not name.startswith(("full_theory/", "tests_ft", "tools/evaluate_ft", "contracts/ft/", "docs/FT_", "docs/ft/")):
                    raise ValueError("unexpected repair source path: " + name)
                if digest(repaired / name) != expected:
                    raise ValueError("repaired source differs: " + name)
                dest = output / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repaired / name, dest)
        for name in repair_members:
            if not name.startswith(("evidence/FT2/", "evidence/FT3/")):
                raise ValueError("unexpected repair evidence path: " + name)
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(repairs.read(name))
        # Only new, committed layer files are applied. Runtime dependency reads
        # do not transfer any source back to the destination repository.
        layer_files = [name for name in run("git", "ls-files", cwd=ROOT).splitlines()
                       if name == "tools/prepare_workspace.py" or
                       name.startswith(("full_theory/", "tests_ft", "contracts/ft/", "tools/evaluate_ft", "tools/audit_ft", "tools/compare_ft")) or
                       name in ("tools/audit_owned_repair_practice_saved.py",
                                "tools/check_owned_material_inspection_saved.py",
                                "tools/continue_ft7_1b2b3b2b2b2b2b2b1b.py",
                                "tools/continue_owned_material_inspection.py",
                                "tools/evaluate_owned_material_inspection.py",
                                "tools/evaluate_owned_repair_practice.py",
                                "tools/evaluate_recall_feasibility.py")]
        for name in layer_files:
            safe_path(name)
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
        repair_freeze = json.loads((output / "evidence/FT3/Repair_Source_Freeze.json").read_text())
        for name, expected in repair_freeze.items():
            if digest(output / name) != expected:
                raise ValueError("accepted FT3 repair differs: " + name)
        baseline = run("git", "ls-tree", "-r", BASE, "baseline/", cwd=output).splitlines()
        for row in baseline:
            meta, name = row.split("\t", 1)
            data = (output / name).read_bytes()
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if actual != meta.split()[2]:
                raise ValueError("sealed baseline changed: " + name)
        reference = output / "evidence/FT0.1/reference"
        historical = json.loads((reference / "Immutable_Manifest.json").read_text())
        for name, expected in historical.items():
            if digest(reference / name) != expected:
                raise ValueError("historical reference changed: " + name)
        result = dict(passed=True, base=BASE, held=HELD,
                      dependency_recipe_sha256=digest(manifest_path),
                      layer_files=len(layer_files), repair_freeze_files=len(repair_freeze),
                      baseline_files=len(baseline), historical_files=len(historical),
                      verified_archive_members=len(held_members)+len(repair_members),
                      claim="Exact prepared inputs; execute the declared tests separately.")
        receipt = output / "evidence/recovery-build/Preparation.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(result, indent=2) + "\n")
        return result
    finally:
        held.close()
        repairs.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--held-archive", type=Path, required=True)
    p.add_argument("--repair-evidence", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--source-checkout", type=Path)
    p.add_argument("--repair-checkout", type=Path)
    args = p.parse_args()
    print(json.dumps(prepare(args.held_archive.resolve(), args.repair_evidence.resolve(),
                             args.output.resolve(), args.source_checkout, args.repair_checkout), indent=2))
