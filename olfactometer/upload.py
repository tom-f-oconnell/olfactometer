#!/usr/bin/env python3

from subprocess import Popen, DEVNULL
import os
from os.path import join, split, splitext, exists, abspath, realpath
import glob
import shutil
import tempfile

# TODO TODO force arduino code to be committed before upload, and embed commit
# hash in arduino code somehow (either through communication -> EEPROM or 
# compile in with arduino-cli compiler flag (-D...)
# (not relevant in pip installed or docker cases, just in [possibly editable
# pip installed] and in-source-tree cases)

# TODO see note above similar line in util.py as to whether to try replacing
# this w/ pkg_resources
this_package_dir = split(abspath(realpath(__file__)))[0]
sketch_name = 'olfactometer.ino'
sketch_path = join(this_package_dir, 'firmware/olfactometer', sketch_name)
nanopb_dir = join(this_package_dir, 'nanopb')

assert exists(this_package_dir), \
    f'this_package_dir={this_package_dir} does not exist'
assert exists(sketch_path), f'sketch_path={sketch_path} does not exist'
assert exists(nanopb_dir), f'nanopb_dir={nanopb_dir} does not exist'


def generate_nanopb_code(sketch_dir):
    proto_files = glob.glob(join(this_package_dir, '*.proto'))
    assert len(proto_files) == 1, \
        f'len(proto_files) != 1, proto_files={proto_files}'
    proto_file = proto_files[0]

    # Just like protoc, the nanopb generator whines if this isn't passed (if not
    # called from the directory containing the *.proto and *.options files).
    # The the nanopb error message seems wrong (references a --proto_path option
    # that doesn't exist on the nanopb generator. hopefully the -I option they
    # also mention is actually the one parsed by the nanopb generator, and not
    # just something used internally by protoc.)
    proto_path, _ = split(proto_file)

    # (would need to specify in setup.py package_data if we wanted to use this
    # version from our nanopb git submodule)
    #nanopb_generator_cmd = 'python {nanopb_dir}/generator/nanopb_generator.py'

    # This executable is installed when you install nanopb from PyPi.
    nanopb_generator_cmd = 'nanopb_generator'

    nanopb_generator_args = \
        f' --output-dir={sketch_dir} -I {proto_path} {proto_file}'

    full_cmd = nanopb_generator_cmd + nanopb_generator_args
    print(full_cmd)

    # TODO need to check if files that would be outputs of nanopb generator
    # already exist? i assume it would just overwrite them (which is fine)?

    # TODO test this .split() method doesn't break if there are spaces in either
    # the sketch_dir or proto_file path (maybe just use shell=True if so, and
    # don't split()?)
    p = Popen(full_cmd.split(), stdout=DEVNULL)
    p.communicate()

    failure = bool(p.returncode)
    if failure:
        raise RuntimeError('nanopb code generation failed')


def make_arduino_sketch_and_libraries(sketch_dir, arduino_lib_dir,
    use_symlinks=True):

    sketch_dir = abspath(sketch_dir)
    arduino_lib_dir = abspath(arduino_lib_dir)

    def copy_or_link(src, dst):
        if use_symlinks:
            os.symlink(src, dst)
        else:
            shutil.copyfile(src, dst)

    ###########################################################################
    # Create the sketch directory
    ###########################################################################
    os.makedirs(sketch_dir, exist_ok=True)
    dest = join(sketch_dir, sketch_name)
    # (if for example, upload is run twice w/ same --build-root argument
    if not exists(dest):
        copy_or_link(sketch_path, dest)
    del dest
    generate_nanopb_code(sketch_dir)

    ###########################################################################
    # Create the Arduino libraries
    ###########################################################################
    os.makedirs(arduino_lib_dir, exist_ok=True)

    nanopb_lib_dir = join(arduino_lib_dir, 'nanopb')
    # exist_ok is a Python 3.2+ feature
    os.makedirs(nanopb_lib_dir, exist_ok=True)

    # These need to be a subset of the *.c and *.h files under nanopb/ or
    # setup.py will not install them correctly (they are now, just noting in
    # case that changes).
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
            copy_or_link(src, dst)

    nanopb_arduino_src_dir = join(this_package_dir, 'nanopb-arduino', 'src')
    nanopb_arduino_lib_dir = join(arduino_lib_dir, 'nanopb-arduino')
    os.makedirs(nanopb_arduino_lib_dir, exist_ok=True)

    files_to_link = glob.glob(join(nanopb_arduino_src_dir, '*'))
    for src in files_to_link:
        dst = join(nanopb_arduino_lib_dir, split(src)[1])
        if not exists(dst):
            copy_or_link(src, dst)


def upload(sketch_dir, arduino_lib_dir, board='arduino:avr:mega',
    port='/dev/ttyACM0', build_root=None, dry_run=False, show_properties=False,
    arduino_debug_prints=False, verbose=False):

    # TODO maybe just like arduino-cli handle the build + build_cache_path now?
    # (at least, if they'll both be under my root tmpdir anyway...)

    if build_root is None:
        td_tmp_build_dir = tempfile.TemporaryDirectory()
        build_root = td_tmp_build_dir.name
    else:
        td_tmp_build_dir = None

    # This does need to be absolute (tmp_build_dir path is absolute I'm
    # assuming, from behavior of <tempfile.TemporaryDirectory>.name)
    build_path = join(build_root, 'build')
    if exists(build_path):
        shutil.rmtree(build_path)

    # arduino-cli's default seemed to be <sketch_dir>/build for me.
    # might depend on where it was run from though?
    build_cache_path = join(build_root, 'build-cache')
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

    # TODO (as above) test for cmds that might have spaces or weird characters
    # to try to break cmd.split() method, and maybe revert to shell=True if
    # there is a problem and no easy fix
    p = Popen(cmd.split())
    p.communicate()

    if td_tmp_build_dir is None:
        if exists(build_path):
            shutil.rmtree(build_path)

        if exists(build_cache_path):
            shutil.rmtree(build_cache_path)
    else:
        # This should delete the contents, as in the if above, without needing
        # to do so explicitly.
        td_tmp_build_dir.cleanup()

    # This p.returncode is set by p.communicate() above.
    failure = bool(p.returncode)
    if failure:
        raise RuntimeError('compilation or upload failed')


def main(port='/dev/ttyACM0', dry_run=False, show_properties=False,
    arduino_debug_prints=False, build_root=None, use_symlinks=True,
    verbose=False):

    if build_root is None:
        # TODO will this just err if it can't be created?
        # (if not, maybe check exists?)
        td_tmp_build_dir = tempfile.TemporaryDirectory()
        # This should exist for the lifetime of any calling code.
        build_root = td_tmp_build_dir.name
    else:
        td_tmp_build_dir = None
        build_root = abspath(build_root)

    # A temporary directory the .ino will get copied to for build.
    sketch_dir = join(build_root, 'olfactometer')
    arduino_lib_dir = join(build_root, 'libraries')

    # This function will create the folders at the paths in the sketch_dir and
    # arduino_lib_dir arguments.
    make_arduino_sketch_and_libraries(sketch_dir, arduino_lib_dir,
        use_symlinks=use_symlinks
    )

    upload(sketch_dir, arduino_lib_dir, build_root=build_root,
        dry_run=dry_run, show_properties=show_properties,
        arduino_debug_prints=arduino_debug_prints, verbose=verbose
    )
    if td_tmp_build_dir is not None:
        td_tmp_build_dir.cleanup()

