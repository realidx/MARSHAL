"""Package selected candidates and offline evidence; no model or scheduler use."""
import argparse
import io
import json
from pathlib import Path
import tarfile
from training.strategic_slices.common import file_hash, write_json
from training.strategic_slices.terminal_analysis import require
from training.strategic_slices.terminal_d import ROOT, load_dataset


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'examples/strategic_slices/strategic-slices-terminal-selected-v4.tar.gz')
    args=parser.parse_args()
    names=('strategic_slices_oracle_consistent_candidates_v4','strategic_slices_terminal_d_v4_analysis',
           'strategic_slices_terminal_selected_v4','strategic_slices_terminal_d_v4_review')
    folders=[ROOT/'new/local_data'/name for name in names]
    data=load_dataset(folders[0])
    for folder in folders[1:3]:
        for name,sha in json.loads((folder/'COMPLETE.json').read_text())['files'].items():
            require(file_hash(folder/name)==sha,'Evidence changed: '+name)
    selection=json.loads((folders[2]/'SELECTION.json').read_text())
    require(selection['dataset_sha256']==file_hash(data.root/'manifest.json'),'Selection dataset differs')
    require(selection['analysis_complete_sha256']==file_hash(folders[1]/'COMPLETE.json'),'Selection analysis differs')
    review=json.loads((folders[3]/'REVIEW.json').read_text())
    require(review['files']['analysis_complete']==file_hash(folders[1]/'COMPLETE.json') and
            review['files']['selection_complete']==file_hash(folders[2]/'COMPLETE.json'),'Review evidence differs')
    files={str(p.relative_to(ROOT)) for folder in folders for p in folder.rglob('*') if p.is_file()}
    files.update('examples/strategic_slices/'+name for name in (
        'analyze_terminal_d_v4.py','select_terminal_d_v4.py','report_terminal_d_v4.py',
        'prepare_terminal_selection_bundle.py','test_terminal_d_selection.py','TERMINAL_D_V4_ANALYSIS.md'))
    files.update('training/strategic_slices/'+name for name in ('terminal_analysis.py','test_terminal_analysis.py'))
    manifest=dict(kind='selected-terminal-slice-data-and-analysis-v1',
        files={name:file_hash(ROOT/name) for name in sorted(files)},pool_parents=100,pool_candidates=800,
        selected_candidates=100,selected_parents=selection['selected_parents'],
        dataset_sha256=selection['dataset_sha256'],model_weights_included=False,
        raw_model_result_archives_included=False,training_run_performed=False)
    with tarfile.open(args.output,'x:gz') as archive:
        for name in sorted(files):archive.add(ROOT/name,arcname=name,recursive=False)
        payload=(json.dumps(manifest,indent=2)+'\n').encode()
        entry=tarfile.TarInfo('TERMINAL_SELECTION_BUNDLE.json');entry.size=len(payload)
        archive.addfile(entry,io.BytesIO(payload))
    write_json(Path(str(args.output)+'.json'),dict(archive=args.output.name,sha256=file_hash(args.output),
        files=len(files),**{k:v for k,v in manifest.items() if k!='files'}))
    print(json.dumps(dict(archive=str(args.output),sha256=file_hash(args.output),files=len(files))))


if __name__=='__main__':main()
