// Author: Tom O'Connell <tom.oconn3ll@gmail.com>

// TODO TODO figure out how we can get python to insert something compile time
// preprocessor macro defined w/ compiler flag? (for git hash)

// TODO TODO use similar technique maybe to assign specific pins? and have a
// mapping of hardware targets to pin assignments (for things like interrupt
// pins and balance_pin, etc)
// TODO TODO or even specific physical olfactometers, as the construction
// varies...

// TODO maybe just use EEPROM for the above data though, and pass it through
// protobuf at init time (no-op if already set?)?

#define USE_MESSAGE_NUMS

// NOTE: DEBUG_PRINTS is defined in ./upload.py and ./olfactometer.py if you
// pass the -g (--arduino-debug-prints) option. Uncomment this if you would like
// to enable debug prints, compiling yourself with some other build system.
//#define DEBUG_PRINTS

#ifdef OLFACTOMETER_VERSION_STR
// Since I couldn't figure out any combination of single / double quotes /
// escape characters that would let me set an arbitrary string in arduino-cli
// extra_flags argument.
// https://stackoverflow.com/questions/2410976
#define STRINGIZE(x) #x
#define STRINGIZE_VALUE_OF(x) STRINGIZE(x)
const char *version_str = STRINGIZE_VALUE_OF(OLFACTOMETER_VERSION_STR);
#else
const char *version_str = "-DOLFACTOMETER_VERSION_STR not set";
#endif

#include <avr/wdt.h>

// Using my fork of https://github.com/eric-wieser/nanopb-arduino
#include <pb_arduino.h>

#include "olf.pb.h"

// TODO are (any of) the arduino avrs / teensy cases where PB_NO_PACKED_STRUCTS
// is necessary? would it autodetect / warn?

// TODO check this actually would be defined here w/ some other things we
// expect to be enabled
#ifdef PB_ENABLE_MALLOC
#error I do not want nanopb malloc enabled
#endif

// TODO consider PB_WITHOUT_64BIT. drawbacks? appropriate err if i accidentally
// use a 64 bit type?

// TODO TODO maybe just convert all reads to a single buffer that i manage?
// (i'm assuming that might simplify non-blocking reading in the loop...)

//uint8_t buffer[128];

// TODO maybe just refactor code to not need this... then could keep Serial
// connection open, and not sure i can doing it this way.
void software_reset() {
    // TODO any point to this? will connection stay open and usable if i don't
    // close it? (don't see how it could...)
    Serial.flush();
    Serial.end();
    // TODO if i can find information clarifying how long my bootloaders take to
    // run, could decrease the timeout period to something lower. just want to
    // leave enough time to disable the WDT in setup (presumably it starts
    // counting ~powerup, while still in bootloader)
    wdt_enable(WDTO_1S);
    while (true) {}
}

bool no_ack = false;
uint8_t expected_msg_num = 0;
void decode(pb_istream_t *stream, const pb_msgdesc_t *fields, void *dest_struct) {
    // TODO can this just be called until it succeeds, or will buffers filled on
    // previous attempts be cleared at that point? (the latter is what i'd
    // assume...)
    bool status;
    // This PB_DECODE_DELIMITED option expects a varint encoded message size
    // first, and uses that to determine how many bytes it needs to read.
    status = pb_decode_ex(stream, fields, dest_struct, PB_DECODE_DELIMITED);

    if (!status) {
        Serial.print("Decoding failed: ");
        Serial.println(PB_GET_ERROR(stream));
        software_reset();
    }

    // TODO probably convert to just reading 2 bytes into array (or union w/
    // uint16_t?)
    while (Serial.available() < 2) { };
    uint8_t high = Serial.read();
    uint8_t low = Serial.read();
    uint16_t target_crc = high << 8 | low;

    bool good = crc_good(target_crc);
    
    if (! good) {
        Serial.println("CRC mismatch");
        software_reset();
    }

    // This doesn't actually seem to change the amount of time I need to sleep
    // on the Python side for `ser.reset_input_buffer()` to work, but it still
    // feels like there might be some cases where it does help.
    // Didn't work (to stop the commented crc debug prints from interfering).
    // To try to give the pyserial side a better chance of
    // `ser.reset_input_buffer()` success in just getting the next byte...
    #ifdef DEBUG_PRINTS
    Serial.flush();
    #endif

    #ifdef USE_MESSAGE_NUMS
    if (fields == Settings_fields) {
        // TODO need to cast the void dest_struct pointer to Settings first?
        no_ack = ((Settings *) dest_struct)->no_ack;
    }
    while (Serial.available() < 1) {};
    uint8_t msg_num = Serial.read();

    // TODO TODO why does ack seem necessary for second decode to work (and the
    // prints after it?). buffer overflow? some way to prevent this without
    // switching to a buffer i manage here? pyserial out_waiting useful,
    // if checked before each write?
    if (! no_ack) {
        // Acknowledging before erring, because Python code is reading one byte
        // here.
        Serial.write(msg_num);
        // TODO want this? timing important?
        Serial.flush();
    }

    if (msg_num != expected_msg_num) {
        Serial.print("msg_num mistmatch. got: ");
        Serial.print(msg_num);
        Serial.print(", expected: ");
        Serial.println(expected_msg_num);
        software_reset();
    }
    // TODO TODO test wraparound behavior
    expected_msg_num++;
    #endif

    init_crc();
}

// TODO are pb_istream_s and pb_istream_t interchangeable in this context?
// (the nanopb def specifies ..._t but nanopb-arduino returns ..._s here)
// (one does seem to be defined as the other, but why? why have 2?)
pb_istream_s stream = as_pb_istream(Serial);

// TODO maybe use *_init_default instead? (though i haven't yet seen a case
// where they were actually different...)
// Allocate space for the decoded message.
Settings settings = Settings_init_zero;
PinSequence pin_seq = PinSequence_init_zero;

// TODO TODO maybe implement timing with hardware timer interrupts (risk of
// missing serial data though?), and do the math in here to convert between
// ticks of timer and desired us pulse features.
// TODO + maybe err if requested pulse features differ from a multiple of this
// (or deviate by more than some tolerance from the a multiple)

// TODO if i'm not going to modify protobuf protocol + python side to specify
// interrupt pin from there, maybe add something for python to query reserved
// pins, for validation on that side? or just handle (as yet
// non-implemented...) error state somehow?
// might want to be able to query reserved pins anyway, unless it's always just
// {0,1} across all hardware targets (which are required for Serial)
bool follow_hardware_timing = false;

// TODO TODO also allow configuration at runtime... (as all pins should be...)
// This seems to be one of the availble interrupt pins on the Mega
// TODO same type of interrupt as we could achieve on 2/3 though?
const uint8_t external_timing_pin = 20;

// TODO what is appropriate type for this? (this seems to work, but maybe some
// would be out of bounds? (for some pins on some targets) maybe use larger?
// TODO const allowed for output of function call? (seems so)
const uint8_t external_timing_interrupt = digitalPinToInterrupt(
  external_timing_pin
);

// For each of these pins, 0 = disabled. Can be set in settings.
// TODO also enable it being high or low by default?
uint8_t balance_pin = 0;
// Mirrors pulse timing of currently active valve. For recording timing this
// firmware produces (without knowing which pin it was pulsing).
uint8_t timing_output_pin = 0;

uint8_t recording_indicator_pin = 0;


// TODO TODO also add an optional pin to signal the pin thats getting switched
// (as before)

uint8_t reserved_pins[] = {0, 1};

bool pin_is_reserved(uint8_t pin) {
    // TODO support disabling balance pin though...
    if (balance_pin && pin == balance_pin) {
        return true;
    }
    if (follow_hardware_timing && pin == external_timing_pin) {
        return true;
    }
    if (timing_output_pin && pin == timing_output_pin) {
        return true;
    }
    if (recording_indicator_pin && pin == recording_indicator_pin) {
        return true;
    }
    for (uint8_t i=0; i<sizeof reserved_pins/sizeof reserved_pins[0]; i++) {
        if (pin == reserved_pins[i]) {
            return true;
        }
    }
    return false;
}

inline void digital_write_pin_group(PinGroup *group, bool state) {
    // uint8_t max >> 8 (max pins_count defined in olf.options)
    for (uint8_t i=0; i<group->pins_count; i++) {
        digitalWrite(group->pins[i], state);
    }
}

volatile uint8_t pin_seq_idx = 0;
volatile bool isr_err = false;
// TODO does this need to be volatile if ONLY the ISR uses it?
// Expecting the first CHANGE on external_timing_pin to be RISING.
volatile bool last_state = LOW;

volatile uint8_t isr_count = 0;

// TODO TODO time this function to see if it's a reasonable length?
// (and what *is* a reasonable length? is there really any other code that can't
// be interruted by this?)
// TODO use a long loop in here (timed outside of an isr, where millis() and the
// like can be relied upon, for reference?) to check that the isr_err flag
// actually is set appropriately!
void external_timing_isr() {
    // Reading the pin to determine whether it was a RISING or FALLING edge
    // from: https://forum.arduino.cc/index.php?topic=521547.0
    bool curr_state = digitalRead(external_timing_pin);

    // TODO could compare this method w/ just assuming we start low
    // (maybe one read at beginning to confirm?) and toggling estimated
    // state at each subsequent change

    // TODO also compare to a rising and falling interrupt that disable
    // themselves and enable the other, as described here:
    // https://stackoverflow.com/questions/33380218

    isr_count++;

    // TODO is this equivalent to keeping counts of # rising edges and # of
    // falling edges and comparing those? maybe do that instead?
    if (curr_state == last_state) {
        isr_err = true;
        detachInterrupt(external_timing_interrupt);
        return;
    }

    // TODO maybe store a group that persists across ISR runs, that only this
    // ISR uses, and that udpates whenever pin_seq_idx changes?
    // (or just make it volatile and update in main loop, which i think might
    // already be checking something equivalent?)
    // (should save a tiny bit of time...)

    // TODO does pin_seq need to be marked volatile just b/c this isr READS it?
    // TODO TODO TODO seems like yes. fix!! (and look for others to fix)
    // https://stackoverflow.com/questions/55278198
    // (but maybe since pin_seq is only read before interrupts are enabled
    // and not updated again until after, it's actually ok??)
    PinGroup group = pin_seq.pin_groups[pin_seq_idx];
    digital_write_pin_group(&group, curr_state);

    if (balance_pin) {
        digitalWrite(balance_pin, curr_state);
    }
    if (timing_output_pin) {
        digitalWrite(timing_output_pin, curr_state);
    }
    if (curr_state == LOW) {
        pin_seq_idx++;
    }
    last_state = curr_state;
    // TODO maybe move this into main loop (to make isr a tiny bit faster...)?
    if (pin_seq_idx == pin_seq.pin_groups_count) {
        detachInterrupt(external_timing_interrupt);
    }
}

void print_pin_group(PinGroup *group) {
    uint8_t pin;
    for (uint8_t i=0; i<group->pins_count; i++) {
        pin = group->pins[i];
        Serial.print(pin);
        if (i < group->pins_count - 1) {
          Serial.print(",");
        }
    }
}

void print_trial_status(uint16_t trial, PinGroup *group) {
    Serial.print("trial: ");
    Serial.print(trial);
    Serial.print(", pin(s): ");
    print_pin_group(group);
    Serial.println();
}

void finish() {
    Serial.println("Finished");
    software_reset();
}

// TODO make sense to be inline? i was just hoping to reduce function call
// overhead, and it's presumed timing impact
// I'm pretty sure this function is wraparound-safe.
unsigned long last_change_us = micros();
inline void busy_wait_us(unsigned long interval_us) {
    while (micros() - last_change_us < interval_us);
    last_change_us = micros();
}

// TODO TODO compare timing accuracy with w/o some interrupt based
// implementation (would timer interrupts really help? when?)
void run_sequence() {
    // TODO probably add other parameters to have this go low periodically too,
    // if allowing recovery from laser power actually has a place...
    if (recording_indicator_pin) {
        digitalWrite(recording_indicator_pin, HIGH);
    }

    // TODO TODO was the casting the serial.prints did with the same rhs values
    // actually necessary (needed here?)?
    unsigned long pre_pulse_us = settings.control.timing.pre_pulse_us;
    unsigned long pulse_us = settings.control.timing.pulse_us;
    unsigned long post_pulse_us = settings.control.timing.post_pulse_us;
    #ifdef DEBUG_PRINTS
    // TODO just do some tests that are near uint32 max (unsigned long) to check
    // i'm not messing some implicit conversion
    Serial.print("pre_pulse_us: ");
    Serial.print(pre_pulse_us);
    Serial.print(", pulse_us: ");
    Serial.print(pulse_us);
    Serial.print(", post_pulse_us: ");
    Serial.println(post_pulse_us);
    #endif

    PinGroup group;
    uint8_t pin;
    for (uint16_t i=0; i<pin_seq.pin_groups_count; i++) {
        group = pin_seq.pin_groups[i];

        print_trial_status(i + 1, &group);

        busy_wait_us(pre_pulse_us);

        if (balance_pin) {
            digitalWrite(balance_pin, HIGH);
        }
        if (timing_output_pin) {
            digitalWrite(timing_output_pin, HIGH);
        }
        digital_write_pin_group(&group, HIGH);

        busy_wait_us(pulse_us);

        if (balance_pin) {
            digitalWrite(balance_pin, LOW);
        }
        if (timing_output_pin) {
            digitalWrite(timing_output_pin, LOW);
        }
        digital_write_pin_group(&group, LOW);

        busy_wait_us(post_pulse_us);
    }

    // TODO maybe sure this is on a pin that bootloader doesn't send high
    if (recording_indicator_pin) {
        digitalWrite(recording_indicator_pin, LOW);
    }

    finish();
}

// TODO maybe somehow check that this is consistent w/ type of values defined in
// olf.options? (or define it in arduino compilation args, maybe just leaving it
// undefined otherwise, and then parse from *.options in python, the same way
// i'm planning on doing some of the validation)
const uint16_t MAX_NUM_PINS = 256;
// TODO maybe implement this as bitmask instead?
// TODO does it actually matter if we initialize this (currently do in setup)?
bool unique_output_pins[MAX_NUM_PINS];

void setup() {
    // Some other code added a delay after this, but I can't see why that'd be
    // necessary...
    // https://www.codeproject.com/articles/1012319/arduino-software-reset
    wdt_disable();

    // Looks like pin 13 defaults to OUTPUT and HIGH, but I don't want that, in
    // case it's (for example) the timing_output_pin
    // TODO make this hardware target specific if others dont have that behavior
    // Just setting it to an INPUT didn't seem sufficient...
    // Still seems to blink a bit on serial connection initiation... avoidable?
    // TODO use different pin if it really matters
    /*
    pinMode(13, OUTPUT);
    digitalWrite(13, LOW);
    */

    // Other candidate rates: 38400, 57600, 115200 (max)
    Serial.begin(115200);
    Serial.println(version_str);

    // TODO maybe print some message to identify this device + the software
    // version? maybe even available pins (though not sure how to calculate...
    // maybe just hardcode based on a few hardware targets?)?

    // If `i` is of type uint8_t, with MAX_NUM_PINS == 256, this seems to not
    // terminate (presumably because wraparound at the very last i++ (when loop
    // should be broken out of, without any more executions of body).
    // TODO maybe use something like peterpolidoro's array / a similar class of
    // will's here?
    for (uint16_t i=0; i<MAX_NUM_PINS; i++) {
      unique_output_pins[i] = false;
    }

    // TODO does nanopb generate appropriate min message sizes?
    // or some way to do something like that? (don't think so)
    // TODO just parse the varint size first and wait until we have that many
    // bytes available before decoding? (or modify pb_decode_ex / stuff it calls
    // to achieve that?)
    while (Serial.available() < 1) {};
    decode(&stream, Settings_fields, &settings);

    balance_pin = settings.balance_pin;
    timing_output_pin = settings.timing_output_pin;
    recording_indicator_pin = settings.recording_indicator_pin;

    if (settings.which_control == Settings_follow_hardware_timing_tag) {
        follow_hardware_timing = settings.control.follow_hardware_timing;

        #ifdef DEBUG_PRINTS
        Serial.println("settings.control == follow_hardware_timing");

        Serial.print("settings.control.follow_hardware_timing: ");
        Serial.println(follow_hardware_timing);
        #endif

        if (! follow_hardware_timing) {
            // Since settings.which_control already indicated we don't have
            // timing information here, which we'd need if we weren't following
            // external timing.
            Serial.println(
                "follow_hardware_timing should be true if specified"
            );
            software_reset();
        }

    } else if (settings.which_control == Settings_timing_tag) {
        #ifdef DEBUG_PRINTS
        Serial.println("settings.control == timing");
        #endif

    } else {
        Serial.print("settings.which_control had bad value");
        software_reset();
    }

    while (Serial.available() < 1) {};
    // delay a short while for it to fill up?
    decode(&stream, PinSequence_fields, &pin_seq);

    // Reading this way depends on olf.options specifying max_count:<x> for
    // PulseSequence.pin_groups and NOT specifying fixed_count:true (in which
    // case we would not have the count, I think).
    // uint16_t for `i` because uint8_t would wraparound right before loop
    // termination if max_count == 256, and an array of full length sent.
    PinGroup group;
    uint8_t pin;
    for (uint16_t i=0; i<pin_seq.pin_groups_count; i++) {
        group = pin_seq.pin_groups[i];
        #ifdef DEBUG_PRINTS
        Serial.print("i: ");
        Serial.print(i);
        Serial.print(", pin_seq.pin_groups[i]: ");
        print_pin_group(&group);
        Serial.println();
        #endif
        for (uint8_t j=0; j<group.pins_count; j++) {
            pin = group.pins[j];
            if (pin_is_reserved(pin)) {
                Serial.print("pin ");
                Serial.print(pin);
                Serial.println(" is reserved!");
                software_reset();
            }
            unique_output_pins[pin] = true;
            #ifdef DEBUG_PRINTS
            #endif
        }
    }

    #ifdef DEBUG_PRINTS
    Serial.println("unique output pins:");
    #endif
    for (uint16_t i=0; i<MAX_NUM_PINS; i++) {
        if (unique_output_pins[i]) {
            pinMode(i, OUTPUT);
            digitalWrite(i, LOW);
            #ifdef DEBUG_PRINTS
            Serial.println(i);
            #endif
        }
    }

    if (balance_pin) {
        pinMode(balance_pin, OUTPUT);
    }
    if (timing_output_pin) {
        pinMode(timing_output_pin, OUTPUT);
    }
    if (recording_indicator_pin) {
        pinMode(recording_indicator_pin, OUTPUT);
        digitalWrite(recording_indicator_pin, LOW);
    }

    if (follow_hardware_timing) {
        // TODO is this actually necessary? it's the default right?
        // but then how was pin 13 on the arduino high until even with code not
        // explicitly setting it to an input? hysteresis or special case of that
        // pin (cause LED)?
        pinMode(external_timing_pin, INPUT);

        // TODO does this persist across resets? need to explicitly initialize
        // it detached or something?
        attachInterrupt(external_timing_interrupt, external_timing_isr, CHANGE);
    }

    if (! follow_hardware_timing) {
        // This ultimately calls finish(), which in turn initiates the watchdog
        // timer based reset, so loop() (and other code below this call) will
        // not be reached, as intended.
        run_sequence();
    }

    // for testing ISR with just one arduino (connect 3<->external_timing_pin)
    /*
    delay(3000);
    pinMode(3, OUTPUT);
    */
    #ifdef DEBUG_PRINTS
    Serial.println("end of setup");
    #endif
}

int last_isr_count = -1;
void loop() {
    PinGroup group;

    if (isr_err) {
        Serial.println("ISR error!");
        software_reset();
    }
    if (last_isr_count < isr_count) {
        group = pin_seq.pin_groups[pin_seq_idx];
        if (isr_count % 2 == 1) {
          print_trial_status(isr_count / 2 + 1, &group);
        }
        #ifdef DEBUG_PRINTS
        Serial.print("pin_seq_idx: ");
        Serial.println(pin_seq_idx);
        Serial.print("pin_seq.pin_groups[pin_seq_idx]: ");
        print_pin_group(&group);
        Serial.println();
        Serial.print("isr_count: ");
        Serial.println(isr_count);
        Serial.print("last_state: ");
        Serial.println(last_state);
        Serial.println();
        #endif
        last_isr_count = isr_count;
    }
    // TODO maybe wait until next high transition / python closing serial
    // connection (doesn't seem to be a great way to detect latter, unless
    // sending a heartbeat or something from the host)? or just stay low? (cause
    // pin 13 flashes in boot loader, so it'll flash in the end of the last
    // trial...)
    if (pin_seq_idx == pin_seq.pin_groups_count) {
        // TODO TODO TODO make this delay configurable with a parameter
        // (right now, this is mainly to deal w/ the timing output pin going
        // high (seemingly) after the reset. none of valve pins going high.
        // arduino mega.
        delay(18000);
        finish();
    }
    // for testing ISR with just one arduino (connect 3<->external_timing_pin)
    /*
    digitalWrite(3, HIGH);
    delay(2000);
    digitalWrite(3, LOW);
    delay(4000);
    */
}

