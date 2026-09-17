"""Prepare pinned C2C source without installing packages or losing copied files."""
import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import tempfile
from examples.strategic_transfer.c2c_paired import C2C_COMMIT
URL='https://github.com/abbykoneill/negotiationgames.git'


def git(path,*args):
    return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()


def pin_checkout(path):
    # Never let Git discover an unrelated ancestor repository.
    if not (path/'.git').exists() or Path(git(path,'rev-parse','--show-toplevel')).resolve()!=path.resolve():
        raise ValueError('Expected an independent C2C checkout')
    if git(path,'status','--porcelain'):
        raise ValueError('C2C checkout has local changes; commit/stash them before changing versions')
    if subprocess.run(['git','-C',str(path),'cat-file','-e',C2C_COMMIT+'^{commit}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        subprocess.run(['git','-C',str(path),'fetch',URL,C2C_COMMIT],check=True)
    subprocess.run(['git','-C',str(path),'checkout','--detach',C2C_COMMIT],check=True)
    if not (path/'c2c/experiments/run_batch.py').is_file():raise ValueError('C2C source missing')


def prepare(target):
    target=Path(target).resolve();target.parent.mkdir(parents=True,exist_ok=True)
    if (target/'.git').exists():
        pin_checkout(target);return target,None
    staging=Path(tempfile.mkdtemp(prefix='c2c-pinned-setup-',dir=target.parent))
    subprocess.run(['git','clone','--no-checkout',URL,str(staging)],check=True)
    # A --no-checkout clone has a deliberately empty index/worktree. Check out
    # directly here; existing user checkouts go through the clean-tree guard.
    if subprocess.run(['git','-C',str(staging),'cat-file','-e',C2C_COMMIT+'^{commit}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        subprocess.run(['git','-C',str(staging),'fetch',URL,C2C_COMMIT],check=True)
    subprocess.run(['git','-C',str(staging),'checkout','--detach',C2C_COMMIT],check=True)
    if git(staging,'rev-parse','HEAD')!=C2C_COMMIT or not (staging/'c2c/experiments/run_batch.py').is_file():
        raise ValueError('Incomplete pinned checkout; original directory untouched')
    backup=None
    if target.exists():
        backup=target.with_name(target.name+'.backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        target.rename(backup)
    try:staging.rename(target)
    except BaseException:
        if backup is not None and not target.exists():backup.rename(target)
        raise
    return target,backup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path('third_party/cooperate-to-compete'))
    args=parser.parse_args();target,backup=prepare(args.directory)
    print('C2C checkout:',target);print('Commit:',git(target,'rev-parse','HEAD'))
    if backup:print('Previous copied directory preserved at:',backup)

if __name__=='__main__':main()
