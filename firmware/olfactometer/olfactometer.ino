// Author: Tom O'Connell <tom.oconn3ll@gmail.com>

// Using https://github.com/eric-wieser/nanopb-arduino
#include <pb_arduino.h>

#include "olf.pb.h"

// TODO check this actually would be defined here w/ some other things we
// expect to be enabled
#ifdef PB_ENABLE_MALLOC
#error I do not want nanopb malloc enabled
#endif

//uint8_t buffer[128];
bool status;

// Allocate space for the decoded message.
PulseTiming message = PulseTiming_init_zero;

// TODO are pb_istream_s and pb_istream_t interchangeale in this context?
// (the nanopb def specifies ..._t but nanopb-arduino returns ..._s here)
pb_istream_s stream = as_pb_istream(Serial);

void setup() {
    Serial.begin(9600);
    Serial.println("setup");
}

void loop() {
    delay(1000);

    // TODO does nanopb generate appropriate min message sizes?
    // or some way to do something like that?
    // TODO just parse the varint size first and wait until we have that many
    // bytes available before decoding? (or modify pb_decode_ex / stuff it calls
    // to achieve that?)
    if (Serial.available() > 0) {
      init_crc();
      // This PB_DECODE_DELIMITED option expects a varint encoded message size
      // first, and uses that to determine how many bytes it needs to read.
      status = pb_decode_ex(&stream, PulseTiming_fields, &message,
        PB_DECODE_DELIMITED
      );

      // TODO probably convert to just reading 2 bytes into array (or union w/
      // uint16_t?)
      while (Serial.available() < 2) { };
      uint8_t high = Serial.read();
      uint8_t low = Serial.read();
      uint16_t target_crc = high << 8 | low;

      /*
      Serial.print("target_crc: ");
      Serial.println(target_crc);

      bool good = crc_good(target_crc);
      Serial.print("good: ");
      Serial.println(good);
      */

      Serial.println("after pb_decode_ex");
      
      // Check for errors...
      if (!status)
      {
          Serial.print("Decoding failed: ");
          Serial.println(PB_GET_ERROR(&stream));
      } else {
          Serial.print("pre_pulse_us: ");
          Serial.print((unsigned long) message.pre_pulse_us);
          Serial.print(", pulse_us: ");
          Serial.print((unsigned long) message.pulse_us);
          Serial.print(", post_pulse_us: ");
          Serial.println((unsigned long) message.post_pulse_us);
      }
    }
}

