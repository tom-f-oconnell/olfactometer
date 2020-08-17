
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

It should still be possible to follow the `Development installation`
instructions to get this working on Windows, but you will need to figure out how
to install `protoc` yourself.


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

#### Installation
```
git clone https://github.com/tom-f-oconnell/olfactometer
cd olfactometer
# (make and activate a virtual environment here, if you would like)
pip install .
```

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
- 18.04 specific instructions on getting the pip installed version
  working, and using "from olfactometer import main"
