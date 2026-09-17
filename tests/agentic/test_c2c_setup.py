from pathlib import Path
import subprocess
import pytest
from examples.final_evaluation import setup_c2c


def make_repo(tmp_path):
    source=tmp_path/'source';source.mkdir()
    subprocess.run(['git','init',str(source)],check=True,capture_output=True)
    file=source/'c2c/experiments/run_batch.py';file.parent.mkdir(parents=True);file.write_text('# pinned source\n')
    subprocess.run(['git','-C',str(source),'add','.'],check=True)
    subprocess.run(['git','-C',str(source),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','fixture'],check=True,capture_output=True)
    commit=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    return source,commit


def test_copied_folder_is_preserved_and_replaced_with_own_repo(tmp_path,monkeypatch):
    source,commit=make_repo(tmp_path)
    monkeypatch.setattr(setup_c2c,'URL',str(source));monkeypatch.setattr(setup_c2c,'C2C_COMMIT',commit)
    target=tmp_path/'copied';target.mkdir();(target/'local_notes.txt').write_text('keep me')
    installed,backup=setup_c2c.prepare(target)
    assert (backup/'local_notes.txt').read_text()=='keep me'
    assert (installed/'.git').exists()
    assert setup_c2c.git(installed,'rev-parse','HEAD')==commit
    assert setup_c2c.prepare(target)==(target,None)
    (target/'c2c/experiments/run_batch.py').write_text('# user changes\n')
    with pytest.raises(ValueError,match='local changes'):setup_c2c.prepare(target)
    assert (target/'c2c/experiments/run_batch.py').read_text()=='# user changes\n'


def test_parent_git_discovery_is_rejected(tmp_path):
    source,_=make_repo(tmp_path);child=source/'copied';child.mkdir()
    with pytest.raises(ValueError,match='independent'):setup_c2c.pin_checkout(child)
