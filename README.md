
### Supported microcontrollers

Anything with an AVR microprocessor that is compatible with the Arduino IDE
should work.

Known to work on:
- Arduino Mega 2560 (R3)

Some AVR based boards known not to work:
- Arduino Nano Every


### Installation
Just [install Docker](https://docs.docker.com/get-docker/), and proceed to the 
`Running` section below.

#### Windows 
The Docker method will unfortunately not work for typical Windows
configurations, and there does not seem to be a workaround. See 
[this issue](https://github.com/docker/for-win/issues/1018) for more details.

See the Windows specific installation instructions under the
`Development installation` section below.


### Running
Copy and paste this example configuration to a new file called `example.yaml`.
```
settings:
  # The parameters under this key are for specifying the timing of
  # individual trials (each with a single pulse from the valve(s)).
  # All trials will share this timing.
  # All of these parameters are in units of microseconds.
  timing:
    # Baseline period.
    pre_pulse_us: 1000000

    # How long the valve(s) will actually be delivering odor for.
    pulse_us: 1000000

    # Delay before next trial.
    # NOTE: the time from offset of the pulse to the onset of the
    # next trial (if there is one) will be:
    # (post_pulse_us + pre_pulse_us)
    post_pulse_us: 9000000

# Example trial structure with 4 trials. If your microcontroller 
# has pin 13 connected to the builtin LED (as Arduino Unos and 
# Megas do), running this config will flash that LED once per trial 
# (for 1s each time).
pin_sequence:
  # The rows in this bulleted list happen one after the other.
  # If the 'timing' key is specified above, each row
  # (i.e. "- pins: ...") will take
  # (pre_pulse_us + pulse_us + post_pulse_us) microseconds.
  pin_groups:
  # The pins listed in each of these rows will all be concurrently 
  # switched ONCE (LOW for pre_pulse_us -> HIGH for pulse_us ->
  # LOW for post_pulse_us)
  - pins: [13, 4, 5]
  - pins: [13, 4]
  - pins: [13]
  - pins: [13, 9, 7]
```

In everything below, replace `/dev/ttyACM0` with the port or serial device of
your Arduino. Run these commands from the same path that has the `example.yaml`
you created above inside of it.

To upload the code to your Arduino, and run an experiment after:
```
sudo docker run -i --device=/dev/ttyACM0 tom0connell/olfactometer -p /dev/ttyACM0 -u < example.yaml
```

To just run an experiment:
```
sudo docker run -i --device=/dev/ttyACM0 tom0oconnell/olfactometer -p /dev/ttyACM0 < example.yaml
```

If you get an error like this, it means that your Arduino is not actually
available at the port you specified (or it is just not connected). The easiest
way to check which port the Arduino is available under is using the Arduino
development environment, but there are other ways.

![Docker wrong device error](docs/screenshots/wrong_port_err.png)


### Updating
```
sudo docker pull tom0connell/olfactometer
```


### Development installation
Do not follow these instructions unless the Docker method above is not possible
for you for some reason. You must verify that things are working as you intend.

#### Dependencies
- `python3.6+`
- `protoc>=3.0.0`
- `arduino-cli` (`setup_arduino-cli.sh` may at least provide hints on what steps
   are required on Windows here)
- A recent version of `pip` (`20.2.2` definitely works, `9.0.1` does not)


#### Windows 


#### Installation
```
git clone https://github.com/tom-f-oconnell/olfactometer
cd olfactometer
```

If you are on Ubuntu 18.04, you should be able to install all the necessary
dependencies with this command. This will probably not work on other systems.
```
./scripts/install_18.04_deps.sh
```
If you are not using 18.04, and thus could not use the script above, also run
this command from within your local clone of this git repository:
```
git submodule update --init
```
If you did run the script for Ubuntu 18.04, it will have done the above git
command for you.

After you have installed the necessary dependencies:
```
# (make and activate a virtual environment here, if you would like)
pip install .
```

If you are on Windows, after making sure that `python>=3.6` and `git` are
installed:
1. Download `arduino-cli.zip` from their website
2. Extract and copy to `C:\Program Files\arduino-cli`, so that inside this new
   folder there is the `arduino-cli.exe` from the ZIP file.
3. Add `C:Program Files\arduino-cli` to your `Path` environment variable, by
   pressing the Windows key, searching for "environment variable", clicking the
   result (works in Windows 10 at least), and then clicking the `Environment
   Variables...` button at the bottom of the window that pops up. In the
   "User variables for <your-username>" section at the top, select the row for
   the `Path` variable, and select "Edit". In the new window, click the "New"
   button, to add a new path to this variable (which is a list of paths). Paste
   / type in `C:\Program Files\arduino-cli`.
4. Download the latest `protoc-<x.y.z>-win64.zip` from [this 
   link](https://github.com/protocolbuffers/protobuf/releases). Repeat steps 2
   and 3 for this ZIP file, though copy the contents of the ZIP file to
   `C:\Program Files\protoc` and only add `C:\Program Files\protoc\bin` to
   `Path`.
5. `cd` to the `olfactometer` directory and (making sure that `python` is
   running the version of python you expect) run:
   `python -m pip install .`
6. Find where the `pip` command in step 5 created the `olf` executable, and add
   this to `Path` as well. For me, the path I needed to add was the path in the
   `Location` row of `pip show olfactometer` output with `\Python38\Scripts`
   appended to the end:
   `C:\Users\tom\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.8_qbz5n2kfra8p0\LocalCache\local-packages\Python38\Scripts`


#### Running
The `-u` flag is only needed on the first run, or after changing the firmware.
```
olf -p <COM-port-of-your-Arduino> -u <config-file>
```


### Building Docker image
```
./docker_build.sh
```


#### Todo

Add instructions for how to interface with this.
- one example using subprocess around the docker installed version
  (and test that it can work OK from non-root python processes...)
- and using "from olfactometer import main" (assuming dev install)

