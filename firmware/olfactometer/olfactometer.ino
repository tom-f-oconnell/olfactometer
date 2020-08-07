// Author: Tom O'Connell <tom.oconn3ll@gmail.com>

// TODO modify to angle brackets if i get the compiler options to not need to
// copy them

/*
 Controlling a servo position using a potentiometer (variable resistor)
 by Michal Rinott <http://people.interaction-ivrea.it/m.rinott>

 modified on 8 Nov 2013
 by Scott Fitzgerald
 http://www.arduino.cc/en/Tutorial/Knob
*/

#include <pb_decode.h>
#include "olf.pb.h"

// TODO check this actually would be defined here w/ some other things we
// expect to be enabled
#ifdef PB_ENABLE_MALLOC
#error I don't want malloc enabled.
#endif

uint8_t buffer[128];
bool status;

void setup() {
    Serial.begin(9600);

    /* Allocate space for the decoded message. */
    PulseTiming message = PulseTiming_init_zero;
    
    // TODO if message_length isn't required, how am i supposed to call this?
    // TODO TODO can i just sent the bufsize to the length of buffer?
    // (> length of actual message in most cases)?
    /* Create a stream that reads from the buffer. */
    //pb_istream_t stream = pb_istream_from_buffer(buffer, message_length);
    pb_istream_t stream = pb_istream_from_buffer(buffer, 128);
    
    /* Now we are ready to decode the message. */
    status = pb_decode(&stream, PulseTiming_fields, &message);
    
    /* Check for errors... */
    if (!status)
    {
        //printf("Decoding failed: %s\n", PB_GET_ERROR(&stream));
        //return 1;
        Serial.print("Decoding failed: ");
        Serial.println(PB_GET_ERROR(&stream));
    }
    
    /* Print the data contained in the message. */
    //printf("Your lucky number was %d!\n", (int)message.lucky_number);
    Serial.print("pre_pulse_us: ");
    Serial.println((unsigned long) message.pre_pulse_us);
}

void loop() {
}

