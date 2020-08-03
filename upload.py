#!/usr/bin/env python3

from subprocess import Popen
from os.path import join, splitext, exists, abspath
import glob
import shutil


sketch_dir = 'firmware/olfactometer'

def generate_and_move_protobuf_code():
    proto_files = glob.glob('*.proto')
    assert len(proto_files) == 1
    proto_file = proto_files[0]

    prefix = splitext(proto_file)[0] + '.pb.'
    # TODO need to remove these in advance, or are they just overwritten anyway?
    generated_files = [prefix + s for s in ('h','c')]

    p = Popen(f'python nanopb/generator/nanopb_generator.py {proto_file}',
        shell=True
    )
    p.communicate()

    for f in generated_files:
        dest = join(sketch_dir, f)
        # This should overwrite with full paths for both, though docs aren't
        # clear.
        shutil.move(f, dest)


def upload(board='arduino:avr:mega', port='/dev/ttyACM0'):
    # This does need to be absolute
    build_path = abspath('build')
    if exists(build_path):
        shutil.rmtree(build_path)

    # This seems to be the --build-cache-path from "arduino compile --help"
    # (this is just the default. could pass it to make it explicit...)
    build_cache_path = join(sketch_dir, 'build')
    if exists(build_cache_path):
        shutil.rmtree(build_cache_path)

    cmd = (f'arduino-cli compile -b {board} -u -t -p {port} -v {sketch_dir} '
        f'--build-path {build_path} '
        '--build-properties compiler.c.extra_flags=-Inanopb '
        '--build-properties compiler.cpp.extra_flags=-Inanopb'
    )
    print(cmd)
    # TODO parse output to check the -t flag indicated successful verification
    p = Popen(cmd, shell=True)
    p.communicate()

    # TODO test these don't err if compilation errs (would compilation err raise
    # anyway?)
    shutil.rmtree(build_path)
    shutil.rmtree(build_cache_path)


def main():
    generate_and_move_protobuf_code()
    # TODO replace w/ passing appropriate options to arduino so it can use the
    # files in situ without having to copy them
    upload()


if __name__ == '__main__':
    main()

