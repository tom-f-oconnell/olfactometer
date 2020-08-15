#!/usr/bin/env python3

from subprocess import Popen
import os
from os.path import join, split, splitext, exists, abspath, realpath
import glob
import shutil


# TODO TODO force arduino code to be committed before upload, and embed commit
# hash in arduino code somehow (either through communication -> EEPROM or 
# compile in with arduino-cli compiler flag (-D...)

project_root = split(split(abspath(realpath(__file__)))[0])[0]
sketch_dir = join(project_root, 'firmware/olfactometer')
nanopb_dir = join(project_root, 'nanopb')
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
                    'submodule update --init" from project root (if nanopb or '
                    'nanopb-arduino directories are empty)?'
                )
            os.symlink(src, dst)

    nanopb_arduino_src_dir = abspath(
        join(project_root, 'nanopb-arduino', 'src')
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

    # TODO also check exit status of this one and fail if need be. test.
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
    show_properties=False, arduino_debug_prints=False, verbose=False):

    # This does need to be absolute
    build_path = abspath(join(project_root, 'build'))
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
    if show_properties:
        cmd += ' --show-properties'
    if arduino_debug_prints:
        # Was between this and compiler.c.extra_flags and / or
        # compiler.cpp.extra_flags. I'm assuming this sets both of those?
        # https://github.com/arduino/arduino-cli/issues/210 warns that this can
        # / will override similar flags specified in boards.txt, though I'm not
        # sure that will be an issue we encounter.
        cmd += ' --build-properties build.extra_flags=-DDEBUG_PRINTS'
    if verbose:
        cmd += ' -v'
        
    upload_args = f' -u -t -p {port}'
    if not (dry_run or show_properties):
        cmd += upload_args

        # TODO i managed to get the same "...Device or resource busy
        # ioctl("TIOCMGET"): Inappropriate ioctl for device" error when i just
        # plugged the arduino in here...

        # This is because arduino-cli hangs for a while (maybe indefinitely?)
        # if it does not exist.
        if not exists(port):
            raise IOError(f'port {port} does not exist. '
                'is the Arduino connected?'
            )

    print(cmd)

    # TODO add error handling for case when arduino was just plugged in and we
    # are still getting:
    # avrdude: ser_open(): can't open device "/dev/ttyACM0": Device or resource
    # busy
    # ioctl("TIOCMGET"): Inappropriate ioctl for device
    # (some resetting we can do? or just wait?)

    # TODO parse output to check the -t flag indicated successful verification
    # (if returncode is sufficient, no need...)

    p = Popen(cmd, shell=True)
    p.communicate()

    if exists(build_path):
        shutil.rmtree(build_path)

    if exists(build_cache_path):
        shutil.rmtree(build_cache_path)

    # This p.returncode is set by p.communicate() above.
    failure = bool(p.returncode)
    if failure:
        raise RuntimeError('compilation or upload failed')


def main(port='/dev/ttyACM0', dry_run=False, show_properties=False,
    arduino_debug_prints=False, verbose=False, clear_libraries=False):

    make_arduino_libraries(delete_existing=clear_libraries)
    generate_and_move_protobuf_code()
    upload(dry_run=dry_run, show_properties=show_properties,
        arduino_debug_prints=arduino_debug_prints, verbose=verbose
    )

