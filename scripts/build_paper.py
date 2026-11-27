"""Package the completed IEEE manuscript, recompile from the ZIP, and publish the PDF locally."""

import argparse
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / 'paper'


def members():
    required = [
        PAPER / 'main.tex', PAPER / 'references.bib',
        PAPER / 'generated' / 'abstract.tex', PAPER / 'generated' / 'results.tex',
    ]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    selected = set(required)
    for folder, suffixes in (('generated', {'.tex'}), ('figures', {'.pdf', '.png', '.jpg'})):
        selected.update(path for path in (PAPER / folder).rglob('*') if path.is_file() and path.suffix in suffixes)
    return sorted(selected)


def compile_zip(archive_path, output_directory, engine):
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('The packaged manuscript contains a corrupt member.')
        archive.extractall(output_directory)
    if engine == 'tectonic':
        for name in ('IEEEtran.cls', 'IEEEtran.bst'):
            local = ROOT / '.upstream' / 'latex' / 'IEEEtran' / name
            if local.is_file():
                shutil.copy2(local, output_directory / name)
        command = ['tectonic', '--only-cached', 'main.tex']
    else:
        command = ['latexmk', '-pdf', '-interaction=nonstopmode', '-halt-on-error', 'main.tex']
    subprocess.run(command, cwd=output_directory, check=True)
    return output_directory / 'main.pdf'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['tectonic', 'latexmk'], default='tectonic')
    args = parser.parse_args()
    assets = members()
    deliverables = ROOT / 'deliverables'
    deliverables.mkdir(exist_ok=True)
    with TemporaryDirectory() as name:
        temp = Path(name)
        archive_path = temp / 'overleaf_project.zip'
        with ZipFile(archive_path, 'w', compression=ZIP_DEFLATED) as archive:
            for path in assets:
                archive.write(path, path.relative_to(PAPER))
        build = temp / 'unpacked'
        build.mkdir()
        pdf = compile_zip(archive_path, build, args.engine)
        shutil.copy2(pdf, PAPER / 'report.pdf')
        shutil.copy2(archive_path, deliverables / archive_path.name)


if __name__ == '__main__':
    main()
