"""Freeze completed non-OOD splits without changing an ongoing corpus run."""
import argparse
import json
from pathlib import Path

from benac_p.b_corpus import checksum, export_dataset, load_bundle, write_json


def snapshot(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or source in output.parents:
        raise ValueError('Snapshot must be outside the source corpus')
    staging = output.with_name(output.name + '.building')
    if output.exists() or staging.exists():
        raise ValueError('Use a fresh snapshot output directory')
    manifest = json.loads((source/'manifest.json').read_text())
    splits = ('train', 'validation', 'test')
    plan = [item for item in manifest['plan'] if item['split'] in splits]
    if {item['split'] for item in plan} != set(splits):
        raise ValueError('Source plan must include train, validation and test')
    bundles, provenance = [], {}
    for item in plan:
        directory = source/'sources'/f"source-{item['index']:04d}"
        if not (directory/'complete.json').exists():
            raise ValueError(f'Required source is unfinished: {directory.name}')
        bundle = load_bundle(directory)
        if bundle['split'] != item['split']:
            raise ValueError('Source split differs from plan')
        bundles.append(bundle)
        provenance[directory.name] = json.loads((directory/'complete.json').read_text())
    config = manifest['configuration']
    tokenizer = Path(config['tokenizer_dir'])
    for name, expected in manifest['tokenizer_sha256'].items():
        if checksum(tokenizer/name) != expected:
            raise ValueError('Tokenizer differs from source corpus')
    staging.mkdir(parents=True)
    write_json(staging/'manifest.json', dict(
        version=manifest['version'], artifact='completed-non-ood-snapshot',
        available_splits=list(splits), plan=plan,
        source_manifest=manifest, source_manifest_sha256=checksum(source/'manifest.json'),
        completed_source_checksums=provenance))
    export_dataset(staging, bundles, tokenizer, config['max_length'],
                   config['generation_max_new_tokens'])
    # Empty OOD files are not a completed OOD evaluation set.
    (staging/'READY.json').unlink()
    for path in staging.glob('ood_test*.jsonl'):
        path.unlink()
    summary = json.loads((staging/'summary.json').read_text())
    summary['splits'].pop('ood_test')
    summary.update(artifact='completed-non-ood-snapshot', available_splits=list(splits),
                   full_corpus_complete=False)
    write_json(staging/'summary.json', summary)
    write_json(staging/'checksums.json', {
        p.name: checksum(p) for p in staging.iterdir()
        if p.is_file() and p.name not in ('READY.json', 'checksums.json')})
    write_json(staging/'READY.json', dict(complete=True, available_splits=list(splits),
                                        checksums_sha256=checksum(staging/'checksums.json')))
    staging.rename(output)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(snapshot(args.source_dir, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
