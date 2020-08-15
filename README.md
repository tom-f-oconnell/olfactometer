
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
- A recent version of `pip` (`20.2.2` definitely works, `9.0.1` does not)

##### Installation
```
pip install .
```
##### Running
The `-u` flag is only needed on the first run, or after changing the firmware.
```
olf -p <COM-port-of-your-Arduino> -u <config-file>
```

### Running

In everything below, replace `/dev/ttyACM0` with the port or serial device of
your Arduino.

To upload the code to your Arduino, and run an experiment after:
```
sudo docker run --device=/dev/ttyACM0 -i olf -p /dev/ttyACM0 -u < <config-file>
```

To just run an experiment:
```
sudo docker run --device=/dev/ttyACM0 -i olf -p /dev/ttyACM0 < <config-file>
```
