#!/usr/bin/env python3

import argparse
from subprocess import run, PIPE

from olfactometer.upload import main as upload_main


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true', default=False,
        help='make arduino-cli compilation verbose'
    )
    args = parser.parse_args()

    # This will only iterate over boards that fall under the "cores" arduino-cli
    # already has installed on your computer (likely just 'avr' or maybe also
    # 'megaavr'). To find more cores to try, run:
    # arduino-cli core update-index
    # arduino-cli core search
    # arduino-cli core install <cores to install>
    p = run('arduino-cli board listall'.split(), stdout=PIPE, check=True)
    # might not work on windows?
    lines = str(p.stdout).split('\\n')[1:-2]
    fqbns = [x.strip().split()[-1].strip() for x in lines]
    print('FQBNs that will be tested:')
    for f in fqbns:
        print(f)
    print()

    # TODO TODO was arduino:avr:nano:cpu=atmega328 a valid input? it's not
    # generated in above right? try it manually / figure out how to enumerate
    # meaningfully distinct CPUs? (re: some troubleshooting w/ Han, when a board
    # with [i think] this fqbn erred on his /dev/ttyUSB0)

    '''
    fqbns = [
        'arduino:avr:mega',
        'arduino:avr:nano',
        'arduino:megaavr:nona4809'
    ]
    '''

    succeeded = []
    failed = []
    for f in fqbns:
        print(f'{f}: ', end='')
        try:
            # TODO maybe refactor to re-use sketch / library directories, to
            # avoid needing to recreate them for each build? do want the
            # directories w/ build artifacts to be clean for each though...
            # TODO add options inside upload.py to make this complete silent?
            # TODO maybe run as subprocess so i can run verbose, capture output
            # while compiling, and show it / store it somewhere? or refactor so
            # that there's an option for the stuff doing the compiling to
            # capture the output during its own internal subprocess call?
            # TODO maybe add a means of also capturing / flagging warnings
            # during compilation
            upload_main(fqbn=f, dry_run=True)
            succeeded.append(f)
        except RuntimeError:
            failed.append(f)

    print()
    print('Succeeded:')
    for f in succeeded:
        print(f)
    print()
    print('Failed:')
    for f in failed:
        print(f)


if __name__ == '__main__':
    main()

