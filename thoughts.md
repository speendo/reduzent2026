- Hardware: yes, unnecessarily extensive. GPIO pin should be configurable. I'm not sure if we stick with LEDC or go with another library that is better for music. (maybe mozzi, ESP32Synth or something different - that will definitely need research).

- Conventions: split now - yes! maybe it's suitable to only split into leaf or controller, maybe we will also need to split into different kinds of leafs (solenoid/piezo) but I would only do this if necessary. Why no comments? Comments are good and improve readability. I like comments. another thing to add (to the verification section) is to always check for redundant code or bad quality code or inefficient code before finishing work.

- planned architecture: yes. also the midi part might be misleading: we did not yet check the midi protocol to see what we can leave out. the list of "essentials" therefore might be missing something.

- missing part: yes. Also we will setup a git repo

- vertical slice: I also think that the webinterface should not be online all the time. each device should have a settings mode and a live mode. settings mode should only be entered on certain occasions (e.g. for a certain amount of time after boot and also if the controler sends a certain signal to the leaf (like: enter settings mode)

- backlog: parasol image upload might be something we need to do. solenoid on-off modes might also be necessary for velocity. the rest of your examples can go to the backlog

Proposed dev-process: I underline the priorities part: every brainstorming phase should have the discussion about: what part of this idea is needed right now and what can go to the product backlog