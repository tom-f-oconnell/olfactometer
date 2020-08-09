#!/usr/bin/env python3

from subprocess import Popen
import os
from os.path import join, split, splitext, exists, abspath, realpath
import glob
import shutil
import argparse


this_script_dir = split(abspath(realpath(__file__)))[0]
sketch_dir = join(this_script_dir, 'firmware/olfactometer')
nanopb_dir = join(this_script_dir, 'nanopb')
arduino_lib_dir = join(split(sketch_dir)[0], 'libraries')


def make_arduino_libraries(delete_existing=False):
    if delete_existing and exists(arduino_lib_dir):
        shutil.rmtree(arduino_lib_dir)

    nanopb_lib_dir = join(arduino_lib_dir, 'nanopb')
    # exist_ok is a Python 3.2+ feature
    os.makedirs(nanopb_lib_dir, exist_ok=True)

    c_and_h_prefixes = ['pb_common', 'pb_encode', 'pb_decode']
    files_to_link = ['pb.h'] + [
        f + s for f in c_and_h_prefixes for s in ('.h','.c')
    ]
    for f in files_to_link:
        dst = join(nanopb_lib_dir, f)
        if not exists(dst):
            src = join(nanopb_dir, f)
            if not exists(src):
                raise IOError(f'required nanopb file {src} not found. try "git '
                    'submodule update --init" from project root?'
                )
            os.symlink(src, dst)

    nanopb_arduino_src_dir = abspath(
        join(this_script_dir, '..', 'nanopb-arduino', 'src')
    )
    nanopb_arduino_lib_dir = join(arduino_lib_dir, 'nanopb-arduino')
    os.makedirs(nanopb_arduino_lib_dir, exist_ok=True)

    files_to_link = glob.glob(join(nanopb_arduino_src_dir, '*'))
    for src in files_to_link:
        dst = join(nanopb_arduino_lib_dir, split(src)[1])
        if not exists(dst):
            os.symlink(src, dst)


def generate_and_move_protobuf_code():
    proto_files = glob.glob('*.proto')
    assert len(proto_files) == 1
    proto_file = proto_files[0]

    prefix = splitext(proto_file)[0] + '.pb.'
    # TODO need to remove these in advance, or are they just overwritten anyway?
    generated_files = [prefix + s for s in ('h','c')]

    p = Popen(f'python {nanopb_dir}/generator/nanopb_generator.py {proto_file}',
        shell=True
    )
    p.communicate()

    for f in generated_files:
        dest = join(sketch_dir, f)
        # This should overwrite with full paths for both, though docs aren't
        # clear.
        shutil.move(f, dest)


def upload(board='arduino:avr:mega', port='/dev/ttyACM0', dry_run=False,
    verbose=False):

    # This does need to be absolute
    build_path = abspath(join(this_script_dir, 'build'))
    if exists(build_path):
        shutil.rmtree(build_path)

    # This is also the default, for me.
    build_cache_path = join(sketch_dir, 'build')
    if exists(build_cache_path):
        shutil.rmtree(build_cache_path)

    cmd = (f'arduino-cli compile -b {board} {sketch_dir} '
        f'--libraries {arduino_lib_dir} '
        f'--build-path {build_path} --build-cache-path {build_cache_path}'
    )
    if verbose:
        cmd += ' -v'
        
    upload_args = f' -u -t -p {port}'
    if not dry_run:
        cmd += upload_args

    print(cmd)

    # TODO add error handling for case when arduino was just plugged in and we
    # are still getting:
    # avrdude: ser_open(): can't open device "/dev/ttyACM0": Device or resource
    # busy
    # ioctl("TIOCMGET"): Inappropriate ioctl for device
    # (some resetting we can do? or just wait?)

    # TODO parse output to check the -t flag indicated successful verification
    p = Popen(cmd, shell=True)
    p.communicate()

    if exists(build_path):
        shutil.rmtree(build_path)

    if exists(build_cache_path):
        shutil.rmtree(build_cache_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--dry-run', action='store_true', default=False,
        help='do not actually upload. just compile.'
    )
    parser.add_argument('-v', '--verbose', action='store_true', default=False,
        help='make arduino-cli compilation verbose'
    )
    parser.add_argument('-c', '--clear-libraries', action='store_true',
        default=False, help='delete and re-create libraries'
    )
    args = parser.parse_args()
    
    make_arduino_libraries(delete_existing=args.clear_libraries)
    generate_and_move_protobuf_code()
    # TODO replace w/ passing appropriate options to arduino so it can use the
    # files in situ without having to copy them
    upload(dry_run=args.dry_run, verbose=args.verbose)


if __name__ == '__main__':
    main()

