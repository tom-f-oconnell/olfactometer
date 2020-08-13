
### Installation

1. Install Docker.
2. `./docker_build.sh`

#### Windows 
The Docker method will unfortunately not work for typical Windows
configurations, and there does not seem to be a workaround. See 
[this issue](https://github.com/docker/for-win/issues/1018) for more details.

Here are some partial instructions for a manual install on Windows:

##### Dependencies 
- `python3.6+`
- `protoc>=3.0.0`
- `arduino-cli` (`setup_arduino-cli.sh` may at least provide hints on what steps
   are required on Windows here)

##### Installation
```
pip install -r requirements.txt
```
##### Running
The `-u` flag is only needed on the first run, or after changing the firmware.
```
python olfactometer.py -p <COM-port-of-your-Arduino> -u
```

### Running

In everything below, replace `/dev/ttyACM0` with the port or serial device of
your Arduino.

To upload the code to your Arduino, and run an experiment after:
```
sudo docker run --device=/dev/ttyACM0 olfactometer -p /dev/ttyACM0 -u
```

To just run an experiment:
```
sudo docker run --device=/dev/ttyACM0 olfactometer -p /dev/ttyACM0 <TODO>
```

#### Todo

Provide a means of configuring `olfactometer.py` (the trial structure,
especially), through command line arguments (including reading config files on
the host). Since Docker makes it harder to change the code, this is especially
important.

