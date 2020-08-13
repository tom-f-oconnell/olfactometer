
### Installation

1. Install Docker.
2. `./docker_build.sh`


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

